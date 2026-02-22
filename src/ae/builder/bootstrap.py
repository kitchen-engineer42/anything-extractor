"""Bootstrap: new task → analyze docs → propose schema → generate workflow."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rich.console import Console
from sqlalchemy.orm import Session

from ae.config import get_settings
from ae.llm import chat_json
from ae.models import (
    Document,
    EventType,
    EvolutionEvent,
    Task,
    TaskStatus,
    WorkflowVersion,
)
from ae.pdf import compute_file_hash, extract_filename_metadata, parse_pdf
from ae.shared.prompts import get_prompt
from ae.shared.types import DocumentAnalysis
from ae.shared.utils import collect_pdf_files, sanitize_task_name, truncate_text

from .codegen import generate_initial_workflow
from .git_ops import commit_workflow
from .pattern_lib import find_matching_patterns
from .schema_mgr import create_schema_version

logger = logging.getLogger(__name__)
console = Console()


def ingest_documents(
    session: Session,
    task: Task,
    input_path: Path,
    max_samples: int = 10,
) -> list[Document]:
    """Ingest PDFs from input path into the database."""
    pdf_files = collect_pdf_files(input_path)
    if not pdf_files:
        raise FileNotFoundError(f"No PDF files found in {input_path}")

    console.print(f"[blue]Found {len(pdf_files)} PDF files[/blue]")

    documents = []
    for i, pdf_path in enumerate(pdf_files):
        file_hash = compute_file_hash(pdf_path)

        # Check for duplicate
        existing = (
            session.query(Document)
            .filter_by(task_id=task.id, file_hash=file_hash)
            .first()
        )
        if existing:
            documents.append(existing)
            continue

        # Parse PDF
        is_sample = i < max_samples
        metadata = extract_filename_metadata(pdf_path.name)

        console.print(f"  Parsing [{i+1}/{len(pdf_files)}]: {pdf_path.name[:60]}...", end="")

        try:
            parse_result = parse_pdf(pdf_path)
            page_count = parse_result.get("page_count", 0)
            parse_method = parse_result.get("method", "unknown")
        except Exception as e:
            logger.warning("Failed to parse %s: %s", pdf_path.name, e)
            parse_result = {"error": str(e), "pages": [], "page_count": 0}
            page_count = 0
            parse_method = "failed"

        doc = Document(
            task_id=task.id,
            filename=pdf_path.name,
            file_hash=file_hash,
            file_path=str(pdf_path.resolve()),
            page_count=page_count,
            parse_method=parse_method,
            parse_result=parse_result,
            is_sample=is_sample,
            metadata_extracted=metadata,
        )
        session.add(doc)
        documents.append(doc)
        console.print(f" [green]OK[/green] ({page_count} pages)")

    session.flush()
    console.print(f"[green]Ingested {len(documents)} documents ({sum(1 for d in documents if d.is_sample)} samples)[/green]")
    return documents


def analyze_documents(
    session: Session,
    task: Task,
    documents: list[Document],
) -> DocumentAnalysis:
    """Analyze sample documents to understand structure and content."""
    settings = get_settings()

    # Collect sample content
    samples = [d for d in documents if d.is_sample][:5]
    doc_contents = []
    for doc in samples:
        pages = doc.parse_result.get("pages", []) if doc.parse_result else []
        text = "\n".join(p.get("text", "") for p in pages[:3])  # First 3 pages
        doc_contents.append(
            f"--- Document: {doc.filename} ---\n"
            f"Filename metadata: {json.dumps(doc.metadata_extracted or {}, ensure_ascii=False)}\n"
            f"{truncate_text(text, 2000)}"
        )

    prompt = get_prompt(
        "builder_analyze_docs",
        num_samples=len(samples),
        doc_contents="\n\n".join(doc_contents),
    )

    result = chat_json(
        messages=[
            {"role": "system", "content": "You are an expert document analyst."},
            {"role": "user", "content": prompt},
        ],
        model=settings.ae_builder_model,
        temperature=0.1,
        max_tokens=4096,
    )

    parsed = result["parsed"]
    analysis = DocumentAnalysis(
        document_type=parsed.get("document_type", "unknown"),
        language=parsed.get("language", "unknown"),
        structure_description=parsed.get("structure_description", ""),
        key_sections=parsed.get("key_sections", []),
        suggested_fields=parsed.get("suggested_fields", []),
        complexity=parsed.get("complexity", "medium"),
        notes=parsed.get("notes", []),
    )

    console.print(f"\n[bold]Document Analysis:[/bold]")
    console.print(f"  Type: {analysis.document_type}")
    console.print(f"  Language: {analysis.language}")
    console.print(f"  Complexity: {analysis.complexity}")
    console.print(f"  Key sections: {', '.join(analysis.key_sections[:5])}")
    console.print(f"  Suggested fields: {len(analysis.suggested_fields)}")

    return analysis


def propose_schema(
    session: Session,
    task: Task,
    analysis: DocumentAnalysis,
) -> dict[str, Any]:
    """Propose extraction schema based on document analysis."""
    settings = get_settings()
    import json as json_mod

    prompt = get_prompt(
        "builder_propose_schema",
        task_description=task.description,
        analysis=json_mod.dumps({
            "document_type": analysis.document_type,
            "language": analysis.language,
            "structure_description": analysis.structure_description,
            "key_sections": analysis.key_sections,
            "suggested_fields": analysis.suggested_fields,
            "complexity": analysis.complexity,
            "notes": analysis.notes,
        }, ensure_ascii=False, indent=2),
    )

    # Check shared patterns
    patterns = find_matching_patterns(session, category=analysis.document_type)
    if patterns:
        prompt += f"\n\nShared patterns available for reuse:\n{json_mod.dumps(patterns[:5], ensure_ascii=False, indent=2)}"

    result = chat_json(
        messages=[
            {"role": "system", "content": "You are an expert at designing data extraction schemas."},
            {"role": "user", "content": prompt},
        ],
        model=settings.ae_builder_model,
        temperature=0.1,
        max_tokens=4096,
    )

    schema_def = result["parsed"]

    # Store schema version
    sv = create_schema_version(session, task.id, schema_def)

    console.print(f"\n[bold]Proposed Schema (v{sv.version}):[/bold]")
    for field in schema_def.get("fields", []):
        name = field.get("name", "?")
        ftype = field.get("type", "string")
        desc = field.get("description_zh", field.get("description", ""))
        req = "[red]*[/red]" if field.get("required") else " "
        console.print(f"  {req} {name} ({ftype}): {desc}")

    return schema_def


def generate_workflow(
    session: Session,
    task: Task,
    schema: dict[str, Any],
    analysis: DocumentAnalysis,
    documents: list[Document],
) -> WorkflowVersion:
    """Generate initial workflow code and commit it."""
    settings = get_settings()

    # Get sample content for the builder
    samples = [d for d in documents if d.is_sample][:3]
    sample_content = ""
    for doc in samples:
        pages = doc.parse_result.get("pages", []) if doc.parse_result else []
        text = "\n".join(p.get("text", "") for p in pages[:2])
        sample_content += f"--- {doc.filename} ---\n{truncate_text(text, 1500)}\n\n"

    console.print("\n[blue]Generating workflow code...[/blue]")

    code, usage = generate_initial_workflow(
        schema=schema,
        sample_content=sample_content,
        analysis={
            "document_type": analysis.document_type,
            "language": analysis.language,
            "structure_description": analysis.structure_description,
            "key_sections": analysis.key_sections,
            "complexity": analysis.complexity,
        },
    )

    # Commit to git
    task_name = sanitize_task_name(task.name)
    module_path, commit_hash = commit_workflow(
        task_name=task_name,
        version=1,
        code=code,
        message=f"[{task_name}] Initial workflow v1 (bootstrap)",
    )

    # Store in DB
    wv = WorkflowVersion(
        task_id=task.id,
        version=1,
        git_commit_hash=commit_hash,
        module_path=module_path,
        model_assignments={},
        is_active=True,
    )
    session.add(wv)
    session.flush()

    # Record evolution event
    event = EvolutionEvent(
        task_id=task.id,
        event_type=EventType.BOOTSTRAP,
        iteration=0,
        trigger={"type": "bootstrap", "description": task.description},
        mutation={"workflow_version": 1, "schema_version": 1},
        outcome={"status": "success", "llm_usage": usage},
    )
    session.add(event)
    session.flush()

    console.print(f"[green]Workflow v1 generated and committed ({commit_hash})[/green]")
    return wv


def run_bootstrap(
    session: Session,
    description: str,
    input_path: Path,
    max_samples: int = 10,
) -> Task:
    """Run the full bootstrap sequence for a new task."""
    settings = get_settings()
    task_name = sanitize_task_name(description)

    console.print(f"\n[bold blue]== Bootstrapping new task: {task_name} ==[/bold blue]\n")

    # 1. Create task
    task = Task(
        name=task_name,
        description=description,
        status=TaskStatus.BOOTSTRAPPING,
        iteration=0,
        max_iteration=settings.max_iterations,
        language=settings.ae_language,
    )
    session.add(task)
    session.flush()

    # 2. Ingest documents
    console.print("[bold]Step 1: Ingesting documents...[/bold]")
    documents = ingest_documents(session, task, input_path, max_samples)

    # 3. Analyze documents
    console.print("\n[bold]Step 2: Analyzing documents...[/bold]")
    analysis = analyze_documents(session, task, documents)

    # 4. Propose schema
    console.print("\n[bold]Step 3: Proposing extraction schema...[/bold]")
    schema = propose_schema(session, task, analysis)

    # 5. Generate workflow
    console.print("\n[bold]Step 4: Generating extraction workflow...[/bold]")
    wv = generate_workflow(session, task, schema, analysis, documents)

    # Update task status
    task.status = TaskStatus.RUNNING
    task.iteration = 0
    session.flush()

    console.print(f"\n[bold green]Bootstrap complete! Task '{task_name}' is ready.[/bold green]")
    console.print(f"  Run extraction: ae run {task_name}")
    console.print(f"  View schema: ae schema {task_name}")
    console.print(f"  View status: ae status {task_name}")

    return task
