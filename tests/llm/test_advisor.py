"""Tests for the Advisor (P4, ADR A2/A9/A11)."""

from __future__ import annotations

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from src.engine.lifepath_choices import ChoiceOptionView, ChoicePointView
from src.llm.advisor import (
    ADVISOR_PROMPT_VERSION,
    Advisor,
    AdvisorConfig,
    AlternativeConsidered,
    HeuristicAdvisor,
    SuggestionRecord,
    _validate_selection,
    advisor_context_hash,
)
from src.llm.prompts import ADVISOR_SYSTEM_PROMPT, build_advisor_prompt

RULES_SUMMARY = "Checks: 2D6 + DM vs 8+.\nDifficulty ladder: Easy +4, Routine +2."


def make_choice() -> ChoicePointView:
    """A career-qualification choice point with one dimmed option."""
    return ChoicePointView(
        choice_id="career_qualification",
        phase="qualify",
        prompt="Choose a career to attempt.",
        options=[
            ChoiceOptionView(
                option_id="navy",
                label="Navy",
                preview=["2D6+1 vs 6+ to qualify", "Gain skill: Pilot"],
                odds_line="DM +1 vs 8 · 72% Favorable",
            ),
            ChoiceOptionView(
                option_id="scout",
                label="Scout",
                preview=["2D6+0 vs 6+ to qualify", "Gain skill: Survival"],
                odds_line="DM +0 vs 8 · 58% Modest",
            ),
            ChoiceOptionView(
                option_id="agent",
                label="Agent",
                preview=["2D6-1 vs 6+ to qualify"],
                odds_line="DM -1 vs 8 · 42% Chancy",
                dimmed=True,
                requirement="INT 8+ required",
            ),
        ],
    )


class TestSuggestionModels:
    def test_context_hash_deterministic(self):
        h1 = advisor_context_hash(make_choice(), RULES_SUMMARY)
        h2 = advisor_context_hash(make_choice(), RULES_SUMMARY)
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    def test_context_hash_changes_with_inputs(self):
        base = advisor_context_hash(make_choice(), RULES_SUMMARY)
        assert advisor_context_hash(make_choice(), RULES_SUMMARY + "x") != base
        other = make_choice()
        other.options[0].label = "Imperial Navy"
        assert advisor_context_hash(other, RULES_SUMMARY) != base

    def test_record_round_trip(self):
        record = SuggestionRecord(
            choice_id="career_qualification",
            selected_option_id="navy",
            rationale="Best odds.",
            alternatives=[AlternativeConsidered(option_id="scout", why_not="Lower odds.")],
            context_hash="ab" * 32,
            model_id="test",
            prompt_version=ADVISOR_PROMPT_VERSION,
        )
        assert SuggestionRecord(**record.model_dump()) == record
        assert ADVISOR_PROMPT_VERSION == "advisor.v1"


class TestAdvisorPrompt:
    def test_prompt_presents_options_verbatim(self):
        prompt = build_advisor_prompt(make_choice(), RULES_SUMMARY)
        for needle in (
            "option_id: navy",
            "option_id: scout",
            "label: Navy",
            "preview: 2D6+1 vs 6+ to qualify",
            "odds: DM +1 vs 8 · 72% Favorable",
            "odds: DM +0 vs 8 · 58% Modest",
        ):
            assert needle in prompt

    def test_prompt_marks_dimmed_unavailable(self):
        prompt = build_advisor_prompt(make_choice(), RULES_SUMMARY)
        assert "UNAVAILABLE (INT 8+ required)" in prompt
        assert "Never select an UNAVAILABLE option" in prompt

    def test_prompt_instructs_single_grounded_pick(self):
        prompt = build_advisor_prompt(make_choice(), RULES_SUMMARY)
        assert 'choice_id: "career_qualification"' in prompt
        assert "Select exactly ONE available option_id" in prompt
        assert "2-4 sentences grounded in the listed previews and odds" in prompt
        assert "up to 2 other available option_ids" in prompt
        assert RULES_SUMMARY in prompt
        assert ADVISOR_SYSTEM_PROMPT  # non-empty system prompt exists


GOOD_OUTPUT = {
    "choice_id": "career_qualification",
    "selected_option_id": "navy",
    "rationale": "Best qualification odds at 72% Favorable, and Pilot fits a pilot build.",
    "alternatives": [{"option_id": "scout", "why_not": "Lower success odds (58%)."}],
}


def scripted_model(outputs: list[dict]) -> tuple[FunctionModel, list[int]]:
    """FunctionModel returning each output dict in turn (the last repeats)."""
    calls = [0]

    def fn(messages, info: AgentInfo) -> ModelResponse:
        calls[0] += 1
        payload = outputs[min(calls[0] - 1, len(outputs) - 1)]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])

    return FunctionModel(fn), calls


