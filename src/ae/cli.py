"""Typer CLI entry point for Anything Extractor."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="ae",
    help="Anything Extractor - Self-adaptive data extraction from PDFs",
    no_args_is_help=True,
)
console = Console()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def _get_task(session, name: str):
    """Get task by name, with error handling."""
    from ae.models import Task

    task = session.query(Task).filter_by(name=name).first()
    if not task:
        # Try partial match
        tasks = session.query(Task).filter(Task.name.contains(name)).all()
        if len(tasks) == 1:
            return tasks[0]
        elif len(tasks) > 1:
            console.print(f"[yellow]Multiple tasks match '{name}':[/yellow]")
            for t in tasks:
                console.print(f"  - {t.name}")
            raise typer.Exit(1)
        console.print(f"[red]Task not found: {name}[/red]")
        raise typer.Exit(1)
    return task


@app.command()
def new(
    description: str = typer.Argument(..., help="Task description (what to extract)"),
    input_path: Path = typer.Option(..., "--input", "-i", help="Path to PDF files"),
    max_samples: int = typer.Option(10, "--samples", "-s", help="Max sample documents for analysis"),
):
    """Create a new extraction task and run bootstrap."""
    from ae.builder.bootstrap import run_bootstrap
    from ae.db import get_session, init_db

    # Ensure tables exist
    init_db()

    if not input_path.exists():
        console.print(f"[red]Input path not found: {input_path}[/red]")
        raise typer.Exit(1)

    with get_session() as session:
        task = run_bootstrap(session, description, input_path, max_samples)
        console.print(f"\n[bold green]Task created: {task.name}[/bold green]")


@app.command()
def run(
    task_name: str = typer.Argument(..., help="Task name"),
    input_path: Optional[Path] = typer.Option(None, "--input", "-i", help="Additional PDFs to ingest"),
    observe: bool = typer.Option(True, "--observe/--no-observe", help="Run observer after extraction"),
    evolve: bool = typer.Option(False, "--evolve/--no-evolve", help="Auto-evolve if quality drops"),
):
    """Run extraction on task documents."""
    from ae.builder.bootstrap import ingest_documents
    from ae.db import get_session
    from ae.observer.judge import run_observer
    from ae.observer.trigger import should_trigger_evolution
    from ae.worker.runner import run_extraction

    with get_session() as session:
        task = _get_task(session, task_name)

        # Ingest new documents if provided
        if input_path:
            console.print(f"[blue]Ingesting new documents from {input_path}...[/blue]")
            ingest_documents(session, task, input_path)

        # Run extraction
        extractions = run_extraction(session, task)

        # Run observer
        if observe and extractions:
            judgments = run_observer(session, task, extractions)

            # Check if evolution is needed
            if evolve and judgments:
                should_evolve, trigger_info = should_trigger_evolution(session, task, judgments)
                if should_evolve:
                    console.print("\n[yellow]Quality drop detected, triggering evolution...[/yellow]")
                    _run_evolution(session, task)


@app.command()
def status(
    task_name: Optional[str] = typer.Argument(None, help="Task name (omit for all tasks)"),
):
    """Show task status, accuracy, and cost metrics."""
    from ae.db import get_session
    from ae.models import Document, Extraction, ObserverJudgment, Task

    with get_session() as session:
        if task_name:
            task = _get_task(session, task_name)
            _show_task_detail(session, task)
        else:
            tasks = session.query(Task).order_by(Task.created_at.desc()).all()
            if not tasks:
                console.print("[yellow]No tasks found. Create one with 'ae new'[/yellow]")
                return

            table = Table(title="Tasks")
            table.add_column("Name", style="cyan")
            table.add_column("Status")
            table.add_column("Iteration")
            table.add_column("Documents")
            table.add_column("Created")

            for t in tasks:
                doc_count = session.query(Document).filter_by(task_id=t.id).count()
                status_color = {
                    "running": "green",
                    "bootstrapping": "yellow",
                    "evolving": "blue",
                    "completed": "bold green",
                    "failed": "red",
                }.get(t.status.value, "white")
                table.add_row(
                    t.name,
                    f"[{status_color}]{t.status.value}[/{status_color}]",
                    f"{t.iteration}/{t.max_iteration}",
                    str(doc_count),
                    t.created_at.strftime("%Y-%m-%d %H:%M"),
                )
            console.print(table)


@app.command()
def observe(
    task_name: str = typer.Argument(..., help="Task name"),
    full: bool = typer.Option(False, "--full", help="Evaluate all extractions (ignore sampling)"),
    vision: bool = typer.Option(False, "--vision", help="Use vision model for evaluation"),
):
    """Trigger observer evaluation."""
    from ae.db import get_session
    from ae.observer.judge import run_observer

    with get_session() as session:
        task = _get_task(session, task_name)
        judgments = run_observer(session, task, force_full=full, use_vision=vision)

        if judgments:
            from ae.observer.trigger import compute_quality_metrics
            metrics = compute_quality_metrics(judgments)
            console.print(f"\n[bold]Quality Metrics:[/bold]")
            console.print(f"  Average score: {metrics.get('avg_score', 0):.2f}")
            console.print(f"  Correct: {metrics.get('correct', 0)}")
            console.print(f"  Partial: {metrics.get('partial', 0)}")
            console.print(f"  Incorrect: {metrics.get('incorrect', 0)}")


@app.command()
def feedback(
    task_name: str = typer.Argument(..., help="Task name"),
):
    """Interactive feedback mode for human corrections."""
    from ae.db import get_session
    from ae.observer.feedback import interactive_feedback

    with get_session() as session:
        task = _get_task(session, task_name)
        interactive_feedback(session, task)


@app.command(name="evolve")
def evolve_cmd(
    task_name: str = typer.Argument(..., help="Task name"),
):
    """Manually trigger builder evolution."""
    from ae.db import get_session

    with get_session() as session:
        task = _get_task(session, task_name)
        _run_evolution(session, task)


@app.command()
def export(
    task_name: str = typer.Argument(..., help="Task name"),
    format: str = typer.Option("json", "--format", "-f", help="Output format (json|excel)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Export extraction results."""
    from ae.db import get_session
    from ae.worker.postprocess import export_excel, export_json

    with get_session() as session:
        task = _get_task(session, task_name)

        if format == "json":
            path = export_json(session, task, output)
        elif format == "excel":
            path = export_excel(session, task, output)
        else:
            console.print(f"[red]Unknown format: {format}. Use 'json' or 'excel'.[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Exported to: {path}[/green]")


