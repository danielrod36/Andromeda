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


import inspect  # noqa: E402

from src.game.lifepath import LifepathController  # noqa: E402
from src.llm.translator import (  # noqa: E402
    _DISPATCH_PREFIXES,
    _STATIC_DISPATCH_IDS,
    dispatch_id_for,
)


class TestDispatchIdFor:
    def test_static_ids_resolve(self):
        assert dispatch_id_for("begin_term") == "begin_term"
        assert dispatch_id_for("claim_cash") == "claim_cash"

    def test_prefixed_ids_resolve(self):
        assert dispatch_id_for("career:navy") == "career:"
        assert dispatch_id_for("assign:3:INT") == "assign:"
        assert dispatch_id_for("skill_table:personal_development") == "skill_table:"

    def test_unknown_ids_do_not_resolve(self):
        assert dispatch_id_for("teleport:mars") is None
        assert dispatch_id_for("career_change_never") is None
        assert dispatch_id_for("career:") is None  # bare prefix is not a choice

    def test_table_covers_controller_dispatch(self):
        """Drift guard: every static id and prefix must appear in apply_choice."""
        source = inspect.getsource(LifepathController.apply_choice)
        for key in sorted(_STATIC_DISPATCH_IDS):
            assert f'"{key}"' in source, f"{key} missing from apply_choice"
        for prefix in _DISPATCH_PREFIXES:
            assert f'startswith("{prefix}")' in source, f"{prefix} missing from apply_choice"
