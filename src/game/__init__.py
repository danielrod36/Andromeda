"""Andromeda game layer — headless flow controllers and GameSession (U5).

This package owns the evolving flow logic (lifepath phases, adventure beats)
and the session object that manages engine state, adapter construction,
autosave, and checkpoint sidecar handling. Both the TUI and the web shell
consume the same flow layer; the engine package has zero game-flow imports.
"""
