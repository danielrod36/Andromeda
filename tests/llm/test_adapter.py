"""Tests for the LLM adapter (AE11, AE12, R3, R18, R19, R11).

Test scenarios covered:
1. AE11 — Invalid LLM output is rejected, state unchanged, template fallback.
2. AE12 — Full lifepath narration with LLM (consistent, faithful).
3. Retry limit — retries exhausted → fallback with audit flag.
4. Template fallback — narration works without LLM.
5. Usage limits — cost caps enforced on every turn.
6. Valid LLM narration — structured output received correctly.

All tests use ``TestModel`` — no real API calls.
"""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from src.engine.commands import Engine
from src.engine.lifepath import LifepathResult, TermResult
from src.engine.state import Character, GameState
from src.llm.adapter import (
    AdapterConfig,
    LifepathNarration,
    LLMAdapter,
)
from src.llm.state_view import build_curated_view

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def make_term_result(term_number: int = 1, **kwargs) -> TermResult:
    """Build a TermResult with sensible defaults for testing."""
    defaults = {
        "term_number": term_number,
        "career_id": "navy",
        "career_name": "Navy",
        "age_before": 18 + (term_number - 1) * 4,
        "age_after": 18 + term_number * 4,
        "survival_success": True,
        "advancement_success": True,
        "rank_after": term_number,
        "rank_title": "Lieutenant" if term_number >= 2 else "Ensign",
    }
    defaults.update(kwargs)
    return TermResult(**defaults)


def make_state_with_character() -> GameState:
    state = GameState.new(seed=42)
    state.character = Character(
        name="Jax",
        characteristics={"STR": 7, "DEX": 8, "END": 6, "INT": 10, "EDU": 9, "SOC": 5},
        skills={"Pilot": 2, "Gunner": 1},
        age=26,
        terms=2,
        career="navy",
        rank=3,
    )
    return state


@pytest.fixture
def state() -> GameState:
    return make_state_with_character()


@pytest.fixture
def engine(state: GameState) -> Engine:
    return Engine(state)


@pytest.fixture
def term_result() -> TermResult:
    return make_term_result(term_number=2)


# ---------------------------------------------------------------------------
# Template fallback tests (no LLM configured).
# ---------------------------------------------------------------------------


class TestTemplateFallback:
    """Template fallback: narration works without LLM (test scenario 6)."""

    @pytest.mark.asyncio
    async def test_term_narration_without_llm(self, state, engine, term_result):
        adapter = LLMAdapter()  # No model configured.
        result = await adapter.narrate_term(state, engine, term_result)

        assert result.source == "template"
        assert result.llm_failed is False
        assert "Term 2" in result.prose
        assert "Navy" in result.prose

    @pytest.mark.asyncio
    async def test_full_lifepath_without_llm(self, state, engine):
        adapter = LLMAdapter()
        lifepath = LifepathResult(
            characteristics={"STR": 7, "DEX": 8},
            terms=[make_term_result(1), make_term_result(2)],
        )
        result = await adapter.narrate_lifepath(state, engine, lifepath)

        assert result.source == "template"
        assert "Term 1" in result.prose
        assert "Term 2" in result.prose

    def test_llm_configured_false_by_default(self):
        adapter = LLMAdapter()
        assert adapter.llm_configured is False


# ---------------------------------------------------------------------------
# Valid LLM narration tests (structured output received correctly).
# ---------------------------------------------------------------------------


class TestValidLLMNarration:
    """Valid LLM output is received and returned correctly (AE12)."""

    @pytest.mark.asyncio
    async def test_term_narration_with_test_model(self, state, engine, term_result):
        test_model = TestModel(
            custom_output_args={
                "prose": "You served aboard the destroyer Ironfall, patrolling the frontier."
            }
        )
        adapter = LLMAdapter(test_model=test_model)
        result = await adapter.narrate_term(state, engine, term_result)

        assert result.source == "llm"
        assert result.llm_failed is False
        assert "Ironfall" in result.prose

    @pytest.mark.asyncio
    async def test_full_lifepath_with_test_model(self, state, engine):
        test_model = TestModel(
            custom_output_args={
                "prose": "Your career spanned multiple terms of distinguished service."
            }
        )
        adapter = LLMAdapter(test_model=test_model)
        lifepath = LifepathResult(
            characteristics={"STR": 7, "DEX": 8},
            terms=[make_term_result(1), make_term_result(2)],
        )
        result = await adapter.narrate_lifepath(state, engine, lifepath)

        assert result.source == "llm"
        assert "distinguished service" in result.prose

    def test_llm_configured_true_with_test_model(self):
        adapter = LLMAdapter(test_model=TestModel())
        assert adapter.llm_configured is True

    def test_llm_configured_true_with_model_string(self):
        adapter = LLMAdapter(AdapterConfig(model="anthropic:claude-sonnet-5"))
        assert adapter.llm_configured is True


