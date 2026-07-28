"""Append-only event log and audit views.

The event log is the engine's single source of truth for "what happened". It is
append-only: the command funnel (:func:`Engine.apply`) is the sole path that
appends entries, and nothing removes or reorders them. The audit log per R4 is a
*view* over this log filtered to roll events — it shares the same storage so
there is one append-only structure, not two.

Each :class:`Event` with ``kind == ROLL`` carries a full :class:`RollResult`
with its inputs (stream, dice, sides, modifiers) and outcome (individual die
values, total), satisfying AE1's inspectability requirement.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel

from src.engine.dice import RollResult


class EventKind(str, Enum):
    """Categories of event log entries.

    ``ROLL`` events are the audit log proper (R4); ``STATE_CHANGE`` and
    ``SYSTEM`` are the non-dice events that share the same append-only log.
    ``REWIND_APPLIED`` marks a Checkpoint rewind boundary so replay tooling
    can skip the abandoned scene branch. Audit views filter to ``ROLL`` only.
    """

    ROLL = "roll"
    STATE_CHANGE = "state_change"
    SYSTEM = "system"
    REWIND_APPLIED = "rewind_applied"


class Event(BaseModel):
    """A single entry in the append-only event log.

    ``seq`` is assigned by :class:`Engine` at append time and is monotonically
    increasing within a campaign. Roll events carry their :class:`RollResult`
    so the audit trail is self-contained.
    """

    seq: int = 0
    kind: EventKind
    command_type: str
    description: str
    # Present when kind == ROLL — the full roll for audit (R4, AE1).
    roll: RollResult | None = None
    # Structured change record for state_change events (field deltas, etc.).
    changes: dict[str, Any] = {}


def audit_rolls(events: list[Event]) -> list[Event]:
    """Return only roll events from the log — the R4 audit view.

    Each returned event has ``.roll`` populated with inputs and outcome, so a
    caller can verify fairness by inspecting stream, dice, modifiers, and result
    for every roll after the fact (AE1).
    """
    return [e for e in events if e.kind == EventKind.ROLL]
