"""Audit viewer: filterable event-log overlay (U13, R15).

A neutral filter model over ``state.events`` that powers a player-facing,
read-only audit overlay. Filters by event kind, RNG stream, and sequence
range. REWIND_APPLIED events render as visible boundary markers showing
which events a rewind abandoned.

Read-only by design (research pitfall: no manual annotation). The event
log is the engine's append-only audit trail; this module only reads and
filters it — it never mutates.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

from src.engine.audit import Event, EventKind
from src.engine.state import GameState

#: Default page size for long logs (U13: "Long logs render bounded").
DEFAULT_PAGE_SIZE: int = 50


# ---------------------------------------------------------------------------
# Row model — one rendered event.
# ---------------------------------------------------------------------------


@dataclass
class AuditRow:
    """A single row in the audit overlay (U13).

    Wraps an :class:`Event` with pre-computed display fields so templates
    don't need to inspect ``RollResult`` or ``EventKind`` directly.
    """

    seq: int
    kind: str
    command_type: str
    description: str
    stream: str = ""
    dice_str: str = ""
    total: int | None = None
    changes: dict[str, Any] = field(default_factory=dict)
    is_rewind_boundary: bool = False
    abandoned_count: int = 0
    rewound_to_seq: int | None = None

    @property
    def kind_class(self) -> str:
        """CSS class for color-coding by kind."""
        return {
            "roll": "kind-roll",
            "state_change": "kind-state",
            "system": "kind-system",
            "rewind_applied": "kind-rewind",
        }.get(self.kind, "kind-other")


# ---------------------------------------------------------------------------
# Filter model.
# ---------------------------------------------------------------------------


@dataclass
class AuditFilter:
    """Filter parameters for the audit overlay (U13).

    All fields are optional — ``None`` or empty means "no filter on this
    axis". The filter is pure data so it can be serialized into query
    params and round-tripped.
    """

    kinds: set[str] | None = None  # EventKind values to include.
    stream: str | None = None  # RNG stream name to match.
    seq_min: int | None = None  # Inclusive lower bound on seq.
    seq_max: int | None = None  # Inclusive upper bound on seq.

    def matches(self, event: Event) -> bool:
        """Return True if *event* passes all filter axes."""
        if self.kinds is not None and event.kind.value not in self.kinds:
            return False
        if self.stream is not None and (event.roll is None or event.roll.stream != self.stream):
            return False
        if self.seq_min is not None and event.seq < self.seq_min:
            return False
        return not (self.seq_max is not None and event.seq > self.seq_max)


# ---------------------------------------------------------------------------
# View assembly.
# ---------------------------------------------------------------------------


@dataclass
class AuditView:
    """Paginated, filtered view of the event log (U13).

    Attributes:
        rows: The filtered, paginated :class:`AuditRow` list.
        total_events: Total events in the log (before filtering).
        filtered_count: Events matching the filter (before paging).
        page: Current page number (1-based).
        per_page: Page size.
        total_pages: Total pages after filtering.
        has_rewinds: Whether any REWIND_APPLIED boundary exists.
        filter: The :class:`AuditFilter` applied.
    """

    rows: list[AuditRow] = field(default_factory=list)
    total_events: int = 0
    filtered_count: int = 0
    page: int = 1
    per_page: int = DEFAULT_PAGE_SIZE
    total_pages: int = 1
    has_rewinds: bool = False
    filter: AuditFilter = field(default_factory=AuditFilter)


def _event_to_row(event: Event) -> AuditRow:
    """Convert a single :class:`Event` to an :class:`AuditRow`."""
    row = AuditRow(
        seq=event.seq,
        kind=event.kind.value,
        command_type=event.command_type,
        description=event.description,
        changes=dict(event.changes),
        is_rewind_boundary=(event.kind == EventKind.REWIND_APPLIED),
    )

    if event.roll is not None:
        roll = event.roll
        row.stream = roll.stream
        dice = "+".join(str(d) for d in roll.rolls)
        mod = f"{'+' if roll.modifiers >= 0 else ''}{roll.modifiers}" if roll.modifiers else ""
        row.dice_str = f"{dice}{mod}" if mod else dice
        row.total = roll.total

    if event.kind == EventKind.REWIND_APPLIED:
        row.abandoned_count = event.changes.get("abandoned_branch_events", 0)
        rewound = event.changes.get("rewound_to_seq")
        if rewound is not None:
            row.rewound_to_seq = rewound

    return row


def build_audit_view(
    state: GameState,
    *,
    audit_filter: AuditFilter | None = None,
    page: int = 1,
    per_page: int = DEFAULT_PAGE_SIZE,
) -> AuditView:
    """Build a paginated, filtered audit view from state (U13, R15).

    Args:
        state: The canonical game state.
        audit_filter: Optional filter. ``None`` = no filtering.
        page: 1-based page number.
        per_page: Maximum rows per page.

    Returns:
        :class:`AuditView` with the filtered, paginated rows.
    """
    flt = audit_filter or AuditFilter()
    if per_page < 1:
        per_page = DEFAULT_PAGE_SIZE
    events = state.events

    # Apply filter.
    filtered = [e for e in events if flt.matches(e)]

    # Check for rewind boundaries in the full log.
    has_rewinds = any(e.kind == EventKind.REWIND_APPLIED for e in events)

    # Paginate.
    total_pages = max(1, (len(filtered) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    page_events = filtered[start:end]

    rows = [_event_to_row(e) for e in page_events]

    return AuditView(
        rows=rows,
        total_events=len(events),
        filtered_count=len(filtered),
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        has_rewinds=has_rewinds,
        filter=flt,
    )


# ---------------------------------------------------------------------------
# Convenience: parse filter from query params (for web routes).
# ---------------------------------------------------------------------------


def filter_from_params(
    kind: str | None = None,
    stream: str | None = None,
    seq_min: str | None = None,
    seq_max: str | None = None,
) -> AuditFilter:
    """Build an :class:`AuditFilter` from query-string parameters.

    Empty strings are treated as "no filter". Invalid integers are ignored.
    """
    kinds = None
    if kind:
        kinds = {k.strip() for k in kind.split(",") if k.strip()}

    s = stream.strip() if stream else None
    s = s or None

    mn: int | None = None
    if seq_min:
        with contextlib.suppress(ValueError):
            mn = int(seq_min)

    mx: int | None = None
    if seq_max:
        with contextlib.suppress(ValueError):
            mx = int(seq_max)

    return AuditFilter(kinds=kinds, stream=s, seq_min=mn, seq_max=mx)