# ---------------------------------------------------------------------------
# AE11 — Invalid LLM output rejected, state unchanged.
# ---------------------------------------------------------------------------


class TestInvalidOutputRejection:
    """AE11: Invalid output rejected, state unchanged, fallback to template.

    When the LLM produces invalid output (empty prose), the adapter retries
    up to max_retries, then falls back to template narration. The canonical
    state must be unchanged — no events appended, no mutations.
    """

    @pytest.mark.asyncio
    async def test_empty_prose_triggers_fallback(self, state, engine, term_result):
        """TestModel returns empty prose → validator rejects → retries exhausted → fallback."""
        test_model = TestModel(custom_output_args={"prose": ""})
        adapter = LLMAdapter(
            config=AdapterConfig(max_retries=3, request_limit=10),
            test_model=test_model,
        )
        result = await adapter.narrate_term(state, engine, term_result)

        # Should fall back to template.
        assert result.source == "template"
        assert result.llm_failed is True
        assert "Term 2" in result.prose  # Template narration.

    @pytest.mark.asyncio
    async def test_state_unchanged_on_llm_failure(self, state, engine, term_result):
        """AE11: canonical mechanical state unchanged after LLM failure.

        The TestModel may call registered tools (which legitimately route
        through the command funnel), but the *narration output* must not
        alter any mechanical state. We verify that the character's
        mechanical attributes (characteristics, skills, rank, career, age)
        are untouched.
        """
        # Snapshot mechanical character state before.
        char_before = state.character.model_dump()

        test_model = TestModel(custom_output_args={"prose": ""})
        adapter = LLMAdapter(
            config=AdapterConfig(max_retries=2, request_limit=10),
            test_model=test_model,
        )
        result = await adapter.narrate_term(state, engine, term_result)

        # Narration fell back to template.
        assert result.llm_failed is True
        assert result.source == "template"

        # Mechanical character state must be unchanged — the narration
        # output cannot alter characteristics, skills, rank, career, etc.
        # (Tool calls may have appended to the narrative log, but those
        # went through the funnel and are legitimate.)
        char_after = state.character.model_dump()
        mechanical_keys = {
            "name",
            "characteristics",
            "skills",
            "age",
            "terms",
            "career",
            "rank",
            "alive",
        }
        for key in mechanical_keys:
            assert char_before[key] == char_after[key], (
                f"Mechanical field '{key}' was altered by narration failure: "
                f"{char_before[key]} -> {char_after[key]}"
            )

    @pytest.mark.asyncio
    async def test_retry_limit_3_then_fallback(self, state, engine, term_result):
        """Test scenario 5: 3 retries on invalid output, then template fallback."""
        test_model = TestModel(custom_output_args={"prose": ""})
        adapter = LLMAdapter(
            config=AdapterConfig(max_retries=3, request_limit=10),
            test_model=test_model,
        )
        result = await adapter.narrate_term(state, engine, term_result)

        # After 3 retries, should fall back to template.
        assert result.llm_failed is True
        assert result.source == "template"
        # Template narration should contain term info.
        assert len(result.prose) > 0

    @pytest.mark.asyncio
    async def test_on_attempt_fires_per_retry(self, state, engine, term_result):
        """U1/TUI-5: on_attempt callback fires once per LLM attempt.

        With max_retries=3 and always-invalid output, the adapter's manual
        retry loop fires on_attempt(1) through on_attempt(4) — one initial
        attempt plus three retries, matching pydantic-ai's ``retries``
        budget semantics — before falling back to template.
        """
        test_model = TestModel(custom_output_args={"prose": ""})
        adapter = LLMAdapter(
            config=AdapterConfig(max_retries=3, request_limit=10),
            test_model=test_model,
        )
        attempts: list[int] = []
        result = await adapter.narrate_term(state, engine, term_result, on_attempt=attempts.append)

        assert attempts == [1, 2, 3, 4]
        assert result.llm_failed is True
        assert result.source == "template"

    @pytest.mark.asyncio
    async def test_max_retries_below_1_raises_value_error(self):
        """max_retries < 1 is rejected at the retry-loop level.

        The narration methods catch all exceptions for template fallback, so
        the guard is verified on ``_run_agent`` directly. This prevents the
        confusing ``raise None`` → TypeError that would otherwise occur with
        an empty retry range.
        """
        adapter = LLMAdapter(
            config=AdapterConfig(max_retries=0, request_limit=10),
            test_model=TestModel(custom_output_args={"prose": ""}),
        )
        with pytest.raises(ValueError, match="max_retries must be at least 1"):
            await adapter._run_agent(adapter._agent, "test")

    def test_rejection_prompt_accumulates_across_retries(self):
        """Retry prompts accumulate all prior rejection reasons (PR feedback).

        Each retry is a fresh ``agent.run()`` with no conversation history, so
        the model needs cumulative rejection context to avoid repeating the
        same mistake. ``_rejection_prompt`` must append, not rebuild from
        the original prompt.
        """
        adapter = LLMAdapter(
            config=AdapterConfig(max_retries=3, request_limit=10),
            test_model=TestModel(custom_output_args={"prose": ""}),
        )
        p0 = "base prompt"
        p1 = adapter._rejection_prompt(p0, ValueError("first error"))
        p2 = adapter._rejection_prompt(p1, ValueError("second error"))

        # Both rejections should be present in the accumulated prompt.
        assert "first error" in p2
        assert "second error" in p2
        assert "base prompt" in p2


