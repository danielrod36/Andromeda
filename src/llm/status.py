"""Degraded-mode status strings shared by both shells (U10/KTD-8 hoist).

These strings surface in the status bar when the LLM fails, so the player
understands why the narration changed. They live here (not in src/tui/) so
the web shell and TUI share one definition — AE3's identical-fallback
guarantee depends on it.
"""

from __future__ import annotations

#: LLM kept producing invalid output after all retries — template shown.
STATUS_NARRATION_UNAVAILABLE = "narration unavailable — showing mechanical outcomes"

#: Network/API/timeout error — can't reach the provider.
STATUS_CONNECTION_LOST = "connection lost — template narration"