@app.command()
def schema(
    task_name: str = typer.Argument(..., help="Task name"),
):
    """Show current extraction schema."""
    from ae.builder.schema_mgr import get_active_schema, get_schema_history
    from ae.db import get_session

    with get_session() as session:
        task = _get_task(session, task_name)
        sv = get_active_schema(session, task.id)

        if not sv:
            console.print("[yellow]No active schema found[/yellow]")
            return

        console.print(f"\n[bold]Schema v{sv.version} (active)[/bold]")
        fields = sv.schema_def.get("fields", [])

        table = Table()
        table.add_column("Field", style="cyan")
        table.add_column("Type")
        table.add_column("Required")
        table.add_column("Description")

        for f in fields:
            table.add_row(
                f.get("name", ""),
                f.get("type", "string"),
                "[red]*[/red]" if f.get("required") else "",
                f.get("description_zh", f.get("description", "")),
            )
        console.print(table)


@app.command()
def history(
    task_name: str = typer.Argument(..., help="Task name"),
):
    """Show evolution history."""
    from ae.db import get_session
    from ae.models import EvolutionEvent

    with get_session() as session:
        task = _get_task(session, task_name)
        events = (
            session.query(EvolutionEvent)
            .filter_by(task_id=task.id)
            .order_by(EvolutionEvent.created_at.asc())
            .all()
        )

        if not events:
            console.print("[yellow]No evolution events found[/yellow]")
            return

        table = Table(title=f"Evolution History: {task.name}")
        table.add_column("Iteration")
        table.add_column("Event")
        table.add_column("Trigger")
        table.add_column("Outcome")
        table.add_column("Time")

        for e in events:
            trigger_str = ""
            if e.trigger:
                trigger_str = e.trigger.get("reason", e.trigger.get("type", ""))
            outcome_str = ""
            if e.outcome:
                outcome_str = e.outcome.get("status", "")
            table.add_row(
                str(e.iteration),
                e.event_type.value,
                trigger_str,
                outcome_str,
                e.created_at.strftime("%Y-%m-%d %H:%M"),
            )
        console.print(table)