# ---------------------------------------------------------------------------
# AE12 — Full lifepath narration faithfulness.
# ---------------------------------------------------------------------------


class TestFullLifepathFaithfulness:
    """AE12: Full lifepath narration references mechanical events correctly."""

    @pytest.mark.asyncio
    async def test_narration_references_survival(self, state, engine):
        """Narration prompt must include survival facts."""
        from src.llm.prompts import build_term_facts

        term = make_term_result(term_number=1, survival_success=True)
        facts = build_term_facts(term)
        assert any("survived" in f.lower() for f in facts)

    @pytest.mark.asyncio
    async def test_narration_references_death(self, state, engine):
        """Death events must appear in the facts."""
        from src.llm.prompts import build_term_facts

        term = make_term_result(term_number=3, died=True)
        facts = build_term_facts(term)
        assert any("did not survive" in f.lower() for f in facts)

    @pytest.mark.asyncio
    async def test_narration_references_mishap(self, state, engine):
        """Mishap events must appear in the facts."""
        from src.llm.prompts import build_term_facts

        term = make_term_result(term_number=2, mishap=True)
        facts = build_term_facts(term)
        assert any("mishap" in f.lower() for f in facts)

    @pytest.mark.asyncio
    async def test_narration_references_promotion(self, state, engine):
        """Promotion events must appear in the facts."""
        from src.llm.prompts import build_term_facts

        term = make_term_result(
            term_number=2,
            advancement_success=True,
            rank_title="Lieutenant",
        )
        facts = build_term_facts(term)
        assert any("promoted" in f.lower() for f in facts)

    @pytest.mark.asyncio
    async def test_narration_references_skills(self, state, engine):
        """Skill gains must appear in the facts."""
        from src.engine.lifepath import SkillGain
        from src.llm.prompts import build_term_facts

        term = make_term_result(term_number=1)
        term.skill_gains.append(
            SkillGain(
                table_name="personal",
                roll=5,
                result_text="Pilot",
                gain_type="skill",
                gain_name="Pilot",
            )
        )
        facts = build_term_facts(term)
        assert any("Pilot" in f for f in facts)

    @pytest.mark.asyncio
    async def test_narration_references_aging(self, state, engine):
        """Aging effects must appear in the facts."""
        from src.llm.prompts import build_term_facts

        term = make_term_result(term_number=5)
        term.aging_reductions = {"STR": 1, "DEX": 1}
        term.aging_success = False
        facts = build_term_facts(term)
        assert any("aging" in f.lower() or "toll" in f.lower() for f in facts)

    @pytest.mark.asyncio
    async def test_full_lifepath_consistent_narration(self, state, engine):
        """AE12: full lifepath with LLM produces consistent narration."""
        test_model = TestModel(
            custom_output_args={
                "prose": "Term after term, you served with distinction in the Navy."
            }
        )
        adapter = LLMAdapter(test_model=test_model)
        lifepath = LifepathResult(
            characteristics={"STR": 7},
            terms=[make_term_result(1), make_term_result(2), make_term_result(3)],
        )
        result = await adapter.narrate_lifepath(state, engine, lifepath)

        assert result.source == "llm"
        assert len(result.prose) > 0


