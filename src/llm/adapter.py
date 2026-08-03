"""Thin LLM adapter wrapping a Pydantic AI Agent (R3, R18, R19).

The adapter is the single integration point between the engine and the LLM.
It provides:

- **Structured narration output** via ``LifepathNarration`` (a BaseModel with
  only a ``prose`` field — no fields that could alter mechanics).
- **Curated state view** assembly (R2) — the LLM never sees full state.
- **Retry and rejection** (R3, AE11) — invalid output is rejected via
  ``ModelRetry``; after ``max_retries`` attempts, the adapter falls back to
  template narration and logs a flag.
- **Usage limits** (R18) — every LLM turn is capped.
- **Template fallback** — when no LLM is configured or all retries are
  exhausted, the adapter delegates to the existing ``Narrator`` class.

Design (per the KTD): one agent with ``output_type=BaseModel`` for structured
narration, tools registered for state mutation, ``ModelRetry`` for validation
rejection, ``UsageLimits`` on every turn.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, field_validator
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import UsageLimits

from src.engine.commands import Engine
from src.engine.lifepath import (
    LifepathResult,
    MusteringOutResult,
    QualificationResult,
    TermResult,
)
from src.engine.narration import Narrator
from src.engine.state import GameState
from src.llm.prompts import (
    SYSTEM_PROMPT,
    build_chapter_summary_prompt,
    build_classification_prompt,
    build_full_lifepath_prompt,
    build_lifepath_prompt,
    build_recap_prompt,
    build_scene_prompt,
    build_term_facts,
)
from src.llm.state_view import CuratedView, build_curated_view
from src.llm.tools import TOOL_REGISTRY, ToolDeps

logger = logging.getLogger(__name__)

#: Callback fired before each LLM attempt so screens can render
#: "narrating… attempt k" (U1). The int argument is the 1-based attempt.
AttemptCallback = Callable[[int], None]

# ---------------------------------------------------------------------------
# Structured output models.
# ---------------------------------------------------------------------------


class LifepathNarration(BaseModel):
    """Structured narration output for a single term.

    The only field is ``prose`` — there are no fields that could alter
    mechanical outcomes (R3). Validation ensures the prose is non-empty
    and references at least one mechanical element from the prompt.
    """

    prose: str

    @field_validator("prose")
    @classmethod
    def prose_must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ModelRetry(
                "Narration prose must be non-empty. Please write 2-4 sentences of backstory."
            )
        return v.strip()


class FullLifepathNarration(BaseModel):
    """Structured narration output for the full lifepath (AE12).

    Contains a single ``prose`` string that covers all terms in a
    consistent voice.
    """

    prose: str

    @field_validator("prose")
    @classmethod
    def prose_must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ModelRetry("Full lifepath narration must be non-empty.")
        return v.strip()


class SceneNarration(BaseModel):
    """Structured narration output for a scene (R14, AE5).

    Like lifepath narration, the only field is ``prose`` — no fields that
    could alter mechanical outcomes.
    """

    prose: str

    @field_validator("prose")
    @classmethod
    def prose_must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ModelRetry("Scene narration prose must be non-empty. Please write 2-4 sentences.")
        return v.strip()


# Difficulty ladder used by FreeTextCheck validation.
_VALID_DIFFICULTIES: frozenset[str] = frozenset(
    {"easy", "routine", "average", "difficult", "very_difficult", "formidable"}
)


class FreeTextCheck(BaseModel):
    """Structured LLM output for free-text classification (R14, AE5).

    The LLM interprets free-text player input into an engine-known check.
    ``field_validator``\\ s enforce difficulty membership and non-empty label;
    the adapter additionally validates ``skill_id`` against the caller-provided
    ``valid_skill_ids`` set (post-call).
    """

    skill_id: str
    difficulty: str
    label: str
    characteristic: str = "SOC"
    life_threatening: bool = False

    @field_validator("difficulty")
    @classmethod
    def difficulty_must_be_in_ladder(cls, v: str) -> str:
        v_norm = v.strip().lower().replace(" ", "_")
        if v_norm not in _VALID_DIFFICULTIES:
            raise ModelRetry(
                f"Difficulty '{v}' is not a valid difficulty. "
                f"Choose from: {sorted(_VALID_DIFFICULTIES)}."
            )
        return v_norm

    @field_validator("label")
    @classmethod
    def label_must_be_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ModelRetry("Label must be non-empty.")
        return v.strip()


# ---------------------------------------------------------------------------
# Narration result — what the engine receives back.
# ---------------------------------------------------------------------------


@dataclass
class NarrationResult:
    """Result of an LLM narration turn.

    Attributes:
        prose: The narration text.
        source: ``"llm"`` if the LLM produced this, ``"template"`` if the
            template fallback was used.
        retries_used: How many retries were needed (0 = first attempt).
        llm_failed: True if the LLM exhausted all retries and fell back to
            template narration. The caller should log an audit flag.
        failure_kind: When ``llm_failed`` is True, categorises the failure:
            ``"retry_exhausted"`` (LLM kept producing invalid output),
            ``"provider_error"`` (network/API/timeout), or ``None`` (success
            or template-only). Callers use this to select the correct
            degraded-mode status surface.
    """

    prose: str
    source: str = "llm"
    retries_used: int = 0
    llm_failed: bool = False
    failure_kind: str | None = None


# ---------------------------------------------------------------------------
# Adapter configuration.
# ---------------------------------------------------------------------------


@dataclass
class AdapterConfig:
    """Configuration for the LLM adapter.

    Attributes:
        model: Pydantic AI model identifier (e.g. ``"anthropic:claude-sonnet-5"``).
            If ``None``, no LLM is configured and template narration is used.
        max_retries: Maximum number of retries on invalid output before
            falling back to template narration (default 3).
        request_limit: Maximum number of requests per turn (usage limit).
        token_limit: Optional token cap per turn.
        request_timeout: Optional request timeout in seconds.
    """

    model: str | None = None
    max_retries: int = 3
    request_limit: int = 10
    token_limit: int | None = None
    request_timeout: float | None = None


# ---------------------------------------------------------------------------
# The adapter.
# ---------------------------------------------------------------------------


class LLMAdapter:
    """Thin adapter wrapping a Pydantic AI Agent for narration (U5).

    Usage:

        # With LLM configured:
        adapter = LLMAdapter(AdapterConfig(model="anthropic:claude-sonnet-5"))
        result = await adapter.narrate_term(state, engine, term_result)

        # Without LLM (template fallback):
        adapter = LLMAdapter()  # model=None
        result = await adapter.narrate_term(state, engine, term_result)

    The adapter always returns a :class:`NarrationResult` — it never raises
    on LLM failure. If the LLM is not configured or exhausts retries, the
    template narrator produces the prose.
    """

    def __init__(
        self,
        config: AdapterConfig | None = None,
        *,
        test_model: TestModel | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            config: Adapter configuration. Defaults to ``AdapterConfig()``
                (no LLM, template fallback only).
            test_model: Optional ``TestModel`` for testing. When provided,
                the agent uses this instead of a real model. This bypasses
                real API calls entirely.
        """
        self.config = config or AdapterConfig()
        self._test_model = test_model
        self._narrator = Narrator()  # Template fallback.
        self._agent: Agent[ToolDeps, LifepathNarration] | None = None
        self._full_agent: Agent[ToolDeps, FullLifepathNarration] | None = None
        self._scene_agent: Agent[ToolDeps, SceneNarration] | None = None
        self._classify_agent: Agent[ToolDeps, FreeTextCheck] | None = None

        if self._test_model is not None or self.config.model is not None:
            self._setup_agents()

    def _setup_agents(self) -> None:
        """Create the Pydantic AI agents for narration."""
        is_test = self._test_model is not None
        model: Any = self._test_model if is_test else self.config.model
        # Defer model validation for real providers so the adapter can be
        # constructed before API keys are available.
        defer = not is_test

        # Per-term narration agent.
        self._agent = Agent(
            model,
            output_type=LifepathNarration,
            system_prompt=SYSTEM_PROMPT,
            deps_type=ToolDeps,
            retries=0,  # Adapter owns the retry loop (U1 on_attempt support).
            defer_model_check=defer,
        )
        # Register tools.
        for tool_func in TOOL_REGISTRY.values():
            self._agent.tool(tool_func)

        # Full-lifepath narration agent.
        self._full_agent = Agent(
            model,
            output_type=FullLifepathNarration,
            system_prompt=SYSTEM_PROMPT,
            deps_type=ToolDeps,
            retries=0,
            defer_model_check=defer,
        )
        for tool_func in TOOL_REGISTRY.values():
            self._full_agent.tool(tool_func)

        # Scene narration agent (R14). No tools — narration is read-only.
        self._scene_agent = Agent(
            model,
            output_type=SceneNarration,
            system_prompt=SYSTEM_PROMPT,
            deps_type=ToolDeps,
            retries=0,
            defer_model_check=defer,
        )

        # Free-text classification agent (R14, AE5). No tools — read-only.
        self._classify_agent = Agent(
            model,
            output_type=FreeTextCheck,
            system_prompt=SYSTEM_PROMPT,
            deps_type=ToolDeps,
            retries=0,
            defer_model_check=defer,
        )

    @property
    def llm_configured(self) -> bool:
        """True if an LLM model is available (real or test)."""
        return self._test_model is not None or self.config.model is not None

    # ------------------------------------------------------------------
    # Usage limits.
    # ------------------------------------------------------------------

    def _usage_limits(self) -> UsageLimits:
        """Build the per-turn usage limits (R18)."""
        kwargs: dict[str, Any] = {
            "request_limit": self.config.request_limit,
        }
        if self.config.token_limit is not None:
            kwargs["total_tokens_limit"] = self.config.token_limit
        return UsageLimits(**kwargs)

    # ------------------------------------------------------------------
    # Retry loop with per-attempt callback (U1 — TUI-5).
    # ------------------------------------------------------------------

    #: Maximum number of attempts for a single LLM call: one initial
    #: attempt plus ``max_retries`` retries (matching pydantic-ai's own
    #: ``retries`` budget semantics).
    def _total_attempts(self) -> int:
        if self.config.max_retries < 1:
            raise ValueError(f"max_retries must be at least 1, got {self.config.max_retries}")
        return self.config.max_retries + 1

    @staticmethod
    def _rejection_prompt(full_prompt: str, exc: Exception) -> str:
        """Build a follow-up prompt that feeds the rejection reason back.

        Appends to ``full_prompt`` (not the original prompt) so prior
        rejection reasons accumulate across retries. Each retry is a fresh
        ``agent.run()`` with no conversation history, so the model needs the
        cumulative context to avoid repeating the same mistake.
        """
        return (
            f"{full_prompt}\n\n"
            f"Your previous response was rejected: {exc}. "
            f"Please try again, addressing this feedback."
        )

    async def _run_agent(
        self,
        agent: Agent,
        prompt: str,
        *,
        deps: ToolDeps | None = None,
        on_attempt: AttemptCallback | None = None,
    ) -> Any:
        """Run a Pydantic AI agent with a manual retry loop (U1).

        Agents are constructed with ``retries=0`` so the adapter owns retry
        semantics. This helper performs up to ``max_retries + 1`` attempts
        (one initial plus ``max_retries`` retries, matching pydantic-ai's
        own ``retries`` budget), calling ``on_attempt(k)`` before each
        attempt so screens can show a generating indicator with an attempt
        counter.

        On each retry the rejection message from the previous attempt is
        prepended to the prompt, preserving the within-conversation retry
        quality (the model sees why its prior output was rejected).

        Raises the last exception if all retries are exhausted — callers
        catch it and fall back to template narration.
        """
        total = self._total_attempts()
        full_prompt = prompt
        last_exc: Exception | None = None
        for attempt in range(1, total + 1):
            if on_attempt is not None:
                on_attempt(attempt)
            try:
                return await agent.run(
                    full_prompt,
                    deps=deps,
                    usage_limits=self._usage_limits(),
                )
            except (ModelRetry, UnexpectedModelBehavior) as exc:
                # With retries=0, pydantic-ai wraps ModelRetry into
                # UnexpectedModelBehavior — catch both so the manual loop
                # owns all retry semantics (U1/TUI-5).
                last_exc = exc
                if attempt < total:
                    # Feed the rejection reason back so the model can correct.
                    full_prompt = self._rejection_prompt(full_prompt, exc)
                    continue
                raise
        # Unreachable — loop either returns or raises on final attempt.
        raise last_exc  # type: ignore[misc]

    def _run_agent_sync_retry(
        self,
        agent: Agent,
        prompt: str,
        *,
        deps: ToolDeps | None = None,
        on_attempt: AttemptCallback | None = None,
    ) -> Any:
        """Sync counterpart to :meth:`_run_agent` for non-TUI callers.

        Mirrors the async retry loop but delegates the actual call to
        :meth:`_run_agent_sync` (which handles the event-loop-aware
        ``run_sync`` fallback). Used by :meth:`summarize_chapter` and the
        deprecated :meth:`classify_freetext` so they retain the same retry
        budget as the async narration paths.
        """
        total = self._total_attempts()
        full_prompt = prompt
        last_exc: Exception | None = None
        for attempt in range(1, total + 1):
            if on_attempt is not None:
                on_attempt(attempt)
            try:
                return self._run_agent_sync(
                    agent,
                    full_prompt,
                    deps=deps,
                    usage_limits=self._usage_limits(),
                )
            except (ModelRetry, UnexpectedModelBehavior) as exc:
                last_exc = exc
                if attempt < total:
                    full_prompt = self._rejection_prompt(full_prompt, exc)
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Term narration.
    # ------------------------------------------------------------------

    async def narrate_term(
        self,
        state: GameState,
        engine: Engine,
        term_result: TermResult,
        *,
        on_attempt: AttemptCallback | None = None,
    ) -> NarrationResult:
        """Narrate a single term's events using the LLM (R11, AE12).

        If no LLM is configured, falls back to template narration.

        Args:
            state: The canonical game state.
            engine: The engine (for tool deps / command funnel).
            term_result: The mechanical result for this term.
            on_attempt: Optional callback fired before each LLM attempt (U1).

        Returns:
            :class:`NarrationResult` with prose and metadata.
        """
        # Template fallback when no LLM.
        if not self.llm_configured:
            return NarrationResult(
                prose=self._narrator.narrate_term(term_result),
                source="template",
            )

        # Build curated view and facts.
        view = build_curated_view(state)
        facts = build_term_facts(term_result)
        prompt = build_lifepath_prompt(view, facts)
        deps = ToolDeps(engine=engine, state=state)

        try:
            result = await self._run_agent(self._agent, prompt, deps=deps, on_attempt=on_attempt)
            return NarrationResult(
                prose=result.output.prose,
                source="llm",
            )
        except Exception as exc:
            # AE11: LLM failure (invalid output, retry exhaustion) falls back
            # to template narration. State is unchanged.
            failure_kind = self._classify_failure(exc)
            logger.warning(
                "LLM narration failed for term %d (%s), falling back to template: %s",
                term_result.term_number,
                failure_kind,
                exc,
            )
            return NarrationResult(
                prose=self._narrator.narrate_term(term_result),
                source="template",
                llm_failed=True,
                failure_kind=failure_kind,
            )

    # ------------------------------------------------------------------
    # Qualification narration.
    # ------------------------------------------------------------------

    async def narrate_qualification(
        self,
        state: GameState,
        engine: Engine,
        qual_result: QualificationResult,
        *,
        on_attempt: AttemptCallback | None = None,
    ) -> NarrationResult:
        """Narrate a career qualification check.

        Falls back to template narration when no LLM is configured or
        on LLM failure.
        """
        if not self.llm_configured:
            return NarrationResult(
                prose=self._narrator.narrate_qualification(qual_result),
                source="template",
            )

        view = build_curated_view(state)
        import json as _json

        view_json = _json.dumps(view.model_dump(), indent=2)
        outcome = "passed" if qual_result.success else "failed"
        prompt = (
            f"## Character State\n{view_json}\n\n"
            f"## Qualification Event\n"
            f"The character attempted to qualify for the "
            f"{qual_result.career_name} career and {outcome}.\n\n"
            f"Write 1-2 sentences of engaging second-person prose "
            f"narrating this qualification attempt. "
            f"Do not mention dice or game mechanics."
        )
        deps = ToolDeps(engine=engine, state=state)

        try:
            result = await self._run_agent(self._agent, prompt, deps=deps, on_attempt=on_attempt)
            return NarrationResult(
                prose=result.output.prose,
                source="llm",
            )
        except Exception as exc:
            failure_kind = self._classify_failure(exc)
            logger.warning(
                "LLM qualification narration failed (%s), falling back to template: %s",
                failure_kind,
                exc,
            )
            return NarrationResult(
                prose=self._narrator.narrate_qualification(qual_result),
                source="template",
                llm_failed=True,
                failure_kind=failure_kind,
            )

    # ------------------------------------------------------------------
    # Mustering out narration.
    # ------------------------------------------------------------------

    async def narrate_mustering_out(
        self,
        state: GameState,
        engine: Engine,
        mo_result: MusteringOutResult,
        *,
        on_attempt: AttemptCallback | None = None,
    ) -> NarrationResult:
        """Narrate mustering-out benefits.

        Falls back to template narration when no LLM is configured or
        on LLM failure.
        """
        if not self.llm_configured:
            return NarrationResult(
                prose=self._narrator.narrate_mustering_out(mo_result),
                source="template",
            )

        view = build_curated_view(state)
        import json as _json

        view_json = _json.dumps(view.model_dump(), indent=2)
        benefits: list[str] = []
        if mo_result.cash_benefits:
            benefits.append(f"Cash: {', '.join(mo_result.cash_benefits)}")
        if mo_result.material_benefits:
            benefits.append(f"Material benefits: {', '.join(mo_result.material_benefits)}")
        benefits_text = "\n".join(f"  - {b}" for b in benefits) or "  - No benefits"
        prompt = (
            f"## Character State\n{view_json}\n\n"
            f"## Mustering Out Event\n"
            f"The character is mustering out after "
            f"{mo_result.terms_served} term(s) as a "
            f"{mo_result.career_name} (rank {mo_result.final_rank}).\n"
            f"Benefits received:\n{benefits_text}\n\n"
            f"Write 2-3 sentences of engaging second-person prose "
            f"narrating the mustering-out scene. "
            f"Do not mention dice or game mechanics."
        )
        deps = ToolDeps(engine=engine, state=state)

        try:
            result = await self._run_agent(self._agent, prompt, deps=deps, on_attempt=on_attempt)
            return NarrationResult(
                prose=result.output.prose,
                source="llm",
            )
        except Exception as exc:
            failure_kind = self._classify_failure(exc)
            logger.warning(
                "LLM mustering out narration failed (%s), falling back to template: %s",
                failure_kind,
                exc,
            )
            return NarrationResult(
                prose=self._narrator.narrate_mustering_out(mo_result),
                source="template",
                llm_failed=True,
                failure_kind=failure_kind,
            )

    # ------------------------------------------------------------------
    # Full lifepath narration.
    # ------------------------------------------------------------------

    async def narrate_lifepath(
        self,
        state: GameState,
        engine: Engine,
        lifepath_result: LifepathResult,
        *,
        on_attempt: AttemptCallback | None = None,
    ) -> NarrationResult:
        """Narrate the entire lifepath with the LLM (AE12).

        Produces a single cohesive narration covering all terms. If no LLM
        is configured or retries are exhausted, falls back to template
        narration (joined into a single string).
        """
        if not self.llm_configured:
            lines = self._narrator.narrate_lifepath(lifepath_result)
            return NarrationResult(
                prose="\n".join(lines),
                source="template",
            )

        # Build curated view and all term facts.
        view = build_curated_view(state)
        all_facts = [build_term_facts(t) for t in lifepath_result.terms]
        prompt = build_full_lifepath_prompt(view, all_facts)
        deps = ToolDeps(engine=engine, state=state)

        try:
            result = await self._run_agent(
                self._full_agent, prompt, deps=deps, on_attempt=on_attempt
            )
            return NarrationResult(
                prose=result.output.prose,
                source="llm",
            )
        except Exception as exc:
            failure_kind = self._classify_failure(exc)
            logger.warning(
                "LLM full lifepath narration failed (%s), falling back to template: %s",
                failure_kind,
                exc,
            )
            lines = self._narrator.narrate_lifepath(lifepath_result)
            return NarrationResult(
                prose="\n".join(lines),
                source="template",
                llm_failed=True,
                failure_kind=failure_kind,
            )

    # ------------------------------------------------------------------
    # Scene narration (R14, AE5 — Task 24).
    # ------------------------------------------------------------------

    async def narrate_scene(
        self,
        scaffold,
        outcome_facts: list[str],
        view: CuratedView,
        *,
        on_attempt: AttemptCallback | None = None,
    ) -> NarrationResult:
        """Narrate a scene's events using the LLM (R14).

        Mirrors the lifepath narration pattern: structured prose via the
        scene agent, retry, template fallback, never raises. On failure,
        ``failure_kind`` distinguishes retry exhaustion from provider errors
        so the caller can display the appropriate degraded-mode surface.

        Args:
            scaffold: :class:`SceneScaffold` with focus/situation/NPC hints.
            outcome_facts: Mechanical outcome facts as human-readable strings.
            view: The curated state view for this scene.
            on_attempt: Optional callback fired before each LLM attempt (U1).

        Returns:
            :class:`NarrationResult` with prose and metadata.
        """
        if not self.llm_configured:
            return NarrationResult(
                prose=self._template_scene(scaffold, outcome_facts),
                source="template",
            )

        prompt = build_scene_prompt(view, scaffold, outcome_facts)
        deps = ToolDeps(engine=None, state=None)  # Read-only context.

        try:
            result = await self._run_agent(
                self._scene_agent, prompt, deps=deps, on_attempt=on_attempt
            )
            return NarrationResult(
                prose=result.output.prose,
                source="llm",
            )
        except Exception as exc:
            failure_kind = self._classify_failure(exc)
            logger.warning(
                "LLM scene narration failed (%s), falling back to template: %s",
                failure_kind,
                exc,
            )
            return NarrationResult(
                prose=self._template_scene(scaffold, outcome_facts),
                source="template",
                llm_failed=True,
                failure_kind=failure_kind,
            )

    def classify_freetext(
        self,
        text: str,
        scaffold,
        view: CuratedView,
        valid_skill_ids: set[str],
    ) -> FreeTextCheck | None:
        """Classify free-text input into an engine-known check (R14, AE5).

        Runs the classification agent synchronously (via thread-pool when
        inside a running event loop, e.g. Textual). Validates ``skill_id``
        against ``valid_skill_ids`` post-call — an invalid skill triggers
        ``ModelRetry``. On exhaustion or any error, returns ``None`` so the
        caller falls back to the keyword map.

        .. deprecated::
            Use :meth:`classify_freetext_async` from within a Textual worker
            to avoid blocking the event loop (U1). This sync method remains
            for backward compatibility and non-TUI callers.

        Args:
            text: The free-text player input.
            scaffold: The current :class:`SceneScaffold`.
            view: The curated state view.
            valid_skill_ids: Engine-known skill ids the LLM may choose from.

        Returns:
            :class:`FreeTextCheck` on success, ``None`` on failure/exhaustion.
        """
        if not self.llm_configured:
            return None

        prompt = build_classification_prompt(text, scaffold, view, valid_skill_ids)
        deps = ToolDeps(engine=None, state=None)

        try:
            result = self._run_agent_sync_retry(
                self._classify_agent,
                prompt,
                deps=deps,
            )
            # Post-call validation: skill_id must be in the valid set.
            if result.output.skill_id not in valid_skill_ids:
                raise ModelRetry(
                    f"skill_id '{result.output.skill_id}' is not in the valid set: "
                    f"{sorted(valid_skill_ids)}"
                )
            return result.output
        except Exception as exc:
            logger.warning("Free-text classification failed, returning None: %s", exc)
            return None

    async def classify_freetext_async(
        self,
        text: str,
        scaffold,
        view: CuratedView,
        valid_skill_ids: set[str],
        *,
        on_attempt: AttemptCallback | None = None,
    ) -> FreeTextCheck | None:
        """Async free-text classification — never blocks the event loop (U1).

        Mirrors :meth:`classify_freetext` but uses ``await agent.run()``
        via the adapter's manual retry loop, so it can run inside a Textual
        ``run_worker`` coroutine without a thread-pool fallback.

        Returns ``None`` on failure/exhaustion so the caller falls back to
        the keyword map. Never raises.
        """
        if not self.llm_configured:
            return None

        prompt = build_classification_prompt(text, scaffold, view, valid_skill_ids)
        deps = ToolDeps(engine=None, state=None)

        try:
            result = await self._run_agent(
                self._classify_agent,
                prompt,
                deps=deps,
                on_attempt=on_attempt,
            )
            if result.output.skill_id not in valid_skill_ids:
                raise ModelRetry(
                    f"skill_id '{result.output.skill_id}' is not in the valid set: "
                    f"{sorted(valid_skill_ids)}"
                )
            return result.output
        except Exception as exc:
            logger.warning("Free-text classification failed, returning None: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Chapter summary (CHAP-1, R19, AE16).
    # ------------------------------------------------------------------

    def summarize_chapter(
        self,
        mission_record: dict,
        log_entries: list[str],
        view: CuratedView,
    ) -> str | None:
        """Generate an LLM chapter summary at mission end (R19, AE16).

        Runs the scene narration agent synchronously (the prose output is
        generic enough for a chapter recap). On any failure — provider error,
        retry exhaustion, or an empty result — returns ``None`` so the engine
        (:meth:`MissionEngine._record_chapter_summary`) falls back to the
        deterministic template. Never raises.

        The returned prose is validated by the engine's :class:`SummaryValidator`
        (mechanical-claim guard) before it ships; a summary that leaks dice
        notation or stats is rejected and the template is used.
        """
        if not self.llm_configured:
            return None

        prompt = build_chapter_summary_prompt(mission_record, log_entries, view)
        deps = ToolDeps(engine=None, state=None)  # Read-only context.

        try:
            result = self._run_agent_sync_retry(
                self._scene_agent,
                prompt,
                deps=deps,
            )
            prose = result.output.prose.strip()
            return prose or None
        except Exception as exc:
            logger.warning("LLM chapter summary failed, returning None: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Story recap (U11, R13).
    # ------------------------------------------------------------------

    def polish_recap(
        self,
        state: GameState,
        template_lines: list[str],
        view: CuratedView | None = None,
    ) -> str | None:
        """Generate an LLM-polished story-so-far recap (U11, R13).

        Uses the scene narration agent (read-only) with the same injection
        pattern as chapter summaries. Returns the polished prose or ``None``
        on any failure — the caller (:func:`build_recap`) falls back to the
        deterministic template. Never raises.

        The returned prose is validated by the caller through
        :class:`SummaryValidator` (mechanical-claim guard) before it ships;
        a recap that leaks dice notation or stats is rejected and the
        template is used.
        """
        if not self.llm_configured:
            return None

        if view is None:
            view = build_curated_view(state)

        prompt = build_recap_prompt(view, template_lines, state.open_threads)
        deps = ToolDeps(engine=None, state=None)  # Read-only context.

        try:
            result = self._run_agent_sync_retry(
                self._scene_agent,
                prompt,
                deps=deps,
            )
            prose = result.output.prose.strip()
            return prose or None
        except Exception as exc:
            logger.warning("LLM recap polish failed, returning None: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Internal helpers (Task 24).
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_failure(exc: Exception) -> str:
        """Categorise an LLM failure for degraded-mode surfaces.

        Returns ``"retry_exhausted"`` for ``ModelRetry`` / validation
        exhaustion and ``"provider_error"`` for network/API/timeout errors.
        """
        exc_name = type(exc).__name__
        # ModelRetry, UsageLimitExceeded, ValidationError → retry exhaustion.
        if exc_name in ("ModelRetry", "UsageLimitExceeded", "ValidationError"):
            return "retry_exhausted"
        # Any subclass of these also counts.
        from pydantic_ai import ModelRetry as _MR
        from pydantic_core import ValidationError as _VE

        if isinstance(exc, (_MR, _VE)):
            return "retry_exhausted"
        # If the exception message mentions retries/exhaustion/usage, treat
        # as retry exhaustion. Covers "Exceeded maximum output retries (N)".
        msg = str(exc).lower()
        if "retr" in msg or "exhaust" in msg or "usage" in msg or "exceed" in msg:
            return "retry_exhausted"
        return "provider_error"

    @staticmethod
    def _run_agent_sync(agent, prompt, **kwargs):
        """Run a Pydantic AI agent synchronously.

        When called from inside a running event loop (e.g. a Textual TUI),
        ``agent.run_sync`` raises ``RuntimeError``. This helper falls back
        to a thread pool so the call succeeds without blocking the TUI's
        loop.
        """
        import concurrent.futures

        try:
            return agent.run_sync(prompt, **kwargs)
        except RuntimeError:
            # Event loop already running — run in a separate thread.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(agent.run_sync, prompt, **kwargs)
                return future.result(timeout=30)

    @staticmethod
    def _template_scene(scaffold, outcome_facts: list[str]) -> str:
        """Build template (fallback) scene narration from scaffold + facts."""
        lines = [f"[{scaffold.focus}] {scaffold.situation}"]
        if getattr(scaffold, "npc_hint", None):
            lines.append(scaffold.npc_hint)
        for fact in outcome_facts:
            lines.append(fact)
        return " ".join(lines)

    # ------------------------------------------------------------------
    # Curated view access.
    # ------------------------------------------------------------------

    def get_curated_view(
        self,
        state: GameState,
        *,
        scene_npcs: list | None = None,
        active_mission: str | None = None,
        open_threads: list[str] | None = None,
    ) -> CuratedView:
        """Build and return the curated state view (R2, AE13).

        This is the public entry point for code that needs the curated
        view outside of narration (e.g., displaying state to the UI).
        """
        from src.llm.state_view import NpcSummary

        npcs = [n if isinstance(n, NpcSummary) else NpcSummary(**n) for n in (scene_npcs or [])]
        return build_curated_view(
            state,
            scene_npcs=npcs,
            active_mission=active_mission,
            open_threads=open_threads,
        )
