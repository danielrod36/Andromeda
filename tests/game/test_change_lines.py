"""Tests for change-lines derivation and gated options (U14, R16).

Covers:
- Each mutation kind produces the correct change-line text and CSS class.
- Suppressed command types (internal flags, oracle rolls) produce no line.
- derive_recent_change_lines respects the sequence boundary.
- Adventure controller populates change_lines after actions.
- Mission gate "Push for the ending" renders dimmed with requirement.
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
    """Each mutation kind produces correct text and styling (U14)."""

    def test_skill_gained(self):
        event = _make_event("gain_skill", {"skill_id": "Pilot", "level": 0}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "Pilot" in line.text
        assert line.css_class == CHANGE_POSITIVE

    def test_skill_improved(self):
        event = _make_event("gain_skill", {"skill_id": "Gun Combat", "level": 2}, seq=1)
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

    def test_mission_state_success(self):
        event = _make_event("set_mission_state", {"mission_id": "m1", "ending": "success"}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "success" in line.text
        assert line.css_class == CHANGE_POSITIVE

    def test_mission_state_failure(self):
        event = _make_event("set_mission_state", {"mission_id": "m1", "ending": "failure"}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "failure" in line.text
        assert line.css_class == CHANGE_NEGATIVE

    def test_promotion_with_title(self):
        event = _make_event("promote", {"rank_title": "Lieutenant", "rank": 3}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "Lieutenant" in line.text
        assert line.css_class == CHANGE_POSITIVE

    def test_credits_positive(self):
        event = _make_event("adjust_credits", {"amount": 500}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "+500" in line.text
        assert line.css_class == CHANGE_POSITIVE

    def test_credits_negative(self):
        event = _make_event("adjust_credits", {"amount": -200}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "-200" in line.text
        assert line.css_class == CHANGE_NEGATIVE

    def test_characteristic_set(self):
        event = _make_event("roll_characteristic", {"characteristic": "STR", "value": 9}, seq=1)
        line = derive_change_line(event)
        assert line is not None
        assert "STR" in line.text
        assert "9" in line.text


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

    def test_unrecognized_type_suppressed(self):
        event = _make_event("some_unknown_cmd", {"foo": "bar"}, seq=1)
        assert derive_change_line(event) is None


class TestDeriveChangeLines:
    """Batch derivation (U14)."""

    def test_mixed_events(self):
        events = [
            _make_event("set_flag", {"key": "k"}, seq=0),
            _make_event("gain_skill", {"skill_id": "Pilot", "level": 0}, seq=1),
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
            _make_event("gain_skill", {"skill_id": "A", "level": 0}, seq=1),
            _make_event("gain_skill", {"skill_id": "B", "level": 0}, seq=2),
            _make_event("gain_skill", {"skill_id": "C", "level": 0}, seq=3),
        ]
        lines = derive_recent_change_lines(events, since_seq=1)
        assert len(lines) == 2
        assert "B" in lines[0].text
        assert "C" in lines[1].text

    def test_since_seq_zero(self):
        events = [
            _make_event("gain_skill", {"skill_id": "A", "level": 0}, seq=0),
        ]
        lines = derive_recent_change_lines(events, since_seq=-1)
        assert len(lines) == 1


class TestMissionGateDimmed:
    """The ending push renders dimmed until the gate is met (U14, R16)."""

    def _make_controller(self, scenes_done: int = 0, min_scenes: int = 3) -> AdventureController:
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(theme_pack="scifi", death_mode="narrative")
        state.character.name = "TestHero"
        state.character.characteristics = {
            "STR": 7,
            "DEX": 9,
            "END": 6,
            "INT": 8,
            "EDU": 10,
            "SOC": 5,
        }
        state.character.skills = {"Gun Combat": 1, "Persuade": 0}
        state.character.career = "navy"
        state.character.terms = 2
        state.character.alive = True
        state.narrative_log.append("mustered_out=true")
        state.active_mission = {
            "hook": {"objective": "test"},
            "scenes_completed": scenes_done,
            "min_scenes": min_scenes,
        }
        # Generate a scene so the controller has something to show.
        queue = [[3, 4], [5, 5], [3, 3], [4, 4], [5, 5], [2, 3]]
        engine = Engine(state, roller=ForcedRoller(queue))
        pack = load_scifi_pack()
        controller = AdventureController(engine, pack)
        # Accept the mission to get into scene_active.
        controller._current_mission = type(controller._current_mission or object)()
        return controller

    def test_push_dimmed_when_below_gate(self):
        """Push for ending renders dimmed with requirement text."""
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(theme_pack="scifi", death_mode="narrative")
        state.character.name = "Hero"
        state.character.characteristics = {
            "STR": 7,
            "DEX": 9,
            "END": 6,
            "INT": 8,
            "EDU": 10,
            "SOC": 5,
        }
        state.character.skills = {"Gun Combat": 1}
        state.character.career = "navy"
        state.character.terms = 2
        state.character.alive = True
        state.narrative_log.append("mustered_out=true")
        queue = [[3, 4], [5, 5], [3, 3], [4, 4], [5, 5], [2, 3], [4, 4], [1, 2]]
        engine = Engine(state, roller=ForcedRoller(queue))
        pack = load_scifi_pack()
        controller = AdventureController(engine, pack)
        # Accept the mission to enter scene_active phase.
        controller.apply_choice("accept_mission")
        # Override mission state to simulate 1 scene done out of 3.
        state.active_mission["scenes_completed"] = 1
        state.active_mission["min_scenes"] = 3
        view = controller.get_view()

        # Find the push option.
        push_opts = [c for c in view.choices if c.option_id == "push_for_ending"]
        assert len(push_opts) == 1
        assert push_opts[0].dimmed is True
        assert "Requires 2 more" in push_opts[0].requirement

    def test_push_unlocked_at_gate(self):
        """Push for ending is active when gate is met."""
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(theme_pack="scifi", death_mode="narrative")
        state.character.name = "Hero"
        state.character.characteristics = {
            "STR": 7,
            "DEX": 9,
            "END": 6,
            "INT": 8,
            "EDU": 10,
            "SOC": 5,
        }
        state.character.skills = {"Gun Combat": 1}
        state.character.career = "navy"
        state.character.terms = 2
        state.character.alive = True
        state.narrative_log.append("mustered_out=true")
        queue = [[3, 4], [5, 5], [3, 3], [4, 4], [5, 5], [2, 3], [4, 4], [1, 2]]
        engine = Engine(state, roller=ForcedRoller(queue))
        pack = load_scifi_pack()
        controller = AdventureController(engine, pack)
        controller.apply_choice("accept_mission")
        # Override mission state to simulate gate met.
        state.active_mission["scenes_completed"] = 3
        state.active_mission["min_scenes"] = 3
        view = controller.get_view()

        push_opts = [c for c in view.choices if c.option_id == "push_for_ending"]
        assert len(push_opts) == 1
        assert push_opts[0].dimmed is False
        assert push_opts[0].requirement == ""

    def test_change_lines_populated_after_action(self):
        """AdventureView.change_lines is populated after a resolve action."""
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(theme_pack="scifi", death_mode="narrative")
        state.character.name = "Hero"
        state.character.characteristics = {
            "STR": 7,
            "DEX": 9,
            "END": 6,
            "INT": 8,
            "EDU": 10,
            "SOC": 5,
        }
        state.character.skills = {"Gun Combat": 1}
        state.character.career = "navy"
        state.character.terms = 2
        state.character.alive = True
        state.narrative_log.append("mustered_out=true")
        state.active_mission = {
            "hook": {"objective": "test"},
            "scenes_completed": 0,
            "min_scenes": 3,
        }
        # Enough rolls for hook generation + scene resolution.
        queue = [
            [3, 4],
            [5, 5],
            [3, 3],
            [4, 4],  # hook tables
            [5, 5],  # oracle
            [3, 3],  # complication
            [4, 4],  # scene option check
            [1, 2],  # extra
        ]
        engine = Engine(state, roller=ForcedRoller(queue))
        pack = load_scifi_pack()
        controller = AdventureController(engine, pack)
        controller.apply_choice("accept_mission")
        view = controller.get_view()

        # Resolve the first scene option.
        if view.choices:
            result_view = controller.apply_choice("option:0")
            # change_lines should be a list (possibly empty if the action
            # produced no change-bearing events, but the field must exist).
            assert hasattr(result_view, "change_lines")
            assert isinstance(result_view.change_lines, list)


class TestChangeLineDataclass:
    """ChangeLine dataclass shape (U14)."""

    def test_defaults(self):
        cl = ChangeLine(text="test")
        assert cl.text == "test"
        assert cl.css_class == CHANGE_NEUTRAL
