"""Scene-start snapshot/restore infrastructure for Checkpoint death mode (AE3).

A *scene* is one F4 cycle (oracle -> options -> choice -> resolution ->
narration). :class:`CheckpointManager` captures a depth-1 snapshot of canonical
state at each scene boundary. On defeat, :meth:`restore` returns the snapshot
state: character, campaign, entities (including removal of LLM-registered
narrative facts), narrative log, and RNG streams revert to scene start.

The append-only **event log is excluded** from rewind — the events from the
abandoned branch remain, and a ``REWIND_APPLIED`` event marks the boundary so
replay tooling can skip the dead branch.

Snapshots use ``model_copy(deep=True)`` followed by ``RngStreams._hydrate()``
to rebuild live ``random.Random`` instances from serializable snapshots.
Persistence is via a sidecar ``{save}.checkpoint.json`` file so rewind works
after relaunch.
"""
from __future__ import annotations

from pathlib import Path

from src.engine.audit import Event, EventKind
from src.engine.persistence import load, save
from src.engine.state import GameState


class CheckpointManager:
    """Manages the scene-start snapshot for Checkpoint death mode.

    Usage::

        mgr = CheckpointManager()
        mgr.take_snapshot(state)   # At each F4 cycle (scene) start.
        # ... scene plays out, character is defeated ...
        restored = mgr.restore(state)   # Rewind to scene start.

    The snapshot is a deep copy of the full :class:`GameState` at scene start.
    On restore, canonical fields (character, campaign, entities, narrative_log,
    rng) come from the snapshot; the events list is preserved from the current
    (pre-rewind) state and a ``REWIND_APPLIED`` event is appended.
    """

    def __init__(self) -> None:
        self._snapshot: GameState | None = None

    @property
    def has_snapshot(self) -> bool:
        """Whether a scene-start snapshot is available for rewind."""
        return self._snapshot is not None

    # ------------------------------------------------------------------
    # Snapshot capture.
    # ------------------------------------------------------------------

    def take_snapshot(self, state: GameState) -> None:
        """Capture canonical state at scene start (depth-1 slot).

        Deep-copies the full state and hydrates RNG streams so live
        ``random.Random`` instances are rebuilt from serializable snapshots.
        The snapshot is replaced at each F4 cycle start.
        """
        snap = state.model_copy(deep=True)
        snap.rng._hydrate()
        self._snapshot = snap

    # ------------------------------------------------------------------
    # Restore / rewind.
    # ------------------------------------------------------------------

    def restore(self, current_state: GameState) -> GameState:
        """Restore canonical state to scene start (AE3).

        Returns a **new** :class:`GameState` with character, campaign,
        entities, narrative_log, and rng from the scene-start snapshot.
        The events list from *current_state* is preserved (append-only),
        and a ``REWIND_APPLIED`` event is appended to mark the abandoned
        branch so replay tooling can skip it.

        Raises:
            RuntimeError: if no snapshot has been taken.
        """
        if self._snapshot is None:
            raise RuntimeError(
                "No checkpoint snapshot available — call take_snapshot() first"
            )

        # Deep-copy the stored snapshot so the original remains intact for
        # repeated restores (e.g., testing or multiple rewind attempts).
        restored = self._snapshot.model_copy(deep=True)
        restored.rng._hydrate()

        # Preserve the append-only event log from the pre-rewind state.
        # The events from the abandoned scene branch stay; canonical state
        # reverts.
        restored.events = list(current_state.events)

        # Compute how many events belong to the abandoned branch.
        snapshot_event_count = len(self._snapshot.events)
        abandoned_count = len(current_state.events) - snapshot_event_count

        # Append the REWIND_APPLIED boundary marker.
        rewind_event = Event(
            seq=len(restored.events),
            kind=EventKind.REWIND_APPLIED,
            command_type="rewind_applied",
            description=(
                f"Checkpoint rewind applied: canonical state restored to "
                f"scene start. {abandoned_count} event(s) from the abandoned "
                f"scene branch retained in the audit log."
            ),
            changes={
                "abandoned_branch_events": abandoned_count,
                "rewound_to_seq": snapshot_event_count - 1,
            },
        )
        restored.events.append(rewind_event)

        return restored

    # ------------------------------------------------------------------
    # Persistence (sidecar file alongside the campaign save).
    # ------------------------------------------------------------------

    def save_snapshot(self, path: str | Path) -> Path | None:
        """Persist the snapshot to ``{path}.checkpoint.json``.

        Returns the snapshot file path, or ``None`` if no snapshot exists.
        """
        if self._snapshot is None:
            return None
        checkpoint_path = Path(str(path) + ".checkpoint.json")
        return save(self._snapshot, checkpoint_path)

    def load_snapshot(self, path: str | Path) -> bool:
        """Load snapshot from ``{path}.checkpoint.json`` if it exists.

        Returns ``True`` if a snapshot was loaded, ``False`` if no checkpoint
        file exists.
        """
        checkpoint_path = Path(str(path) + ".checkpoint.json")
        if not checkpoint_path.exists():
            return False
        self._snapshot = load(checkpoint_path)
        self._snapshot.rng._hydrate()
        return True

    def clear(self) -> None:
        """Discard the current snapshot."""
        self._snapshot = None
