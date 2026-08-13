"""LLM settings persistence — API key, endpoint, model selection.

Settings are stored as JSON in a settings directory so they persist across
sessions. The API key is NOT stored in this file (M0.7, D7): it lives in the
OS keychain via ``keyring`` (service ``andromeda``), with an owner-only
(0600) fallback file on systems without a keychain. The ``api_key`` field
on :class:`LLMSettings` is runtime-only, resolved at load.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator

if TYPE_CHECKING:
    from src.llm.adapter import LLMAdapter

from src.llm.providers import PROVIDER_CONFIGS, get_provider_config


class LLMSettings(BaseModel):
    """User-configurable LLM connection settings.

    Attributes:
        provider: Provider key from :data:`PROVIDER_CONFIGS`.
        model: Model identifier without provider prefix.
        api_key: API key for the provider. Stored locally only.
        base_url: Optional custom endpoint URL.
        max_retries: Max retries on invalid LLM output before template fallback.
    """

    provider: str = "anthropic"
    model: str = ""
    api_key: str = ""
    key_backend: str = ""
    """Where the API key is stored: ``"keyring"`` | ``"file"`` | ``""`` (no key).
    The key itself is never persisted in this file (M0.7, D7)."""
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
            raise ValueError(f"Base URL must use http or https scheme, got '{parsed.scheme}'")
        if not parsed.netloc:
            raise ValueError("Base URL must include a host")
        return v

    @property
    def is_configured(self) -> bool:
        """Whether enough info is present to attempt an LLM connection."""
        cfg = get_provider_config(self.provider)
        needs_url = not cfg["default_base_url"]
        return bool(self.model and self.api_key and (self.base_url or not needs_url))

    @property
    def model_string(self) -> str | None:
        """Pydantic AI model string (``"prefix:model"``) or None."""
        if not self.model:
            return None
        cfg = get_provider_config(self.provider)
        return f"{cfg['pydantic_prefix']}:{self.model}"

    def effective_base_url(self) -> str:
        """The base URL to use — explicit override or provider default."""
        return self.base_url or get_provider_config(self.provider).get("default_base_url", "")

    def env_overrides(self) -> dict[str, str]:
        """Return environment variables to set before creating the adapter.

        Maps api_key and base_url to env vars for both the UI provider's
        own env name AND the Pydantic AI provider prefix's env name (so
        OpenAI-compatible providers like DeepSeek/OpenRouter correctly
        populate OPENAI_API_KEY / OPENAI_BASE_URL).
        """
        cfg = get_provider_config(self.provider)
        env: dict[str, str] = {}

        # Provider-specific key env var (e.g. DEEPSEEK_API_KEY).
        key_env = cfg["key_env"]
        base_env = cfg["base_url_env"]

        if self.api_key:
            env[key_env] = self.api_key
        url = self.effective_base_url()
        if url:
            env[base_env] = url

        # Also set Pydantic AI's provider prefix env vars so the model
        # string (e.g. "openai:deepseek-chat") finds the right endpoint.
        pydantic_prefix = cfg["pydantic_prefix"]
        pydantic_key_env = f"{pydantic_prefix.upper()}_API_KEY"
        pydantic_base_env = f"{pydantic_prefix.upper()}_BASE_URL"
        if pydantic_key_env != key_env and self.api_key:
            env[pydantic_key_env] = self.api_key
        if pydantic_base_env != base_env and url:
            env[pydantic_base_env] = url

        return env


#: Default settings directory — alongside saves, in the project root.
DEFAULT_SETTINGS_DIR: Path = Path("settings")


def settings_path(settings_dir: str | Path = DEFAULT_SETTINGS_DIR) -> Path:
    """Return the path to the LLM settings JSON file."""
    return Path(settings_dir) / "llm.json"


def load_settings(settings_dir: str | Path = DEFAULT_SETTINGS_DIR) -> LLMSettings:
    """Load LLM settings from disk and resolve the API key from the store.

    The on-disk file never contains the key (M0.7): the key is read from
    the OS keychain (or the 0600 fallback file) into the runtime-only
    ``api_key`` field. Legacy files that still hold a plaintext key are
    migrated: the key moves into the store and the file is rewritten
    scrubbed.
    """
    from src.llm.keystore import get_keystore

    path = settings_path(settings_dir)
    if not path.exists():
        return LLMSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        settings = LLMSettings.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        return LLMSettings()

    store = get_keystore(settings_dir)
    legacy_key = settings.api_key  # present only in pre-M0.7 files
    if legacy_key:
        try:
            store.set(settings.provider, legacy_key)
            settings.key_backend = store.backend_name
            # Rewrite scrubbed — the file must not keep the key.
            scrubbed = settings.model_copy(update={"api_key": ""})
            _write_settings_file(scrubbed, settings_dir)
        except Exception:
            pass  # degrade: keep the key in-memory, don't crash startup
    elif settings.key_backend:
        settings.api_key = store.get(settings.provider)
    return settings


def save_settings(settings: LLMSettings, settings_dir: str | Path = DEFAULT_SETTINGS_DIR) -> Path:
    """Persist LLM settings atomically; the API key goes to the store (M0.7).

    When ``settings.api_key`` is set, it is written to the OS keychain (or
    the 0600 fallback file) and ``key_backend`` records which. The JSON
    file is written without the key, with owner-only permissions.
    """
    from src.llm.keystore import get_keystore

    store = get_keystore(settings_dir)
    to_persist = settings.model_copy(update={"api_key": ""})
    if settings.api_key:
        store.set(settings.provider, settings.api_key)
        to_persist.key_backend = store.backend_name
    elif to_persist.key_backend:
        # Caller saved with an empty key — clear any previously stored entry
        # so the old key does not resurrect on reload.
        with contextlib.suppress(Exception):
            store.delete(settings.provider)
        to_persist.key_backend = ""
    return _write_settings_file(to_persist, settings_dir)


def _write_settings_file(settings: LLMSettings, settings_dir: str | Path) -> Path:
    """Write the settings JSON (never contains the key) with 0600 perms."""
    path = settings_path(settings_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    payload = settings.model_dump()
    payload.pop("api_key", None)  # belt: the key never lands on disk here
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
    os.chmod(path, 0o600)
    return path


def resolve_api_key(settings: LLMSettings, settings_dir: str | Path = DEFAULT_SETTINGS_DIR) -> str:
    """Return the stored API key for the settings' provider ("" when none)."""
    from src.llm.keystore import get_keystore

    if settings.api_key:  # already resolved (runtime)
        return settings.api_key
    return get_keystore(settings_dir).get(settings.provider)