class TestAdvisor:
    @pytest.mark.asyncio
    async def test_suggest_deterministic_and_stamped(self):
        """TestModel happy path: content from model, stamps from Advisor."""
        stamped_input = dict(GOOD_OUTPUT, context_hash="bogus", model_id="bogus")
        advisor = Advisor(test_model=TestModel(custom_output_args=stamped_input))
        record = await advisor.suggest(make_choice(), RULES_SUMMARY)

        assert record is not None
        assert record.selected_option_id == "navy"
        assert record.alternatives[0].option_id == "scout"
        # Stamps overwrite whatever the model emitted (ADR A2).
        assert record.context_hash == advisor_context_hash(make_choice(), RULES_SUMMARY)
        assert record.model_id == "test"  # TestModel default model_name
        assert record.prompt_version == "advisor.v1"

    @pytest.mark.asyncio
    async def test_retry_then_success_on_invalid_id(self):
        """Invalid id on attempt 1 (ModelRetry), valid id on attempt 2."""
        bad = dict(GOOD_OUTPUT, selected_option_id="zzz")
        model, calls = scripted_model([bad, GOOD_OUTPUT])
        advisor = Advisor(test_model=model)
        record = await advisor.suggest(make_choice(), RULES_SUMMARY)

        assert calls[0] == 2
        assert record is not None
        assert record.selected_option_id == "navy"

    @pytest.mark.asyncio
    async def test_exhaustion_returns_none_never_raises(self):
        """Always-invalid output: max_retries+1 attempts, then None."""
        bad = dict(GOOD_OUTPUT, selected_option_id="zzz")
        model, calls = scripted_model([bad])
        advisor = Advisor(config=AdvisorConfig(max_retries=2), test_model=model)
        record = await advisor.suggest(make_choice(), RULES_SUMMARY)

        assert calls[0] == 3  # 1 initial + 2 retries
        assert record is None

    @pytest.mark.asyncio
    async def test_unavailable_without_model(self):
        advisor = Advisor()  # no model configured
        assert advisor.advisor_available is False
        assert await advisor.suggest(make_choice(), RULES_SUMMARY) is None

    def test_validate_selection_lists_valid_ids(self):
        record = SuggestionRecord(**{**GOOD_OUTPUT, "selected_option_id": "zzz"})
        with pytest.raises(ModelRetry, match=r"Valid option_ids: \['navy', 'scout'\]"):
            _validate_selection(record, ["navy", "scout"])
        _validate_selection(SuggestionRecord(**GOOD_OUTPUT), ["navy", "scout"])  # no raise


class TestHeuristicAdvisor:
    @pytest.mark.asyncio
    async def test_picks_highest_odds_with_grounded_rationale(self):
        record = await HeuristicAdvisor().suggest(make_choice(), RULES_SUMMARY)
        assert record.selected_option_id == "navy"  # 72% beats 58%
        assert "Best odds: 72%" in record.rationale
        assert "DM +1 vs 8" in record.rationale  # cites the odds_line verbatim
        assert "Alternatives: scout" in record.rationale
        assert record.alternatives[0].option_id == "scout"
        assert "58%" in record.alternatives[0].why_not

    @pytest.mark.asyncio
    async def test_narrative_odds_sum_strong_and_weak(self):
        choice = make_choice()
        choice.options[0].odds_line = "DM +0 · 17% strong / 42% weak / 42% miss · Chancy"
        choice.options[1].odds_line = "DM +1 vs 8 · 50% Modest"
        record = await HeuristicAdvisor().suggest(choice, RULES_SUMMARY)
        assert record.selected_option_id == "navy"  # 17+42=59 beats 50

    @pytest.mark.asyncio
    async def test_tie_breaks_on_skill_mentions(self):
        choice = make_choice()
        choice.options[1].odds_line = "DM +1 vs 8 · 72% Favorable"  # tie navy
        choice.options[1].preview = ["Gain skill: Pilot", "Gain skill: Survival"]
        record = await HeuristicAdvisor().suggest(choice, RULES_SUMMARY)
        assert record.selected_option_id == "scout"  # 2 skill lines beats 1

    @pytest.mark.asyncio
    async def test_final_tie_break_is_list_order(self):
        choice = make_choice()
        choice.options[1].odds_line = "DM +1 vs 8 · 72% Favorable"  # identical to navy
        choice.options[1].preview = list(choice.options[0].preview)
        record = await HeuristicAdvisor().suggest(choice, RULES_SUMMARY)
        assert record.selected_option_id == "navy"  # listed first

    @pytest.mark.asyncio
    async def test_dimmed_options_never_selected(self):
        choice = make_choice()
        choice.options[2].odds_line = "DM +4 vs 8 · 97% Straightforward"  # dimmed 97%
        record = await HeuristicAdvisor().suggest(choice, RULES_SUMMARY)
        assert record.selected_option_id == "navy"
        assert all(a.option_id != "agent" for a in record.alternatives)

    @pytest.mark.asyncio
    async def test_deterministic_and_stamped(self):
        r1 = await HeuristicAdvisor().suggest(make_choice(), RULES_SUMMARY)
        r2 = await HeuristicAdvisor().suggest(make_choice(), RULES_SUMMARY)
        assert r1.model_dump_json() == r2.model_dump_json()
        assert r1.context_hash == advisor_context_hash(make_choice(), RULES_SUMMARY)
        assert r1.model_id == "heuristic.v1"
        assert r1.prompt_version == "advisor.v1"
