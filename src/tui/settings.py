"""LLM settings persistence — API key, endpoint, model selection.

Settings are stored as JSON in a settings directory so they persist across
sessions. The file is loaded on app startup and used to configure the LLM
adapter. Keys are never written to the engine state or save files.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator


class LLMSettings(BaseModel):
    """User-configurable LLM connection settings.

    Attributes:
        provider: Model provider (``"anthropic"``, ``"openai"``, ``"groq"``,
            ``"custom"``). Default ``"anthropic"``.
        model: Model identifier without provider prefix
            (e.g. ``"claude-sonnet-5"``, ``"gpt-4o"``).
        api_key: API key for the provider. Stored locally only.
        base_url: Optional custom endpoint URL (for proxies, local LLMs,
            OpenAI-compatible endpoints). When set, the appropriate
            ``*_BASE_URL`` env var is populated at adapter creation time.
        max_retries: Max retries on invalid LLM output before template fallback.
    """

    provider: str = "anthropic"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    max_retries: int = 3

    @field_validator("base_url")
    @classmethod
    def base_url_must_be_http_or_https(cls, v: str) -> str:
        """Reject non-http(s) schemes to prevent SSRF via the base URL field."""
        if not v:
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"Base URL must use http or https scheme, got '{parsed.scheme}'"
            )
        if not parsed.netloc:
            raise ValueError("Base URL must include a host")
        return v

    @property
    def is_configured(self) -> bool:
        """Whether enough info is present to attempt an LLM connection."""
        return bool(self.model and self.api_key)

    @property
    def model_string(self) -> str | None:
        """Pydantic AI model string (``"provider:model"``) or None."""
        if not self.model:
            return None
        return f"{self.provider}:{self.model}"

    def env_overrides(self) -> dict[str, str]:
        """Return environment variables to set before creating the adapter.

        Maps api_key and base_url to the provider-specific env vars that
        Pydantic AI's provider clients read.
        """
        env: dict[str, str] = {}
        if self.api_key:
            env[self._key_env_name()] = self.api_key
        if self.base_url:
            env[self._base_url_env_name()] = self.base_url
        return env

    def _key_env_name(self) -> str:
        return {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "groq": "GROQ_API_KEY",
        }.get(self.provider, "API_KEY")

    def _base_url_env_name(self) -> str:
        return {
            "anthropic": "ANTHROPIC_BASE_URL",
            "openai": "OPENAI_BASE_URL",
            "groq": "GROQ_BASE_URL",
        }.get(self.provider, "BASE_URL")


#: Default settings directory — alongside saves, in the project root.
DEFAULT_SETTINGS_DIR: Path = Path("settings")


def settings_path(settings_dir: str | Path = DEFAULT_SETTINGS_DIR) -> Path:
    """Return the path to the LLM settings JSON file."""
    return Path(settings_dir) / "llm.json"


def load_settings(settings_dir: str | Path = DEFAULT_SETTINGS_DIR) -> LLMSettings:
    """Load LLM settings from disk, or return defaults if none exist."""
    path = settings_path(settings_dir)
    if not path.exists():
        return LLMSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LLMSettings.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        return LLMSettings()


def save_settings(
    settings: LLMSettings, settings_dir: str | Path = DEFAULT_SETTINGS_DIR
) -> Path:
    """Persist LLM settings to disk atomically.

    The file is given restrictive permissions (0600) because it contains the
    API key in plaintext. For stronger protection, consider integrating the
    system keyring — but for a single-player local game, file permissions are
    the pragmatic baseline.
    """
    path = settings_path(settings_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(settings.model_dump(), indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)
    # Restrict to owner-only — the file contains an API key.
    os.chmod(path, 0o600)
    return path


#: Common model presets shown in the settings screen dropdown.
MODEL_PRESETS: dict[str, list[str]] = {
    "anthropic": [
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-haiku-4-5-20251001",
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
    ],
    "groq": [
        "llama-3.3-70b-versatile",
    ],
}
