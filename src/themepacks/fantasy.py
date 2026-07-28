"""Fantasy theme-pack loader for original fantasy content (R21, U9).

Provides :func:`load_fantasy_pack` as a convenience entry point for the fantasy
pack. The actual content lives in ``src/themepacks/data/fantasy/`` as YAML files;
this module just calls the generic loader and returns the result.

No engine code changes — this uses the exact same loader infrastructure as the
sci-fi pack.
"""
from __future__ import annotations

from src.themepacks.base import DATA_ROOT, LoadedThemePack, ThemePackLoader


def load_fantasy_pack() -> LoadedThemePack:
    """Load and return the original fantasy theme pack.

    Reads ``src/themepacks/data/fantasy/`` and validates all content at load
    time. Returns a :class:`LoadedThemePack` satisfying the :class:`ThemePack`
    Protocol — the same interface the sci-fi pack uses.
    """
    pack_dir = DATA_ROOT / "fantasy"
    return ThemePackLoader(pack_dir).load()
