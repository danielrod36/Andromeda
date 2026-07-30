"""Tests for mission lifecycle: hooks, accept/refuse, resolution, persistence.

Covers AE15 (mission hook offered, accepted, played to ending; consequences
persist; returns to hook generation), R23 (missions as discrete arcs with
endings), mission refusal generating a new hook.
"""

from __future__ import annotations

import pytest

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.mission import (
    Mission,
    MissionEnding,
    MissionEngine,
    MissionHook,
    MissionState,
)
from src.engine.state import CampaignConfig, GameState
from src.themepacks.base import get_pack

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def pack():
    return get_pack("scifi")


def make_engine(queue, seed=42):
    """Create an engine with ForcedRoller."""
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig()
    state.character.characteristics = {
        "STR": 7,
        "DEX": 7,
        "END": 7,
        "INT": 7,
        "EDU": 7,
        "SOC": 7,
    }
    state.character.skills = {"Gun Combat": 1, "Persuade": 0}
    return Engine(state, roller=ForcedRoller(queue))


# ---------------------------------------------------------------------------
# Hook generation (R23, AE15).
# ---------------------------------------------------------------------------


class TestHookGeneration:
    """Mission hooks generated from theme-pack mission tables."""

    def test_generate_hook_produces_all_components(self, pack):
        """Hook has patron, objective, complication, reward."""
        # Queue: 4 rolls for patron, objective, complication, reward.
        engine = make_engine([[3, 4], [5, 5], [3, 3], [4, 4]])
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()

        assert len(hook.patron) > 0
        assert len(hook.objective) > 0
        assert len(hook.complication) > 0
        assert len(hook.reward) > 0
        assert len(hook.oracle_rolls) == 4

    def test_hook_summary_is_readable(self, pack):
        """Hook summary contains all components."""
        engine = make_engine([[3, 4], [5, 5], [3, 3], [4, 4]])
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()

        summary = hook.summary
        assert "Objective" in summary
        assert "Complication" in summary
        assert "Reward" in summary

    def test_same_rolls_produce_same_hook(self, pack):
        """Same rolls produce identical hooks (determinism)."""
        engine1 = make_engine([[3, 4], [5, 5], [3, 3], [4, 4]])
        engine2 = make_engine([[3, 4], [5, 5], [3, 3], [4, 4]])

        me1 = MissionEngine(engine1, pack)
        me2 = MissionEngine(engine2, pack)

        h1 = me1.generate_hook()
        h2 = me2.generate_hook()

        assert h1.patron == h2.patron
        assert h1.objective == h2.objective
        assert h1.complication == h2.complication
        assert h1.reward == h2.reward

    def test_hook_rolls_recorded_in_audit(self, pack):
        """Mission table rolls recorded in event log."""
        engine = make_engine([[3, 4], [5, 5], [3, 3], [4, 4]])
        me = MissionEngine(engine, pack)
        me.generate_hook()

        mission_events = [e for e in engine.state.events if e.command_type == "mission_table_roll"]
        assert len(mission_events) == 4


# ---------------------------------------------------------------------------
# AE15: Accept/refuse mission.
# ---------------------------------------------------------------------------


class TestMissionAcceptRefuse:
    """Mission hook offered, accepted or refused; engine returns to hook gen."""

    def test_accept_mission_sets_active(self, pack):
        """Accepting a hook transitions to active state."""
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],  # hook rolls
            ]
        )
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        mission = me.accept_mission(hook)

        assert mission.state == MissionState.ACTIVE
        assert mission.hook is hook
        assert me.active_mission is mission
        # Persisted in state.
        assert engine.state.active_mission is not None
        assert engine.state.active_mission["id"] == mission.id

    def test_accept_mission_records_in_audit(self, pack):
        """Accepting a mission is recorded in the event log."""
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],
            ]
        )
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        me.accept_mission(hook)

        mission_events = [e for e in engine.state.events if e.command_type == "set_mission_state"]
        assert len(mission_events) >= 1

    def test_refuse_generates_new_hook(self, pack):
        """Refusing a hook generates a new one (AE15)."""
        # 4 rolls for first hook, 4 for second.
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],  # first hook
                [6, 6],
                [2, 2],
                [5, 6],
                [1, 1],  # second hook
            ]
        )
        me = MissionEngine(engine, pack)
        hook1 = me.generate_hook()
        hook2 = me.refuse_mission()

        # The new hook should have different rolls.
        assert hook2.oracle_rolls != hook1.oracle_rolls

    def test_refuse_does_not_set_active_mission(self, pack):
        """Refusing does not set an active mission."""
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],  # first hook
                [6, 6],
                [2, 2],
                [5, 6],
                [1, 1],  # second hook
            ]
        )
        me = MissionEngine(engine, pack)
        me.generate_hook()
        me.refuse_mission()

        assert engine.state.active_mission is None


