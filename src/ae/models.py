"""SQLAlchemy ORM models for all core tables."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --- Enums ---

class TaskStatus(str, enum.Enum):
    BOOTSTRAPPING = "bootstrapping"
    RUNNING = "running"
    EVOLVING = "evolving"
    COMPLETED = "completed"
    FAILED = "failed"


class JudgmentResult(str, enum.Enum):
    CORRECT = "correct"
    PARTIAL = "partial"
    INCORRECT = "incorrect"
    MISSING = "missing"


class FeedbackType(str, enum.Enum):
    CORRECTION = "correction"
    APPROVAL = "approval"
    REJECTION = "rejection"
    COMMENT = "comment"


class EventType(str, enum.Enum):
    BOOTSTRAP = "bootstrap"
    SCHEMA_UPDATE = "schema_update"
    WORKFLOW_UPDATE = "workflow_update"
    MODEL_DOWNGRADE = "model_downgrade"
    CODE_MIGRATION = "code_migration"
    CORNER_CASE_ADDED = "corner_case_added"
    PATTERN_PROMOTED = "pattern_promoted"
    EVOLUTION_TRIGGERED = "evolution_triggered"


# --- Models ---

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.BOOTSTRAPPING, nullable=False
    )
    iteration: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_iteration: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="bilingual", nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    documents: Mapped[list[Document]] = relationship(back_populates="task")
    schema_versions: Mapped[list[SchemaVersion]] = relationship(back_populates="task")
    workflow_versions: Mapped[list[WorkflowVersion]] = relationship(back_populates="task")
    evolution_events: Mapped[list[EvolutionEvent]] = relationship(back_populates="task")
    corner_cases: Mapped[list[CornerCase]] = relationship(back_populates="task")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parse_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parse_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_extracted: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    task: Mapped[Task] = relationship(back_populates="documents")
    extractions: Mapped[list[Extraction]] = relationship(back_populates="document")


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_def: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    task: Mapped[Task] = relationship(back_populates="schema_versions")
    extractions: Mapped[list[Extraction]] = relationship(back_populates="schema_version")


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    git_commit_hash: Mapped[str | None] = mapped_column(String(40), nullable=True)
    module_path: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_nodes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_assignments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    task: Mapped[Task] = relationship(back_populates="workflow_versions")
    extractions: Mapped[list[Extraction]] = relationship(back_populates="workflow_version")


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    workflow_version_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_versions.id"), nullable=False
    )
    schema_version_id: Mapped[int] = mapped_column(
        ForeignKey("schema_versions.id"), nullable=False
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    field_confidences: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="extractions")
    workflow_version: Mapped[WorkflowVersion] = relationship(back_populates="extractions")
    schema_version: Mapped[SchemaVersion] = relationship(back_populates="extractions")
    judgments: Mapped[list[ObserverJudgment]] = relationship(back_populates="extraction")


class ObserverJudgment(Base):
    __tablename__ = "observer_judgments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    extraction_id: Mapped[int] = mapped_column(
        ForeignKey("extractions.id"), nullable=False
    )
    result: Mapped[JudgmentResult] = mapped_column(
        Enum(JudgmentResult), nullable=False
    )
    field_judgments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    used_vision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sampling_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    extraction: Mapped[Extraction] = relationship(back_populates="judgments")
    feedback_records: Mapped[list[FeedbackRecord]] = relationship(
        back_populates="judgment"
    )


class FeedbackRecord(Base):
    __tablename__ = "feedback_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    judgment_id: Mapped[int] = mapped_column(
        ForeignKey("observer_judgments.id"), nullable=False
    )
    feedback_type: Mapped[FeedbackType] = mapped_column(
        Enum(FeedbackType), nullable=False
    )
    field_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    judgment: Mapped[ObserverJudgment] = relationship(back_populates="feedback_records")


class EvolutionEvent(Base):
    __tablename__ = "evolution_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    event_type: Mapped[EventType] = mapped_column(Enum(EventType), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mutation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outcome: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    task: Mapped[Task] = relationship(back_populates="evolution_events")


class SharedPattern(Base):
    __tablename__ = "shared_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    implementation: Mapped[str] = mapped_column(Text, nullable=False)
    implementation_type: Mapped[str] = mapped_column(
        String(20), default="code", nullable=False
    )  # code, regex, prompt
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class CornerCase(Base):
    __tablename__ = "corner_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_type: Mapped[str] = mapped_column(
        String(20), default="prompt", nullable=False
    )  # prompt, code, regex
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    task: Mapped[Task] = relationship(back_populates="corner_cases")
