"""Re-export from src.llm.providers (U5/KTD-8 hoist).

Provider configs now live in src/llm/providers.py so the web shell and
GameSession can construct adapters without importing src/tui/. This module
re-exports everything for backward compatibility with existing TUI code.
"""

from __future__ import annotations

from src.llm.providers import (  # noqa: F401
    PROVIDER_CONFIGS,
    fetch_available_models,
    get_provider_config,
    models_endpoint,
    provider_labels,
)
