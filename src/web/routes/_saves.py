"""Shared save-loading helpers for web routes (U9, U1).

The adventure and lifepath routes both need to load a save, construct an
:class:`Engine`, and resolve the theme pack. Extracting that here avoids
duplicating the pack-resolution conditional across route modules.

U1 adds the session registry: :func:`get_or_create_session` returns a
cached :class:`GameSession` plus flow controllers, keyed by the resolved
saves directory and save stem so per-test directories never collide.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.engine.commands import Engine
from src.engine.persistence import load
from src.engine.state import GameState
from src.game.saves import resolve_save_path
from src.themepacks.base import LoadedThemePack, get_pack
from src.themepacks.cepheus_scifi import load_scifi_pack

if TYPE_CHECKING:
    from starlette.requests import Request

    from src.game.adventure import AdventureController
    from src.game.lifepath import LifepathController
    from src.game.session import GameSession
    from src.llm.settings import LLMSettings

#: Default saves directory (shared with menu/lifepath/adventure routes).
DEFAULT_SAVES_DIR = Path("saves")


@dataclass
class SessionBundle:
    """Cached session data for one save (U1).

    Holds the :class:`GameSession` (engine, adapter, action gate, stale-write
    guard) plus the save's flow controllers, each constructed once and reused
    across requests. Caching the controllers is load-bearing:
    ``_current_scene``, ``_current_hook``, ``_current_term_result``, and the
    controller-owned :class:`CheckpointManager` all live on the instance.
    """

    session: GameSession
    adventure_controller: AdventureController | None = None
    lifepath_controller: LifepathController | None = None


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


def load_state_for_save(save_name: str, saves_dir: Path | None = None) -> tuple[GameState, Path]:
    """Load a save and return ``(state, save_path)`` without constructing an Engine.

    Used by read-only routes (e.g. SSE streaming) that need state but not
    an Engine instance. Raises :class:`FileNotFoundError` if the save does
    not exist.
    """
    directory = saves_dir or DEFAULT_SAVES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    save_path = resolve_save_path(directory, save_name)
    if not save_path.exists():
        raise FileNotFoundError(f"Save not found: {save_name}")
    state: GameState = load(save_path)
    return state, save_path


# ---------------------------------------------------------------------------
# U1: Session registry helpers.
# ---------------------------------------------------------------------------


def _resolve_pack(state: GameState) -> LoadedThemePack:
    """Resolve the theme pack for a state (shared by engine + controllers)."""
    return (
        load_scifi_pack()
        if state.campaign.theme_pack == "scifi"
        else get_pack(state.campaign.theme_pack)
    )


def get_or_create_session(
    save_name: str,
    saves_dir: Path,
    request: Request,
) -> SessionBundle:
    """Return the cached :class:`SessionBundle` for *save_name*, creating it on miss.

    The registry lives on ``request.app.state.session_registry``, keyed by
    ``(resolved_saves_dir, save_stem)``. On a cache miss the GameSession is
    constructed from disk and the flow controllers are built once. The
    controller's :class:`CheckpointManager` is wired to the session's so
    scene-start snapshots persist to disk through ``session.save()``.

    Raises :class:`FileNotFoundError` if the save does not exist.
    """
    from src.game.adventure import AdventureController
    from src.game.lifepath import LifepathController
    from src.game.session import GameSession

    directory = Path(saves_dir)
    directory.mkdir(parents=True, exist_ok=True)
    save_path = resolve_save_path(directory, save_name)
    if not save_path.exists():
        raise FileNotFoundError(f"Save not found: {save_name}")

    registry: dict = request.app.state.session_registry
    key = (str(save_path.parent.resolve()), save_path.stem)

    bundle = registry.get(key)
    if bundle is not None:
        return bundle

    # Cache miss: construct the session + controllers once.
    settings: LLMSettings | None = getattr(request.app.state, "llm_settings", None)
    session = GameSession(save_path, settings=settings)
    pack = _resolve_pack(session.state)

    adv = AdventureController(session.engine, pack)
    # Wire the controller's checkpoint manager to the session's so the
    # scene-start snapshot survives across requests and persists to disk.
    adv._checkpoint_mgr = session.checkpoint_mgr

    life = LifepathController(session.engine, pack)

    bundle = SessionBundle(
        session=session,
        adventure_controller=adv,
        lifepath_controller=life,
    )
    registry[key] = bundle
    return bundle


def get_session(save_name: str, request: Request) -> SessionBundle | None:
    """Return the cached bundle if it exists, or ``None`` (no construction)."""
    registry: dict = request.app.state.session_registry
    for (_dir, _stem), bundle in registry.items():
        if _stem == save_name:
            return bundle
    return None
