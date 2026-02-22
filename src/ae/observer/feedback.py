"""CLI feedback recorder for human corrections."""

from __future__ import annotations

import json
import logging
from typing import Any

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table
from sqlalchemy.orm import Session

from ae.models import (
    Document,
    Extraction,
    FeedbackRecord,
    FeedbackType,
    ObserverJudgment,
    SchemaVersion,
    Task,
)

logger = logging.getLogger(__name__)
console = Console()


def interactive_feedback(
    session: Session,
    task: Task,
) -> list[FeedbackRecord]:
    """Interactive feedback mode: show extractions and collect corrections."""
    # Get latest extractions with judgments
    schema_ver = (
        session.query(SchemaVersion)
        .filter_by(task_id=task.id, is_active=True)
        .first()
    )
    if not schema_ver:
        console.print("[red]No active schema found[/red]")
        return []

    fields = schema_ver.schema_def.get("fields", [])
    field_names = [f.get("name", "") for f in fields]

    # Get extractions that have judgments
    extractions = (
        session.query(Extraction, Document, ObserverJudgment)
        .join(Document, Extraction.document_id == Document.id)
        .join(ObserverJudgment, ObserverJudgment.extraction_id == Extraction.id)
        .filter(Document.task_id == task.id)
        .order_by(ObserverJudgment.overall_score.asc())
        .limit(20)
        .all()
    )

    if not extractions:
        console.print("[yellow]No extractions with judgments found. Run 'ae observe' first.[/yellow]")
        return []

    records = []
    for ext, doc, judgment in extractions:
        console.print(f"\n[bold]Document: {doc.filename}[/bold]")
        console.print(f"Score: {judgment.overall_score:.2f} | Result: {judgment.result.value}")

        # Show extraction as table
        table = Table(show_header=True)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_column("Confidence")

        result = ext.result or {}
        confidences = ext.field_confidences or {}
        for fname in field_names:
            val = result.get(fname, "")
            if isinstance(val, (list, dict)):
                val = json.dumps(val, ensure_ascii=False)
            conf = confidences.get(fname, 0)
            conf_color = "green" if conf > 0.8 else "yellow" if conf > 0.5 else "red"
            table.add_row(fname, str(val)[:100], f"[{conf_color}]{conf:.2f}[/{conf_color}]")

        console.print(table)

        # Ask for feedback
        action = Prompt.ask(
            "Action",
            choices=["approve", "correct", "reject", "skip", "quit"],
            default="skip",
        )

        if action == "quit":
            break
        elif action == "skip":
            continue
        elif action == "approve":
            record = FeedbackRecord(
                judgment_id=judgment.id,
                feedback_type=FeedbackType.APPROVAL,
                comment="User approved",
            )
            session.add(record)
            records.append(record)
        elif action == "reject":
            comment = Prompt.ask("Reason for rejection", default="")
            record = FeedbackRecord(
                judgment_id=judgment.id,
                feedback_type=FeedbackType.REJECTION,
                comment=comment,
            )
            session.add(record)
            records.append(record)
        elif action == "correct":
            # Allow field-level correction
            field = Prompt.ask(
                "Which field to correct?",
                choices=field_names + ["cancel"],
                default="cancel",
            )
            if field != "cancel":
                original = str(result.get(field, ""))
                console.print(f"Current value: {original}")
                corrected = Prompt.ask("Corrected value")
                comment = Prompt.ask("Comment (optional)", default="")
                record = FeedbackRecord(
                    judgment_id=judgment.id,
                    feedback_type=FeedbackType.CORRECTION,
                    field_name=field,
                    original_value=original,
                    corrected_value=corrected,
                    comment=comment,
                )
                session.add(record)
                records.append(record)

    session.flush()
    console.print(f"\n[green]Recorded {len(records)} feedback entries[/green]")
    return records