# ---------------------------------------------------------------------------
# Mission resolution and consequences (R23, AE15).
# ---------------------------------------------------------------------------


class TestMissionResolution:
    """Missions resolve with endings; consequences persist."""

    def test_resolve_success(self, pack):
        """Mission resolved with SUCCESS ending."""
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],  # hook
            ]
        )
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        mission = me.accept_mission(hook)

        me.resolve_mission(mission, MissionEnding.SUCCESS)

        assert mission.state == MissionState.RESOLVED
        assert mission.ending == MissionEnding.SUCCESS
        assert me.active_mission is None

    def test_resolve_failure(self, pack):
        """Mission resolved with FAILURE ending."""
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],
            ]
        )
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        mission = me.accept_mission(hook)

        me.resolve_mission(mission, MissionEnding.FAILURE)

        assert mission.ending == MissionEnding.FAILURE

    def test_resolve_abandonment(self, pack):
        """Mission resolved with ABANDONMENT ending."""
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],
            ]
        )
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        mission = me.accept_mission(hook)

        me.resolve_mission(mission, MissionEnding.ABANDONMENT)

        assert mission.ending == MissionEnding.ABANDONMENT

    def test_consequences_persist_after_resolution(self, pack):
        """Consequences are recorded and persist in completed missions."""
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],
            ]
        )
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        mission = me.accept_mission(hook)

        consequences = ["Reputation increased.", "Payment received."]
        me.resolve_mission(mission, MissionEnding.SUCCESS, consequences)

        # Active mission cleared, completed mission recorded.
        assert engine.state.active_mission is None
        assert len(engine.state.completed_missions) == 1
        completed = engine.state.completed_missions[0]
        assert completed["ending"] == "success"
        assert "Reputation increased." in completed["consequences"]

    def test_returns_to_hook_after_resolution(self, pack):
        """After resolution, engine can generate a new hook (AE15)."""
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],  # first mission hook
                [6, 6],
                [2, 2],
                [5, 6],
                [1, 1],  # second mission hook
            ]
        )
        me = MissionEngine(engine, pack)

        hook1 = me.generate_hook()
        mission1 = me.accept_mission(hook1)
        me.resolve_mission(mission1, MissionEnding.SUCCESS)

        hook2 = me.generate_hook()
        assert hook2.oracle_rolls != hook1.oracle_rolls


# ---------------------------------------------------------------------------
# Mission persistence across save/resume (AE8).
# ---------------------------------------------------------------------------


class TestMissionPersistence:
    """Mission state persists in GameState for save/resume."""

    def test_mission_to_dict_roundtrips(self, pack):
        """Mission serializes to dict correctly."""
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],
            ]
        )
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        mission = me.accept_mission(hook)

        d = mission.to_dict()
        assert d["id"] == mission.id
        assert d["state"] == "active"
        assert d["hook"]["patron"] == hook.patron

    def test_mission_recorded_in_completed_list(self, pack):
        """Completed missions are in the completed_missions list."""
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],
            ]
        )
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        mission = me.accept_mission(hook)
        me.resolve_mission(mission, MissionEnding.SUCCESS)

        assert len(engine.state.completed_missions) == 1

    def test_multiple_missions_accumulate(self, pack):
        """Multiple completed missions accumulate in history."""
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],  # mission 1
                [6, 6],
                [2, 2],
                [5, 6],
                [1, 1],  # mission 2
            ]
        )
        me = MissionEngine(engine, pack)

        # Mission 1.
        hook1 = me.generate_hook()
        m1 = me.accept_mission(hook1)
        me.resolve_mission(m1, MissionEnding.SUCCESS)

        # Mission 2.
        hook2 = me.generate_hook()
        m2 = me.accept_mission(hook2)
        me.resolve_mission(m2, MissionEnding.FAILURE)

        assert len(engine.state.completed_missions) == 2
        assert engine.state.completed_missions[0]["ending"] == "success"
        assert engine.state.completed_missions[1]["ending"] == "failure"


