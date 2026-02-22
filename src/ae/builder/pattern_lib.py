"""Shared pattern library management (EvoMap-inspired)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from ae.models import SharedPattern

logger = logging.getLogger(__name__)


def find_matching_patterns(
    session: Session,
    category: str | None = None,
    min_confidence: float = 0.6,
) -> list[dict[str, Any]]:
    """Find patterns matching criteria, ordered by confidence."""
    query = session.query(SharedPattern).filter(
        SharedPattern.confidence >= min_confidence
    )
    if category:
        query = query.filter_by(category=category)

    patterns = query.order_by(SharedPattern.confidence.desc()).all()
    return [
        {
            "name": p.name,
            "category": p.category,
            "description": p.description,
            "implementation": p.implementation,
            "implementation_type": p.implementation_type,
            "confidence": p.confidence,
            "usage_count": p.usage_count,
            "success_count": p.success_count,
        }
        for p in patterns
    ]


def promote_pattern(
    session: Session,
    name: str,
    category: str,
    description: str,
    implementation: str,
    implementation_type: str = "code",
) -> SharedPattern:
    """Promote a successful extraction pattern to the shared library."""
    existing = session.query(SharedPattern).filter_by(name=name).first()
    if existing:
        existing.implementation = implementation
        existing.implementation_type = implementation_type
        existing.description = description
        session.flush()
        logger.info("Updated shared pattern: %s", name)
        return existing

    pattern = SharedPattern(
        name=name,
        category=category,
        description=description,
        implementation=implementation,
        implementation_type=implementation_type,
        confidence=0.5,
        usage_count=0,
        success_count=0,
    )
    session.add(pattern)
    session.flush()
    logger.info("Promoted new shared pattern: %s", name)
    return pattern


def update_pattern_stats(
    session: Session,
    name: str,
    success: bool,
) -> None:
    """Update usage and success counts for a pattern."""
    pattern = session.query(SharedPattern).filter_by(name=name).first()
    if pattern:
        pattern.usage_count += 1
        if success:
            pattern.success_count += 1
        # Update confidence based on success rate
        if pattern.usage_count > 0:
            pattern.confidence = pattern.success_count / pattern.usage_count
        session.flush()


def list_all_patterns(session: Session) -> list[dict[str, Any]]:
    """List all patterns in the library."""
    patterns = (
        session.query(SharedPattern)
        .order_by(SharedPattern.confidence.desc())
        .all()
    )
    return [
        {
            "name": p.name,
            "category": p.category,
            "description": p.description,
            "implementation_type": p.implementation_type,
            "confidence": p.confidence,
            "usage_count": p.usage_count,
            "success_count": p.success_count,
        }
        for p in patterns
    ]
