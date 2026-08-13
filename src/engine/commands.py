"""Command funnel: the sole mutation path into :class:`GameState`.

Every state change — player action, LLM tool call, oracle roll — is a
:class:`Command` object passed through :meth:`Engine.apply`, which runs the
pipeline::

    validate → resolve (dice) → mutate → append event

``validate`` may raise and leaves state untouched; ``resolve`` rolls dice via
the injected :class:`Roller` (production: ``LiveRoller`` reading the named RNG
streams; tests: ``ForcedRoller`` with queued results); ``mutate`` applies the
state change and returns an :class:`Event`; the funnel assigns a sequence
number and appends it to the log.

The funnel is the engine's trust boundary: nothing outside it mutates state,
and every roll is recorded with its inputs and outcome (R1, R4, AE1).
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from src.engine.audit import Event, EventKind
from src.engine.dice import LiveRoller, Roller, RollResult
from src.engine.state import GameState

# Canonical Cepheus characteristics.
_CHARACTERISTICS: tuple[str, ...] = (
    "STR",
    "DEX",
    "END",
    "INT",
    "EDU",
    "SOC",
)


class Command(BaseModel):
    """Base class for commands processed through :meth:`Engine.apply`.

    Subclasses implement some or all of :meth:`validate`, :meth:`resolve`,
    :meth:`mutate`. ``validate`` runs first and may reject the command before
    any state is touched; ``resolve`` rolls dice through the injected
    :class:`Roller` so tests can force outcomes; ``mutate`` applies the change
    and returns the :class:`Event` to append.
    """

    #: Short identifier recorded in events for audit/replay.
    command_type: ClassVar[str] = "command"

    def validate(self, state: GameState) -> None:
        """Reject the command against current state. Raise on invalid.

        Default implementation accepts everything; override to enforce
        preconditions. Must not mutate state.
        """

    def resolve(self, state: GameState, roller: Roller) -> RollResult | None:
        """Roll dice if the command needs them. Default: no roll.

        Returning ``None`` marks the command as non-dice; returning a
        :class:`RollResult` causes the funnel to append a ``ROLL`` event
        alongside the mutation event.
        """
        return None

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        """Apply the mutation and return the :class:`Event` to append.

        ``seq`` is assigned by the funnel after this returns; subclasses should
        leave it at the default. The returned event's ``kind`` controls whether
        it appears in the audit (roll) view.
        """
        raise NotImplementedError


class Engine:
    """The command funnel — the sole mutation path into :class:`GameState`.

    Construct with a ``GameState`` and (optionally) a ``Roller``. In production
    the roller defaults to :class:`LiveRoller` bound to the state's RNG streams;
    in tests, pass a :class:`ForcedRoller` to inject deterministic dice.

    Mutating the state outside :meth:`apply` breaks determinism, audit, and
    checkpoint guarantees — every change goes through the funnel.
    """

    def __init__(
        self,
        state: GameState,
        roller: Roller | None = None,
    ) -> None:
        self._state = state
        self._roller: Roller = roller if roller is not None else LiveRoller(state.rng)

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def roller(self) -> Roller:
        return self._roller

    def swap_state(self, state: GameState) -> None:
        """Swap canonical state (checkpoint restore), rebinding a live roller.

        A :class:`LiveRoller` holds the previous state's ``RngStreams``;
        without rebinding, post-restore rolls would advance the abandoned
        branch's streams while the restored state's RNG stays frozen —
        silently breaking the determinism/replay guarantee (AE3). A
        :class:`ForcedRoller` (tests) is left untouched.
        """
        self._state = state
        if isinstance(self._roller, LiveRoller):
            self._roller = LiveRoller(state.rng)

    def apply(self, cmd: Command) -> Event:
        """Run ``validate → resolve → mutate → append`` and return the event.

        ``validate`` raising aborts the whole command: state, RNG, and log are
        untouched. After validation, the dice are rolled, the mutation runs,
        and the event is appended with its sequence number assigned.
        """
        # 1. Validate — may raise; state untouched on failure.
        cmd.validate(self._state)

        # 2. Resolve dice via the injected roller.
        roll = cmd.resolve(self._state, self._roller)

        # 3. Mutate — produces the event to append.
        event = cmd.mutate(self._state, roll)

        # 4. Assign sequence number and append (append-only log).
        event.seq = len(self._state.events)
        self._state.events.append(event)
        return event

    def check(self, cmd: Command) -> None:
        """Validate-only gate (P2.T1, A4): run ``cmd.validate(state)`` and nothing else.

        No resolve, no mutate, no RNG consumption, no event append. Returns
        ``None`` when the command is legal against current state; raises
        exactly what ``validate`` raises otherwise. Parts 4–5 use it to vet
        LLM-proposed commands before recording them.
        """
        cmd.validate(self._state)


# ---------------------------------------------------------------------------
# Minimal concrete commands.
#
# These exist to exercise the funnel and audit log end-to-end in U1; U3 and U7
# add the real lifepath and scene commands on the same base.
# ---------------------------------------------------------------------------


class RollCharacteristicCommand(Command):
    """Roll 2D6 on the lifepath stream and set a characteristic.

    Used by lifepath chargen (U3); included here as the canonical example of a
    dice-rolling command so U1 can verify the full funnel: validation rejects
    unknown characteristics, the roll is logged with inputs and outcome, and
    repeated application with the same seed is deterministic.
    """

    command_type: ClassVar[str] = "roll_characteristic"

    characteristic: str

    def validate(self, state: GameState) -> None:
        if self.characteristic not in _CHARACTERISTICS:
            known = ", ".join(_CHARACTERISTICS)
            raise ValueError(
                f"Unknown characteristic {self.characteristic!r}; expected one of: {known}"
            )

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("lifepath", ndice=2, sides=6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None  # resolve always rolls for this command
        value = roll.total
        state.character.characteristics[self.characteristic] = value
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=(f"Rolled 2D6={roll.rolls}={value} for {self.characteristic}"),
            roll=roll,
            changes={"characteristic": self.characteristic, "value": value},
        )


class SetFlagCommand(Command):
    """Set an arbitrary string flag on the narrative log — a no-dice command.

    Exercises the validate-before-touch guarantee: a flag name of "" is
    rejected before any state change, and the appended event is a
    ``STATE_CHANGE`` (not a ``ROLL``) so it doesn't appear in the audit view.
    """

    command_type: ClassVar[str] = "set_flag"

    key: str
    value: str
    #: Provenance stamp — set to ``"llm"`` by LLM tool wrappers so pill
    #: extraction can distinguish LLM-originated events from engine-originated
    #: ones (KTD-R4, R13).  Engine code never sets this field.
    origin: str | None = None

    def validate(self, state: GameState) -> None:
        if not self.key:
            raise ValueError("flag key must be non-empty")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.narrative_log.append(f"{self.key}={self.value}")
        changes: dict = {"key": self.key, "value": self.value}
        if self.origin is not None:
            changes["origin"] = self.origin
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Set flag {self.key}={self.value}",
            changes=changes,
        )


class FlagDegradationCommand(Command):
    """Append an audit event marking a degraded code path (R13, Task 17).

    Unlike :class:`SetFlagCommand` this writes **no** narrative-log line — it
    exists so degraded behavior (missing option data, LLM fallback exhausted)
    is inspectable in the append-only event log without polluting the player's
    narrative. Used by :meth:`SceneEngine.generate_options` when pack option
    data is missing or yields fewer than two options.
    """

    command_type: ClassVar[str] = "flag_degradation"

    area: str
    reason: str

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Degradation ({self.area}): {self.reason}",
            changes={"area": self.area, "reason": self.reason},
        )


class SetCharacterDeadCommand(Command):
    """Mark the character as dead via the command funnel (R8, AE2).

    Used by the Ironman death strategy so that ``alive = False`` is routed
    through :meth:`Engine.apply`, producing an audit event and preserving
    replay/reconstruct guarantees.
    """

    command_type: ClassVar[str] = "set_character_dead"

    reason: str = ""

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.character.alive = False
        desc = f"Character died: {self.reason}" if self.reason else "Character died."
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=desc,
            changes={"alive": False, "reason": self.reason},
        )


class SetCharacterNameCommand(Command):
    """Set the character's name through the command funnel (P5.T6, ADR A10).

    The TUI currently assigns ``state.character.name`` directly
    (src/tui/app.py:167, :192) — an invariant-1 violation. The chargen
    session (Part 6) routes name changes through the funnel so they are
    validated, evented, and replayable. The frozen TUI is not rewired (A8).
    """

    command_type: ClassVar[str] = "set_character_name"

    name: str
    #: Provenance stamp (ADR A10): "player" | "freetext" | "advisor".
    origin: str = "player"

    def validate(self, state: GameState) -> None:
        if not self.name.strip():
            raise ValueError("character name must be non-empty")
        if len(self.name.strip()) > 80:
            raise ValueError("character name must be 80 characters or fewer")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.character.name = self.name.strip()
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Character named {state.character.name}",
            changes={"name": state.character.name, "origin": self.origin},
        )


class RecordAdviceCommand(Command):
    """Record an Advisor suggestion in the event log (P2.T9, A2/A10).

    The payload IS the record (a serialized SuggestionRecord, Part 4).
    ``validate`` is the no-op default — advice is non-mechanical, so there is
    no rules precondition. ``mutate`` appends a ``SYSTEM`` event and changes
    nothing else; replay re-applies the record deterministically and never
    re-calls the LLM.
    """

    command_type: ClassVar[str] = "record_advice"

    payload: dict

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        description = str(
            self.payload.get("description")
            or f"Advice recorded for choice {self.payload.get('choice_id', '?')}"
        )
        return Event(
            kind=EventKind.SYSTEM,
            command_type=self.command_type,
            description=description,
            changes=dict(self.payload),
        )


class RecordProposalCommand(Command):
    """Record a free-text translation in the event log (P2.T9, A3).

    The payload IS the record (a serialized TranslationRecord, Part 5),
    including its validation outcome — rejected proposals are recorded too.
    ``validate`` is the no-op default; ``mutate`` appends a ``SYSTEM`` event
    and changes nothing else.
    """

    command_type: ClassVar[str] = "record_proposal"

    payload: dict

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        description = str(
            self.payload.get("description")
            or f"Proposal recorded for choice {self.payload.get('choice_id', '?')}"
        )
        return Event(
            kind=EventKind.SYSTEM,
            command_type=self.command_type,
            description=description,
            changes=dict(self.payload),
        )


class RecordNarrationCommand(Command):
    """Funnel shipped narration prose into canonical state (M0.5, D6).

    The prose that actually shipped to the player — LLM or template — is
    appended to ``state.narrative_log`` and recorded as a ``SYSTEM`` event.
    Replay re-reads this record; it never re-calls the LLM (the same
    guarantee :class:`RecordAdviceCommand` makes for advice).
    """

    command_type: ClassVar[str] = "record_narration"

    text: str
    beat: str = ""
    source: str = "llm"  # "llm" | "template"

    def validate(self, state: GameState) -> None:
        if not self.text or not self.text.strip():
            raise ValueError("narration text must be non-empty")
        if len(self.text) > 4000:
            raise ValueError("narration text must be 4000 characters or fewer")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.narrative_log.append(self.text.strip())
        return Event(
            kind=EventKind.SYSTEM,
            command_type=self.command_type,
            description=f"Narration shipped ({self.beat or 'beat'}, {self.source})",
            changes={"text": self.text.strip(), "beat": self.beat, "source": self.source},
        )


class RecordStoryDirectionCommand(Command):
    """Record a player story direction for future narration conditioning (M0.5, D6).

    Directions are appended to ``narrative_log`` with the scannable
    ``story_direction=`` prefix (the same flag-channel convention as
    ``crisis_cost=``/``term_phase=``) and recorded as a ``SYSTEM`` event.
    Prompt builders surface recent directions so future prose is steered
    without ever touching mechanics.
    """

    command_type: ClassVar[str] = "record_story_direction"

    text: str
    beat: str = ""

    def validate(self, state: GameState) -> None:
        if not self.text or not self.text.strip():
            raise ValueError("story direction must be non-empty")
        if len(self.text) > 1000:
            raise ValueError("story direction must be 1000 characters or fewer")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.narrative_log.append(f"story_direction={self.text.strip()}")
        return Event(
            kind=EventKind.SYSTEM,
            command_type=self.command_type,
            description="Story direction recorded",
            changes={"text": self.text.strip(), "beat": self.beat},
        )
