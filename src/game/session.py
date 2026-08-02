"""GameSession — the session object shells drive (U5).

Four rules protect the engine invariants across the session lifecycle:

1. **Never cache GameState.** All reads go through ``engine.state`` because
   ``swap_state`` (checkpoint rewind) replaces the state object and rebinds
   the roller. A cached reference would point at the abandoned branch.

2. **Checkpoint sidecar cadence.** In checkpoint death mode, a save is two
   documents — main file plus ``{save}.checkpoint.json``. The session owns
   the main-then-sidecar write order around every autosave and resume.

3. **Per-session action gate.** At most one in-flight beat per session
   (KTD-9). Concurrent actions (double-click, second tab) are rejected.

4. **Stale-write detection.** Before every autosave, the session checks
   whether the on-disk document has changed since the last write. If it
   has, the autosave refuses and surfaces a conflict notice rather than
   silently overwriting (which would erase the other shell's events).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from src.engine.commands import Engine
from src.engine.persistence import load, save
from src.engine.state import GameState
from src.llm.settings import LLMSettings, create_llm_adapter

logger = logging.getLogger(__name__)


class StaleWriteError(Exception):
    """Raised when the on-disk save has changed since the session's last write."""


class GameSession:
    """Manages engine state, adapter, autosave, and checkpoint sidecar (U5).

    The session is constructed with a save path and optional LLM settings.
    It loads the GameState on construction and provides:

    - ``state`` property that always reads the current engine state
    - ``adapter`` — a configured LLMAdapter or None (template mode)
    - ``save()`` — autosave with stale-write detection + sidecar cadence
    - ``action_in_flight`` — the per-session action gate

    The session never caches GameState — rule 1. All state reads go through
    ``self._engine.state``, which is rebound by ``swap_state`` on rewind.
    """

    def __init__(
        self,
        save_path: Path,
        *,
        settings: LLMSettings | None = None,
        engine: Engine | None = None,
    ) -> None:
        """Initialize the session.

        Args:
            save_path: Path to the main save JSON file.
            settings: LLM settings (for adapter construction). When None,
                no adapter is created (template mode).
            engine: An existing Engine, or None to load from save_path.
        """
        self._save_path = save_path
        self._engine = engine or self._load_engine(save_path)
        self._settings = settings
        self._adapter = create_llm_adapter(settings) if settings else None

        # Stale-write detection: hash of the last document we wrote.
        self._last_write_hash: str | None = self._compute_disk_hash()

        # Action gate: at most one in-flight beat.
        self._action_in_flight = False

    # ------------------------------------------------------------------
    # Rule 1: never cache GameState — all reads through engine.state.
    # ------------------------------------------------------------------

    @property
    def state(self) -> GameState:
        """The current game state — always read fresh from the engine."""
        return self._engine.state

    @property
    def engine(self) -> Engine:
        """The engine instance."""
        return self._engine

    @property
    def adapter(self):
        """The configured LLM adapter, or None for template mode."""
        return self._adapter

    # ------------------------------------------------------------------
    # Rule 3: per-session action gate.
    # ------------------------------------------------------------------

    @property
    def action_in_flight(self) -> bool:
        """True when an action is being processed — rejects concurrent actions."""
        return self._action_in_flight

    def begin_action(self) -> bool:
        """Try to begin an action. Returns False if one is already in flight."""
        if self._action_in_flight:
            return False
        self._action_in_flight = True
        return True

    def end_action(self) -> None:
        """Mark the current action as complete."""
        self._action_in_flight = False

    # ------------------------------------------------------------------
    # Rule 2 + 4: autosave with stale-write detection + sidecar cadence.
    # ------------------------------------------------------------------

    @property
    def checkpoint_sidecar_path(self) -> Path:
        """The checkpoint sidecar path: ``{save}.checkpoint.json``."""
        return self._save_path.with_suffix(".checkpoint.json")

    def save(self) -> None:
        """Autosave the game state with stale-write detection (U5 rule 4).

        Writes the main document first, then the checkpoint sidecar (if in
        checkpoint mode). If the on-disk document has changed since the
        last write (another shell saved), raises :class:`StaleWriteError`.
        """
        # Rule 4: check for stale write.
        disk_hash = self._compute_disk_hash()
        if self._last_write_hash is not None and disk_hash != self._last_write_hash:
            raise StaleWriteError(
                f"Save file {self._save_path} was modified by another session. "
                f"Use 'Reload from disk' or 'Save as new copy' to resolve the conflict."
            )

        # Write main document (atomic: temp + os.replace via persistence.save).
        save(self.state, self._save_path)
        self._last_write_hash = self._compute_disk_hash()

        # Rule 2: write checkpoint sidecar if in checkpoint death mode.
        if self.state.campaign.death_mode == "checkpoint":
            self._write_sidecar()

    def _write_sidecar(self) -> None:
        """Write the checkpoint sidecar document."""
        sidecar_path = self.checkpoint_sidecar_path
        # The sidecar stores the checkpoint snapshot if one exists;
        # otherwise it's a minimal document recording the death mode.
        sidecar_data = {"death_mode": "checkpoint", "save_version": self.state.save_version}
        import json

        tmp = sidecar_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sidecar_data, indent=2), encoding="utf-8")
        tmp.replace(sidecar_path)

    def _compute_disk_hash(self) -> str | None:
        """Hash the on-disk document pair (main + sidecar) for stale-write detection."""
        if not self._save_path.exists():
            return None
        h = hashlib.sha256()
        h.update(self._save_path.read_bytes())
        if self.checkpoint_sidecar_path.exists():
            h.update(self.checkpoint_sidecar_path.read_bytes())
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Loading.
    # ------------------------------------------------------------------

    @staticmethod
    def _load_engine(save_path: Path) -> Engine:
        """Load a GameState from disk and wrap in an Engine."""
        state = load(save_path)
        return Engine(state)
