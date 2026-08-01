"""Tests for mission lifecycle: hooks, accept/refuse, resolution, persistence.

Covers AE15 (mission hook offered, accepted, played to ending; consequences
persist; returns to hook generation), R23 (missions as discrete arcs with
endings), mission refusal generating a new hook, Task 19 (persisted mission
IDs, progress gating, real endings).
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
    NextMissionIdCommand,
    ResolveMissionCommand,
)
from src.engine.persistence import load, save
from src.engine.state import CampaignConfig, GameState
from src.themepacks.base import get_pack

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def pack():
    return get_pack("scifi")


@pytest.fixture
def engine_and_pack():
    """Fresh (engine, pack) for isolated command tests (Task 19).

    Queues enough oracle rolls for one ``generate_hook()`` call (4 × 2D6)
    so tests that just need a hook for accept/refuse don't each have to
    rebuild the queue.
    """
    pack = get_pack("scifi")
    state = GameState.new(seed=42)
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
    engine = Engine(
        state,
        roller=ForcedRoller([[3, 4], [5, 5], [3, 3], [4, 4]]),
    )
    return engine, pack


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


def meet_min_scenes(engine, mission):
    """Bump ``scenes_completed`` past the gate so success/failure resolve (Task 19)."""
    mission.scenes_completed = mission.min_scenes
    if engine.state.active_mission is not None:
        engine.state.active_mission["scenes_completed"] = mission.min_scenes


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
        meet_min_scenes(engine, mission)  # Task 19: meet min_scenes gate.

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
        meet_min_scenes(engine, mission)  # Task 19: meet min_scenes gate.

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
        meet_min_scenes(engine, mission)  # Task 19: meet min_scenes gate.

        consequences = ["Reputation increased.", "Payment received."]
        me.resolve_mission(mission, MissionEnding.SUCCESS, consequences)

        # Active mission cleared, completed mission recorded.
        assert engine.state.active_mission is None
        assert len(engine.state.completed_missions) == 1
        completed = engine.state.completed_missions[0]
        assert completed["ending"] == "success"
        assert "Reputation increased." in completed["consequences"]
        # Task 19: consequences must not be doubled by the resolve flow.
        assert len(completed["consequences"]) == len(consequences)

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
        meet_min_scenes(engine, mission1)  # Task 19: meet min_scenes gate.
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
        meet_min_scenes(engine, mission)  # Task 19: meet min_scenes gate.
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
        meet_min_scenes(engine, m1)  # Task 19: meet min_scenes gate.
        me.resolve_mission(m1, MissionEnding.SUCCESS)

        # Mission 2.
        hook2 = me.generate_hook()
        m2 = me.accept_mission(hook2)
        meet_min_scenes(engine, m2)  # Task 19: meet min_scenes gate.
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
        # Hook rolls + scene oracle rolls + scene check + complication roll
        # (Task 18: weak-hit path rolls the pack complication table).
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],  # hook
                [5, 5],
                [4, 4],  # scene oracle
                [6, 6],  # scene check (resolves as weak hit given untrained DM)
                [3, 3],  # complication-table roll on the oracle stream
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

        # 4. Resolve mission. Task 19: bump past the min_scenes gate — the
        # full-arc test exercises wiring, not gating (covered separately).
        meet_min_scenes(engine, mission)
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


# ---------------------------------------------------------------------------
# Task 19: Persisted mission IDs, progress gating, real endings.
# ---------------------------------------------------------------------------


class TestPersistedMissionId:
    """Mission IDs come from state.mission_counter and survive save/load."""

    def test_next_mission_id_increments_counter(self, engine_and_pack):
        engine, _pack = engine_and_pack
        assert engine.state.mission_counter == 0
        cmd = NextMissionIdCommand()
        event = engine.apply(cmd)
        assert engine.state.mission_counter == 1
        assert event.changes["mission_id"] == "mission_1"

    def test_mission_ids_survive_save_load(self, engine_and_pack, tmp_path):
        """Two engines over the same save produce distinct mission ids (R23)."""
        engine, pack = engine_and_pack
        me = MissionEngine(engine, pack)
        me.generate_hook()
        id_first = me._next_mission_id()
        save(engine.state, tmp_path / "s.json")

        engine2 = Engine(load(tmp_path / "s.json"))
        me2 = MissionEngine(engine2, pack)
        id_second = me2._next_mission_id()

        assert id_second != id_first
        # The counter persisted: engine2 picked up from engine1's value and
        # advanced by exactly one more claim.
        assert engine2.state.mission_counter == engine.state.mission_counter + 1

    def test_accept_mission_uses_persisted_id(self, engine_and_pack):
        """MissionEngine.accept_mission pulls ids from state, not an in-memory counter."""
        engine, pack = engine_and_pack
        # Pre-bump the counter to simulate a resumed game.
        engine.state.mission_counter = 4
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        mission = me.accept_mission(hook)
        assert mission.id == "mission_5"
        assert engine.state.mission_counter == 5


class TestResolveMissionProgressGating:
    """ResolveMissionCommand enforces min_scenes for success/failure."""

    def _active_mission(self, scenes_completed: int, min_scenes: int = 3) -> dict:
        return {
            "id": "m1",
            "scenes_completed": scenes_completed,
            "min_scenes": min_scenes,
            "hook": "x",
            "status": "active",
        }

    def test_cannot_resolve_success_before_min_scenes(self, engine_and_pack):
        engine, _pack = engine_and_pack
        engine.state.active_mission = self._active_mission(scenes_completed=0)
        with pytest.raises(ValueError, match="scenes"):
            engine.apply(ResolveMissionCommand(ending="success"))

    def test_cannot_resolve_failure_before_min_scenes(self, engine_and_pack):
        engine, _pack = engine_and_pack
        engine.state.active_mission = self._active_mission(scenes_completed=2)
        with pytest.raises(ValueError, match="scenes"):
            engine.apply(ResolveMissionCommand(ending="failure"))

    def test_can_resolve_success_at_min_scenes(self, engine_and_pack):
        engine, _pack = engine_and_pack
        engine.state.active_mission = self._active_mission(scenes_completed=3)
        engine.apply(ResolveMissionCommand(ending="success"))
        assert engine.state.active_mission is None
        assert engine.state.completed_missions[-1]["ending"] == "success"

    def test_abandonment_always_allowed(self, engine_and_pack):
        engine, _pack = engine_and_pack
        engine.state.active_mission = self._active_mission(scenes_completed=0)
        engine.apply(ResolveMissionCommand(ending="abandonment"))
        assert engine.state.active_mission is None
        assert engine.state.completed_missions[-1]["ending"] == "abandonment"

    def test_resolve_validates_ending_value(self, engine_and_pack):
        engine, _pack = engine_and_pack
        engine.state.active_mission = self._active_mission(scenes_completed=3)
        with pytest.raises(ValueError, match="Unknown ending"):
            engine.apply(ResolveMissionCommand(ending="glorious"))

    def test_resolve_requires_active_mission(self, engine_and_pack):
        engine, _pack = engine_and_pack
        with pytest.raises(ValueError, match="No active mission"):
            engine.apply(ResolveMissionCommand(ending="abandonment"))


class TestSceneCountIncrement:
    """play_scene increments scenes_completed in canonical state."""

    def test_play_scene_increments_scenes_completed(self, pack):
        engine = make_engine(
            [
                [3, 4],
                [5, 5],
                [3, 3],
                [4, 4],  # hook rolls
                [5, 5],
                [4, 4],  # scene oracle
                [6, 6],  # scene check
            ]
        )
        me = MissionEngine(engine, pack)
        from src.engine.scene import SceneEngine

        se = SceneEngine(engine, pack)
        hook = me.generate_hook()
        mission = me.accept_mission(hook)
        assert engine.state.active_mission["scenes_completed"] == 0

        scene = me.play_scene(mission, se)
        assert scene is not None
        assert engine.state.active_mission["scenes_completed"] == 1
        assert mission.scenes_played == 1

    def test_accept_mission_records_min_scenes_default(self, pack):
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
        # Default min_scenes applied.
        assert mission.min_scenes == 3
        assert engine.state.active_mission["min_scenes"] == 3
        assert engine.state.active_mission["scenes_completed"] == 0


class TestResolveViaEngineRecordsEnding:
    """MissionEngine.resolve_mission routes through ResolveMissionCommand."""

    def test_resolve_records_consequences_from_hook_text(self, pack):
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
        # Push past min_scenes so success is allowed.
        engine.state.active_mission["scenes_completed"] = mission.min_scenes
        mission.scenes_completed = mission.min_scenes

        me.resolve_mission(mission, MissionEnding.SUCCESS)
        assert engine.state.completed_missions[-1]["ending"] == "success"
        assert engine.state.active_mission is None


# ---------------------------------------------------------------------------
# Task 21 — open threads added on accept, removed on resolve (R25).
# ---------------------------------------------------------------------------


class TestOpenThreadLifecycle:
    """Mission hooks become open threads on accept and clear on resolve."""

    def test_accept_adds_open_thread(self, engine_and_pack):
        from src.engine.mission import MissionEngine

        engine, pack = engine_and_pack
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        summary = hook.summary
        me.accept_mission(hook)
        assert summary in engine.state.open_threads

    def test_resolve_removes_open_thread(self, engine_and_pack):
        from src.engine.mission import MissionEngine

        engine, pack = engine_and_pack
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        summary = hook.summary
        mission = me.accept_mission(hook)
        assert summary in engine.state.open_threads
        # Push past min_scenes so success is allowed.
        engine.state.active_mission["scenes_completed"] = mission.min_scenes
        mission.scenes_completed = mission.min_scenes
        me.resolve_mission(mission, MissionEnding.SUCCESS)
        assert summary not in engine.state.open_threads


# ---------------------------------------------------------------------------
# Task 22 — chapter summaries generated at mission resolve (R19, AE16).
# ---------------------------------------------------------------------------


class TestChapterSummaryOnResolve:
    """MissionEngine.resolve_mission appends a chapter summary (Task 22)."""

    def test_resolving_mission_appends_chapter_summary(self, pack):
        """A resolved mission leaves exactly one chapter summary in state."""
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
        meet_min_scenes(engine, mission)

        assert engine.state.chapter_summaries == []
        me.resolve_mission(mission, MissionEnding.SUCCESS)

        assert len(engine.state.chapter_summaries) == 1
        summary = engine.state.chapter_summaries[0]
        # Template embeds the ending and the hook objective.
        assert "success" in summary.lower()
        assert hook.objective in summary

    def test_summary_emits_add_chapter_summary_event(self, engine_and_pack):
        """The summary is applied via AddChapterSummaryCommand (audited)."""
        engine, pack = engine_and_pack
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        mission = me.accept_mission(hook)
        meet_min_scenes(engine, mission)

        me.resolve_mission(mission, MissionEnding.SUCCESS)

        summary_events = [e for e in engine.state.events if e.command_type == "add_chapter_summary"]
        assert len(summary_events) == 1
        assert summary_events[0].changes["summary"] == engine.state.chapter_summaries[0]

    def test_abandonment_also_summarizes(self, engine_and_pack):
        """The abandon path produces a chapter summary too (Task 19 + 22)."""
        engine, pack = engine_and_pack
        me = MissionEngine(engine, pack)
        hook = me.generate_hook()
        mission = me.accept_mission(hook)

        me.resolve_mission(mission, MissionEnding.ABANDONMENT)

        assert len(engine.state.chapter_summaries) == 1
        assert "abandonment" in engine.state.chapter_summaries[0].lower()

    def test_two_missions_curated_view_has_two_summaries_no_raw_events(self, engine_and_pack):
        """AE16: after two missions, curated view carries two summaries and
        no raw event history.
        """
        import json

        from src.llm.state_view import build_curated_view

        engine, pack = engine_and_pack
        me = MissionEngine(engine, pack)

        # Mission 1 — needs its own hook rolls (the fixture queues 4 rolls).
        hook1 = me.generate_hook()
        mission1 = me.accept_mission(hook1)
        meet_min_scenes(engine, mission1)
        me.resolve_mission(mission1, MissionEnding.SUCCESS)

        # Mission 2 — queue fresh oracle rolls for the second hook.
        engine.roller.extend([[3, 4], [5, 5], [3, 3], [4, 4]])
        hook2 = me.generate_hook()
        mission2 = me.accept_mission(hook2)
        meet_min_scenes(engine, mission2)
        me.resolve_mission(mission2, MissionEnding.FAILURE)

        assert len(engine.state.chapter_summaries) == 2

        view = build_curated_view(engine.state)
        assert len(view.chapter_summaries) == 2

        # No raw event-log content should leak into the curated view.
        raw = json.dumps(view.model_dump())
        assert "command_type" not in raw
        assert "scene_check" not in raw
        assert "resolve_mission" not in raw


# ---------------------------------------------------------------------------
# CHAP-1: LLM chapter summaries. resolve_mission accepts an injected
# summary_generator (sync callable); when it returns a valid summary, that
# lands in state.chapter_summaries instead of the deterministic template.
# Mirrors the classify_freetext(llm_classifier=...) injection pattern.
# ---------------------------------------------------------------------------


class TestChapterSummaryInjection:
    """An injected summary generator produces the chapter summary (R19, AE16)."""

    def test_summary_generator_used_when_provided(self, pack):
        """A provided summary_generator's output replaces the template."""
        engine = make_engine([[3, 4], [5, 5], [3, 3], [4, 4]])
        me = MissionEngine(engine, pack)
        mission = me.accept_mission(me.generate_hook())
        meet_min_scenes(engine, mission)

        def gen(record, log_entries):
            return "The Vega cargo run ended with the crew richer and a step ahead of the guild."

        me.resolve_mission(mission, MissionEnding.SUCCESS, summary_generator=gen)

        assert engine.state.chapter_summaries
        assert engine.state.chapter_summaries[-1] == (
            "The Vega cargo run ended with the crew richer and a step ahead of the guild."
        )

    def test_template_fallback_when_generator_returns_none(self, pack):
        """When the generator signals LLM failure (None), the template ships."""
        engine = make_engine([[3, 4], [5, 5], [3, 3], [4, 4]])
        me = MissionEngine(engine, pack)
        mission = me.accept_mission(me.generate_hook())
        meet_min_scenes(engine, mission)

        def gen(record, log_entries):
            return None  # LLM unavailable / failed

        me.resolve_mission(mission, MissionEnding.SUCCESS, summary_generator=gen)

        # Template summary always mentions the mission and the ending.
        assert engine.state.chapter_summaries
        assert "success" in engine.state.chapter_summaries[-1].lower()

    def test_invalid_llm_summary_falls_back_to_template(self, pack):
        """An LLM summary that fails mechanical-claim validation is rejected;
        the safe template ships instead (R19 validation gate)."""
        engine = make_engine([[3, 4], [5, 5], [3, 3], [4, 4]])
        me = MissionEngine(engine, pack)
        mission = me.accept_mission(me.generate_hook())
        meet_min_scenes(engine, mission)

        def gen(record, log_entries):
            # Leaks mechanical claims — must be rejected by the validator.
            return "The crew rolled 2d6+3 vs 8 for a strong hit (DM +2)."

        me.resolve_mission(mission, MissionEnding.SUCCESS, summary_generator=gen)

        summary = engine.state.chapter_summaries[-1]
        # The invalid LLM text must NOT have shipped; the template did.
        assert "2d6" not in summary.lower()
        assert "vs 8" not in summary.lower()

    def test_template_fallback_when_generator_raises(self, pack):
        """When the generator raises an exception, the engine catches it and
        ships the template summary (mission resolution never crashes)."""
        engine = make_engine([[3, 4], [5, 5], [3, 3], [4, 4]])
        me = MissionEngine(engine, pack)
        mission = me.accept_mission(me.generate_hook())
        meet_min_scenes(engine, mission)

        def gen(record, log_entries):
            raise RuntimeError("provider timeout")

        me.resolve_mission(mission, MissionEnding.SUCCESS, summary_generator=gen)

        # Template summary always mentions the mission and the ending.
        assert engine.state.chapter_summaries
        assert "success" in engine.state.chapter_summaries[-1].lower()
