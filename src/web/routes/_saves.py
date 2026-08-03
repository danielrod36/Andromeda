"""Shared save-loading helpers for web routes (U9).

The adventure and lifepath routes both need to load a save, construct an
:class:`Engine`, and resolve the theme pack. Extracting that here avoids
duplicating the pack-resolution conditional across route modules.
"""

from __future__ import annotations

from pathlib import Path

from src.engine.commands import Engine
from src.engine.persistence import load
from src.engine.state import GameState
from src.game.saves import resolve_save_path
from src.themepacks.base import LoadedThemePack, get_pack
from src.themepacks.cepheus_scifi import load_scifi_pack

#: Default saves directory (shared with menu/lifepath/adventure routes).
DEFAULT_SAVES_DIR = Path("saves")


def load_engine_for_save(
    save_name: str, saves_dir: Path | None = None
) -> tuple[Engine, LoadedThemePack, Path]:
    """Load a save and construct an :class:`Engine` with the correct pack.

    Raises :class:`FileNotFoundError` if the save does not exist.
    """
    directory = saves_dir or DEFAULT_SAVES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    save_path = resolve_save_path(directory, save_name)
    if not save_path.exists():
        raise FileNotFoundError(f"Save not found: {save_name}")
    state: GameState = load(save_path)
    engine = Engine(state)
    pack = (
        load_scifi_pack()
        if state.campaign.theme_pack == "scifi"
        else get_pack(state.campaign.theme_pack)
    )
    return engine, pack, save_path
