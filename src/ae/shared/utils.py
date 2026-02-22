"""Shared utility functions."""

from __future__ import annotations

import ast
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def sanitize_task_name(description: str) -> str:
    """Convert a task description into a valid directory/identifier name."""
    # Remove non-alphanumeric chars except Chinese characters and spaces
    name = re.sub(r"[^\w\s\u4e00-\u9fff-]", "", description)
    # Replace spaces with underscores
    name = re.sub(r"\s+", "_", name.strip())
    # Truncate
    if len(name) > 60:
        name = name[:60]
    return name.lower() if name.isascii() else name


def validate_python_code(code: str) -> tuple[bool, str]:
    """Validate Python code via AST parsing. Returns (is_valid, error_message)."""
    try:
        tree = ast.parse(code)
        # Check that extract() function exists
        has_extract = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "extract":
                has_extract = True
                break
        if not has_extract:
            return False, "Missing required 'extract' function"
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"


def truncate_text(text: str, max_chars: int = 3000) -> str:
    """Truncate text to max_chars, adding ellipsis if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def safe_json_loads(text: str) -> dict[str, Any]:
    """Try to parse JSON from text, handling common LLM output issues."""
    text = text.strip()

    # Remove markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last line if they are fences
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    # Try to find JSON array
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            return {"items": json.loads(text[start:end])}
        except json.JSONDecodeError:
            pass

    return {"raw": text, "_parse_error": True}


def format_schema_for_display(schema: dict[str, Any]) -> str:
    """Format a schema definition for human-readable display."""
    lines = []
    fields = schema.get("fields", [])
    for f in fields:
        name = f.get("name", "?")
        ftype = f.get("type", "string")
        desc = f.get("description_zh", f.get("description", ""))
        required = "required" if f.get("required") else "optional"
        lines.append(f"  {name} ({ftype}, {required}): {desc}")
    return "\n".join(lines)


def collect_pdf_files(input_path: Path) -> list[Path]:
    """Collect all PDF files from a path (file or directory, recursive)."""
    input_path = Path(input_path)
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.rglob("*.pdf")) + sorted(input_path.rglob("*.PDF"))
    return []
