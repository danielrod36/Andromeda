"""AI provider configurations and model fetching.

Each provider entry defines:
- Pydantic AI model-string prefix (how Pydantic AI routes the request)
- API key and base URL env-var names
- Default base URL (pre-filled in the settings UI)
- Models-listing endpoint and auth-header format (for the fetch-models feature)
- Model name presets (fallback when the API can't be reached)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider configuration registry.
#
# ``pydantic_prefix`` determines the model string passed to Pydantic AI.
# OpenAI-compatible providers (DeepSeek, OpenRouter, Groq, Xiaomi) all use
# "openai" as the prefix and rely on OPENAI_BASE_URL / OPENAI_API_KEY env vars
# to point Pydantic AI's OpenAI client at the right endpoint.
# ---------------------------------------------------------------------------


PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "label": "Anthropic",
        "pydantic_prefix": "anthropic",
        "key_env": "ANTHROPIC_API_KEY",
        "base_url_env": "ANTHROPIC_BASE_URL",
        "default_base_url": "https://api.anthropic.com",
        "models_path": "/v1/models",
        "auth_header": "x-api-key",
        "auth_prefix": "",
        "extra_headers": {"anthropic-version": "2023-06-01"},
        "presets": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5-20251001"],
    },
    "openai": {
        "label": "OpenAI",
        "pydantic_prefix": "openai",
        "key_env": "OPENAI_API_KEY",
        "base_url_env": "OPENAI_BASE_URL",
        "default_base_url": "https://api.openai.com",
        "models_path": "/v1/models",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "presets": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
    },
    "deepseek": {
        "label": "DeepSeek",
        "pydantic_prefix": "openai",
        "key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "default_base_url": "https://api.deepseek.com",
        "models_path": "/v1/models",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "presets": ["deepseek-chat", "deepseek-reasoner"],
    },
    "openrouter": {
        "label": "OpenRouter",
        "pydantic_prefix": "openai",
        "key_env": "OPENROUTER_API_KEY",
        "base_url_env": "OPENROUTER_BASE_URL",
        "default_base_url": "https://openrouter.ai/api",
        "models_path": "/v1/models",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "presets": [
            "anthropic/claude-sonnet-5",
            "openai/gpt-4o",
            "deepseek/deepseek-chat",
        ],
    },
    "xiaomi_mimo": {
        "label": "Xiaomi MiMo",
        "pydantic_prefix": "openai",
        "key_env": "XIAOMI_MIMO_API_KEY",
        "base_url_env": "XIAOMI_MIMO_BASE_URL",
        "default_base_url": "",  # User must supply
        "models_path": "/v1/models",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "presets": ["mimo-7b", "mimo-8b"],
    },
    "groq": {
        "label": "Groq",
        "pydantic_prefix": "openai",
        "key_env": "GROQ_API_KEY",
        "base_url_env": "GROQ_BASE_URL",
        "default_base_url": "https://api.groq.com/openai",
        "models_path": "/v1/models",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "presets": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    },
    "custom": {
        "label": "Custom (OpenAI-compatible)",
        "pydantic_prefix": "openai",
        "key_env": "CUSTOM_API_KEY",
        "base_url_env": "CUSTOM_BASE_URL",
        "default_base_url": "",
        "models_path": "/v1/models",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "presets": [],
    },
}


def provider_labels() -> list[tuple[str, str]]:
    """Return (label, key) pairs for dropdown population."""
    return [(cfg["label"], key) for key, cfg in PROVIDER_CONFIGS.items()]


def get_provider_config(provider: str) -> dict[str, Any]:
    """Return config for a provider key, falling back to 'custom'."""
    return PROVIDER_CONFIGS.get(provider, PROVIDER_CONFIGS["custom"])


def models_endpoint(provider: str, base_url: str | None = None) -> str:
    """Build the full models-listing URL for a provider."""
    cfg = get_provider_config(provider)
    url = base_url or cfg["default_base_url"]
    if not url:
        return ""
    return url.rstrip("/") + cfg["models_path"]


# ---------------------------------------------------------------------------
# Model fetching — calls the provider's /models endpoint.
# ---------------------------------------------------------------------------


async def fetch_available_models(
    provider: str,
    api_key: str,
    base_url: str | None = None,
) -> list[str]:
    """Fetch the list of available model IDs from a provider.

    Returns a sorted list of model ID strings. Raises ``RuntimeError`` on
    network errors, auth failures, or unexpected response formats.
    """
    import httpx

    cfg = get_provider_config(provider)
    url = models_endpoint(provider, base_url)
    if not url:
        raise RuntimeError(
            f"No base URL configured for {cfg['label']}. "
            "Please enter a base URL."
        )

    headers: dict[str, str] = {}
    auth_header = cfg.get("auth_header", "Authorization")
    auth_prefix = cfg.get("auth_prefix", "Bearer ")
    headers[auth_header] = auth_prefix + api_key
    headers.update(cfg.get("extra_headers", {}))

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 401:
            raise RuntimeError("Authentication failed. Check your API key.") from exc
        elif status == 403:
            raise RuntimeError("Access denied. Your API key may lack permissions.") from exc
        elif 400 <= status < 500:
            raise RuntimeError(f"API request failed (HTTP {status}). Check your configuration.") from exc
        else:
            raise RuntimeError(f"API request failed (HTTP {status}). Try again later.") from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"Connection failed. Check your network and base URL.") from exc

    # Parse model IDs — most OpenAI-compatible APIs return {"data": [{"id": ...}]}.
    # Anthropic returns {"data": [{"id": ...}]} as well.
    models: list[str] = []
    if isinstance(data, dict) and "data" in data:
        for entry in data["data"]:
            if isinstance(entry, dict) and "id" in entry:
                models.append(entry["id"])
    elif isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and "id" in entry:
                models.append(entry["id"])
            elif isinstance(entry, str):
                models.append(entry)

    if not models:
        raise RuntimeError(
            "No models found in API response. "
            f"Unexpected format: {str(data)[:200]}"
        )

    return sorted(models)
