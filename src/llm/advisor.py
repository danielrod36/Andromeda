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

from pydantic import BaseModel

from src.engine.lifepath_choices import ChoicePointView

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
