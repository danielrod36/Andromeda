"""Mission lifecycle: hook generation, accept/refuse, arc progression, endings (U7).

Missions are discrete arcs with a beginning (hook), middle (sequence of
scenes), and end (success, failure, or abandonment). Consequences persist
across missions in canonical state (R23, AE15).

Mission state machine::

    hook -> accepted -> active -> resolved (success | failure | abandonment)
          -> refused (generate new hook)

The engine generates hooks from theme-pack mission tables (patron types,
objectives, complications, rewards). On accept, the mission runs as a
sequence of scenes toward an ending. After resolution, the engine returns
to hook generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

from src.engine.audit import Event, EventKind
from src.engine.commands import Command, Engine, FlagDegradationCommand
from src.engine.dice import Roller, RollResult
from src.engine.lifepath import lookup_table_result
from src.engine.scene import SceneEngine, SceneResult
from src.engine.state import GameState
from src.engine.summary import AddChapterSummaryCommand, SummaryValidator, build_template_summary
from src.rulesets.cepheus import CepheusRuleSet
from src.themepacks.base import LoadedThemePack

# ---------------------------------------------------------------------------
# Mission state and data structures.
# ---------------------------------------------------------------------------


class MissionState(str, Enum):
    """Lifecycle states for a mission (R23)."""

    HOOK = "hook"
    ACTIVE = "active"
    RESOLVED = "resolved"


class MissionEnding(str, Enum):
    """Possible endings for a resolved mission (R23, AE15)."""

    SUCCESS = "success"
    FAILURE = "failure"
    ABANDONMENT = "abandonment"


@dataclass
class MissionHook:
    """A generated mission hook (patron + objective + complication + reward)."""

    patron: str
    objective: str
    complication: str
    reward: str
    description: str = ""
    oracle_rolls: list[int] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """Human-readable summary of the hook."""
        return (
            f"{self.patron} | Objective: {self.objective} | "
            f"Complication: {self.complication} | Reward: {self.reward}"
        )


@dataclass
class Mission:
    """A mission instance with lifecycle state."""

    id: str
    hook: MissionHook
    state: MissionState = MissionState.HOOK
    scenes_played: int = 0
    scene_results: list[SceneResult] = field(default_factory=list)
    ending: MissionEnding | None = None
    consequences: list[str] = field(default_factory=list)
    # Task 19: progress gating + pack-supplied ending texts.
    scenes_completed: int = 0
    min_scenes: int = 3
    success_text: str = ""
    failure_text: str = ""
    abandonment_text: str = ""

    @property
    def is_active(self) -> bool:
        return self.state == MissionState.ACTIVE

    @property
    def is_resolved(self) -> bool:
        return self.state == MissionState.RESOLVED

    def to_dict(self) -> dict:
        """Serialize for storage in GameState."""
        return {
            "id": self.id,
            "hook": {
                "patron": self.hook.patron,
                "objective": self.hook.objective,
                "complication": self.hook.complication,
                "reward": self.hook.reward,
                "description": self.hook.description,
            },
            "state": self.state.value,
            "scenes_played": self.scenes_played,
            "ending": self.ending.value if self.ending else None,
            "consequences": list(self.consequences),
            "scenes_completed": self.scenes_completed,
            "min_scenes": self.min_scenes,
            "success_text": self.success_text,
            "failure_text": self.failure_text,
            "abandonment_text": self.abandonment_text,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Mission:
        """Reconstruct a Mission from its serialized dict form.

        Used on resume from save to restore the in-memory ``_current_mission``
        from ``state.active_mission``.
        """
        hook_data = data.get("hook", {})
        hook = MissionHook(
            patron=hook_data.get("patron", ""),
            objective=hook_data.get("objective", ""),
            complication=hook_data.get("complication", ""),
            reward=hook_data.get("reward", ""),
            description=hook_data.get("description", ""),
        )
        state_str = data.get("state", "active")
        try:
            mission_state = MissionState(state_str)
        except ValueError:
            mission_state = MissionState.ACTIVE

        ending = None
        ending_str = data.get("ending")
        if ending_str:
            try:
                ending = MissionEnding(ending_str)
            except ValueError:
                ending = None

        return cls(
            id=data.get("id", ""),
            hook=hook,
            state=mission_state,
            scenes_played=data.get("scenes_played", 0),
            ending=ending,
            consequences=list(data.get("consequences", [])),
            scenes_completed=data.get("scenes_completed", 0),
            min_scenes=data.get("min_scenes", 3),
            success_text=data.get("success_text", ""),
            failure_text=data.get("failure_text", ""),
            abandonment_text=data.get("abandonment_text", ""),
        )


# ---------------------------------------------------------------------------
# Commands.
# ---------------------------------------------------------------------------


class MissionTableRollCommand(Command):
    """Roll 2D6 on the oracle stream for a mission table lookup (R23)."""

    command_type: ClassVar[str] = "mission_table_roll"
    table_id: str

    def resolve(self, state: GameState, roller: Roller) -> RollResult:
        return roller.roll("oracle", ndice=2, sides=6)

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        assert roll is not None
        return Event(
            kind=EventKind.ROLL,
            command_type=self.command_type,
            description=f"Mission table roll ({self.table_id}): {roll.total}",
            roll=roll,
            changes={"table_id": self.table_id, "roll_total": roll.total},
        )


class SetMissionStateCommand(Command):
    """Set the active mission or record a completed mission in state (R23, AE15)."""

    command_type: ClassVar[str] = "set_mission_state"

    mission_data: dict | None = None  # If None, clears active mission.
    completed_mission: dict | None = None  # If set, appends to completed list.

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        desc_parts: list[str] = []
        if self.mission_data is not None:
            state.active_mission = self.mission_data
            desc_parts.append(f"Active mission set: {self.mission_data.get('id', '?')}")
        elif self.completed_mission is not None:
            # Clear active mission, append to history.
            state.active_mission = None
            state.completed_missions.append(self.completed_mission)
            desc_parts.append(
                f"Mission completed: {self.completed_mission.get('id', '?')} "
                f"({self.completed_mission.get('ending', '?')})"
            )
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description="; ".join(desc_parts) if desc_parts else "Mission state cleared",
            changes={
                "mission_data": self.mission_data,
                "completed_mission": self.completed_mission,
            },
        )


class NextMissionIdCommand(Command):
    """Claim the next mission ID from persisted state (Task 19, R23).

    Increments ``state.mission_counter`` so the id survives save/load —
    a resumed game cannot collide with ids issued before the save. The
    returned id is ``mission_{N}`` where ``N`` is the post-increment counter.
    """

    command_type: ClassVar[str] = "next_mission_id"

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.mission_counter += 1
        mission_id = f"mission_{state.mission_counter}"
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Mission id claimed: {mission_id}",
            changes={"mission_id": mission_id, "counter": state.mission_counter},
        )


class ResolveMissionCommand(Command):
    """End the active mission with an explicit ending (Task 19, R23, AE15).

    Success/failure require ``scenes_completed >= min_scenes``; abandonment
    is always allowed (player agency). The mission record is moved to
    ``completed_missions`` with the ending stamped on it. Consequences are
    the caller's responsibility — they should be sourced from the mission
    hook's ending text (pack data), not hardcoded here.
    """

    command_type: ClassVar[str] = "resolve_mission"
    ending: str  # "success" | "failure" | "abandonment"

    def validate(self, state: GameState) -> None:
        if not state.active_mission:
            raise ValueError("No active mission")
        if self.ending not in ("success", "failure", "abandonment"):
            raise ValueError(f"Unknown ending {self.ending!r}")
        if self.ending != "abandonment":
            done = int(state.active_mission.get("scenes_completed", 0))
            needed = int(state.active_mission.get("min_scenes", 3))
            if done < needed:
                raise ValueError(f"Mission needs {needed} scenes before resolution ({done} done)")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        mission = dict(state.active_mission)
        mission["ending"] = self.ending
        mission["status"] = "completed"
        state.completed_missions.append(mission)
        state.active_mission = None
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description=f"Mission {mission.get('id', '?')} ended: {self.ending}",
            changes={"mission_id": mission.get("id", "?"), "ending": self.ending},
        )


# ---------------------------------------------------------------------------
# Mission engine.
# ---------------------------------------------------------------------------


class MissionEngine:
    """Orchestrates the full mission lifecycle (R23, AE15).

    Usage::

        engine = MissionEngine(engine, pack)
        hook = engine.generate_hook()
        mission = engine.accept_mission(hook)
        # Play scenes...
        engine.resolve_mission(mission, MissionEnding.SUCCESS)

    After resolution, the engine returns to hook generation — call
    :meth:`generate_hook` again for the next mission.
    """

    def __init__(
        self,
        engine: Engine,
        pack: LoadedThemePack,
        ruleset: CepheusRuleSet | None = None,
    ) -> None:
        self.engine = engine
        self.pack = pack
        self.ruleset = ruleset or CepheusRuleSet()
        self._active_mission: Mission | None = None
        # The in-memory counter is intentionally gone (Task 19): mission ids
        # come from ``state.mission_counter`` via :class:`NextMissionIdCommand`
        # so they survive save/load without collision.

    @property
    def active_mission(self) -> Mission | None:
        return self._active_mission

    def _next_mission_id(self) -> str:
        """Claim the next persisted mission id through the command funnel.

        Wraps :class:`NextMissionIdCommand` so callers don't touch state
        directly. The increment lands in ``state.mission_counter`` and is
        therefore replayable from a save (Task 19).
        """
        event = self.engine.apply(NextMissionIdCommand())
        return event.changes["mission_id"]

    # ------------------------------------------------------------------
    # Hook generation (R23, AE15).
    # ------------------------------------------------------------------

    def generate_hook(self) -> MissionHook:
        """Generate a mission hook from theme-pack mission tables.

        Rolls on patron_type, mission_objective, mission_complication, and
        mission_reward tables. Same RNG state -> same hook deterministically.
        """
        rolls: list[int] = []

        patron_roll = self._mission_table_roll("patron_type")
        rolls.append(patron_roll)
        patron = self._lookup_mission_table("patron_type", patron_roll)

        objective_roll = self._mission_table_roll("mission_objective")
        rolls.append(objective_roll)
        objective = self._lookup_mission_table("mission_objective", objective_roll)

        complication_roll = self._mission_table_roll("mission_complication")
        rolls.append(complication_roll)
        complication = self._lookup_mission_table("mission_complication", complication_roll)

        reward_roll = self._mission_table_roll("mission_reward")
        rolls.append(reward_roll)
        reward = self._lookup_mission_table("mission_reward", reward_roll)

        description = self._build_hook_description(patron, objective, complication, reward)

        return MissionHook(
            patron=patron,
            objective=objective,
            complication=complication,
            reward=reward,
            description=description,
            oracle_rolls=rolls,
        )

    # ------------------------------------------------------------------
    # Accept / refuse (R23, AE15).
    # ------------------------------------------------------------------

    def accept_mission(self, hook: MissionHook) -> Mission:
        """Accept a mission hook: transition to active state.

        Persists the mission in GameState so save/resume works mid-mission.
        The mission id is claimed from ``state.mission_counter`` via the
        command funnel so it survives save/load without collision (Task 19).
        """
        mission_id = self._next_mission_id()
        mission = Mission(
            id=mission_id,
            hook=hook,
            state=MissionState.ACTIVE,
            min_scenes=self._mission_min_scenes(),
            success_text=self._mission_ending_text("success"),
            failure_text=self._mission_ending_text("failure"),
            abandonment_text=self._mission_ending_text("abandonment"),
        )
        self._active_mission = mission

        # Persist in canonical state.
        self.engine.apply(SetMissionStateCommand(mission_data=mission.to_dict()))

        # Track the hook as an open thread (R25) so the curated view and fact
        # retrieval can reference it; removed when the mission resolves.
        from src.engine.scene import AddOpenThreadCommand

        self.engine.apply(AddOpenThreadCommand(thread=hook.summary))

        # Log the acceptance.
        self.engine.apply(_LogMissionCommand(text=f"Mission accepted: {hook.summary}"))

        return mission

    def refuse_mission(self) -> MissionHook:
        """Refuse the current hook: generate a new one.

        The engine returns to hook generation, rolling new tables.
        """
        self.engine.apply(_LogMissionCommand(text="Mission refused. Generating new hook..."))
        return self.generate_hook()

    # ------------------------------------------------------------------
    # Mission progression (R23).
    # ------------------------------------------------------------------

    def play_scene(self, mission: Mission, scene_engine: SceneEngine) -> SceneResult:
        """Play one scene of the active mission.

        Generates a scaffold and options. The caller (TUI) presents options
        to the player and resolves the chosen one. This method generates the
        scaffold + options and records the scene in the mission. The
        ``scenes_completed`` counter on the persisted mission dict is
        incremented so progress gating (Task 19) sees the latest value.
        """
        result = scene_engine.run_scene()
        mission.scenes_played += 1
        mission.scene_results.append(result)
        # Task 19: increment the persisted progress counter kept in sync
        # with ``scenes_played``. Storing both keeps older readers (which
        # only know ``scenes_played``) working while the new
        # :class:`ResolveMissionCommand` gating reads ``scenes_completed``.
        mission.scenes_completed = mission.scenes_played

        # Update persisted state.
        self.engine.apply(SetMissionStateCommand(mission_data=mission.to_dict()))

        return result

    # ------------------------------------------------------------------
    # Mission resolution (R23, AE15, Task 19).
    # ------------------------------------------------------------------

    def resolve_mission(
        self,
        mission: Mission,
        ending: MissionEnding,
        consequences: list[str] | None = None,
    ) -> None:
        """Resolve a mission with the given ending.

        Routes through :class:`ResolveMissionCommand` so the funnel validates
        progress gating (``scenes_completed >= min_scenes`` for success or
        failure; abandonment always allowed) and records the move from
        ``active_mission`` to ``completed_missions`` atomically (Task 19).

        ``consequences`` are stamped onto the in-memory mission before the
        pre-resolution :class:`SetMissionStateCommand` flush, so they land in
        the completed-mission record carried through the funnel — no direct
        state writes outside ``Engine.apply``.
        """
        # Keep the in-memory ``Mission`` in lock-step with canonical state.
        mission.ending = ending
        mission.state = MissionState.RESOLVED
        if consequences:
            mission.consequences.extend(consequences)
        # Persist the latest counter/text/consequences before resolving so
        # the command's validate step sees the gate values and the mutate
        # step carries consequences through to the completed record.
        self.engine.apply(SetMissionStateCommand(mission_data=mission.to_dict()))

        self.engine.apply(ResolveMissionCommand(ending=ending.value))

        # The mission's hook is no longer an open thread (R25).
        from src.engine.scene import RemoveOpenThreadCommand

        self.engine.apply(RemoveOpenThreadCommand(thread=mission.hook.summary))

        self.engine.apply(
            _LogMissionCommand(
                text=f"Mission resolved: {mission.id} ({ending.value}). "
                f"Consequences: {', '.join(mission.consequences) or 'none'}."
            )
        )

        # Task 22 (R19, AE16): generate a deterministic chapter summary from
        # the completed mission record + the narrative log, validate it with
        # the mechanical-claim guard, and route it through the funnel. The
        # template cannot fail by construction; the validator is a guard for
        # future LLM-polished text. On validation failure we flag the
        # degradation and ship the template anyway so the chapter always has
        # a summary in the curated view.
        self._record_chapter_summary(mission)

        self._active_mission = None

    # ------------------------------------------------------------------
    # Internal helpers.
    # ------------------------------------------------------------------

    def _record_chapter_summary(self, mission: Mission) -> None:
        """Build, validate, and persist a chapter summary (Task 22, R19, AE16).

        Uses :func:`build_template_summary` on the canonical completed-mission
        record plus the current narrative log, validates with
        :class:`SummaryValidator`, then applies
        :class:`AddChapterSummaryCommand` through the funnel. On validation
        failure, applies :class:`FlagDegradationCommand` and ships the template
        summary anyway — the template is safe by construction; the guard exists
        for future LLM-polished text.
        """
        # The canonical completed record was just appended by
        # ResolveMissionCommand; read it back so the summary reflects exactly
        # what landed in state (ending, scenes, hook).
        record = self.engine.state.completed_missions[-1]
        summary = build_template_summary(record, list(self.engine.state.narrative_log))
        result = SummaryValidator().validate(summary, self.engine.state)
        if not result.valid:
            self.engine.apply(
                FlagDegradationCommand(
                    area="summary",
                    reason=(
                        f"chapter summary validation failed; shipping template. "
                        f"Errors: {result.error_summary}"
                    ),
                )
            )
        self.engine.apply(AddChapterSummaryCommand(summary=summary))

    def _get_mission_table(self, table_id: str):
        """Look up a mission table by id."""
        if table_id not in self.pack.mission_tables:
            available = sorted(self.pack.mission_tables.keys())
            raise KeyError(
                f"Mission table '{table_id}' not found in pack '{self.pack.id}'. "
                f"Available: {available}"
            )
        return self.pack.mission_tables[table_id]

    def _mission_table_roll(self, table_id: str) -> int:
        """Roll 2D6 on the oracle stream via the command funnel."""
        cmd = MissionTableRollCommand(table_id=table_id)
        event = self.engine.apply(cmd)
        return event.changes["roll_total"]

    def _lookup_mission_table(self, table_id: str, roll: int) -> str:
        """Look up a mission table result by roll value."""
        table = self._get_mission_table(table_id)
        entry = lookup_table_result(table.entries.entries, roll)
        return entry.result

    @staticmethod
    def _build_hook_description(
        patron: str,
        objective: str,
        complication: str,
        reward: str,
    ) -> str:
        """Build a narrative description from hook components."""
        return (
            f"A {patron} The mission: {objective} "
            f"However, there's a complication: {complication} "
            f"The reward: {reward}"
        )

    # ------------------------------------------------------------------
    # Pack-driven mission defaults (Task 19).
    # ------------------------------------------------------------------

    def _mission_min_scenes(self) -> int:
        """Return the configured ``min_scenes`` for the active hook.

        Pack authors can ship a ``mission_arc`` table whose matched row
        carries ``min_scenes`` (see :class:`MissionHookEntry`). When the
        pack doesn't ship one, the Cepheus default of three scenes applies
        so resolve gating degrades gracefully on older packs.
        """
        entry = self._lookup_optional_arc_entry()
        if entry is not None:
            return int(getattr(entry, "min_scenes", 3))
        return 3

    def _mission_ending_text(self, ending: str) -> str:
        """Return pack-supplied ending prose for ``ending`` (Task 19).

        ``ending`` is one of ``"success"``, ``"failure"``, ``"abandonment"``.
        Falls back to ``""`` when the pack ships no mission-arc data, so the
        TUI's narrator can supply a sensible default instead of the engine
        hardcoding strings.
        """
        entry = self._lookup_optional_arc_entry()
        if entry is None:
            return ""
        field = f"{ending}_text"
        return str(getattr(entry, field, "") or "")

    def _lookup_optional_arc_entry(self):
        """Return a ``mission_arc`` table row if the pack ships one.

        The lookup rolls 2D6 on the oracle stream when the table exists.
        Returns ``None`` for packs without a ``mission_arc`` table so
        callers fall back to defaults without raising.
        """
        if "mission_arc" not in self.pack.mission_tables:
            return None
        roll = self._mission_table_roll("mission_arc")
        table = self._get_mission_table("mission_arc")
        return lookup_table_result(table.entries.entries, roll)


class _LogMissionCommand(Command):
    """Internal command to append a mission log entry."""

    command_type: ClassVar[str] = "log_mission"
    text: str

    def validate(self, state: GameState) -> None:
        if not self.text or not self.text.strip():
            raise ValueError("Mission log text must be non-empty")

    def mutate(self, state: GameState, roll: RollResult | None) -> Event:
        state.narrative_log.append(self.text.strip())
        return Event(
            kind=EventKind.STATE_CHANGE,
            command_type=self.command_type,
            description="Mission log entry",
            changes={"text": self.text},
        )
