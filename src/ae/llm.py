"""LLM client wrapper with multi-provider support via LiteLLM."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import litellm

from ae.config import get_settings

logger = logging.getLogger(__name__)

# Suppress litellm's verbose default logging
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

_initialized = False

# Known provider prefixes that LiteLLM handles natively
_KNOWN_PREFIXES = (
    "openai/",
    "anthropic/",
    "openrouter/",
    "gemini/",
    "mistral/",
    "groq/",
    "deepseek/",
    "together_ai/",
    "bedrock/",
    "vertex_ai/",
    "azure/",
    "cohere/",
    "replicate/",
    "huggingface/",
    "ollama/",
    "perplexity/",
)


def _ensure_initialized() -> None:
    """Set up LiteLLM with provider API keys from settings (once)."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    settings = get_settings()

    # Drop unsupported params (e.g. response_format) instead of erroring
    litellm.drop_params = True

    # Set provider API keys so LiteLLM can route to them
    if settings.siliconflow_api_key:
        # SiliconFlow is OpenAI-compatible; no special litellm env var needed.
        # Handled in _resolve_model via api_base + api_key.
        pass
    if settings.openai_api_key:
        litellm.openai_key = settings.openai_api_key
    if settings.anthropic_api_key:
        litellm.anthropic_key = settings.anthropic_api_key
    if settings.openrouter_api_key:
        litellm.openrouter_api_key = settings.openrouter_api_key


def _resolve_model(model: str) -> tuple[str, dict[str, Any]]:
    """Resolve a model name to (litellm_model, extra_kwargs).

    - If model has a known provider prefix (e.g. "openai/gpt-4o") → pass through.
    - If no prefix → route via ae_default_provider setting (default: siliconflow).

    For SiliconFlow, we use the "openai/" prefix with a custom api_base + api_key
    since SiliconFlow exposes an OpenAI-compatible endpoint.
    """
    settings = get_settings()
    extra: dict[str, Any] = {}

    # Check if model already has a known provider prefix
    for prefix in _KNOWN_PREFIXES:
        if model.startswith(prefix):
            return model, extra

    # No prefix — route through default provider
    provider = settings.ae_default_provider.lower().strip()

    if provider == "siliconflow":
        # SiliconFlow is OpenAI-compatible: use openai/ prefix with custom base
        extra["api_base"] = settings.siliconflow_base_url
        extra["api_key"] = settings.siliconflow_api_key
        return f"openai/{model}", extra
    elif provider == "openai":
        return f"openai/{model}", extra
    elif provider == "anthropic":
        return f"anthropic/{model}", extra
    elif provider == "openrouter":
        return f"openrouter/{model}", extra
    elif provider == "gemini":
        return f"gemini/{model}", extra
    elif provider == "mistral":
        return f"mistral/{model}", extra
    elif provider == "groq":
        return f"groq/{model}", extra
    elif provider == "deepseek":
        return f"deepseek/{model}", extra
    else:
        # Unknown provider — try as openai-compatible with base URL
        extra["api_base"] = settings.siliconflow_base_url
        extra["api_key"] = settings.siliconflow_api_key
        return f"openai/{model}", extra


def chat(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    response_format: dict | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Send a chat completion request and return the response with usage info."""
    _ensure_initialized()
    settings = get_settings()
    model = model or settings.ae_worker_model

    resolved_model, extra_kwargs = _resolve_model(model)

    request_kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        request_kwargs["response_format"] = response_format
    request_kwargs.update(extra_kwargs)
    request_kwargs.update(kwargs)

    logger.debug("LLM call: model=%s (resolved=%s), messages=%d", model, resolved_model, len(messages))

    response = litellm.completion(**request_kwargs)

    choice = response.choices[0]
    usage = response.usage

    return {
        "content": choice.message.content or "",
        "finish_reason": choice.finish_reason,
        "tokens_prompt": usage.prompt_tokens if usage else 0,
        "tokens_completion": usage.completion_tokens if usage else 0,
        "tokens_total": usage.total_tokens if usage else 0,
        "model": model,
    }


def chat_json(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    **kwargs,
) -> dict[str, Any]:
    """Chat with JSON response format. Returns parsed JSON plus usage info."""
    try:
        result = chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            **kwargs,
        )
    except Exception:
        # Fallback: some models don't support response_format
        logger.debug("JSON mode not supported, falling back to plain chat")
        # Add JSON instruction to the last user message
        patched = list(messages)
        if patched and patched[-1]["role"] == "user":
            patched[-1] = {**patched[-1], "content": patched[-1]["content"] + "\n\nRespond with valid JSON only, no other text."}
        result = chat(
            messages=patched,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    parsed = _parse_json_response(result["content"])
    result["parsed"] = parsed
    return result


def _parse_json_response(content: str) -> dict:
    """Robustly parse JSON from LLM response, handling markdown fences and other wrappers."""
    content = content.strip()

    # Strip markdown code fences
    if content.startswith("```"):
        lines = content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    # Try direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object
    start = content.find("{")
    end = content.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(content[start:end])
        except json.JSONDecodeError:
            pass

    # Try to find JSON array
    start = content.find("[")
    end = content.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            return {"items": json.loads(content[start:end])}
        except json.JSONDecodeError:
            pass

    return {"raw": content, "_parse_error": True}


def chat_vision(
    messages: list[dict[str, Any]],
    images: list[str | Path] | None = None,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    **kwargs,
) -> dict[str, Any]:
    """Chat with vision capabilities. Images can be file paths or base64 strings."""
    settings = get_settings()
    model = model or settings.ae_observer_vision_model

    if images:
        # Build the content with images for the last user message
        last_user_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user":
                last_user_idx = i
                break

        if last_user_idx is not None:
            content_parts = []
            # Add text
            text = messages[last_user_idx].get("content", "")
            if isinstance(text, str):
                content_parts.append({"type": "text", "text": text})
            elif isinstance(text, list):
                content_parts.extend(text)

            # Add images
            for img in images:
                if isinstance(img, str) and img.startswith("data:"):
                    # Already a data URI
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": img},
                    })
                elif isinstance(img, (str, Path)) and Path(img).exists():
                    img_data = Path(img).read_bytes()
                    b64 = base64.b64encode(img_data).decode()
                    suffix = Path(img).suffix.lower().lstrip(".")
                    media_type = f"image/{suffix}" if suffix != "jpg" else "image/jpeg"
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{b64}",
                        },
                    })

            messages = messages.copy()
            messages[last_user_idx] = {
                **messages[last_user_idx],
                "content": content_parts,
            }

    return chat(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )


def make_cache_key(messages: list[dict], model: str) -> str:
    """Create a hash key for caching LLM responses."""
    content = json.dumps({"messages": messages, "model": model}, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()
