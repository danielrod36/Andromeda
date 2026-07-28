"""Death mode strategy pattern for adventure-loop defeat (R8, AE2, AE3, AE4).

Three death modes govern what happens when the character is defeated during
adventure play (not chargen — U3's lifepath engine handles chargen
death/mishap branching separately):

* **Ironman** — permanent death. ``character.alive = False``; the game offers
  a new lifepath restart.
* **Checkpoint** — rewind canonical state to scene start via
  :class:`~src.engine.checkpoint.CheckpointManager`. The abandoned branch
  stays in the append-only audit log.
* **Narrative** — apply a lasting consequence (:class:`~src.engine.state.Injury`)
  visible on the character sheet; play continues.

All strategies implement :class:`DeathStrategy` with a single
``handle_defeat(state, context) -> DefeatResult`` method, making the mode
swappable per campaign configuration (``campaign.death_mode``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.engine.checkpoint import CheckpointManager
from src.engine.state import GameState, Injury


@dataclass
class DefeatContext:
    """Context passed to death strategies when a defeat is triggered.

    Attributes:
        reason: A short description of what caused the defeat (e.g.,
            "overwhelmed by pirates"). Used in consequence names and messages.
        scene_label: An optional label for the scene where defeat occurred.
    """

    reason: str = ""
    scene_label: str = ""


@dataclass
class DefeatResult:
    """Result of handling a defeat condition.

    Attributes:
        mode: The death mode name (``"ironman"``, ``"checkpoint"``,
            ``"narrative"``).
        message: Human-readable description of what happened, for the TUI.
        play_continues: Whether the player keeps playing after this defeat.
        restored_state: For Checkpoint mode, the rewound ``GameState``.
        restart_offered: For Ironman mode, whether the game offers a restart.
    """

    mode: str
    message: str
    play_continues: bool
    restored_state: GameState | None = None
    restart_offered: bool = False


@runtime_checkable
class DeathStrategy(Protocol):
    """Strategy for handling defeat in the adventure loop (R8).

    Each concrete strategy applies its death mode's effect and returns
    instructions for what happens next via :class:`DefeatResult`.
    """

    mode: str

    def handle_defeat(
        self, state: GameState, context: DefeatContext
    ) -> DefeatResult: ...


# ---------------------------------------------------------------------------
# Concrete strategies.
# ---------------------------------------------------------------------------


class IronmanStrategy:
    """Ironman: permanent death (R8, AE2).

    Sets ``character.alive = False`` and signals that the game should offer a
    new lifepath restart. The character is dead; the save may be retired.
    """

    mode: str = "ironman"

    def handle_defeat(
        self, state: GameState, context: DefeatContext
    ) -> DefeatResult:
        state.character.alive = False
        reason = context.reason or "an encounter"
        name = state.character.name or "the traveler"
        return DefeatResult(
            mode=self.mode,
            message=(
                f"{name} has died from {reason}. "
                f"Ironman mode: death is permanent."
            ),
            play_continues=False,
            restart_offered=True,
        )


class CheckpointStrategy:
    """Checkpoint: rewind canonical state to scene start (R8, AE3).

    Delegates to :class:`~src.engine.checkpoint.CheckpointManager` to restore
    character, campaign, entities, narrative log, and RNG streams to their
    scene-start snapshot. The audit log is preserved (append-only) with a
    ``REWIND_APPLIED`` boundary marker.
    """

    mode: str = "checkpoint"

    def __init__(self, checkpoint: CheckpointManager) -> None:
        self.checkpoint = checkpoint

    def handle_defeat(
        self, state: GameState, context: DefeatContext
    ) -> DefeatResult:
        restored = self.checkpoint.restore(state)
        reason = context.reason or "an encounter"
        return DefeatResult(
            mode=self.mode,
            message=(
                f"Defeat from {reason} — rewinding to scene start. "
                f"The abandoned branch is retained in the audit log."
            ),
            play_continues=True,
            restored_state=restored,
        )


class NarrativeStrategy:
    """Narrative: apply a lasting consequence, continue play (R8, AE4).

    Adds an :class:`~src.engine.state.Injury` entity to the character sheet
    representing the lasting consequence of the defeat. The character
    survives and play continues with the setback visible in canonical state.
    """

    mode: str = "narrative"

    def handle_defeat(
        self, state: GameState, context: DefeatContext
    ) -> DefeatResult:
        reason = context.reason or "a defeat"
        injury = Injury(
            name=f"Defeat: {reason}",
            severity="severe",
            description=(
                f"A lasting consequence from {reason}. The character was "
                f"defeated but survived with a serious injury."
            ),
        )
        state.entities.append(injury)
        return DefeatResult(
            mode=self.mode,
            message=(
                f"Defeat from {reason} — a lasting consequence is applied. "
                f"Play continues."
            ),
            play_continues=True,
        )


# ---------------------------------------------------------------------------
# Factory.
# ---------------------------------------------------------------------------

#: The three valid death mode identifiers.
DEATH_MODES: tuple[str, ...] = ("ironman", "checkpoint", "narrative")


def get_death_strategy(
    mode: str,
    checkpoint: CheckpointManager | None = None,
) -> DeathStrategy:
    """Return the death strategy for the given campaign mode (R8).

    Args:
        mode: One of ``"ironman"``, ``"checkpoint"``, ``"narrative"``.
        checkpoint: Required for ``"checkpoint"`` mode; ignored otherwise.

    Raises:
        ValueError: if *mode* is not a recognized death mode, or if
            ``"checkpoint"`` is requested without a :class:`CheckpointManager`.
    """
    if mode == "ironman":
        return IronmanStrategy()
    if mode == "checkpoint":
        if checkpoint is None:
            raise ValueError(
                "Checkpoint death mode requires a CheckpointManager instance"
            )
        return CheckpointStrategy(checkpoint)
    if mode == "narrative":
        return NarrativeStrategy()
    raise ValueError(
        f"Unknown death mode {mode!r}; expected one of: {', '.join(DEATH_MODES)}"
    )
