"""Schema versioning and management."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from ae.models import SchemaVersion

logger = logging.getLogger(__name__)


def create_schema_version(
    session: Session,
    task_id: int,
    schema_def: dict[str, Any],
) -> SchemaVersion:
    """Create a new schema version, deactivating previous ones."""
    # Get next version number
    latest = (
        session.query(SchemaVersion)
        .filter_by(task_id=task_id)
        .order_by(SchemaVersion.version.desc())
        .first()
    )
    next_version = (latest.version + 1) if latest else 1

    # Deactivate previous versions
    session.query(SchemaVersion).filter_by(task_id=task_id, is_active=True).update(
        {"is_active": False}
    )

    sv = SchemaVersion(
        task_id=task_id,
        version=next_version,
        schema_def=schema_def,
        is_active=True,
    )
    session.add(sv)
    session.flush()

    logger.info("Created schema version %d for task %d", next_version, task_id)
    return sv


def get_active_schema(session: Session, task_id: int) -> SchemaVersion | None:
    """Get the active schema version for a task."""
    return (
        session.query(SchemaVersion)
        .filter_by(task_id=task_id, is_active=True)
        .first()
    )


def get_schema_history(session: Session, task_id: int) -> list[SchemaVersion]:
    """Get all schema versions for a task, ordered by version."""
    return (
        session.query(SchemaVersion)
        .filter_by(task_id=task_id)
        .order_by(SchemaVersion.version.asc())
        .all()
    )


def diff_schemas(old_schema: dict, new_schema: dict) -> dict[str, Any]:
    """Compare two schemas and return the differences."""
    old_fields = {f["name"]: f for f in old_schema.get("fields", [])}
    new_fields = {f["name"]: f for f in new_schema.get("fields", [])}

    added = [f for name, f in new_fields.items() if name not in old_fields]
    removed = [f for name, f in old_fields.items() if name not in new_fields]
    modified = []

    for name in set(old_fields) & set(new_fields):
        if old_fields[name] != new_fields[name]:
            modified.append({
                "field": name,
                "old": old_fields[name],
                "new": new_fields[name],
            })

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
    }
