"""Tests for build_beat_facts (M0.4) — events to LLM-safe mechanical facts."""

from __future__ import annotations

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.state import CampaignConfig, GameState
from src.game.adventure import AdventureController
from src.game.beats import build_beat_facts
from src.themepacks.cepheus_scifi import load_scifi_pack


def _play_one_scene() -> tuple[Engine, int]:
    """Accept a mission and resolve one option; return (engine, action_start)."""
    queue = [
        [3, 4],
        [5, 5],
        [3, 3],
        [4, 4],  # hook tables
        [5, 5],
        [4, 4],  # scene oracle
        [6, 6],  # scene check (12 raw → strong hit at most DMs)
        [3, 3],  # possible npc_reaction/complication follow-ups
    ]
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(
        resolution_profile="narrative", death_mode="narrative", theme_pack="scifi"
    )
    state.character.name = "TestHero"
    state.character.characteristics = {"STR": 7, "DEX": 9, "END": 6, "INT": 8, "EDU": 10, "SOC": 5}
    state.character.skills = {"Gun Combat": 1, "Persuade": 0}
    state.character.career = "navy"
    state.character.terms = 2
    state.narrative_log.append("mustered_out=true")
    engine = Engine(state, roller=ForcedRoller(queue))
    controller = AdventureController(engine, load_scifi_pack())
    controller.get_view()
    controller.apply_choice("accept_mission")
    action_start = len(engine.state.events)
    controller.apply_choice("option:0")
    return engine, action_start


def test_beat_facts_describe_the_check_without_pips():
    engine, start = _play_one_scene()
    facts = build_beat_facts(engine.state.events[start:])
    assert any("check" in f for f in facts)
    joined = " ".join(facts)
    # No raw pip lists or RNG vocabulary leak into narration facts.
    assert "[" not in joined
    assert "2D6" not in joined


def test_beat_facts_cover_mission_resolution():
    engine, _ = _play_one_scene()
    # Two more scenes (oracle+check each), the pre-push scene generation
    # (oracle), then the push's own check.
    engine.roller.extend(
        [
            [5, 5],
            [4, 4],
            [6, 6],  # scene 2: oracle, oracle, check
            [5, 5],
            [4, 4],
            [6, 6],  # scene 3: oracle, oracle, check
            [6, 6],
            [3, 3],  # scene 4 oracle rolls (from the pre-push get_view)
            [6, 6],  # the push's scene check → strong hit → success
            [6, 6],  # the push_for_ending action itself needs a roll
            [3, 3],  # complication/consequence roll after the push
        ]
    )
    controller = AdventureController(engine, load_scifi_pack())
    controller.get_view()
    controller.apply_choice("option:0")
    controller.get_view()
    controller.apply_choice("option:0")
    controller.get_view()
    before = len(engine.state.events)
    controller.apply_choice("push_for_ending")
    facts = build_beat_facts(engine.state.events[before:])
    assert any("mission" in f.lower() and ("success" in f or "ended" in f) for f in facts)


def test_empty_slice_gives_empty_facts():
    assert build_beat_facts([]) == []