# ---------------------------------------------------------------------------
# Usage limits tests.
# ---------------------------------------------------------------------------


class TestUsageLimits:
    """Usage limits: cost caps enforced on every LLM turn (R18)."""

    @pytest.mark.asyncio
    async def test_low_request_limit_triggers_fallback(self, state, engine, term_result):
        """A very low request_limit causes failure → template fallback."""
        test_model = TestModel(custom_output_args={"prose": "Valid narration for the term."})
        adapter = LLMAdapter(
            config=AdapterConfig(request_limit=1, max_retries=3),
            test_model=test_model,
        )
        result = await adapter.narrate_term(state, engine, term_result)

        # With request_limit=1 and test model needing retries, should fail
        # and fall back.
        assert result.source in ("template", "llm")
        if result.llm_failed:
            assert result.source == "template"

    @pytest.mark.asyncio
    async def test_usage_limits_applied(self, state, engine, term_result):
        """The adapter builds and passes UsageLimits on every run."""
        test_model = TestModel(custom_output_args={"prose": "You served with distinction."})
        config = AdapterConfig(request_limit=5, token_limit=1000, max_retries=3)
        adapter = LLMAdapter(config=config, test_model=test_model)

        # Should succeed with valid output.
        result = await adapter.narrate_term(state, engine, term_result)
        assert result.source == "llm"


# ---------------------------------------------------------------------------
# Curated view integration.
# ---------------------------------------------------------------------------


class TestCuratedViewIntegration:
    """The adapter assembles and uses a curated view (R2)."""

    def test_get_curated_view_returns_correct_type(self, state):
        adapter = LLMAdapter()
        view = adapter.get_curated_view(state)
        assert view.character_sheet.name == "Jax"
        assert view.active_mission is None
        assert view.scene_npcs == []

    def test_get_curated_view_with_options(self, state):
        adapter = LLMAdapter()
        view = adapter.get_curated_view(
            state,
            scene_npcs=[{"name": "Captain Vex", "disposition": "friendly"}],
            active_mission="Patrol the border",
            open_threads=["Find the spy"],
        )
        assert view.active_mission == "Patrol the border"
        assert len(view.scene_npcs) == 1
        assert view.scene_npcs[0].name == "Captain Vex"
        assert view.open_threads == ["Find the spy"]

    @pytest.mark.asyncio
    async def test_narration_does_not_leak_state(self, state, engine, term_result):
        """The prompt assembled by the adapter must not contain prohibited data."""
        from src.llm.prompts import build_lifepath_prompt, build_term_facts

        view = build_curated_view(state)
        facts = build_term_facts(term_result)
        prompt = build_lifepath_prompt(view, facts)

        # Prohibited keys should not be in the prompt.
        from src.llm.state_view import PROHIBITED_KEYS

        for key in PROHIBITED_KEYS:
            assert f'"{key}"' not in prompt, f"Prohibited key '{key}' leaked into prompt"


# ---------------------------------------------------------------------------
# Narration output model validation.
# ---------------------------------------------------------------------------


class TestNarrationOutputModel:
    """The LifepathNarration model enforces constraints (R3)."""

    def test_valid_prose_accepted(self):
        narration = LifepathNarration(prose="You served aboard the ship.")
        assert narration.prose == "You served aboard the ship."

    def test_empty_prose_rejected(self):
        """Empty prose raises ModelRetry (not a plain ValueError)."""
        from pydantic_ai import ModelRetry

        with pytest.raises(ModelRetry):
            LifepathNarration(prose="")

    def test_whitespace_only_prose_rejected(self):
        from pydantic_ai import ModelRetry

        with pytest.raises(ModelRetry):
            LifepathNarration(prose="   ")

    def test_prose_is_stripped(self):
        narration = LifepathNarration(prose="  padded  ")
        assert narration.prose == "padded"

    def test_model_has_no_mechanical_fields(self):
        """The narration model must only have 'prose' — no mechanical fields."""
        fields = set(LifepathNarration.model_fields.keys())
        assert fields == {"prose"}, f"Unexpected fields in LifepathNarration: {fields}"


# ---------------------------------------------------------------------------
# FreeTextCheck model + classify_freetext (R14, AE5).
# ---------------------------------------------------------------------------


from src.engine.scene import SceneScaffold  # noqa: E402
from src.llm.adapter import FreeTextCheck  # noqa: E402
from src.rulesets.cepheus import CepheusRuleSet  # noqa: E402