# ---------------------------------------------------------------------------
# Integration: full mission arc.
# ---------------------------------------------------------------------------


class TestFullMissionArc:
    """Full mission arc: hook -> accept -> play -> resolve (AE15)."""

    def test_full_arc_success(self, pack):
        """Hook offered, accepted, played, resolved with consequences."""
        # Hook rolls + scene oracle rolls + scene check.
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],  # hook
                [5, 5],
                [4, 4],  # scene oracle
                [6, 6],  # scene check (strong hit)
            ]
        )
        me = MissionEngine(engine, pack)
        from src.engine.scene import SceneEngine

        se = SceneEngine(engine, pack)

        # 1. Hook.
        hook = me.generate_hook()
        assert hook is not None

        # 2. Accept.
        mission = me.accept_mission(hook)
        assert mission.is_active

        # 3. Play a scene.
        scene_result = me.play_scene(mission, se)
        assert len(scene_result.options) >= 2

        # Resolve the scene check.
        check = se.resolve_scene(scene_result.scaffold, scene_result.options[0])
        se.apply_consequences(check, scene_result.scaffold)

        # 4. Resolve mission.
        me.resolve_mission(mission, MissionEnding.SUCCESS, ["Mission reward gained."])

        assert mission.is_resolved
        assert engine.state.active_mission is None
        assert len(engine.state.completed_missions) == 1

    def test_full_arc_with_refusal(self, pack):
        """Refuse first hook, accept second, play, resolve."""
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],  # hook 1
                [6, 6],
                [2, 2],
                [5, 6],
                [1, 1],  # hook 2
                [5, 5],
                [4, 4],  # scene oracle
            ]
        )
        me = MissionEngine(engine, pack)

        # 1. First hook — refused.
        hook1 = me.generate_hook()
        hook2 = me.refuse_mission()
        assert hook1.oracle_rolls != hook2.oracle_rolls

        # 2. Accept second hook.
        mission = me.accept_mission(hook2)
        assert mission.is_active

        # 3. Resolve.
        me.resolve_mission(mission, MissionEnding.ABANDONMENT)
        assert mission.ending == MissionEnding.ABANDONMENT


# ---------------------------------------------------------------------------
# Mission.from_dict — resume reconstruction (Fix #3).
# ---------------------------------------------------------------------------


class TestMissionFromDict:
    """Mission.from_dict reconstructs a Mission from its serialized form (Fix #3)."""

    def test_round_trip(self):
        """to_dict -> from_dict produces an equivalent Mission."""
        hook = MissionHook(
            patron="Noble",
            objective="Spy on rivals",
            complication="Double agent",
            reward="Political favor",
            description="A dangerous mission.",
        )
        original = Mission(
            id="mission_5",
            hook=hook,
            state=MissionState.ACTIVE,
            scenes_played=3,
            consequences=["Gained a contact.", "Lost a ship."],
        )
        reconstructed = Mission.from_dict(original.to_dict())

        assert reconstructed.id == "mission_5"
        assert reconstructed.hook.patron == "Noble"
        assert reconstructed.hook.objective == "Spy on rivals"
        assert reconstructed.state == MissionState.ACTIVE
        assert reconstructed.scenes_played == 3
        assert reconstructed.consequences == ["Gained a contact.", "Lost a ship."]
        assert reconstructed.is_active

    def test_from_dict_with_ending(self):
        """from_dict handles a resolved mission with an ending."""
        hook = MissionHook(
            patron="Merchant", objective="Deliver", complication="None", reward="Cash"
        )
        original = Mission(
            id="mission_3",
            hook=hook,
            state=MissionState.RESOLVED,
            ending=MissionEnding.SUCCESS,
        )
        reconstructed = Mission.from_dict(original.to_dict())

        assert reconstructed.state == MissionState.RESOLVED
        assert reconstructed.ending == MissionEnding.SUCCESS

    def test_from_dict_handles_missing_fields(self):
        """from_dict handles incomplete dicts gracefully."""
        data = {"id": "mission_1", "hook": {"patron": "Test"}}
        mission = Mission.from_dict(data)

        assert mission.id == "mission_1"
        assert mission.hook.patron == "Test"
        assert mission.state == MissionState.ACTIVE
        assert mission.scenes_played == 0
