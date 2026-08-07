"""The Advisor — recorded, reasoned, reproducible choice suggestions (P4).

ADR A2: advisor output is *recorded, never applied*. The record IS the
reproducibility guarantee — it carries a ``context_hash`` over the exact
inputs (``choice.model_dump_json()`` + ``rules_summary``) plus ``model_id``
and ``prompt_version``, and enters the event log as the payload of
``RecordAdviceCommand`` (Part 2). Replay re-applies the recorded bytes and
never re-calls the LLM.

The LLM layer is strictly advisory: it selects among engine-enumerated
candidates (ADR A3) and never mutates state.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.usage import UsageLimits

from src.engine.lifepath_choices import ChoiceOptionView, ChoicePointView
from src.llm.prompts import ADVISOR_SYSTEM_PROMPT, build_advisor_prompt

logger = logging.getLogger(__name__)

#: Version tag stamped on every record; bump when the advisor prompt or
#: output contract changes so replays can identify stale records.
ADVISOR_PROMPT_VERSION = "advisor.v1"


class AlternativeConsidered(BaseModel):
    """A runner-up option the advisor weighed and rejected (P4.T1)."""

    option_id: str
    why_not: str


class SuggestionRecord(BaseModel):
    """The recorded output of one advisor turn (P4.T1, ADR A2).

    ``choice_id``/``selected_option_id``/``rationale``/``alternatives`` come
    from the model; ``context_hash``/``model_id``/``prompt_version`` are
    *stamped by the advisor* after the run (the model cannot know them), so
    they default to ``""`` here and both Advisor and HeuristicAdvisor always
    overwrite them via ``model_copy(update=...)``.
    """

    choice_id: str
    selected_option_id: str
    rationale: str
    alternatives: list[AlternativeConsidered] = []
    context_hash: str = ""
    model_id: str = ""
    prompt_version: str = ""


def advisor_context_hash(choice: ChoicePointView, rules_summary: str) -> str:
    """sha256 of ``choice.model_dump_json()`` + ``rules_summary`` (P4.T1).

    Pure and deterministic: same choice view and digest string, same hash.
    """
    digest = hashlib.sha256()
    digest.update(choice.model_dump_json().encode("utf-8"))
    digest.update(rules_summary.encode("utf-8"))
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# LLM Advisor (P4.T3, ADR A2/A9).
# ---------------------------------------------------------------------------


@dataclass
class AdvisorConfig:
    """Configuration for the LLM Advisor (P4.T3). Mirrors AdapterConfig."""

    model: str | None = None
    max_retries: int = 3
    request_limit: int = 5
    token_limit: int | None = None
    request_timeout: float | None = None


def _validate_selection(record: SuggestionRecord, valid_ids: list[str]) -> None:
    """Post-call candidate check (P4.T3, ADR A3).

    Mirrors ``classify_freetext``'s ``valid_skill_ids`` gate: candidate
    membership can't live in a field_validator because the valid set is
    per-call. Raises ``ModelRetry`` listing the valid ids to feed the
    retry loop.
    """
    if record.selected_option_id not in valid_ids:
        raise ModelRetry(
            f"selected_option_id '{record.selected_option_id}' is not an available option. "
            f"Valid option_ids: {valid_ids}."
        )


class Advisor:
    """LLM advisor producing recorded suggestions (P4.T3, ADR A2/A9).

    Retry semantics mirror ``LLMAdapter._run_agent``: the agent is built
    with ``retries=0`` and the advisor owns the loop (``max_retries + 1``
    attempts, rejection reason appended to the prompt). Never raises —
    exhaustion or provider failure returns ``None`` and the caller reports
    advice as unavailable (ADR A1).
    """

    def __init__(
        self, config: AdvisorConfig | None = None, *, test_model: Any | None = None
    ) -> None:
        self.config = config or AdvisorConfig()
        self._agent: Agent[None, SuggestionRecord] | None = None
        self._model_id = "none"
        if test_model is not None or self.config.model is not None:
            model: Any = test_model if test_model is not None else self.config.model
            self._model_id = (
                getattr(test_model, "model_name", None) or self.config.model or "unknown"
            )
            self._agent = Agent(
                model,
                output_type=SuggestionRecord,
                system_prompt=ADVISOR_SYSTEM_PROMPT,
                retries=0,  # Advisor owns the retry loop (mirrors LLMAdapter).
                defer_model_check=test_model is None,
            )

    @property
    def advisor_available(self) -> bool:
        """True if an LLM model (real or test) is configured."""
        return self._agent is not None

    async def suggest(self, choice: ChoicePointView, rules_summary: str) -> SuggestionRecord | None:
        """Suggest one option for the choice point; ``None`` when unavailable.

        The record is stamped post-run: ``choice_id``, ``context_hash``,
        ``model_id``, and ``prompt_version`` always overwrite the model's own
        output — the LLM advises on *content*, the advisor owns *provenance*.
        """
        if self._agent is None:
            return None
        prompt = build_advisor_prompt(choice, rules_summary)
        valid_ids = [o.option_id for o in choice.options if not o.dimmed]
        try:
            record = await self._run_with_retries(prompt, valid_ids)
        except Exception as exc:
            logger.warning("Advisor failed; advice unavailable: %s", exc)
            return None
        return record.model_copy(
            update={
                "choice_id": choice.choice_id,
                "context_hash": advisor_context_hash(choice, rules_summary),
                "model_id": self._model_id,
                "prompt_version": ADVISOR_PROMPT_VERSION,
            }
        )

    async def _run_with_retries(self, prompt: str, valid_ids: list[str]) -> SuggestionRecord:
        """Manual retry loop mirroring ``LLMAdapter._run_agent`` (P4.T3)."""
        total = self.config.max_retries + 1
        full_prompt = prompt
        last_exc: Exception | None = None
        for attempt in range(1, total + 1):
            try:
                result = await self._agent.run(
                    full_prompt,
                    usage_limits=UsageLimits(request_limit=self.config.request_limit),
                )
                _validate_selection(result.output, valid_ids)
                return result.output
            except (ModelRetry, UnexpectedModelBehavior) as exc:
                last_exc = exc
                if attempt < total:
                    full_prompt = (
                        f"{full_prompt}\n\n"
                        f"Your previous response was rejected: {exc}. "
                        f"Please try again, addressing this feedback."
                    )
                    continue
                raise
        raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# HeuristicAdvisor — deterministic offline path (P4.T4, ADR A11).
# ---------------------------------------------------------------------------

_PCT_RE = re.compile(r"(\d+)%")


def _success_pct(option: ChoiceOptionView) -> int:
    """Success probability parsed from an odds_line (P4.T4).

    Classic lines (``DM +1 vs 8 · 72% Favorable``) carry one percentage.
    Narrative lines (``17% strong / 42% weak / 42% miss``) count strong +
    weak as success. No odds_line (or no percentage) sorts as 0%.
    """
    if not option.odds_line:
        return 0
    pcts = [int(m) for m in _PCT_RE.findall(option.odds_line)]
    if not pcts:
        return 0
    if "strong" in option.odds_line and len(pcts) >= 2:
        return pcts[0] + pcts[1]
    return pcts[0]


def _skill_mentions(option: ChoiceOptionView) -> int:
    """Count preview lines mentioning skill gains (tie-breaker, P4.T4)."""
    return sum(1 for line in option.preview if "skill" in line.lower())


class HeuristicAdvisor:
    """Deterministic offline advisor (P4.T4, ADR A11).

    Picks the available option with the highest parsed success probability;
    ties break toward more skill mentions in the preview, then toward list
    order (stable). Pure: no clocks, no RNG, same input → same record.
    """

    model_id = "heuristic.v1"

    async def suggest(self, choice: ChoicePointView, rules_summary: str) -> SuggestionRecord | None:
        """Pick the highest-odds available option with a templated rationale.

        Returns ``None`` when every option is dimmed (UNAVAILABLE means
        unavailable), matching the LLM ``Advisor`` behavior.
        """
        candidates = [o for o in choice.options if not o.dimmed]
        if not candidates:
            return None
        scored = sorted(
            enumerate(candidates),
            key=lambda t: (_success_pct(t[1]), _skill_mentions(t[1]), -t[0]),
            reverse=True,
        )
        best = scored[0][1]
        best_pct, best_skills = _success_pct(best), _skill_mentions(best)

        if best.odds_line:
            rationale = f'Best odds: {best_pct}% ("{best.odds_line}").'
        else:
            rationale = "Selected on preview content (no odds line)."
        if best_skills:
            rationale += f" Preview lists {best_skills} skill-related gain(s)."

        alternatives: list[AlternativeConsidered] = []
        for _i, opt in scored[1:3]:
            pct, skills = _success_pct(opt), _skill_mentions(opt)
            if pct < best_pct:
                why = f"Lower success odds ({pct}%)."
            elif skills < best_skills:
                why = "Fewer skill gains in preview."
            else:
                why = "Equal odds and skill gains; listed later."
            alternatives.append(AlternativeConsidered(option_id=opt.option_id, why_not=why))
        if alternatives:
            rationale += f" Alternatives: {', '.join(a.option_id for a in alternatives)}."

        return SuggestionRecord(
            choice_id=choice.choice_id,
            selected_option_id=best.option_id,
            rationale=rationale,
            alternatives=alternatives,
            context_hash=advisor_context_hash(choice, rules_summary),
            model_id=self.model_id,
            prompt_version=ADVISOR_PROMPT_VERSION,
        )
