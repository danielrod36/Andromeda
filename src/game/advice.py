"""Advisor glue for the game layer (P4.T5, ADR A2/A10).

``record_advice`` is the single path by which a suggestion enters canonical
state: through the funnel, as the payload of ``RecordAdviceCommand``. The
record is never *applied* — confirming a suggestion is a separate step (the
Part 6 ``choose()`` path) that applies the underlying game Command with
``origin="advisor"``.

ADR A1: this module has **zero runtime ``src.llm`` imports** — the
``SuggestionRecord`` annotation is ``TYPE_CHECKING``-only and the record is
consumed via ``model_dump()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.engine.audit import Event
from src.engine.commands import Engine, RecordAdviceCommand

if TYPE_CHECKING:
    from src.llm.advisor import SuggestionRecord


def record_advice(engine: Engine, record: SuggestionRecord) -> Event:
    """Append a suggestion to the event log via the funnel (P4.T5, ADR A2).

    The record IS the advice: the command payload is ``record.model_dump()``
    and the event kind is SYSTEM, so replay re-applies the same bytes and
    never re-calls the LLM. State is otherwise untouched.

    Provenance (ADR A10): when the player later confirms this suggestion, the
    chooser applies the underlying game Command with ``origin="advisor"``,
    surfaced in that event's ``changes["origin"]``; the link between this
    record and the applied choice is the shared ``choice_id``.
    """
    return engine.apply(RecordAdviceCommand(payload=record.model_dump()))