@app.command()
def workflow(
    task_name: str = typer.Argument(..., help="Task name"),
    diff: Optional[str] = typer.Option(None, "--diff", help="Diff two versions (e.g., '1 2')"),
):
    """Show or diff workflow code."""
    from ae.builder.git_ops import get_workflow_code, get_workflow_diff, list_workflow_versions
    from ae.db import get_session
    from ae.shared.utils import sanitize_task_name

    with get_session() as session:
        task = _get_task(session, task_name)
        safe_name = sanitize_task_name(task.name)

        if diff:
            parts = diff.split()
            if len(parts) != 2:
                console.print("[red]Usage: --diff 'v1 v2' (e.g., --diff '1 2')[/red]")
                raise typer.Exit(1)
            v1, v2 = int(parts[0]), int(parts[1])
            diff_text = get_workflow_diff(safe_name, v1, v2)
            console.print(diff_text)
        else:
            versions = list_workflow_versions(safe_name)
            if not versions:
                console.print("[yellow]No workflows found[/yellow]")
                return

            latest = max(versions)
            code = get_workflow_code(safe_name, latest)
            console.print(f"\n[bold]Workflow v{latest}:[/bold]\n")
            from rich.syntax import Syntax
            syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
            console.print(syntax)


@app.command()
def patterns():
    """List shared pattern library."""
    from ae.builder.pattern_lib import list_all_patterns
    from ae.db import get_session

    with get_session() as session:
        pats = list_all_patterns(session)

        if not pats:
            console.print("[yellow]No shared patterns found[/yellow]")
            return

        table = Table(title="Shared Pattern Library")
        table.add_column("Name", style="cyan")
        table.add_column("Category")
        table.add_column("Type")
        table.add_column("Confidence")
        table.add_column("Usage")
        table.add_column("Success Rate")

        for p in pats:
            success_rate = p["success_count"] / p["usage_count"] if p["usage_count"] > 0 else 0
            table.add_row(
                p["name"],
                p["category"],
                p["implementation_type"],
                f"{p['confidence']:.2f}",
                str(p["usage_count"]),
                f"{success_rate:.0%}",
            )
        console.print(table)


