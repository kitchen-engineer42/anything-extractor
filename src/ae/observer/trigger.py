"""Trigger logic: when to call Builder for evolution."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from ae.models import (
    JudgmentResult,
    ObserverJudgment,
    Task,
    TaskStatus,
)

logger = logging.getLogger(__name__)

# Thresholds
QUALITY_THRESHOLD = 0.75  # Below this triggers evolution
INCORRECT_THRESHOLD = 0.10  # More than 10% incorrect triggers evolution
MIN_JUDGMENTS = 3  # Need at least this many judgments to trigger


def should_trigger_evolution(
    session: Session,
    task: Task,
    judgments: list[ObserverJudgment],
) -> tuple[bool, dict[str, Any]]:
    """Determine if Builder should be triggered for evolution.

    Returns (should_trigger, trigger_info).
    """
    if task.iteration >= task.max_iteration:
        logger.info("Max iterations reached (%d), no evolution", task.max_iteration)
        return False, {"reason": "max_iterations_reached"}

    if task.status == TaskStatus.EVOLVING:
        logger.info("Task already evolving, skip trigger")
        return False, {"reason": "already_evolving"}

    if len(judgments) < MIN_JUDGMENTS:
        logger.info("Too few judgments (%d), skip trigger", len(judgments))
        return False, {"reason": "insufficient_judgments", "count": len(judgments)}

    # Compute metrics
    scores = [j.overall_score for j in judgments if j.overall_score is not None]
    avg_score = sum(scores) / len(scores) if scores else 0.5

    total = len(judgments)
    incorrect = sum(1 for j in judgments if j.result == JudgmentResult.INCORRECT)
    partial = sum(1 for j in judgments if j.result == JudgmentResult.PARTIAL)
    correct = sum(1 for j in judgments if j.result == JudgmentResult.CORRECT)

    incorrect_rate = incorrect / total if total > 0 else 0
    quality_ok = avg_score >= QUALITY_THRESHOLD and incorrect_rate <= INCORRECT_THRESHOLD

    trigger_info = {
        "avg_score": avg_score,
        "incorrect_rate": incorrect_rate,
        "correct": correct,
        "partial": partial,
        "incorrect": incorrect,
        "total": total,
    }

    if quality_ok:
        logger.info(
            "Quality OK (score=%.2f, incorrect=%.0f%%), no evolution needed",
            avg_score, incorrect_rate * 100,
        )
        trigger_info["reason"] = "quality_ok"
        return False, trigger_info

    # Quality drop detected
    logger.info(
        "Quality drop detected (score=%.2f, incorrect=%.0f%%), triggering evolution",
        avg_score, incorrect_rate * 100,
    )
    trigger_info["reason"] = "quality_drop"
    return True, trigger_info


def compute_quality_metrics(
    judgments: list[ObserverJudgment],
) -> dict[str, Any]:
    """Compute detailed quality metrics from judgments."""
    if not judgments:
        return {"empty": True}

    scores = [j.overall_score for j in judgments if j.overall_score is not None]
    avg_score = sum(scores) / len(scores) if scores else 0

    # Per-field analysis
    field_stats: dict[str, dict[str, Any]] = {}
    for j in judgments:
        if not j.field_judgments:
            continue
        for fj in j.field_judgments:
            fname = fj.get("field_name", "unknown")
            if fname not in field_stats:
                field_stats[fname] = {"correct": 0, "partial": 0, "incorrect": 0, "missing": 0, "total": 0, "scores": []}
            field_stats[fname]["total"] += 1
            result = fj.get("result", "partial")
            if result in field_stats[fname]:
                field_stats[fname][result] += 1
            score = fj.get("score")
            if score is not None:
                field_stats[fname]["scores"].append(score)

    # Compute per-field averages
    for fname, stats in field_stats.items():
        scores = stats.pop("scores", [])
        stats["avg_score"] = sum(scores) / len(scores) if scores else 0
        stats["accuracy"] = stats["correct"] / stats["total"] if stats["total"] > 0 else 0

    return {
        "avg_score": avg_score,
        "total_judgments": len(judgments),
        "correct": sum(1 for j in judgments if j.result == JudgmentResult.CORRECT),
        "partial": sum(1 for j in judgments if j.result == JudgmentResult.PARTIAL),
        "incorrect": sum(1 for j in judgments if j.result == JudgmentResult.INCORRECT),
        "field_stats": field_stats,
    }
