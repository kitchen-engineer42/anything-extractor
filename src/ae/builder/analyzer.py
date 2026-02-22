"""Builder analyzer: diagnoses systemic vs corner-case issues."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from ae.config import get_settings
from ae.llm import chat_json
from ae.models import (
    CornerCase,
    Extraction,
    ObserverJudgment,
    Task,
)
from ae.shared.prompts import get_prompt
from ae.shared.types import DiagnosisResult, IssueType

logger = logging.getLogger(__name__)


def diagnose_issues(
    session: Session,
    task: Task,
    workflow_code: str,
    schema: dict[str, Any],
    failed_extractions: list[dict[str, Any]],
    judgments: list[dict[str, Any]],
) -> DiagnosisResult:
    """Analyze failed extractions and diagnose root cause."""
    settings = get_settings()

    prompt = get_prompt(
        "builder_diagnose_issues",
        failed_extractions=json.dumps(failed_extractions[:10], ensure_ascii=False, indent=2),
        judgments=json.dumps(judgments[:10], ensure_ascii=False, indent=2),
        schema=json.dumps(schema, ensure_ascii=False, indent=2),
        workflow_code=workflow_code[:5000],
    )

    result = chat_json(
        messages=[
            {"role": "system", "content": "You are an expert at diagnosing data extraction pipeline issues."},
            {"role": "user", "content": prompt},
        ],
        model=settings.ae_builder_model,
        temperature=0.1,
        max_tokens=4096,
    )

    parsed = result["parsed"]

    issue_type = IssueType.SYSTEMIC if parsed.get("issue_type") == "systemic" else IssueType.CORNER_CASE

    return DiagnosisResult(
        issue_type=issue_type,
        affected_fields=parsed.get("affected_fields", []),
        affected_percentage=parsed.get("affected_percentage", 0.0),
        description=parsed.get("description", ""),
        suggested_fix=parsed.get("suggested_fix", ""),
        evidence=parsed.get("evidence", []),
    )


def add_corner_case(
    session: Session,
    task_id: int,
    field_name: str,
    description: str,
    pattern: str | None = None,
    resolution: str | None = None,
    resolution_type: str = "prompt",
) -> CornerCase:
    """Add a corner case to the database."""
    cc = CornerCase(
        task_id=task_id,
        field_name=field_name,
        description=description,
        pattern=pattern,
        resolution=resolution,
        resolution_type=resolution_type,
    )
    session.add(cc)
    session.flush()
    logger.info("Added corner case for field '%s' in task %d", field_name, task_id)
    return cc


def get_corner_cases(session: Session, task_id: int) -> list[dict[str, Any]]:
    """Get all corner cases for a task as dicts."""
    cases = session.query(CornerCase).filter_by(task_id=task_id).all()
    return [
        {
            "field_name": c.field_name,
            "description": c.description,
            "pattern": c.pattern,
            "resolution": c.resolution,
            "resolution_type": c.resolution_type,
        }
        for c in cases
    ]


def collect_failed_extractions(
    session: Session,
    task_id: int,
    iteration: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect failed/partial extractions and their judgments for a task iteration.

    Returns (failed_extractions, judgments).
    """
    extractions = (
        session.query(Extraction)
        .join(Extraction.document)
        .filter(
            Extraction.iteration == iteration,
            Extraction.document.has(task_id=task_id),
        )
        .all()
    )

    failed = []
    judg_list = []

    for ext in extractions:
        judgments = (
            session.query(ObserverJudgment)
            .filter_by(extraction_id=ext.id)
            .all()
        )
        for j in judgments:
            if j.result.value in ("incorrect", "partial"):
                failed.append({
                    "extraction_id": ext.id,
                    "document_filename": ext.document.filename,
                    "result": ext.result,
                    "field_confidences": ext.field_confidences,
                })
                judg_list.append({
                    "extraction_id": ext.id,
                    "result": j.result.value,
                    "field_judgments": j.field_judgments,
                    "reasoning": j.reasoning,
                    "overall_score": j.overall_score,
                })

    return failed, judg_list
