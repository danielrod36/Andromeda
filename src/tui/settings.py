"""Re-export from src.llm.settings (U5/KTD-8 hoist).

Settings persistence and adapter construction now live in src/llm/settings.py
so the web shell and GameSession can configure the LLM without importing
src/tui/. This module re-exports everything for backward compatibility with
existing TUI code.
"""

from __future__ import annotations

from src.llm.settings import (  # noqa: F401
    DEFAULT_SETTINGS_DIR,
    MODEL_PRESETS,
    LLMSettings,
    apply_llm_env,
    create_llm_adapter,
    load_settings,
    save_settings,
    settings_path,
)
