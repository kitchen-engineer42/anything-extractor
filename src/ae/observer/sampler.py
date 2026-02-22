"""Sampling strategy for observer evaluation."""

from __future__ import annotations

import logging
import random
from typing import Any

from ae.models import Extraction

logger = logging.getLogger(__name__)


def compute_sample_rate(iteration: int, total_judgments: int = 0) -> float:
    """Compute sampling rate based on iteration and history.

    Strategy:
    - Iteration 0: 100% (bootstrap)
    - Iteration 1-3: 50%
    - Iteration 4-9: 20%
    - Iteration 10+: 5% (minimum for regression detection)
    """
    if iteration <= 0:
        return 1.0
    elif iteration <= 3:
        return 0.5
    elif iteration <= 9:
        return 0.2
    else:
        return 0.05


def select_samples(
    extractions: list[Extraction],
    iteration: int,
    force_full: bool = False,
) -> tuple[list[Extraction], str]:
    """Select extractions to evaluate.

    Returns (selected_extractions, sampling_method).
    """
    if force_full or iteration <= 0:
        return extractions, "full"

    rate = compute_sample_rate(iteration)
    n_samples = max(1, int(len(extractions) * rate))

    # Priority sampling: prefer low-confidence and failed extractions
    priority = []
    normal = []

    for ext in extractions:
        if ext.status == "failed":
            priority.append(ext)
        elif ext.overall_confidence is not None and ext.overall_confidence < 0.6:
            priority.append(ext)
        else:
            normal.append(ext)

    selected = list(priority)
    remaining_slots = n_samples - len(selected)

    if remaining_slots > 0 and normal:
        selected.extend(random.sample(normal, min(remaining_slots, len(normal))))

    method = f"priority+random(rate={rate:.0%}, n={len(selected)}/{len(extractions)})"
    logger.info("Sampling: %s", method)
    return selected, method
