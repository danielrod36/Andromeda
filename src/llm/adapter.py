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
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, field_validator
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import UsageLimits

from src.engine.commands import Engine
from src.engine.lifepath import LifepathResult, TermResult
from src.engine.narration import Narrator
from src.engine.state import GameState
from src.llm.prompts import (
    SYSTEM_PROMPT,
    build_full_lifepath_prompt,
    build_lifepath_prompt,
    build_term_facts,
)
from src.llm.state_view import CuratedView, build_curated_view
from src.llm.tools import TOOL_REGISTRY, ToolDeps

logger = logging.getLogger(__name__)

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
                "Narration prose must be non-empty. "
                "Please write 2-4 sentences of backstory."
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
            raise ModelRetry(
                "Full lifepath narration must be non-empty."
            )
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
    """

    prose: str
    source: str = "llm"
    retries_used: int = 0
    llm_failed: bool = False


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

        if self._test_model is not None or self.config.model is not None:
            self._setup_agents()

    def _setup_agents(self) -> None:
        """Create the Pydantic AI agents for narration."""
        is_test = self._test_model is not None
        model: Any = (
            self._test_model if is_test else self.config.model
        )
        # Defer model validation for real providers so the adapter can be
        # constructed before API keys are available.
        defer = not is_test

        # Per-term narration agent.
        self._agent = Agent(
            model,
            output_type=LifepathNarration,
            system_prompt=SYSTEM_PROMPT,
            deps_type=ToolDeps,
            retries=self.config.max_retries,
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
            retries=self.config.max_retries,
            defer_model_check=defer,
        )
        for tool_func in TOOL_REGISTRY.values():
            self._full_agent.tool(tool_func)

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
    # Term narration.
    # ------------------------------------------------------------------

    async def narrate_term(
        self,
        state: GameState,
        engine: Engine,
        term_result: TermResult,
    ) -> NarrationResult:
        """Narrate a single term's events using the LLM (R11, AE12).

        If no LLM is configured, falls back to template narration.

        Args:
            state: The canonical game state.
            engine: The engine (for tool deps / command funnel).
            term_result: The mechanical result for this term.

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
            result = await self._agent.run(
                prompt,
                deps=deps,
                usage_limits=self._usage_limits(),
            )
            return NarrationResult(
                prose=result.output.prose,
                source="llm",
            )
        except Exception as exc:
            # AE11: LLM failure (invalid output, retry exhaustion) falls back
            # to template narration. State is unchanged.
            logger.warning(
                "LLM narration failed for term %d, falling back to "
                "template: %s",
                term_result.term_number,
                exc,
            )
            return NarrationResult(
                prose=self._narrator.narrate_term(term_result),
                source="template",
                llm_failed=True,
            )

    # ------------------------------------------------------------------
    # Full lifepath narration.
    # ------------------------------------------------------------------

    async def narrate_lifepath(
        self,
        state: GameState,
        engine: Engine,
        lifepath_result: LifepathResult,
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
            result = await self._full_agent.run(
                prompt,
                deps=deps,
                usage_limits=self._usage_limits(),
            )
            return NarrationResult(
                prose=result.output.prose,
                source="llm",
            )
        except Exception as exc:
            logger.warning(
                "LLM full lifepath narration failed, falling back to "
                "template: %s",
                exc,
            )
            lines = self._narrator.narrate_lifepath(lifepath_result)
            return NarrationResult(
                prose="\n".join(lines),
                source="template",
                llm_failed=True,
            )

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

        npcs = [
            n if isinstance(n, NpcSummary) else NpcSummary(**n)
            for n in (scene_npcs or [])
        ]
        return build_curated_view(
            state,
            scene_npcs=npcs,
            active_mission=active_mission,
            open_threads=open_threads,
        )
