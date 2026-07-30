"""Tests for the LLM adapter's qualification and mustering-out narration.

Covers the narration methods added for the interactive lifepath:
``narrate_qualification`` and ``narrate_mustering_out``, including
template fallback (no LLM) and TestModel-driven LLM narration.
"""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from src.engine.commands import Engine
from src.engine.lifepath import MusteringOutResult, QualificationResult
from src.engine.state import Character, GameState
from src.llm.adapter import AdapterConfig, LLMAdapter

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def make_state() -> GameState:
    state = GameState.new(seed=42)
    state.character = Character(
        name="Test",
        characteristics={"STR": 7, "DEX": 8, "END": 6, "INT": 10, "EDU": 9, "SOC": 5},
        skills={"Pilot": 2},
        age=22,
        terms=1,
        career="navy",
        rank=1,
    )
    return state


@pytest.fixture
def state():
    return make_state()


@pytest.fixture
def engine(state):
    return Engine(state)


@pytest.fixture
def qual_result():
    return QualificationResult(
        career_id="navy",
        career_name="Navy",
        characteristic="INT",
        char_value=10,
        char_dm=1,
        raw_roll=5,
        adjusted_total=6,
        target=5,
        success=True,
    )


@pytest.fixture
def mo_result():
    return MusteringOutResult(
        terms_served=2,
        final_rank=2,
        career_name="Navy",
        cash_benefits=["40,000 Cr", "50,000 Cr"],
        material_benefits=["Weapon", "Ship Share"],
        cash_rolls=[5, 6],
        material_rolls=[1, 6],
    )


# ---------------------------------------------------------------------------
# Qualification narration.
# ---------------------------------------------------------------------------


class TestQualificationNarration:
    @pytest.mark.asyncio
    async def test_template_fallback_without_llm(self, state, engine, qual_result):
        adapter = LLMAdapter()
        result = await adapter.narrate_qualification(state, engine, qual_result)

        assert result.source == "template"
        assert result.llm_failed is False
        assert "Navy" in result.prose

    @pytest.mark.asyncio
    async def test_llm_narration_with_test_model(self, state, engine, qual_result):
        test_model = TestModel(
            custom_output_args={
                "prose": "The Navy recruiter nodded approvingly at your test scores."
            }
        )
        adapter = LLMAdapter(test_model=test_model)
        result = await adapter.narrate_qualification(state, engine, qual_result)

        assert result.source == "llm"
        assert "Navy recruiter" in result.prose

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back(self, state, engine, qual_result):
        test_model = TestModel(custom_output_args={"prose": ""})
        adapter = LLMAdapter(
            config=AdapterConfig(max_retries=2),
            test_model=test_model,
        )
        result = await adapter.narrate_qualification(state, engine, qual_result)

        assert result.source == "template"
        assert result.llm_failed is True
        assert "Navy" in result.prose


# ---------------------------------------------------------------------------
# Mustering out narration.
# ---------------------------------------------------------------------------


class TestMusteringOutNarration:
    @pytest.mark.asyncio
    async def test_template_fallback_without_llm(self, state, engine, mo_result):
        adapter = LLMAdapter()
        result = await adapter.narrate_mustering_out(state, engine, mo_result)

        assert result.source == "template"
        assert "Navy" in result.prose

    @pytest.mark.asyncio
    async def test_llm_narration_with_test_model(self, state, engine, mo_result):
        test_model = TestModel(
            custom_output_args={
                "prose": "With a firm handshake and final salute, you departed the fleet."
            }
        )
        adapter = LLMAdapter(test_model=test_model)
        result = await adapter.narrate_mustering_out(state, engine, mo_result)

        assert result.source == "llm"
        assert "departed" in result.prose

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back(self, state, engine, mo_result):
        test_model = TestModel(custom_output_args={"prose": ""})
        adapter = LLMAdapter(
            config=AdapterConfig(max_retries=2),
            test_model=test_model,
        )
        result = await adapter.narrate_mustering_out(state, engine, mo_result)

        assert result.source == "template"
        assert result.llm_failed is True
