"""Workflow code generation and modification using Builder LLM."""

from __future__ import annotations

import logging
from typing import Any

from ae.config import get_settings
from ae.llm import chat
from ae.shared.prompts import get_prompt
from ae.shared.utils import truncate_text, validate_python_code

logger = logging.getLogger(__name__)


def generate_initial_workflow(
    schema: dict[str, Any],
    sample_content: str,
    analysis: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Generate initial workflow code from schema and document analysis.

    Returns (code, llm_usage).
    """
    settings = get_settings()
    import json

    prompt = get_prompt(
        "builder_generate_workflow",
        schema=json.dumps(schema, ensure_ascii=False, indent=2),
        sample_content=truncate_text(sample_content, 6000),
        analysis=json.dumps(analysis, ensure_ascii=False, indent=2),
    )

    result = chat(
        messages=[
            {"role": "system", "content": "You are an expert Python developer specializing in data extraction pipelines. Generate clean, efficient Python code."},
            {"role": "user", "content": prompt},
        ],
        model=settings.ae_builder_model,
        temperature=0.2,
        max_tokens=8192,
    )

    code = result["content"].strip()

    # Strip markdown fences if present
    if code.startswith("```python"):
        code = code[len("```python"):].strip()
    if code.startswith("```"):
        code = code[3:].strip()
    if code.endswith("```"):
        code = code[:-3].strip()

    # Validate
    is_valid, error = validate_python_code(code)
    if not is_valid:
        logger.warning("Generated code validation failed: %s. Retrying...", error)
        # Retry with error feedback
        retry_result = chat(
            messages=[
                {"role": "system", "content": "You are an expert Python developer. Fix the code based on the error."},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": code},
                {"role": "user", "content": f"The code has an error: {error}\nPlease fix and regenerate the COMPLETE module. Only Python code, no markdown."},
            ],
            model=settings.ae_builder_model,
            temperature=0.1,
            max_tokens=8192,
        )
        code = retry_result["content"].strip()
        if code.startswith("```python"):
            code = code[len("```python"):].strip()
        if code.startswith("```"):
            code = code[3:].strip()
        if code.endswith("```"):
            code = code[:-3].strip()

        is_valid, error = validate_python_code(code)
        if not is_valid:
            raise ValueError(f"Generated code still invalid after retry: {error}")

    usage = {
        "tokens_total": result["tokens_total"],
        "model": result["model"],
    }
    return code, usage


def modify_workflow(
    current_code: str,
    diagnosis: dict[str, Any],
    schema: dict[str, Any],
    sample_failures: list[dict[str, Any]],
    corner_cases: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Modify existing workflow code to fix diagnosed issues.

    Returns (new_code, llm_usage).
    """
    settings = get_settings()
    import json

    prompt = get_prompt(
        "builder_modify_workflow",
        workflow_code=current_code,
        diagnosis=json.dumps(diagnosis, ensure_ascii=False, indent=2),
        schema=json.dumps(schema, ensure_ascii=False, indent=2),
        sample_failures=json.dumps(sample_failures[:5], ensure_ascii=False, indent=2),
        corner_cases=json.dumps(corner_cases, ensure_ascii=False, indent=2),
    )

    result = chat(
        messages=[
            {"role": "system", "content": "You are an expert Python developer. Modify the workflow code to fix the issues while preserving working functionality."},
            {"role": "user", "content": prompt},
        ],
        model=settings.ae_builder_model,
        temperature=0.2,
        max_tokens=8192,
    )

    code = result["content"].strip()
    if code.startswith("```python"):
        code = code[len("```python"):].strip()
    if code.startswith("```"):
        code = code[3:].strip()
    if code.endswith("```"):
        code = code[:-3].strip()

    is_valid, error = validate_python_code(code)
    if not is_valid:
        logger.warning("Modified code validation failed: %s. Retrying...", error)
        retry_result = chat(
            messages=[
                {"role": "system", "content": "Fix the Python code error."},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": code},
                {"role": "user", "content": f"Error: {error}\nRegenerate the COMPLETE module. Only Python code."},
            ],
            model=settings.ae_builder_model,
            temperature=0.1,
            max_tokens=8192,
        )
        code = retry_result["content"].strip()
        if code.startswith("```python"):
            code = code[len("```python"):].strip()
        if code.startswith("```"):
            code = code[3:].strip()
        if code.endswith("```"):
            code = code[:-3].strip()

        is_valid, error = validate_python_code(code)
        if not is_valid:
            raise ValueError(f"Modified code still invalid after retry: {error}")

    usage = {
        "tokens_total": result["tokens_total"],
        "model": result["model"],
    }
    return code, usage


def generate_cost_optimized_workflow(
    current_code: str,
    schema: dict[str, Any],
    field_accuracy: dict[str, dict[str, float]],
    model_tiers: list[str],
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Optimize workflow for cost: downgrade models per-field, migrate to code/regex.

    Returns (new_code, model_assignments, llm_usage).
    """
    settings = get_settings()
    import json

    # Determine model assignments based on accuracy
    model_assignments: dict[str, str] = {}
    for field_name, accuracies in field_accuracy.items():
        assigned_model = model_tiers[0]  # default to largest
        for tier_model in model_tiers:
            acc = accuracies.get(tier_model, 0.0)
            if acc >= 0.95:  # Safe threshold
                assigned_model = tier_model
        model_assignments[field_name] = assigned_model

    prompt = f"""Optimize this workflow for cost reduction.

Current code:
{current_code}

Field accuracy by model tier:
{json.dumps(field_accuracy, ensure_ascii=False, indent=2)}

Model tiers (largest to smallest): {model_tiers}

Suggested model assignments:
{json.dumps(model_assignments, ensure_ascii=False, indent=2)}

Rules:
1. For fields with deterministic patterns (dates, IDs, fixed formats), migrate to regex/Python code
2. Update model selection using context.get_model_for_field()
3. Keep LLM calls only for fields that need understanding
4. Preserve the extract() function signature

Generate the COMPLETE updated module. Only Python code."""

    result = chat(
        messages=[
            {"role": "system", "content": "You are a cost optimization expert for data extraction pipelines."},
            {"role": "user", "content": prompt},
        ],
        model=settings.ae_builder_model,
        temperature=0.2,
        max_tokens=8192,
    )

    code = result["content"].strip()
    if code.startswith("```python"):
        code = code[len("```python"):].strip()
    if code.startswith("```"):
        code = code[3:].strip()
    if code.endswith("```"):
        code = code[:-3].strip()

    usage = {"tokens_total": result["tokens_total"], "model": result["model"]}
    return code, model_assignments, usage
