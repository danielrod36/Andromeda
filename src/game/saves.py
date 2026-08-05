"""Save discovery, naming, and resume routing — shared save utilities (U6).

Hoisted from src/tui/app.py so the web shell has a single implementation of
save discovery, filename sanitization, and the resume phase predicate. The
TUI retains its own copies for now; adopting these functions across both
shells is a follow-up task (R11 drift-prevention).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine.state import GameState


@dataclass
class SaveInfo:
    """Metadata for a save file, used by the save-picker UI."""

    path: Path
    name: str
    theme_pack: str
    character_name: str
    terms: int
    career: str
    alive: bool
    mtime: float


def is_checkpoint_sidecar(path: Path) -> bool:
    """True if the path is a checkpoint sidecar (not a loadable save)."""
    return path.name.endswith(".checkpoint.json")


def safe_save_name(name: str) -> str:
    """Sanitize a campaign name into a safe filename stem.

    Matches the TUI's convention: spaces and slashes → underscores.
    Also strips path components (``..``, backslash, null bytes) to prevent
    path traversal — the web shell accepts save names from POST data.
    """
    if not name:
        return "unnamed"
    # Strip any path component — only the final filename segment survives.
    name = Path(name).name
    # Remove path traversal and null bytes.
    name = name.replace("..", "").replace("\\", "").replace("\x00", "")
    # TUI convention: spaces and slashes → underscores.
    name = name.replace(" ", "_").replace("/", "_")
    return name or "unnamed"


def resolve_save_path(saves_dir: str | Path, name: str) -> Path:
    """Resolve a save name to a path, verifying it stays within saves_dir.

    Defense-in-depth against path traversal: validates the resolved path
    is inside ``saves_dir`` before returning. The web shell calls this
    on user-supplied save names from POST data.
    """
    saves_dir = Path(saves_dir).resolve()
    safe = safe_save_name(name)
    save_path = (saves_dir / f"{safe}.json").resolve()
    if not save_path.is_relative_to(saves_dir):
        raise ValueError(f"Save path escapes saves directory: {name!r}")
    return save_path


def discover_saves(saves_dir: str | Path) -> list[SaveInfo]:
    """Return metadata for all save files, sorted by mtime (newest first).

    Checkpoint sidecars (``*.checkpoint.json``) are filtered out — they are
    not loadable campaign saves.
    """
    saves_dir = Path(saves_dir)
    results: list[SaveInfo] = []
    if not saves_dir.is_dir():
        return results
    for path in sorted(saves_dir.glob("*.json")):
        if is_checkpoint_sidecar(path):
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            campaign = data.get("campaign", {})
            character = data.get("character", {})
            stat = path.stat()
            results.append(
                SaveInfo(
                    path=path,
                    name=path.stem,
                    theme_pack=campaign.get("theme_pack", "unknown"),
                    character_name=character.get("name", ""),
                    terms=character.get("terms", 0),
                    career=character.get("career", ""),
                    alive=character.get("alive", True),
                    mtime=stat.st_mtime,
                )
            )
        except (json.JSONDecodeError, OSError):
            continue
    results.sort(key=lambda s: s.mtime, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Resume phase predicate (U6 — shared with U12 memorial routing).
# ---------------------------------------------------------------------------


def determine_resume_route(state: GameState) -> str:
    """Determine which web route a saved game should resume into (U6).

    This is the web-shell resume predicate. The TUI's own
    flag-scanning resume logic is unchanged (KTD-3).

    Routes:
    - ``"memorial"`` — dead character (shared with U12)
    - ``"lifepath"`` — mid-lifepath (characteristics not done, or career
      not chosen, or term_phase flags set without muster_out)
    - ``"freetext_prompt"`` — pending free-text interpretation (U3)
    - ``"adventure"`` — mustered out or active mission

    Args:
        state: The loaded :class:`GameState`.

    Returns:
        A route identifier the web layer maps to a URL.
    """
    char = state.character

    # Dead character → memorial (shared with U12).
    if not char.alive:
        return "memorial"

    # Pending free-text interpretation (U3) → restore the prompt.
    if state.pending_freetext is not None:
        return "freetext_prompt"

    # Mid-lifepath: characteristics not assigned, or no career yet, or
    # term flags present without mustering out.  The six Cepheus stats are
    # STR, DEX, END, INT, EDU, SOC.
    if len(char.characteristics) < 6:
        return "lifepath"
    if not char.career:
        return "lifepath"
    if "mustered_out=true" not in state.narrative_log:
        return "lifepath"

    # Mustered out → adventure.
    return "adventure"
