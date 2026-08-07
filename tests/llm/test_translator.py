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


import pytest  # noqa: E402
from pydantic_ai.messages import ModelResponse, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402
from pydantic_ai.models.test import TestModel  # noqa: E402

from src.llm.adapter import AdapterConfig  # noqa: E402
from src.llm.translator import Translator  # noqa: E402

RULES_SUMMARY = "Cepheus Engine lifepath: 2D6 + DM vs target; qualification, then 4-year terms."


class TestTranslatorPropose:
    @pytest.mark.asyncio
    async def test_clean_mapping_passes(self):
        """'Follow my father into the Navy' → career:navy, gate passed (P5.T4)."""
        translator = Translator(
            test_model=TestModel(
                custom_output_args={
                    "selected_option_id": "career:navy",
                    "rationale": (
                        "The player names the Navy and a family tradition of "
                        "service. The Navy preview — 2D6+1 vs 6+ to qualify "
                        "(INT 9) — best honors that intent."
                    ),
                }
            )
        )
        record = await translator.propose(
            "I want to follow my father into the Navy", career_choice(), RULES_SUMMARY
        )
        assert record.validation == "passed"
        assert record.selected_option_id == "career:navy"
        assert record.rejection_reason == ""
        assert "2D6+1 vs 6+ to qualify" in record.rationale
        assert record.context_hash == context_hash_for(career_choice())
        assert record.choice_id == "choose_career"

    @pytest.mark.asyncio
    async def test_honest_no_fit_returns_rejected_no_match(self):
        """selected=None is a valid honest answer → rejected_no_match (P5.T4)."""
        translator = Translator(
            test_model=TestModel(
                custom_output_args={
                    "selected_option_id": None,
                    "rationale": "None of the listed careers involve raising space horses.",
                }
            )
        )
        record = await translator.propose(
            "I want to breed space horses", career_choice(), RULES_SUMMARY
        )
        assert record.validation == "rejected_no_match"
        assert record.selected_option_id is None
        assert "space horses" in record.rationale
        assert record.rejection_reason == ""

    @pytest.mark.asyncio
    async def test_dimmed_candidate_rejected_invalid(self):
        """Gate (a): selecting a dimmed option rejects with its requirement (P5.T4)."""
        translator = Translator(
            test_model=TestModel(
                custom_output_args={
                    "selected_option_id": "career:agent",
                    "rationale": "Agent fits; 2D6+0 vs 6+ to qualify (SOC 8+).",
                }
            )
        )
        record = await translator.propose("I want to be a spy", career_choice(), RULES_SUMMARY)
        assert record.validation == "rejected_invalid"
        assert record.selected_option_id == "career:agent"
        assert "SOC 8+ required" in record.rejection_reason

    @pytest.mark.asyncio
    async def test_undispatchable_candidate_rejected_invalid(self):
        """Gate (b): a candidate with no controller path is rejected (P5.T4)."""
        weird = ChoicePointView(
            choice_id="choose_career",
            phase="choose_career",
            prompt="Choose.",
            allows_freetext=True,
            options=[
                ChoiceOptionView(
                    option_id="teleport:mars",
                    label="Teleport to Mars",
                    preview=["instant travel, no roll"],
                ),
            ],
        )
        translator = Translator(
            test_model=TestModel(
                custom_output_args={
                    "selected_option_id": "teleport:mars",
                    "rationale": "Teleport to Mars matches instant travel, no roll.",
                }
            )
        )
        record = await translator.propose("beam me up", weird, RULES_SUMMARY)
        assert record.validation == "rejected_invalid"
        assert "no engine command path" in record.rejection_reason

    @pytest.mark.asyncio
    async def test_rationale_without_citation_rejected_invalid(self):
        """Gate (c): rationale citing no candidate string rejects (P5.T4)."""
        translator = Translator(
            test_model=TestModel(
                custom_output_args={
                    "selected_option_id": "career:navy",
                    "rationale": "Because reasons.",
                }
            )
        )
        record = await translator.propose("navy please", career_choice(), RULES_SUMMARY)
        assert record.validation == "rejected_invalid"
        assert "does not cite" in record.rejection_reason
        assert record.rationale == "Because reasons."  # model's words preserved

    @pytest.mark.asyncio
    async def test_freetext_disabled_choice_rejected_invalid(self):
        choice = career_choice().model_copy(update={"allows_freetext": False})
        translator = Translator(
            test_model=TestModel(
                custom_output_args={
                    "selected_option_id": "career:navy",
                    "rationale": "Navy preview: 2D6+1 vs 6+ to qualify (INT 9).",
                }
            )
        )
        record = await translator.propose("navy", choice, RULES_SUMMARY)
        assert record.validation == "rejected_invalid"
        assert "does not accept free-text" in record.rejection_reason


class TestTranslatorRetryAndFallback:
    @pytest.mark.asyncio
    async def test_retry_once_then_pass_on_hallucinated_id(self):
        """Invalid id → validation error naming valid ids → retry passes (P5.T4)."""
        model_calls = {"n": 0}
        seen_contents: list[str] = []

        def model_fn(messages, info: AgentInfo) -> ModelResponse:
            model_calls["n"] += 1
            for message in messages:
                for part in getattr(message, "parts", []):
                    content = getattr(part, "content", None)
                    if isinstance(content, str):
                        seen_contents.append(content)
            if model_calls["n"] == 1:
                args = {"selected_option_id": "career:marines", "rationale": "hallucinated"}
            else:
                args = {
                    "selected_option_id": "career:navy",
                    "rationale": "Navy honors the intent: 2D6+1 vs 6+ to qualify (INT 9).",
                }
            return ModelResponse(
                parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=args)]
            )

        translator = Translator(
            config=AdapterConfig(max_retries=2),
            test_model=FunctionModel(model_fn),
        )
        record = await translator.propose(
            "I want to follow my father into the Navy", career_choice(), RULES_SUMMARY
        )
        assert record.validation == "passed"
        assert record.selected_option_id == "career:navy"
        assert model_calls["n"] == 2  # one rejected attempt + one retry
        # The retry prompt carries the validation feedback (invalid id named).
        assert any("career:marines" in c and "rejected" in c for c in seen_contents)

    @pytest.mark.asyncio
    async def test_exhaustion_on_persistent_hallucination(self):
        """Every attempt returns an invalid id → rejected_no_match, never raises (P5.T4)."""
        translator = Translator(
            config=AdapterConfig(max_retries=2),
            test_model=TestModel(
                custom_output_args={
                    "selected_option_id": "career:marines",
                    "rationale": "Marines are cool.",
                }
            ),
        )
        record = await translator.propose("oorah", career_choice(), RULES_SUMMARY)
        assert record.validation == "rejected_no_match"
        assert record.selected_option_id is None
        assert "exhausted" in record.rejection_reason

    @pytest.mark.asyncio
    async def test_no_llm_configured_rejected_no_match(self):
        """ADR A1: without a model the translator never raises (P5.T4)."""
        translator = Translator()
        record = await translator.propose("anything", career_choice(), RULES_SUMMARY)
        assert record.validation == "rejected_no_match"
        assert "no LLM configured" in record.rejection_reason
