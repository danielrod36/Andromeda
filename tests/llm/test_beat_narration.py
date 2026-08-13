"""Tests for narrate_beat / narrate_world_intro (M0.4)."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from src.engine.state import GameState
from src.llm.adapter import AdapterConfig, LLMAdapter
from src.llm.state_view import build_curated_view


def _view(state: GameState):
    return build_curated_view(state)


class TestNarrateBeat:
    async def test_llm_beat_returns_prose(self):
        state = GameState.new(seed=1)
        adapter = LLMAdapter(AdapterConfig(), test_model=TestModel())
        result = await adapter.narrate_beat(
            _view(state), ["The persuade check succeeded brilliantly (margin +3)."], state=state
        )
        assert result.source == "llm"
        assert result.prose.strip()

    async def test_template_beat_joins_facts(self):
        state = GameState.new(seed=1)
        adapter = LLMAdapter()  # no model → template
        result = await adapter.narrate_beat(_view(state), ["Fact one.", "Fact two."], state=state)
        assert result.source == "template"
        assert "Fact one." in result.prose and "Fact two." in result.prose

    async def test_steering_text_acknowledged_in_template(self):
        state = GameState.new(seed=1)
        adapter = LLMAdapter()
        result = await adapter.narrate_beat(
            _view(state), ["A thing happened."], state=state, steering_text="make it noir"
        )
        assert "make it noir" in result.prose

    async def test_mechanical_leak_falls_back_to_template(self):
        """Prose that leaks dice notation fails the mechanical-claim guard."""
        state = GameState.new(seed=1)
        # custom_output_args forces the structured output verbatim (pydantic-ai 2.x TestModel).
        adapter = LLMAdapter(
            AdapterConfig(),
            test_model=TestModel(custom_output_args={"prose": "You rolled 2D6 and got 11 vs 8."}),
        )
        result = await adapter.narrate_beat(_view(state), ["A check happened."], state=state)
        assert result.source == "template"
        assert result.llm_failed
        assert result.prose == "A check happened."  # the template floor ships


class TestNarrateWorldIntro:
    async def test_template_returns_pack_intro(self):
        state = GameState.new(seed=1)
        adapter = LLMAdapter()
        result = await adapter.narrate_world_intro(
            _view(state), pack_name="Frontier Sci-Fi", pack_intro="The frontier calls.", state=state
        )
        assert result.source == "template"
        assert result.prose == "The frontier calls."

    async def test_template_without_pack_intro_uses_generic_line(self):
        state = GameState.new(seed=1)
        adapter = LLMAdapter()
        result = await adapter.narrate_world_intro(
            _view(state), pack_name="Frontier Sci-Fi", pack_intro="", state=state
        )
        assert result.source == "template"
        assert "Frontier Sci-Fi" in result.prose

    async def test_llm_world_intro(self):
        state = GameState.new(seed=1)
        adapter = LLMAdapter(AdapterConfig(), test_model=TestModel())
        result = await adapter.narrate_world_intro(
            _view(state), pack_name="Frontier Sci-Fi", pack_intro="x", state=state
        )
        assert result.source == "llm"
        assert result.prose.strip()
