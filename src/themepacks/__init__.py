"""Theme-pack loading, validation, and discovery (U2: R20, R21).

Theme packs are pure YAML/JSON data validated into Pydantic models at load time.
The directory-scan registry discovers packs under ``src/themepacks/data/``.
"""
from src.themepacks.base import (
    DATA_ROOT,
    LoadedThemePack,
    PackLoadError,
    ThemePackLoader,
    discover_packs,
    get_pack,
    validate_pack,
)
from src.themepacks.cepheus_scifi import load_scifi_pack

__all__ = [
    "DATA_ROOT",
    "LoadedThemePack",
    "PackLoadError",
    "ThemePackLoader",
    "discover_packs",
    "get_pack",
    "load_scifi_pack",
    "validate_pack",
]
