"""LLM-as-Judge observer evaluation."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress
from sqlalchemy.orm import Session

from ae.config import get_settings
from ae.llm import chat_json, chat_vision
from ae.models import (
    Document,
    Extraction,
    JudgmentResult,
    ObserverJudgment,
    SchemaVersion,
    Task,
)
from ae.pdf import get_all_text, render_page_to_image
from ae.shared.prompts import get_prompt
from ae.shared.utils import truncate_text

from .sampler import select_samples

logger = logging.getLogger(__name__)
console = Console()


def judge_extraction(
    session: Session,
    extraction: Extraction,
    document: Document,
    schema: dict[str, Any],
    use_vision: bool = False,
    sampling_method: str = "full",
) -> ObserverJudgment:
    """Judge a single extraction result using LLM-as-Judge."""
    settings = get_settings()

    doc_text = get_all_text(document.parse_result or {})

    if use_vision and document.file_path and Path(document.file_path).exists():
        judgment_data = _judge_with_vision(
            extraction, document, schema, doc_text
        )
    else:
        judgment_data = _judge_text_only(
            extraction, schema, doc_text
        )

    # Map result string to enum
    result_str = judgment_data.get("overall_result", "partial")
    result_map = {
        "correct": JudgmentResult.CORRECT,
        "partial": JudgmentResult.PARTIAL,
        "incorrect": JudgmentResult.INCORRECT,
        "missing": JudgmentResult.MISSING,
    }
    result_enum = result_map.get(result_str, JudgmentResult.PARTIAL)

    judgment = ObserverJudgment(
        extraction_id=extraction.id,
        result=result_enum,
        field_judgments=judgment_data.get("field_judgments"),
        reasoning=judgment_data.get("reasoning", ""),
        used_vision=use_vision,
        overall_score=judgment_data.get("overall_score", 0.5),
        sampling_method=sampling_method,
    )
    session.add(judgment)
    session.flush()

    return judgment


def _judge_text_only(
    extraction: Extraction,
    schema: dict[str, Any],
    doc_text: str,
) -> dict[str, Any]:
    """Judge using text-only comparison."""
    settings = get_settings()

    prompt = get_prompt(
        "observer_judge_extraction",
        document_content=truncate_text(doc_text, 4000),
        schema=json.dumps(schema, ensure_ascii=False, indent=2),
        extraction_result=json.dumps(extraction.result or {}, ensure_ascii=False, indent=2),
    )

    result = chat_json(
        messages=[
            {"role": "system", "content": "You are a strict but fair quality judge for data extraction."},
            {"role": "user", "content": prompt},
        ],
        model=settings.ae_observer_model,
        temperature=0.1,
        max_tokens=4096,
    )

    return result["parsed"]


def _judge_with_vision(
    extraction: Extraction,
    document: Document,
    schema: dict[str, Any],
    doc_text: str,
) -> dict[str, Any]:
    """Judge using vision model (can see the actual PDF pages)."""
    settings = get_settings()

    prompt = get_prompt(
        "observer_judge_vision",
        extraction_result=json.dumps(extraction.result or {}, ensure_ascii=False, indent=2),
        schema=json.dumps(schema, ensure_ascii=False, indent=2),
    )

    # Render first page as image
    images = []
    try:
        pdf_path = Path(document.file_path)
        if pdf_path.exists():
            img_bytes = render_page_to_image(pdf_path, 1)
            b64 = base64.b64encode(img_bytes).decode()
            images.append(f"data:image/png;base64,{b64}")
    except Exception as e:
        logger.warning("Failed to render page image: %s", e)

    if not images:
        # Fallback to text-only
        return _judge_text_only(extraction, schema, doc_text)

    result = chat_vision(
        messages=[
            {"role": "system", "content": "You are a quality judge with vision. Compare extraction against the PDF."},
            {"role": "user", "content": prompt},
        ],
        images=images,
        model=settings.ae_observer_vision_model,
        temperature=0.1,
        max_tokens=4096,
    )

    try:
        parsed = json.loads(result["content"])
    except json.JSONDecodeError:
        content = result["content"]
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
        else:
            parsed = {"overall_result": "partial", "overall_score": 0.5, "reasoning": content}

    return parsed


def run_observer(
    session: Session,
    task: Task,
    extractions: list[Extraction] | None = None,
    force_full: bool = False,
    use_vision: bool = False,
) -> list[ObserverJudgment]:
    """Run observer evaluation on extractions."""
    settings = get_settings()

    # Get active schema
    schema_ver = (
        session.query(SchemaVersion)
        .filter_by(task_id=task.id, is_active=True)
        .first()
    )
    if not schema_ver:
        raise ValueError("No active schema found")

    # Get extractions if not provided
    if extractions is None:
        extractions = (
            session.query(Extraction)
            .join(Document)
            .filter(
                Document.task_id == task.id,
                Extraction.iteration == task.iteration,
            )
            .all()
        )

    if not extractions:
        console.print("[yellow]No extractions to evaluate[/yellow]")
        return []

    # Select samples
    selected, sampling_method = select_samples(
        extractions, task.iteration, force_full
    )

    console.print(
        f"\n[blue]Observer evaluating {len(selected)}/{len(extractions)} extractions "
        f"(method: {sampling_method})[/blue]"
    )

    # Use vision for bootstrap (iter 0) if fewer than 20 docs
    if task.iteration == 0 and len(selected) <= 20:
        use_vision = True

    judgments = []
    with Progress(console=console) as progress:
        judge_task = progress.add_task("Judging...", total=len(selected))

        for ext in selected:
            doc = session.query(Document).get(ext.document_id)
            progress.update(judge_task, description=f"[cyan]{doc.filename[:50]}...")

            try:
                judgment = judge_extraction(
                    session, ext, doc, schema_ver.schema_def,
                    use_vision=use_vision,
                    sampling_method=sampling_method,
                )
                judgments.append(judgment)
            except Exception as e:
                logger.error("Judgment failed for extraction %d: %s", ext.id, e)

            progress.advance(judge_task)

    # Summary
    scores = [j.overall_score for j in judgments if j.overall_score is not None]
    avg_score = sum(scores) / len(scores) if scores else 0
    correct = sum(1 for j in judgments if j.result == JudgmentResult.CORRECT)
    partial = sum(1 for j in judgments if j.result == JudgmentResult.PARTIAL)
    incorrect = sum(1 for j in judgments if j.result == JudgmentResult.INCORRECT)

    console.print(f"\n[bold]Observer Results:[/bold]")
    console.print(f"  Average score: {avg_score:.2f}")
    console.print(f"  Correct: {correct}, Partial: {partial}, Incorrect: {incorrect}")

    return judgments
