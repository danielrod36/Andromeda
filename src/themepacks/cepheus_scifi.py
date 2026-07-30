"""Sci-fi theme-pack loader for the CE SRD content (R21).

Provides :func:`load_scifi_pack` as a convenience entry point for the sci-fi
pack. The actual content lives in ``src/themepacks/data/scifi/`` as YAML files;
this module just calls the generic loader and returns the result.
"""

from __future__ import annotations

from src.themepacks.base import DATA_ROOT, LoadedThemePack, ThemePackLoader


def load_scifi_pack() -> LoadedThemePack:
    """Load and return the CE SRD sci-fi theme pack.

    Reads ``src/themepacks/data/scifi/`` and validates all content at load time.
    Returns a :class:`LoadedThemePack` satisfying the :class:`ThemePack` Protocol.
    """
    pack_dir = DATA_ROOT / "scifi"
    return ThemePackLoader(pack_dir).load()
