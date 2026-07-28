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
from src.engine.commands import Command, Engine
from src.engine.dice import RollResult, Roller
from src.engine.lifepath import lookup_table_result
from src.engine.scene import SceneEngine, SceneResult
from src.engine.state import GameState
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
        }


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
        self._mission_counter = 0
        self._active_mission: Mission | None = None

    @property
    def active_mission(self) -> Mission | None:
        return self._active_mission

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
        complication = self._lookup_mission_table(
            "mission_complication", complication_roll
        )

        reward_roll = self._mission_table_roll("mission_reward")
        rolls.append(reward_roll)
        reward = self._lookup_mission_table("mission_reward", reward_roll)

        description = self._build_hook_description(
            patron, objective, complication, reward
        )

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
        """
        self._mission_counter += 1
        mission = Mission(
            id=f"mission_{self._mission_counter}",
            hook=hook,
            state=MissionState.ACTIVE,
        )
        self._active_mission = mission

        # Persist in canonical state.
        self.engine.apply(
            SetMissionStateCommand(mission_data=mission.to_dict())
        )

        # Log the acceptance.
        self.engine.apply(
            _LogMissionCommand(text=f"Mission accepted: {hook.summary}")
        )

        return mission

    def refuse_mission(self) -> MissionHook:
        """Refuse the current hook: generate a new one.

        The engine returns to hook generation, rolling new tables.
        """
        self.engine.apply(
            _LogMissionCommand(text="Mission refused. Generating new hook...")
        )
        return self.generate_hook()

    # ------------------------------------------------------------------
    # Mission progression (R23).
    # ------------------------------------------------------------------

    def play_scene(self, mission: Mission, scene_engine: SceneEngine) -> SceneResult:
        """Play one scene of the active mission.

        Generates a scaffold and options. The caller (TUI) presents options
        to the player and resolves the chosen one. This method generates the
        scaffold + options and records the scene in the mission.
        """
        result = scene_engine.run_scene()
        mission.scenes_played += 1
        mission.scene_results.append(result)

        # Update persisted state.
        self.engine.apply(
            SetMissionStateCommand(mission_data=mission.to_dict())
        )

        return result

    # ------------------------------------------------------------------
    # Mission resolution (R23, AE15).
    # ------------------------------------------------------------------

    def resolve_mission(
        self,
        mission: Mission,
        ending: MissionEnding,
        consequences: list[str] | None = None,
    ) -> None:
        """Resolve a mission with the given ending.

        Transitions the mission to RESOLVED, records consequences, and
        persists in canonical state. After resolution, the engine returns
        to hook generation.
        """
        mission.state = MissionState.RESOLVED
        mission.ending = ending
        if consequences:
            mission.consequences.extend(consequences)

        # Persist as completed mission; clears active_mission.
        self.engine.apply(
            SetMissionStateCommand(completed_mission=mission.to_dict())
        )

        self.engine.apply(
            _LogMissionCommand(
                text=f"Mission resolved: {mission.id} ({ending.value}). "
                f"Consequences: {', '.join(mission.consequences) or 'none'}."
            )
        )

        self._active_mission = None

    # ------------------------------------------------------------------
    # Internal helpers.
    # ------------------------------------------------------------------

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