def delete_api_key(
    settings: LLMSettings, settings_dir: str | Path = DEFAULT_SETTINGS_DIR
) -> LLMSettings:
    """Remove the stored key and return updated (persisted) settings."""
    from src.llm.keystore import get_keystore

    get_keystore(settings_dir).delete(settings.provider)
    updated = settings.model_copy(update={"api_key": "", "key_backend": ""})
    _write_settings_file(updated, settings_dir)
    return updated


def masked_key_tail(settings: LLMSettings, settings_dir: str | Path = DEFAULT_SETTINGS_DIR) -> str:
    """The masked tail shown in the UI (``…1234``), or "" when no key."""
    from src.llm.keystore import masked_tail

    return masked_tail(resolve_api_key(settings, settings_dir))


#: Common model presets per provider (fallback when API fetch is unavailable).
MODEL_PRESETS: dict[str, list[str]] = {
    key: cfg.get("presets", []) for key, cfg in PROVIDER_CONFIGS.items()
}


# ---------------------------------------------------------------------------
# Adapter construction (hoisted from src/tui/app.py — U5/KTD-8).
# ---------------------------------------------------------------------------


def apply_llm_env(settings: LLMSettings) -> None:
    """Populate provider-specific env vars from settings.

    Pydantic AI's provider clients read ``ANTHROPIC_API_KEY``,
    ``OPENAI_API_KEY``, etc. We set them so the adapter can construct
    agents without explicit key passing.
    """
    for key, value in settings.env_overrides().items():
        if value:
            os.environ[key] = value


def create_llm_adapter(settings: LLMSettings) -> LLMAdapter | None:
    """Build an :class:`LLMAdapter` from settings (U5 hoist from app.py).

    Returns a configured adapter when settings are complete, or ``None``
    when no model/key is set (caller should use template narration).
    """
    if not settings.is_configured:
        return None
    from src.llm.adapter import AdapterConfig, LLMAdapter

    apply_llm_env(settings)
    return LLMAdapter(
        AdapterConfig(
            model=settings.model_string,
            max_retries=settings.max_retries,
        )
    )
