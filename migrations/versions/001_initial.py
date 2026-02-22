"""Initial migration: create all tables.

Revision ID: 001
Revises: None
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("bootstrapping", "running", "evolving", "completed", "failed", name="taskstatus"), nullable=False, server_default="bootstrapping"),
        sa.Column("iteration", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_iteration", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("language", sa.String(20), nullable=False, server_default="bilingual"),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("parse_method", sa.String(50), nullable=True),
        sa.Column("parse_result", sa.JSON(), nullable=True),
        sa.Column("is_sample", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("metadata_extracted", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "schema_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_def", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("git_commit_hash", sa.String(40), nullable=True),
        sa.Column("module_path", sa.Text(), nullable=False),
        sa.Column("pipeline_nodes", sa.JSON(), nullable=True),
        sa.Column("confidence_config", sa.JSON(), nullable=True),
        sa.Column("model_assignments", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "extractions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("workflow_version_id", sa.Integer(), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("schema_version_id", sa.Integer(), sa.ForeignKey("schema_versions.id"), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("field_confidences", sa.JSON(), nullable=True),
        sa.Column("overall_confidence", sa.Float(), nullable=True),
        sa.Column("llm_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "observer_judgments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("extraction_id", sa.Integer(), sa.ForeignKey("extractions.id"), nullable=False),
        sa.Column("result", sa.Enum("correct", "partial", "incorrect", "missing", name="judgmentresult"), nullable=False),
        sa.Column("field_judgments", sa.JSON(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("used_vision", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("sampling_method", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "feedback_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("judgment_id", sa.Integer(), sa.ForeignKey("observer_judgments.id"), nullable=False),
        sa.Column("feedback_type", sa.Enum("correction", "approval", "rejection", "comment", name="feedbacktype"), nullable=False),
        sa.Column("field_name", sa.String(255), nullable=True),
        sa.Column("original_value", sa.Text(), nullable=True),
        sa.Column("corrected_value", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "evolution_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("event_type", sa.Enum("bootstrap", "schema_update", "workflow_update", "model_downgrade", "code_migration", "corner_case_added", "pattern_promoted", "evolution_triggered", name="eventtype"), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.JSON(), nullable=True),
        sa.Column("mutation", sa.JSON(), nullable=True),
        sa.Column("outcome", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "shared_patterns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("implementation", sa.Text(), nullable=False),
        sa.Column("implementation_type", sa.String(20), nullable=False, server_default="code"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "corner_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("field_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolution_type", sa.String(20), nullable=False, server_default="prompt"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("corner_cases")
    op.drop_table("shared_patterns")
    op.drop_table("evolution_events")
    op.drop_table("feedback_records")
    op.drop_table("observer_judgments")
    op.drop_table("extractions")
    op.drop_table("workflow_versions")
    op.drop_table("schema_versions")
    op.drop_table("documents")
    op.drop_table("tasks")

    op.execute("DROP TYPE IF EXISTS taskstatus")
    op.execute("DROP TYPE IF EXISTS judgmentresult")
    op.execute("DROP TYPE IF EXISTS feedbacktype")
    op.execute("DROP TYPE IF EXISTS eventtype")
