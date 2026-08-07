"""Free-text translator: map player intent onto engine-enumerated candidates (P5).

ADR A3 — candidate-constrained translation. The engine enumerates the legal
candidates (the ``ChoicePointView``'s options); the LLM may only pick one.
The proposal passes a heuristic compliance gate and is recorded via
``RecordProposalCommand`` (ADR A2/A10) — the LLM never mutates state.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, create_model
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import UsageLimits

from src.engine.lifepath_choices import ChoicePointView
from src.llm.adapter import AdapterConfig
from src.llm.prompts import TRANSLATOR_SYSTEM_PROMPT, build_translator_prompt

logger = logging.getLogger(__name__)

#: Prompt contract version for translator proposals (P5.T1, ADR A9).
TRANSLATOR_PROMPT_VERSION = "translator.v1"


class TranslationRecord(BaseModel):
    """Recorded free-text translation proposal (P5.T1).

    Master-locked shape plus the additive ``rejection_reason`` field (see
    part-5 Changelog): on a rejection it carries the gate reason for the UI
    while ``rationale`` preserves the model's own words.
    """

    choice_id: str
    text: str
    selected_option_id: str | None
    rationale: str
    context_hash: str
    validation: str  # "passed" | "rejected_no_match" | "rejected_invalid"
    rejection_reason: str = ""


def context_hash_for(choice: ChoicePointView) -> str:
    """Fingerprint the exact candidate list the model saw (P5.T1).

    A recorded proposal is auditable against the precise options on offer:
    same options → same hash; any label/preview/dimmed change → new hash.
    """
    canonical = json.dumps(choice.model_dump(), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Candidate → controller dispatch resolution (P5.T3, ADR A3).
# ---------------------------------------------------------------------------

#: Static option ids handled by ``LifepathController.apply_choice``
#: (src/game/lifepath.py:887-1001). Drift-guarded by TestDispatchIdFor.
_STATIC_DISPATCH_IDS: frozenset[str] = frozenset(
    {
        "roll_pool",
        "fallback_retry",
        "fallback_draft",
        "fallback_drifter",
        "career_change_new",
        "career_change_muster",
        "begin_term",
        "commission_attempt",
        "commission_decline",
        "advancement_attempt",
        "advancement_decline",
        "roll_aging",
        "roll_mishap",
        "crisis_pay",
        "crisis_scar",
        "reenlist_continue",
        "reenlist_muster",
        "claim_cash",
        "claim_material",
        "begin_adventure",
        "auto_advance",
    }
)

#: Prefix-dispatched option ids (``apply_choice`` routes via ``startswith``).
_DISPATCH_PREFIXES: tuple[str, ...] = (
    "assign:",
    "bg_skill:",
    "career:",
    "skill_table:",
    "aging_stat:",
    "injury_stat:",
)


def dispatch_id_for(option_id: str) -> str | None:
    """Resolve an option_id to its controller dispatch key (P5.T3).

    Returns the exact id for static keys, the matched prefix for templated
    keys, or ``None`` when no ``LifepathController.apply_choice`` branch would
    handle it — the hard dispatch gate (b) of :meth:`Translator.propose`.
    """
    if option_id in _STATIC_DISPATCH_IDS:
        return option_id
    for prefix in _DISPATCH_PREFIXES:
        if option_id.startswith(prefix) and option_id != prefix:
            return prefix
    return None


# ---------------------------------------------------------------------------
# Translator (P5.T4, ADR A3).
# ---------------------------------------------------------------------------


class Translator:
    """Candidate-constrained free-text translator (P5.T4, ADR A3).

    ``propose`` runs a per-call agent whose output schema only admits the
    enumerated candidate ids, then applies a heuristic compliance gate AFTER
    parse:

    (a) selected id must be a non-dimmed candidate              (hard)
    (b) ``dispatch_id_for(selected)`` must resolve              (hard)
    (c) rationale must be non-empty and cite at least one       (soft — failure
        candidate label/preview string                          still rejects)

    Returns a :class:`TranslationRecord`; never raises (ADR A1: exhaustion,
    provider errors, and missing configuration all yield rejected records).
    """

    def __init__(
        self,
        config: AdapterConfig | None = None,
        *,
        test_model: TestModel | FunctionModel | None = None,
    ) -> None:
        self.config = config or AdapterConfig()
        self._test_model = test_model

    @property
    def llm_configured(self) -> bool:
        return self._test_model is not None or self.config.model is not None

    def _usage_limits(self) -> UsageLimits:
        kwargs: dict[str, Any] = {"request_limit": self.config.request_limit}
        if self.config.token_limit is not None:
            kwargs["total_tokens_limit"] = self.config.token_limit
        return UsageLimits(**kwargs)

    @staticmethod
    def _selection_model(candidate_ids: list[str]) -> type[BaseModel]:
        """Per-call output model: selected id is ``Literal[None, *ids]`` (P5.T4).

        Membership failures become pydantic validation errors naming every
        valid id, surfaced to the retry prompt — unlike the scene-side
        post-call check (adapter.py:901-905), which exhausts immediately.
        Dimmed ids stay in the schema so gate (a) rejects them post-parse.
        """
        return create_model(
            "TranslationSelection",
            selected_option_id=(Literal[None, *candidate_ids], ...),
            rationale=(str, ...),
        )

    def _build_agent(self, selection_model: type[BaseModel]) -> Agent:
        is_test = self._test_model is not None
        model: Any = self._test_model if is_test else self.config.model
        return Agent(
            model,
            output_type=selection_model,
            system_prompt=TRANSLATOR_SYSTEM_PROMPT,
            retries=0,  # Translator owns the retry loop (adapter pattern).
            defer_model_check=not is_test,
        )

    async def _run_agent(self, agent: Agent, prompt: str) -> Any:
        """Manual retry loop mirroring ``LLMAdapter._run_agent`` (P5.T4).

        Feeds the validation *cause* (which lists the valid ids) back into
        the retry prompt; raises the last exception on exhaustion.
        """
        total = self.config.max_retries + 1
        full_prompt = prompt
        last_exc: Exception | None = None
        for _attempt in range(1, total + 1):
            try:
                return await agent.run(full_prompt, usage_limits=self._usage_limits())
            except (ModelRetry, UnexpectedModelBehavior) as exc:
                last_exc = exc
                if _attempt < total:
                    reason = exc.__cause__ or exc
                    full_prompt = (
                        f"{full_prompt}\n\n"
                        f"Your previous response was rejected: {reason}. "
                        f"Please try again, addressing this feedback."
                    )
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    async def propose(
        self,
        text: str,
        choice: ChoicePointView,
        rules_summary: str,
    ) -> TranslationRecord:
        """Translate player free text into a recorded candidate proposal (P5.T4)."""
        base: dict[str, Any] = {
            "choice_id": choice.choice_id,
            "text": text,
            "context_hash": context_hash_for(choice),
        }
        if not choice.allows_freetext:
            return TranslationRecord(
                **base,
                selected_option_id=None,
                rationale="",
                validation="rejected_invalid",
                rejection_reason="this decision does not accept free-text input",
            )
        if not self.llm_configured:
            return TranslationRecord(
                **base,
                selected_option_id=None,
                rationale="",
                validation="rejected_no_match",
                rejection_reason="translator unavailable: no LLM configured",
            )
        candidate_ids = [o.option_id for o in choice.options]
        agent = self._build_agent(self._selection_model(candidate_ids))
        prompt = build_translator_prompt(text, choice, rules_summary)
        try:
            result = await self._run_agent(agent, prompt)
        except Exception as exc:
            logger.warning("translator failed/exhausted, rejecting proposal: %s", exc)
            return TranslationRecord(
                **base,
                selected_option_id=None,
                rationale="",
                validation="rejected_no_match",
                rejection_reason="translation failed or retries exhausted",
            )
        return self._gate(result.output.selected_option_id, result.output.rationale, choice, base)

    @staticmethod
    def _gate(
        selected_id: str | None,
        rationale: str,
        choice: ChoicePointView,
        base: dict[str, Any],
    ) -> TranslationRecord:
        """Heuristic compliance gate applied AFTER parse (P5.T4, ADR A3)."""
        if selected_id is None:
            return TranslationRecord(
                **base,
                selected_option_id=None,
                rationale=rationale.strip(),
                validation="rejected_no_match",
            )
        option = next(o for o in choice.options if o.option_id == selected_id)
        if option.dimmed:
            return TranslationRecord(
                **base,
                selected_option_id=selected_id,
                rationale=rationale.strip(),
                validation="rejected_invalid",
                rejection_reason=(
                    f"option '{selected_id}' is not selectable "
                    f"({option.requirement or 'currently unavailable'})"
                ),
            )
        if dispatch_id_for(selected_id) is None:
            return TranslationRecord(
                **base,
                selected_option_id=selected_id,
                rationale=rationale.strip(),
                validation="rejected_invalid",
                rejection_reason=f"no engine command path exists for '{selected_id}'",
            )
        clean = rationale.strip()
        citations = [
            s.strip() for o in choice.options for s in [o.label, *o.preview] if len(s.strip()) >= 3
        ]
        if not clean or not any(s.lower() in clean.lower() for s in citations):
            return TranslationRecord(
                **base,
                selected_option_id=selected_id,
                rationale=clean,
                validation="rejected_invalid",
                rejection_reason="rationale does not cite any candidate label or preview mechanic",
            )
        return TranslationRecord(
            **base, selected_option_id=selected_id, rationale=clean, validation="passed"
        )