def _show_task_detail(session, task):
    """Show detailed task status."""
    from ae.models import Document, Extraction, ObserverJudgment, WorkflowVersion
    from ae.builder.schema_mgr import get_active_schema
    from ae.observer.trigger import compute_quality_metrics

    doc_count = session.query(Document).filter_by(task_id=task.id).count()
    sample_count = session.query(Document).filter_by(task_id=task.id, is_sample=True).count()
    ext_count = session.query(Extraction).join(Document).filter(Document.task_id == task.id).count()

    active_wf = session.query(WorkflowVersion).filter_by(task_id=task.id, is_active=True).first()
    active_schema = get_active_schema(session, task.id)

    console.print(f"\n[bold]Task: {task.name}[/bold]")
    console.print(f"  Description: {task.description}")
    console.print(f"  Status: {task.status.value}")
    console.print(f"  Iteration: {task.iteration}/{task.max_iteration}")
    console.print(f"  Language: {task.language}")
    console.print(f"  Documents: {doc_count} ({sample_count} samples)")
    console.print(f"  Extractions: {ext_count}")

    if active_wf:
        console.print(f"  Active workflow: v{active_wf.version} ({active_wf.git_commit_hash})")
    if active_schema:
        field_count = len(active_schema.schema_def.get("fields", []))
        console.print(f"  Active schema: v{active_schema.version} ({field_count} fields)")

    # Quality metrics from latest judgments
    latest_judgments = (
        session.query(ObserverJudgment)
        .join(Extraction)
        .join(Document)
        .filter(Document.task_id == task.id)
        .order_by(ObserverJudgment.created_at.desc())
        .limit(50)
        .all()
    )

    if latest_judgments:
        metrics = compute_quality_metrics(latest_judgments)
        console.print(f"\n[bold]Quality (last {len(latest_judgments)} judgments):[/bold]")
        console.print(f"  Average score: {metrics.get('avg_score', 0):.2f}")
        console.print(f"  Correct: {metrics.get('correct', 0)} | Partial: {metrics.get('partial', 0)} | Incorrect: {metrics.get('incorrect', 0)}")

        # Per-field breakdown
        field_stats = metrics.get("field_stats", {})
        if field_stats:
            table = Table(title="Field Quality")
            table.add_column("Field", style="cyan")
            table.add_column("Accuracy")
            table.add_column("Avg Score")

            for fname, stats in sorted(field_stats.items()):
                acc = stats.get("accuracy", 0)
                acc_color = "green" if acc > 0.8 else "yellow" if acc > 0.5 else "red"
                table.add_row(
                    fname,
                    f"[{acc_color}]{acc:.0%}[/{acc_color}]",
                    f"{stats.get('avg_score', 0):.2f}",
                )
            console.print(table)

    # Cost metrics
    total_tokens = (
        session.query(Extraction)
        .join(Document)
        .filter(Document.task_id == task.id)
        .with_entities(Extraction.llm_tokens_used)
        .all()
    )
    total = sum(t[0] for t in total_tokens if t[0])
    total_calls = (
        session.query(Extraction)
        .join(Document)
        .filter(Document.task_id == task.id)
        .with_entities(Extraction.llm_calls)
        .all()
    )
    calls = sum(c[0] for c in total_calls if c[0])
    if total > 0:
        console.print(f"\n[bold]Cost:[/bold]")
        console.print(f"  Total LLM calls: {calls}")
        console.print(f"  Total tokens: {total:,}")


