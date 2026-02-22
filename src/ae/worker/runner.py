"""Dynamic workflow loader and executor."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress
from sqlalchemy.orm import Session

from ae.config import get_settings
from ae.builder.analyzer import get_corner_cases
from ae.builder.pattern_lib import find_matching_patterns
from ae.builder.schema_mgr import get_active_schema
from ae.models import (
    Document,
    Extraction,
    Task,
    WorkflowVersion,
)
from ae.pdf import extract_filename_metadata
from ae.shared.types import ExtractionResult, WorkflowContext
import ae.llm as llm_module

logger = logging.getLogger(__name__)
console = Console()


def load_workflow_module(module_path: str, task_name: str, version: int):
    """Dynamically load a workflow module from the workflows directory."""
    settings = get_settings()
    filepath = settings.workflows_path / task_name / f"extract_v{version}.py"

    if not filepath.exists():
        raise FileNotFoundError(f"Workflow not found: {filepath}")

    module_name = f"workflow_{task_name}_v{version}"

    spec = importlib.util.spec_from_file_location(module_name, str(filepath))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load workflow module: {filepath}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    if not hasattr(module, "extract"):
        raise AttributeError(f"Workflow module missing 'extract' function: {filepath}")

    return module


def build_workflow_context(
    session: Session,
    document: Document,
    schema_def: dict[str, Any],
    workflow_version: WorkflowVersion,
    task: Task,
) -> WorkflowContext:
    """Build a WorkflowContext for a document."""
    settings = get_settings()

    pages = []
    if document.parse_result:
        pages = document.parse_result.get("pages", [])

    corner_cases = get_corner_cases(session, task.id)
    patterns = find_matching_patterns(session)
    filename_meta = extract_filename_metadata(document.filename)

    return WorkflowContext(
        pages=pages,
        schema=schema_def,
        llm_client=llm_module,
        pdf_path=document.file_path,
        parse_result=document.parse_result or {},
        corner_cases=corner_cases,
        shared_patterns=patterns,
        model_tiers=settings.worker_model_tiers,
        model_assignments=workflow_version.model_assignments or {},
        filename_metadata=filename_meta,
        task_config=task.config or {},
    )


def run_extraction(
    session: Session,
    task: Task,
    documents: list[Document] | None = None,
    workflow_version: WorkflowVersion | None = None,
) -> list[Extraction]:
    """Run extraction workflow on documents.

    If documents is None, runs on all task documents.
    If workflow_version is None, uses the active one.
    """
    settings = get_settings()

    # Get active schema
    schema_ver = get_active_schema(session, task.id)
    if schema_ver is None:
        raise ValueError(f"No active schema for task {task.name}")

    # Get active workflow
    if workflow_version is None:
        workflow_version = (
            session.query(WorkflowVersion)
            .filter_by(task_id=task.id, is_active=True)
            .first()
        )
    if workflow_version is None:
        raise ValueError(f"No active workflow for task {task.name}")

    # Load workflow module
    task_name = task.name
    module = load_workflow_module(
        workflow_version.module_path, task_name, workflow_version.version
    )

    # Get documents
    if documents is None:
        documents = session.query(Document).filter_by(task_id=task.id).all()

    extractions = []
    console.print(f"\n[blue]Running extraction (workflow v{workflow_version.version}) on {len(documents)} documents...[/blue]")

    with Progress(console=console) as progress:
        task_progress = progress.add_task("Extracting...", total=len(documents))

        for doc in documents:
            progress.update(task_progress, description=f"[cyan]{doc.filename[:50]}...")

            try:
                context = build_workflow_context(
                    session, doc, schema_ver.schema_def, workflow_version, task
                )

                result: ExtractionResult = module.extract(context)

                extraction = Extraction(
                    document_id=doc.id,
                    workflow_version_id=workflow_version.id,
                    schema_version_id=schema_ver.id,
                    iteration=task.iteration,
                    result=result.fields,
                    field_confidences=result.field_confidences,
                    overall_confidence=_compute_overall_confidence(result.field_confidences),
                    llm_calls=result.llm_calls or context._llm_calls,
                    llm_tokens_used=result.llm_tokens or context._llm_tokens,
                    status="completed",
                )
            except Exception as e:
                logger.error("Extraction failed for %s: %s", doc.filename, e, exc_info=True)
                extraction = Extraction(
                    document_id=doc.id,
                    workflow_version_id=workflow_version.id,
                    schema_version_id=schema_ver.id,
                    iteration=task.iteration,
                    result=None,
                    field_confidences=None,
                    overall_confidence=0.0,
                    llm_calls=0,
                    llm_tokens_used=0,
                    status="failed",
                    error=str(e),
                )

            session.add(extraction)
            extractions.append(extraction)
            progress.advance(task_progress)

    session.flush()

    completed = sum(1 for e in extractions if e.status == "completed")
    failed = sum(1 for e in extractions if e.status == "failed")
    console.print(f"[green]Extraction complete: {completed} success, {failed} failed[/green]")

    return extractions


def run_extraction_single(
    session: Session,
    task: Task,
    document: Document,
    workflow_version: WorkflowVersion | None = None,
) -> Extraction:
    """Run extraction on a single document."""
    results = run_extraction(session, task, [document], workflow_version)
    return results[0] if results else None


def _compute_overall_confidence(field_confidences: dict[str, float] | None) -> float:
    """Compute overall confidence from field confidences."""
    if not field_confidences:
        return 0.0
    values = [v for v in field_confidences.values() if isinstance(v, (int, float))]
    return sum(values) / len(values) if values else 0.0