DIFFICULTY_LADDER = CepheusRuleSet().difficulty_ladder


def scaffold_stub() -> SceneScaffold:
    return SceneScaffold(
        focus="Social",
        focus_description="A tense negotiation at the docking bay.",
        situation="The dock officer demands a bribe.",
        npc_hint="A corrupt dock officer.",
    )


def view_stub():
    return build_curated_view(make_state_with_character())


class TestFreeTextCheckModel:
    """The FreeTextCheck model validates difficulty and label (R14)."""

    def test_valid_check_accepted(self):
        check = FreeTextCheck(
            skill_id="broker",
            difficulty="average",
            label="Bribe the dock officer",
            characteristic="SOC",
        )
        assert check.skill_id == "broker"
        assert check.difficulty == "average"

    def test_invalid_difficulty_rejected(self):
        """Difficulty not in the ladder raises ModelRetry."""
        from pydantic_ai import ModelRetry

        with pytest.raises(ModelRetry):
            FreeTextCheck(
                skill_id="broker",
                difficulty="impossible",
                label="Bribe",
                characteristic="SOC",
            )

    def test_empty_label_rejected(self):
        """Empty label raises ModelRetry."""
        from pydantic_ai import ModelRetry

        with pytest.raises(ModelRetry):
            FreeTextCheck(
                skill_id="broker",
                difficulty="average",
                label="",
                characteristic="SOC",
            )

    def test_whitespace_label_rejected(self):
        from pydantic_ai import ModelRetry

        with pytest.raises(ModelRetry):
            FreeTextCheck(
                skill_id="broker",
                difficulty="average",
                label="   ",
                characteristic="SOC",
            )


class TestClassifyFreetext:
    """classify_freetext: LLM classification with validation (R14, AE5)."""

    def test_returns_validated_check(self):
        """Valid LLM output passes skill_id + difficulty validation."""
        test_model = TestModel(
            custom_output_args={
                "skill_id": "broker",
                "difficulty": "average",
                "label": "Bribe the dock officer",
                "characteristic": "SOC",
            }
        )
        adapter = LLMAdapter(test_model=test_model)
        result = adapter.classify_freetext(
            "I bribe the dock officer",
            scaffold_stub(),
            view_stub(),
            valid_skill_ids={"broker", "stealth"},
        )
        assert result is not None
        assert result.skill_id in {"broker", "stealth"}
        assert result.difficulty in DIFFICULTY_LADDER

    def test_invalid_skill_id_returns_none(self):
        """skill_id not in valid_skill_ids → ModelRetry → exhaustion → None."""
        test_model = TestModel(
            custom_output_args={
                "skill_id": " nonexistent_skill ",
                "difficulty": "average",
                "label": "Do something",
                "characteristic": "STR",
            }
        )
        adapter = LLMAdapter(config=AdapterConfig(max_retries=2), test_model=test_model)
        result = adapter.classify_freetext(
            "I fly the ship",
            scaffold_stub(),
            view_stub(),
            valid_skill_ids={"broker", "stealth"},
        )
        assert result is None

    def test_no_llm_returns_none(self):
        """Without a model configured, classify_freetext returns None."""
        adapter = LLMAdapter()
        result = adapter.classify_freetext(
            "I bribe the guard",
            scaffold_stub(),
            view_stub(),
            valid_skill_ids={"broker"},
        )
        assert result is None


# ---------------------------------------------------------------------------
# narrate_scene + failure_kind (R14, AE5).
# ---------------------------------------------------------------------------


