"""Shared type definitions, protocols, and TypedDicts."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict


# --- Workflow Contract ---

class WorkflowContext:
    """Context object passed to workflow extract() functions."""

    def __init__(
        self,
        pages: list[dict[str, Any]],
        schema: dict[str, Any],
        llm_client: Any,
        pdf_path: str,
        parse_result: dict[str, Any],
        corner_cases: list[dict[str, Any]] | None = None,
        shared_patterns: list[dict[str, Any]] | None = None,
        model_tiers: list[str] | None = None,
        model_assignments: dict[str, str] | None = None,
        filename_metadata: dict[str, str] | None = None,
        task_config: dict[str, Any] | None = None,
    ):
        self.pages = pages
        self.schema = schema
        self.llm = llm_client
        self.pdf_path = pdf_path
        self.parse_result = parse_result
        self.corner_cases = corner_cases or []
        self.shared_patterns = shared_patterns or []
        self.model_tiers = model_tiers or []
        self.model_assignments = model_assignments or {}
        self.filename_metadata = filename_metadata or {}
        self.task_config = task_config or {}
        self._llm_calls = 0
        self._llm_tokens = 0

    def get_model_for_field(self, field_name: str) -> str:
        """Get the assigned model for a field, or the default worker model."""
        return self.model_assignments.get(field_name, self.model_tiers[0] if self.model_tiers else "")

    def track_llm_usage(self, calls: int = 1, tokens: int = 0):
        self._llm_calls += calls
        self._llm_tokens += tokens


@dataclass
class ExtractionResult:
    """Result returned by workflow extract() functions."""

    fields: dict[str, Any]
    field_confidences: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    llm_calls: int = 0
    llm_tokens: int = 0
    errors: list[str] = field(default_factory=list)


class WorkflowProtocol(Protocol):
    """Protocol that workflow modules must implement."""

    def extract(self, context: WorkflowContext) -> ExtractionResult: ...


# --- Schema Types ---

class FieldType(str, enum.Enum):
    STRING = "string"
    NUMBER = "number"
    DATE = "date"
    LIST = "list"
    BOOLEAN = "boolean"
    OBJECT = "object"
    TEXT = "text"  # Long-form text


class SchemaField(TypedDict, total=False):
    name: str
    type: str
    description: str
    description_zh: str
    required: bool
    examples: list[str]
    extraction_hint: str


class SchemaDefinition(TypedDict, total=False):
    fields: list[SchemaField]
    version: int
    description: str
    description_zh: str


# --- Observer Types ---

class FieldJudgment(TypedDict, total=False):
    field_name: str
    result: str  # correct, partial, incorrect, missing
    expected: str
    actual: str
    reasoning: str
    score: float


class JudgmentSummary(TypedDict, total=False):
    overall_result: str
    overall_score: float
    field_judgments: list[FieldJudgment]
    reasoning: str
    used_vision: bool


# --- Builder Types ---

class IssueType(str, enum.Enum):
    SYSTEMIC = "systemic"
    CORNER_CASE = "corner_case"


@dataclass
class DiagnosisResult:
    issue_type: IssueType
    affected_fields: list[str]
    affected_percentage: float
    description: str
    suggested_fix: str
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DocumentAnalysis:
    """Result of Builder analyzing sample documents."""
    document_type: str
    language: str
    structure_description: str
    key_sections: list[str]
    suggested_fields: list[SchemaField]
    complexity: str  # low, medium, high
    notes: list[str] = field(default_factory=list)