def _run_evolution(session, task):
    """Run a full evolution cycle: diagnose → fix → re-run → re-observe."""
    from ae.builder.analyzer import collect_failed_extractions, diagnose_issues, add_corner_case, get_corner_cases
    from ae.builder.codegen import modify_workflow
    from ae.builder.git_ops import commit_workflow, get_workflow_code
    from ae.builder.schema_mgr import get_active_schema
    from ae.models import (
        EventType,
        EvolutionEvent,
        TaskStatus,
        WorkflowVersion,
    )
    from ae.shared.types import IssueType
    from ae.shared.utils import sanitize_task_name
    from ae.worker.runner import run_extraction
    from ae.observer.judge import run_observer

    task.status = TaskStatus.EVOLVING
    session.flush()

    console.print(f"\n[bold blue]== Evolution cycle for {task.name} (iteration {task.iteration}) ==[/bold blue]")

    # 1. Collect failed extractions
    failed, judgments = collect_failed_extractions(session, task.id, task.iteration)
    if not failed:
        console.print("[green]No failed extractions found. Quality is good![/green]")
        task.status = TaskStatus.RUNNING
        session.flush()
        return

    # 2. Diagnose
    console.print("[blue]Diagnosing issues...[/blue]")
    active_wf = session.query(WorkflowVersion).filter_by(task_id=task.id, is_active=True).first()
    active_schema = get_active_schema(session, task.id)

    if not active_wf or not active_schema:
        console.print("[red]No active workflow or schema found[/red]")
        task.status = TaskStatus.RUNNING
        session.flush()
        return

    safe_name = sanitize_task_name(task.name)
    current_code = get_workflow_code(safe_name, active_wf.version)

    diagnosis = diagnose_issues(
        session, task, current_code,
        active_schema.schema_def, failed, judgments,
    )

    console.print(f"  Issue type: {diagnosis.issue_type.value}")
    console.print(f"  Affected fields: {', '.join(diagnosis.affected_fields)}")
    console.print(f"  Description: {diagnosis.description}")

    # 3. Handle based on issue type
    corner_cases = get_corner_cases(session, task.id)

    if diagnosis.issue_type == IssueType.CORNER_CASE:
        # Add corner cases
        for field in diagnosis.affected_fields:
            add_corner_case(
                session, task.id, field,
                description=diagnosis.description,
                resolution=diagnosis.suggested_fix,
            )
        console.print(f"[yellow]Added {len(diagnosis.affected_fields)} corner cases[/yellow]")

    # 4. Generate new workflow
    console.print("[blue]Generating improved workflow...[/blue]")
    new_code, usage = modify_workflow(
        current_code=current_code,
        diagnosis={
            "issue_type": diagnosis.issue_type.value,
            "affected_fields": diagnosis.affected_fields,
            "description": diagnosis.description,
            "suggested_fix": diagnosis.suggested_fix,
        },
        schema=active_schema.schema_def,
        sample_failures=failed[:5],
        corner_cases=corner_cases,
    )

    # 5. Commit
    new_version = active_wf.version + 1
    module_path, commit_hash = commit_workflow(
        task_name=safe_name,
        version=new_version,
        code=new_code,
        message=f"[{safe_name}] Workflow v{new_version}: {diagnosis.issue_type.value} fix",
    )

    # Deactivate old, create new
    active_wf.is_active = False
    new_wv = WorkflowVersion(
        task_id=task.id,
        version=new_version,
        git_commit_hash=commit_hash,
        module_path=module_path,
        model_assignments=active_wf.model_assignments,
        is_active=True,
    )
    session.add(new_wv)
    session.flush()

    # Record event
    event = EvolutionEvent(
        task_id=task.id,
        event_type=EventType.WORKFLOW_UPDATE,
        iteration=task.iteration,
        trigger={
            "reason": diagnosis.issue_type.value,
            "affected_fields": diagnosis.affected_fields,
            "description": diagnosis.description,
        },
        mutation={"workflow_version": new_version, "commit": commit_hash},
        outcome={"status": "generated", "llm_usage": usage},
    )
    session.add(event)

    # 6. Increment iteration
    task.iteration += 1
    task.status = TaskStatus.RUNNING
    session.flush()

    console.print(f"[green]Evolution complete: workflow v{new_version} ({commit_hash})[/green]")
    console.print(f"[green]Iteration: {task.iteration}/{task.max_iteration}[/green]")

    # 7. Re-run on failed docs only
    console.print("\n[blue]Re-running extraction on previously failed documents...[/blue]")
    from ae.models import Document
    failed_doc_ids = list({f["extraction_id"] for f in failed})
    # Get the actual documents
    from ae.models import Extraction
    failed_docs = (
        session.query(Document)
        .join(Extraction)
        .filter(Extraction.id.in_([f["extraction_id"] for f in failed]))
        .distinct()
        .all()
    )
    if failed_docs:
        new_extractions = run_extraction(session, task, failed_docs, new_wv)
        # Re-observe
        if new_extractions:
            run_observer(session, task, new_extractions)


if __name__ == "__main__":
    app()
