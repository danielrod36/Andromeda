"""Tests for the free-text translator (P5)."""

from __future__ import annotations

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.lifepath_choices import ChoiceOptionView, ChoicePointView
from src.engine.state import GameState
from src.llm.translator import (
    TRANSLATOR_PROMPT_VERSION,
    TranslationRecord,
    context_hash_for,
)


def make_engine(queue=None):
    """Fresh engine; translator paths roll no dice, so the queue is usually empty."""
    state = GameState.new(seed=42)
    return Engine(state, roller=ForcedRoller(queue or []))


def career_choice() -> ChoicePointView:
    """A choose-career decision with one dimmed option (P5 fixture)."""
    return ChoicePointView(
        choice_id="choose_career",
        phase="choose_career",
        prompt="Choose a career to attempt qualification for.",
        allows_freetext=True,
        freetext_hint="Describe the career you imagine, in your own words.",
        options=[
            ChoiceOptionView(
                option_id="career:navy",
                label="Navy",
                preview=["2D6+1 vs 6+ to qualify (INT 9)", "First career: all Service skills at 0"],
            ),
            ChoiceOptionView(
                option_id="career:scout",
                label="Scout",
                preview=["2D6+0 vs 7+ to qualify (INT 9)"],
            ),
            ChoiceOptionView(
                option_id="career:agent",
                label="Agent",
                preview=["2D6+0 vs 6+ to qualify (SOC 8+)"],
                dimmed=True,
                requirement="SOC 8+ required (yours: SOC 5)",
            ),
        ],
    )


class TestTranslationRecord:
    def test_master_shape_and_prompt_version(self):
        record = TranslationRecord(
            choice_id="choose_career",
            text="I want to follow my father into the Navy",
            selected_option_id="career:navy",
            rationale="The Navy preview fits: 2D6+1 vs 6+ to qualify.",
            context_hash="abc123",
            validation="passed",
        )
        assert TRANSLATOR_PROMPT_VERSION == "translator.v1"
        assert record.validation == "passed"
        assert record.rejection_reason == ""  # additive field defaults empty
        # Records ride in RecordProposalCommand payloads — must round-trip.
        assert TranslationRecord.model_validate_json(record.model_dump_json()) == record

    def test_context_hash_deterministic_and_sensitive(self):
        h1 = context_hash_for(career_choice())
        assert h1 == context_hash_for(career_choice())
        assert len(h1) == 16
        changed = career_choice()
        changed.options[0] = changed.options[0].model_copy(update={"label": "Imperial Navy"})
        assert context_hash_for(changed) != h1


from src.llm.prompts import TRANSLATOR_SYSTEM_PROMPT, build_translator_prompt  # noqa: E402


class TestBuildTranslatorPrompt:
    def test_prompt_lists_candidates_verbatim(self):
        prompt = build_translator_prompt(
            "I want to follow my father into the Navy",
            career_choice(),
            "Cepheus Engine lifepath: 2D6 + DM vs target.",
        )
        assert 'option_id: "career:navy"' in prompt
        assert 'label: "Navy"' in prompt
        assert "preview: 2D6+1 vs 6+ to qualify (INT 9)" in prompt
        assert "UNAVAILABLE — SOC 8+ required (yours: SOC 5); do not select" in prompt
        assert '"I want to follow my father into the Navy"' in prompt
        assert "selected_option_id = null" in prompt
        assert "never invent or combine ids" in prompt
        assert "Cepheus Engine lifepath" in prompt

    def test_system_prompt_forbids_invention(self):
        assert "never invent options" in TRANSLATOR_SYSTEM_PROMPT
