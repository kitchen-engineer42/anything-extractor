"""Per-field confidence scoring."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default weights for confidence components
DEFAULT_WEIGHTS = {
    "llm_self_confidence": 0.3,
    "extraction_method_prior": 0.15,
    "historical_accuracy": 0.25,
    "source_text_clarity": 0.2,
    "corner_case_match": 0.1,
}


def compute_field_confidence(
    field_name: str,
    extracted_value: Any,
    llm_confidence: float = 0.5,
    method_prior: float = 0.7,
    historical_accuracy: float | None = None,
    source_text_present: bool = True,
    corner_case_matched: bool = False,
    weights: dict[str, float] | None = None,
) -> float:
    """Compute composite confidence score for a single field.

    Components:
    1. LLM self-confidence (from the model's own assessment)
    2. Extraction method prior (regex=high, LLM=medium, etc.)
    3. Historical accuracy (from past extractions if available)
    4. Source text clarity (was source text found?)
    5. Corner case match (penalize if it matches a known edge case)
    """
    w = weights or DEFAULT_WEIGHTS

    # Null values get very low confidence
    if extracted_value is None:
        return 0.1

    scores = {
        "llm_self_confidence": llm_confidence,
        "extraction_method_prior": method_prior,
        "historical_accuracy": historical_accuracy if historical_accuracy is not None else 0.5,
        "source_text_clarity": 0.8 if source_text_present else 0.2,
        "corner_case_match": 0.3 if corner_case_matched else 0.7,
    }

    total = sum(w.get(k, 0) * scores.get(k, 0.5) for k in w)
    return min(max(total, 0.0), 1.0)


def compute_extraction_confidences(
    fields: dict[str, Any],
    schema: dict[str, Any],
    llm_confidences: dict[str, float] | None = None,
    method_priors: dict[str, float] | None = None,
    historical: dict[str, float] | None = None,
) -> dict[str, float]:
    """Compute confidence scores for all fields in an extraction."""
    llm_confidences = llm_confidences or {}
    method_priors = method_priors or {}
    historical = historical or {}

    confidences = {}
    for field_def in schema.get("fields", []):
        name = field_def.get("name", "")
        value = fields.get(name)

        confidences[name] = compute_field_confidence(
            field_name=name,
            extracted_value=value,
            llm_confidence=llm_confidences.get(name, 0.5),
            method_prior=method_priors.get(name, 0.7),
            historical_accuracy=historical.get(name),
            source_text_present=value is not None,
        )

    return confidences


def calibrate_weights(
    judgments: list[dict[str, Any]],
    current_weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """Adjust confidence weights based on observer judgments.

    Simple approach: increase weight of components that correlate with correct judgments.
    """
    weights = dict(current_weights or DEFAULT_WEIGHTS)

    if not judgments:
        return weights

    # For now, return default weights
    # Future: implement gradient-based weight adjustment
    return weights
