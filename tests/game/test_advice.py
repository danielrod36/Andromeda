"""Tests for record_advice — advisor output into the funnel (P4.T5, ADR A2)."""

from __future__ import annotations

from src.engine.audit import EventKind
from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.state import CampaignConfig, GameState
from src.game.advice import record_advice
from src.llm.advisor import ADVISOR_PROMPT_VERSION, AlternativeConsidered, SuggestionRecord


def make_engine() -> Engine:
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(death_mode="narrative")
    return Engine(state, roller=ForcedRoller([]))


def make_record() -> SuggestionRecord:
    return SuggestionRecord(
        choice_id="career_qualification",
        selected_option_id="navy",
        rationale='Best odds: 72% ("DM +1 vs 8 · 72% Favorable"). Alternatives: scout.',
        alternatives=[AlternativeConsidered(option_id="scout", why_not="Lower odds (58%).")],
        context_hash="ab" * 32,
        model_id="heuristic.v1",
        prompt_version=ADVISOR_PROMPT_VERSION,
    )


def test_event_appended_kind_system():
    engine = make_engine()
    event = record_advice(engine, make_record())
    assert len(engine.state.events) == 1
    assert event.kind == EventKind.SYSTEM
    assert event.command_type == "record_advice"
    assert event.changes == make_record().model_dump()


def test_state_otherwise_untouched():
    engine = make_engine()
    before = engine.state.model_dump()
    record_advice(engine, make_record())
    after = engine.state.model_dump()
    assert len(after["events"]) == len(before["events"]) + 1
    for key in before:
        if key != "events":
            assert after[key] == before[key], f"state.{key} changed"


def test_replay_byte_identical():
    """ADR A2: same record on same-seed states → identical event + state bytes.

    ``GameState.new(seed=42)`` guarantees identical initial state, so two
    fresh engines stand in for cloned states; the LLM is never involved.
    """
    engine_a, engine_b = make_engine(), make_engine()
    event_a = record_advice(engine_a, make_record())
    event_b = record_advice(engine_b, make_record())
    assert event_a.model_dump_json() == event_b.model_dump_json()
    assert engine_a.state.model_dump_json() == engine_b.state.model_dump_json()