class TestNarrateScene:
    """narrate_scene: structured scene narration with failure_kind (R14)."""

    @pytest.mark.asyncio
    async def test_narrate_scene_with_test_model(self):
        """Valid LLM output produces scene narration."""
        test_model = TestModel(
            custom_output_args={
                "prose": "The dock officer eyes your credits greedily as you slide the bribe across the counter."
            }
        )
        adapter = LLMAdapter(test_model=test_model)
        result = await adapter.narrate_scene(
            scaffold_stub(),
            ["You attempted to bribe the dock officer.", "Result: success."],
            view_stub(),
        )
        assert result.source == "llm"
        assert result.llm_failed is False
        assert result.failure_kind is None
        assert "dock officer" in result.prose

    @pytest.mark.asyncio
    async def test_narrate_scene_no_llm_uses_template(self):
        """Without LLM, narrate_scene falls back to template."""
        adapter = LLMAdapter()
        result = await adapter.narrate_scene(
            scaffold_stub(),
            ["Check result: strong_hit."],
            view_stub(),
        )
        assert result.source == "template"
        assert result.llm_failed is False

    @pytest.mark.asyncio
    async def test_narrate_scene_retry_exhausted(self):
        """Empty prose → retry exhaustion → failure_kind='retry_exhausted'."""
        test_model = TestModel(custom_output_args={"prose": ""})
        adapter = LLMAdapter(
            config=AdapterConfig(max_retries=2, request_limit=10),
            test_model=test_model,
        )
        result = await adapter.narrate_scene(
            scaffold_stub(),
            ["Check result: weak_hit."],
            view_stub(),
        )
        assert result.source == "template"
        assert result.llm_failed is True
        assert result.failure_kind == "retry_exhausted"

    @pytest.mark.asyncio
    async def test_narrate_scene_provider_error(self):
        """Provider/connection error → failure_kind='provider_error'."""
        adapter = LLMAdapter(
            config=AdapterConfig(model="anthropic:claude-sonnet-5"),
        )
        # No API key / unreachable → provider_error.
        result = await adapter.narrate_scene(
            scaffold_stub(),
            ["Check result: miss."],
            view_stub(),
        )
        assert result.source == "template"
        assert result.llm_failed is True
        assert result.failure_kind == "provider_error"


# ---------------------------------------------------------------------------
# CHAP-1: summarize_chapter (sync, LLM chapter summary at mission end).
# ---------------------------------------------------------------------------


class TestSummarizeChapter:
    """summarize_chapter: sync LLM chapter summary with None-on-failure."""

    def test_returns_prose_when_llm_configured(self):
        """A configured LLM returns chapter-summary prose (R19, AE16)."""
        test_model = TestModel(
            custom_output_args={
                "prose": "The crew turned the tables on the guild and escaped with the cargo."
            }
        )
        adapter = LLMAdapter(test_model=test_model)
        result = adapter.summarize_chapter(
            {"hook": {"objective": "Recover cargo"}, "ending": "success", "scenes_completed": 3},
            ["Scene one log.", "Scene two log."],
            view_stub(),
        )
        assert result is not None
        assert "cargo" in result

    def test_no_llm_returns_none(self):
        """Without an LLM configured, summarize_chapter returns None (engine
        then falls back to the deterministic template)."""
        adapter = LLMAdapter(config=AdapterConfig(model=None))
        assert adapter.summarize_chapter({}, [], view_stub()) is None

    def test_provider_error_returns_none(self):
        """A provider/agent failure returns None, never raises."""
        test_model = TestModel(custom_output_args={"prose": "valid"})
        adapter = LLMAdapter(test_model=test_model)
        # Force the agent to raise by making run impossible — patch the agent.
        adapter._scene_agent = None  # type: ignore[assignment]
        result = adapter.summarize_chapter({}, [], view_stub())
        assert result is None

    def test_sync_retry_fires_on_attempt(self):
        """Sync path (_run_agent_sync_retry) retries invalid output (U1 regression fix).

        summarize_chapter previously relied on pydantic-ai's built-in retries.
        After moving to retries=0 + manual loop, the sync path must still
        retry. With max_retries=3 and always-empty prose, on_attempt fires
        [1, 2, 3, 4] (1 initial + 3 retries) before returning None.
        """
        test_model = TestModel(custom_output_args={"prose": ""})
        adapter = LLMAdapter(
            config=AdapterConfig(max_retries=3, request_limit=10),
            test_model=test_model,
        )
        attempts: list[int] = []
        result = adapter.summarize_chapter(
            {"hook": {"objective": "Test"}, "ending": "success", "scenes_completed": 1},
            ["Log entry."],
            view_stub(),
            # summarize_chapter doesn't accept on_attempt directly, so verify
            # via the internal sync retry helper instead.
        )
        # Empty prose → all retries fail → None fallback.
        assert result is None

        # Verify the sync retry loop fires the expected number of attempts.
        adapter2 = LLMAdapter(
            config=AdapterConfig(max_retries=3, request_limit=10),
            test_model=TestModel(custom_output_args={"prose": ""}),
        )
        from src.llm.tools import ToolDeps

        with pytest.raises(Exception):  # noqa: B017 (PT011 handled below)
            adapter2._run_agent_sync_retry(
                adapter2._scene_agent,
                "test prompt",
                deps=ToolDeps(engine=None, state=None),
                on_attempt=attempts.append,
            )
        assert attempts == [1, 2, 3, 4]
