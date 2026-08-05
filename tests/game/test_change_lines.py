"""Tests for change-lines derivation and gated options (U14, R16).

Covers:
- Each mutation kind produces the correct change-line text and CSS class.
- Suppressed command types (internal flags, oracle rolls) produce no line.
- derive_recent_change_lines respects the sequence boundary.
- Adventure controller populates change_lines after actions.
- Mission gate "Push for the ending" renders dimmed with requirement.
- Integration: mission resolution produces change_lines via resolve_mission.
"""

from __future__ import annotations

from src.engine.audit import Event, EventKind
from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.state import CampaignConfig, GameState
from src.game.adventure import AdventureController
from src.game.change_lines import (
    CHANGE_NEGATIVE,
    CHANGE_NEUTRAL,
    CHANGE_POSITIVE,
    ChangeLine,
    derive_change_line,
    derive_change_lines,
    derive_recent_change_lines,
)
from src.themepacks.cepheus_scifi import load_scifi_pack


def _make_event(
    command_type: str,
    changes: dict,
    seq: int = 0,
    kind: EventKind = EventKind.STATE_CHANGE,
) -> Event:
    return Event(
        seq=seq,
        kind=kind,
        command_type=command_type,
        description="test",
        changes=changes,
    )


class TestChangeLineDerivation:
    """Each mutation kind produces correct text and styling (U14).

    Command types and changes-dict field names match what the engine's
    Command subclasses actually emit in their ``mutate()`` methods.
    """

    def test_skill_gained(self):
        event = _make_event("lifepath_gain_skill", {"skill_id": "Pilot", "level": 0}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "Pilot" in line.text
        assert line.css_class == CHANGE_POSITIVE

    def test_skill_improved(self):
        event = _make_event("lifepath_gain_skill", {"skill_id": "Gun Combat", "level": 2}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "level 2" in line.text
        assert line.css_class == CHANGE_POSITIVE

    def test_register_fact(self):
        event = _make_event("register_fact", {"name": "Station Alpha", "description": ""}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "Station Alpha" in line.text
        assert line.css_class == CHANGE_POSITIVE

    def test_add_injury(self):
        event = _make_event("add_injury", {"name": "Broken Arm", "severity": "severe"}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "Broken Arm" in line.text
        assert "severe" in line.text
        assert line.css_class == CHANGE_NEGATIVE

    def test_add_open_thread(self):
        event = _make_event("add_open_thread", {"thread": "Debt to Vaska"}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "Debt to Vaska" in line.text
        assert line.css_class == CHANGE_NEUTRAL

    def test_remove_open_thread(self):
        event = _make_event("remove_open_thread", {"thread": "Debt to Vaska"}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "resolved" in line.text.lower()
        assert line.css_class == CHANGE_POSITIVE

    def test_character_dead(self):
        event = _make_event("set_character_dead", {"reason": "pirate ambush"}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "died" in line.text.lower()
        assert "pirate ambush" in line.text
        assert line.css_class == CHANGE_NEGATIVE

    def test_resolve_mission_success(self):
        event = _make_event(
            "resolve_mission", {"mission_id": "mission_1", "ending": "success"}, seq=1
        )
        line = derive_change_line(event)
        assert line is not None
        assert "success" in line.text
        assert "mission_1" in line.text
        assert line.css_class == CHANGE_POSITIVE

    def test_resolve_mission_failure(self):
        event = _make_event(
            "resolve_mission", {"mission_id": "mission_1", "ending": "failure"}, seq=1
        )
        line = derive_change_line(event)
        assert line is not None
        assert "failure" in line.text
        assert line.css_class == CHANGE_NEGATIVE

    def test_resolve_mission_abandonment(self):
        event = _make_event(
            "resolve_mission",
            {"mission_id": "mission_2", "ending": "abandonment"},
            seq=1,
        )
        line = derive_change_line(event)
        assert line is not None
        assert "abandonment" in line.text
        assert line.css_class == CHANGE_NEGATIVE

    def test_commission_success(self):
        event = _make_event(
            "lifepath_commission",
            {"career_id": "navy", "success": True, "target": 8},
            seq=1,
            kind=EventKind.ROLL,
        )
        line = derive_change_line(event)
        assert line is not None
        assert "Commissioned" in line.text
        assert line.css_class == CHANGE_POSITIVE

    def test_commission_failed_suppressed(self):
        event = _make_event(
            "lifepath_commission",
            {"career_id": "navy", "success": False, "target": 8},
            seq=1,
            kind=EventKind.ROLL,
        )
        assert derive_change_line(event) is None

    def test_advancement_success(self):
        event = _make_event(
            "lifepath_advancement",
            {
                "career_id": "navy",
                "success": True,
                "new_rank": 3,
                "target": 6,
            },
            seq=1,
            kind=EventKind.ROLL,
        )
        line = derive_change_line(event)
        assert line is not None
        assert "rank 3" in line.text
        assert line.css_class == CHANGE_POSITIVE

    def test_advancement_failed_suppressed(self):
        event = _make_event(
            "lifepath_advancement",
            {"career_id": "navy", "success": False, "new_rank": 2, "target": 6},
            seq=1,
            kind=EventKind.ROLL,
        )
        assert derive_change_line(event) is None

    def test_benefit_cash(self):
        event = _make_event(
            "lifepath_benefit",
            {
                "benefit_type": "cash",
                "result_text": "50,000 Cr",
                "adjusted_roll": 5,
                "credits": 50000,
            },
            seq=1,
            kind=EventKind.ROLL,
        )
        line = derive_change_line(event)
        assert line is not None
        assert "50,000 Cr" in line.text
        assert line.css_class == CHANGE_POSITIVE

    def test_benefit_material_emits_change_line(self):
        """U9: material benefits now produce a positive change-line too."""
        event = _make_event(
            "lifepath_benefit",
            {
                "benefit_type": "material",
                "result_text": "Low Pulsar",
                "adjusted_roll": 3,
                "credits": 0,
            },
            seq=1,
            kind=EventKind.ROLL,
        )
        line = derive_change_line(event)
        assert line is not None
        assert "Low Pulsar" in line.text
        assert line.css_class == CHANGE_POSITIVE

    def test_aging_apply(self):
        event = _make_event(
            "lifepath_aging_apply",
            {"characteristic": "STR", "points": 2, "new_value": 5, "crisis": False},
            seq=1,
        )
        line = derive_change_line(event)
        assert line is not None
        assert "STR" in line.text
        assert "reduced" in line.text.lower()
        assert line.css_class == CHANGE_NEGATIVE

    def test_characteristic_rolled(self):
        event = _make_event(
            "roll_characteristic",
            {"characteristic": "STR", "value": 9},
            seq=1,
            kind=EventKind.ROLL,
        )
        line = derive_change_line(event)
        assert line is not None
        assert "STR" in line.text
        assert "9" in line.text

    def test_characteristic_assigned(self):
        event = _make_event(
            "lifepath_assign_characteristic",
            {"characteristic": "DEX", "value": 11},
            seq=1,
        )
        line = derive_change_line(event)
        assert line is not None
        assert "DEX" in line.text
        assert "11" in line.text


class TestSuppressedTypes:
    """Internal/noisy command types produce no change-line (U14)."""

    def test_set_flag_suppressed(self):
        event = _make_event("set_flag", {"key": "phase", "value": "x"}, seq=1)
        assert derive_change_line(event) is None

    def test_oracle_roll_suppressed(self):
        event = _make_event(
            "oracle_roll", {"table_id": "t", "roll_total": 7, "result_text": "x"}, seq=1
        )
        assert derive_change_line(event) is None

    def test_scene_check_suppressed(self):
        event = _make_event(
            "scene_check",
            {"skill": "Gun Combat", "difficulty": "average", "success": True},
            seq=1,
        )
        assert derive_change_line(event) is None

    def test_rng_snapshot_suppressed(self):
        event = _make_event("set_rng_snapshot", {"stream": "oracle"}, seq=1)
        assert derive_change_line(event) is None

    def test_set_mission_state_suppressed(self):
        """set_mission_state is internal bookkeeping — suppress from change-lines."""
        event = _make_event(
            "set_mission_state",
            {"mission_data": {"id": "m1"}, "completed_mission": None},
            seq=1,
        )
        assert derive_change_line(event) is None

    def test_unrecognized_type_suppressed(self):
        event = _make_event("some_unknown_cmd", {"foo": "bar"}, seq=1)
        assert derive_change_line(event) is None


class TestDeriveChangeLines:
    """Batch derivation (U14)."""

    def test_mixed_events(self):
        events = [
            _make_event("set_flag", {"key": "k"}, seq=0),
            _make_event("lifepath_gain_skill", {"skill_id": "Pilot", "level": 0}, seq=1),
            _make_event("oracle_roll", {"table_id": "t"}, seq=2),
            _make_event("add_injury", {"name": "Cut", "severity": "minor"}, seq=3),
        ]
        lines = derive_change_lines(events)
        assert len(lines) == 2  # Only skill and injury.
        assert "Pilot" in lines[0].text
        assert "Cut" in lines[1].text

    def test_empty_list(self):
        assert derive_change_lines([]) == []

    def test_all_suppressed(self):
        events = [_make_event("set_flag", {"key": "k"}, seq=0)]
        assert derive_change_lines(events) == []


class TestRecentChangeLines:
    """Sequence-boundary filtering (U14)."""

    def test_since_seq(self):
        events = [
            _make_event("lifepath_gain_skill", {"skill_id": "A", "level": 0}, seq=1),
            _make_event("lifepath_gain_skill", {"skill_id": "B", "level": 0}, seq=2),
            _make_event("lifepath_gain_skill", {"skill_id": "C", "level": 0}, seq=3),
        ]
        lines = derive_recent_change_lines(events, since_seq=1)
        assert len(lines) == 2
        assert "B" in lines[0].text
        assert "C" in lines[1].text

    def test_since_seq_zero(self):
        events = [
            _make_event("lifepath_gain_skill", {"skill_id": "A", "level": 0}, seq=0),
        ]
        lines = derive_recent_change_lines(events, since_seq=-1)
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# Adventure controller integration (dimmed gate + change_lines populated).
# ---------------------------------------------------------------------------


def _make_adventure_engine(queue: list | None = None, death_mode: str = "narrative") -> Engine:
    """Create an engine with a mustered-out character ready for adventure."""
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(
        resolution_profile="narrative",
        death_mode=death_mode,
        theme_pack="scifi",
    )
    state.character.name = "TestHero"
    state.character.characteristics = {
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    state.character.skills = {
        "Gun Combat": 1,
        "Persuade": 0,
        "Stealth": 2,
        "Investigate": 1,
    }
    state.character.career = "navy"
    state.character.terms = 2
    state.character.alive = True
    state.narrative_log.append("mustered_out=true")
    return Engine(state, roller=ForcedRoller(queue or []))


_DEFAULT_QUEUE = [
    [3, 4],
    [5, 5],
    [3, 3],
    [4, 4],  # mission hook tables
    [5, 5],
    [4, 4],  # scene oracle tables (first scene)
    [6, 6],  # scene check
    [5, 5],
    [4, 4],  # scene oracle tables (second scene)
    [5, 5],  # scene check
    [5, 5],
    [4, 4],  # scene oracle tables (third scene)
    [5, 5],  # scene check (third scene)
    [6, 6],  # scene check (push for ending)
]


class TestMissionGateDimmed:
    """The ending push renders dimmed until the gate is met (U14, R16)."""

    def test_push_dimmed_when_below_gate(self):
        """Push for ending renders dimmed with requirement text."""
        engine = _make_adventure_engine(_DEFAULT_QUEUE * 3)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        # Override mission state to simulate 1 scene done out of 3.
        engine.state.active_mission["scenes_completed"] = 1
        engine.state.active_mission["min_scenes"] = 3
        view = controller.get_view()

        push_opts = [c for c in view.choices if c.option_id == "push_for_ending"]
        assert len(push_opts) == 1
        assert push_opts[0].dimmed is True
        assert "Requires 2 more" in push_opts[0].requirement

    def test_push_unlocked_at_gate(self):
        """Push for ending is active when gate is met."""
        engine = _make_adventure_engine(_DEFAULT_QUEUE * 3)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        # Override mission state to simulate gate met.
        engine.state.active_mission["scenes_completed"] = 3
        engine.state.active_mission["min_scenes"] = 3
        view = controller.get_view()

        push_opts = [c for c in view.choices if c.option_id == "push_for_ending"]
        assert len(push_opts) == 1
        assert push_opts[0].dimmed is False
        assert push_opts[0].requirement == ""

    def test_change_lines_populated_after_action(self):
        """AdventureView.change_lines is populated after a resolve action."""
        engine = _make_adventure_engine(_DEFAULT_QUEUE * 3)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")
        view = controller.get_view()

        # Resolve the first scene option.
        if view.choices:
            result_view = controller.apply_choice("option:0")
            # change_lines should be a list of ChangeLine objects (possibly
            # empty if the action produced no change-bearing events, but the
            # field must exist and each item must be a ChangeLine).
            assert hasattr(result_view, "change_lines")
            assert isinstance(result_view.change_lines, list)
            for cl in result_view.change_lines:
                assert isinstance(cl, ChangeLine)

    def test_change_lines_on_mission_resolve(self):
        """Mission resolution produces a change-line via resolve_mission event."""
        engine = _make_adventure_engine(_DEFAULT_QUEUE * 5)
        controller = AdventureController(engine, load_scifi_pack())
        controller.apply_choice("accept_mission")

        # Resolve enough scenes to unlock the ending push.
        min_scenes = engine.state.active_mission["min_scenes"]
        for _ in range(min_scenes):
            controller.apply_choice("option:0")

        # Push for the ending — this triggers resolve_mission.
        view = controller.apply_choice("push_for_ending")

        # The view should carry change_lines from the resolve_mission event.
        assert hasattr(view, "change_lines")
        assert isinstance(view.change_lines, list)
        # resolve_mission always produces a change-line with the ending.
        mission_lines = [cl for cl in view.change_lines if "Mission resolved" in cl.text]
        assert len(mission_lines) == 1
        assert mission_lines[0].css_class in (CHANGE_POSITIVE, CHANGE_NEGATIVE)


class TestChangeLineDataclass:
    """ChangeLine dataclass shape (U14)."""

    def test_defaults(self):
        cl = ChangeLine(text="test")
        assert cl.text == "test"
        assert cl.css_class == CHANGE_NEUTRAL
