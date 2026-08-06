"""Tests for the Advisor (P4, ADR A2/A9/A11)."""

from __future__ import annotations

from src.engine.lifepath_choices import ChoiceOptionView, ChoicePointView
from src.llm.advisor import (
    ADVISOR_PROMPT_VERSION,
    AlternativeConsidered,
    SuggestionRecord,
    advisor_context_hash,
)

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
