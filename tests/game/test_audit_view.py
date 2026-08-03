"""Tests for the audit viewer filter model and view assembly (U13, R15).

Covers:
- Filter by EventKind returns matching events in sequence order.
- Filter by RNG stream returns only events from that stream.
- Filter by sequence range.
- REWIND_APPLIED rows render as boundaries with abandoned counts.
- Long logs paginate correctly.
- filter_from_params round-trips query-string values.
"""

from __future__ import annotations

from src.engine.audit import Event, EventKind
from src.engine.dice import RollResult
from src.engine.state import GameState
from src.game.audit_view import (
    AuditFilter,
    AuditRow,
    build_audit_view,
    filter_from_params,
)


def _make_event(
    seq: int,
    kind: EventKind = EventKind.STATE_CHANGE,
    command_type: str = "test_cmd",
    description: str = "test event",
    roll: RollResult | None = None,
    changes: dict | None = None,
) -> Event:
    return Event(
        seq=seq,
        kind=kind,
        command_type=command_type,
        description=description,
        roll=roll,
        changes=changes or {},
    )


def _make_roll(stream: str = "combat", values: list[int] | None = None) -> RollResult:
    vals = values or [3, 4]
    return RollResult(
        stream=stream,
        ndice=len(vals),
        sides=6,
        modifiers=0,
        rolls=vals,
        total=sum(vals),
    )


def _make_state_with_events(events: list[Event]) -> GameState:
    state = GameState.new(seed=1)
    state.events = events
    return state


class TestAuditFilter:
    """The filter model (U13)."""

    def test_no_filter_returns_all(self):
        events = [_make_event(0), _make_event(1), _make_event(2)]
        flt = AuditFilter()
        result = [e for e in events if flt.matches(e)]
        assert len(result) == 3

    def test_filter_by_kind(self):
        events = [
            _make_event(0, kind=EventKind.ROLL),
            _make_event(1, kind=EventKind.STATE_CHANGE),
            _make_event(2, kind=EventKind.ROLL),
            _make_event(3, kind=EventKind.SYSTEM),
        ]
        flt = AuditFilter(kinds={"roll"})
        result = [e for e in events if flt.matches(e)]
        assert len(result) == 2
        assert all(e.kind == EventKind.ROLL for e in result)

    def test_filter_by_multiple_kinds(self):
        events = [
            _make_event(0, kind=EventKind.ROLL),
            _make_event(1, kind=EventKind.STATE_CHANGE),
            _make_event(2, kind=EventKind.SYSTEM),
        ]
        flt = AuditFilter(kinds={"roll", "system"})
        result = [e for e in events if flt.matches(e)]
        assert len(result) == 2

    def test_filter_by_stream(self):
        events = [
            _make_event(0, kind=EventKind.ROLL, roll=_make_roll("combat")),
            _make_event(1, kind=EventKind.ROLL, roll=_make_roll("oracle")),
            _make_event(2, kind=EventKind.ROLL, roll=_make_roll("combat")),
        ]
        flt = AuditFilter(stream="combat")
        result = [e for e in events if flt.matches(e)]
        assert len(result) == 2
        assert all(e.roll.stream == "combat" for e in result)

    def test_filter_stream_excludes_non_roll_events(self):
        """Stream filter excludes events without a roll."""
        events = [
            _make_event(0, kind=EventKind.ROLL, roll=_make_roll("combat")),
            _make_event(1, kind=EventKind.STATE_CHANGE),
        ]
        flt = AuditFilter(stream="combat")
        result = [e for e in events if flt.matches(e)]
        assert len(result) == 1

    def test_filter_by_seq_range(self):
        events = [_make_event(i) for i in range(10)]
        flt = AuditFilter(seq_min=3, seq_max=6)
        result = [e for e in events if flt.matches(e)]
        assert len(result) == 4
        assert result[0].seq == 3
        assert result[-1].seq == 6

    def test_combined_filters(self):
        events = [
            _make_event(0, kind=EventKind.ROLL, roll=_make_roll("combat")),
            _make_event(1, kind=EventKind.ROLL, roll=_make_roll("oracle")),
            _make_event(2, kind=EventKind.ROLL, roll=_make_roll("combat")),
            _make_event(3, kind=EventKind.STATE_CHANGE, roll=_make_roll("combat")),
        ]
        flt = AuditFilter(kinds={"roll"}, stream="combat")
        result = [e for e in events if flt.matches(e)]
        assert len(result) == 2


class TestBuildAuditView:
    """View assembly with pagination (U13)."""

    def test_basic_view(self):
        events = [_make_event(i) for i in range(5)]
        state = _make_state_with_events(events)
        view = build_audit_view(state)
        assert len(view.rows) == 5
        assert view.total_events == 5
        assert view.filtered_count == 5
        assert view.page == 1
        assert view.total_pages == 1

    def test_preserves_sequence_order(self):
        events = [
            _make_event(5),
            _make_event(2),
            _make_event(8),
        ]
        state = _make_state_with_events(events)
        view = build_audit_view(state)
        # Events are returned in log order (as stored), not sorted.
        assert view.rows[0].seq == 5
        assert view.rows[1].seq == 2
        assert view.rows[2].seq == 8

    def test_pagination(self):
        events = [_make_event(i) for i in range(120)]
        state = _make_state_with_events(events)
        view = build_audit_view(state, per_page=50, page=1)
        assert len(view.rows) == 50
        assert view.total_pages == 3
        assert view.page == 1

    def test_pagination_page_2(self):
        events = [_make_event(i) for i in range(120)]
        state = _make_state_with_events(events)
        view = build_audit_view(state, per_page=50, page=2)
        assert len(view.rows) == 50
        assert view.page == 2
        assert view.rows[0].seq == 50

    def test_pagination_last_page(self):
        events = [_make_event(i) for i in range(120)]
        state = _make_state_with_events(events)
        view = build_audit_view(state, per_page=50, page=3)
        assert len(view.rows) == 20
        assert view.page == 3

    def test_page_out_of_range_clamped(self):
        events = [_make_event(i) for i in range(10)]
        state = _make_state_with_events(events)
        view = build_audit_view(state, per_page=5, page=99)
        assert view.page == 2  # Clamped to last page.

    def test_filtered_view(self):
        events = [
            _make_event(0, kind=EventKind.ROLL, roll=_make_roll("combat")),
            _make_event(1, kind=EventKind.STATE_CHANGE),
            _make_event(2, kind=EventKind.ROLL, roll=_make_roll("oracle")),
        ]
        state = _make_state_with_events(events)
        flt = AuditFilter(kinds={"roll"})
        view = build_audit_view(state, audit_filter=flt)
        assert view.filtered_count == 2
        assert all(r.kind == "roll" for r in view.rows)

    def test_empty_log(self):
        state = GameState.new(seed=1)
        view = build_audit_view(state)
        assert len(view.rows) == 0
        assert view.total_events == 0


class TestAuditRow:
    """Row model rendering fields (U13)."""

    def test_roll_row_has_dice_str(self):
        event = _make_event(
            0,
            kind=EventKind.ROLL,
            roll=RollResult(stream="combat", ndice=2, sides=6, modifiers=1, rolls=[3, 5], total=9),
        )
        state = _make_state_with_events([event])
        view = build_audit_view(state)
        row = view.rows[0]
        assert row.stream == "combat"
        assert "3" in row.dice_str
        assert "5" in row.dice_str
        assert "+1" in row.dice_str
        assert row.total == 9

    def test_roll_row_no_modifier(self):
        event = _make_event(
            0,
            kind=EventKind.ROLL,
            roll=RollResult(stream="oracle", ndice=2, sides=6, modifiers=0, rolls=[2, 4], total=6),
        )
        state = _make_state_with_events([event])
        view = build_audit_view(state)
        row = view.rows[0]
        assert row.dice_str == "2+4"

    def test_rewind_boundary_row(self):
        event = _make_event(
            0,
            kind=EventKind.REWIND_APPLIED,
            changes={"abandoned_branch_events": 7, "rewound_to_seq": 12},
        )
        state = _make_state_with_events([event])
        view = build_audit_view(state)
        row = view.rows[0]
        assert row.is_rewind_boundary is True
        assert row.abandoned_count == 7
        assert row.rewound_to_seq == 12

    def test_kind_class_css_mapping(self):
        row = AuditRow(seq=0, kind="roll", command_type="", description="")
        assert row.kind_class == "kind-roll"
        row = AuditRow(seq=0, kind="rewind_applied", command_type="", description="")
        assert row.kind_class == "kind-rewind"

    def test_has_rewinds_detected(self):
        events = [
            _make_event(0),
            _make_event(1, kind=EventKind.REWIND_APPLIED),
            _make_event(2),
        ]
        state = _make_state_with_events(events)
        view = build_audit_view(state)
        assert view.has_rewinds is True

    def test_has_rewinds_false(self):
        events = [_make_event(0), _make_event(1)]
        state = _make_state_with_events(events)
        view = build_audit_view(state)
        assert view.has_rewinds is False


class TestFilterFromParams:
    """Query-string filter parsing (U13)."""

    def test_empty_params(self):
        flt = filter_from_params()
        assert flt.kinds is None
        assert flt.stream is None
        assert flt.seq_min is None
        assert flt.seq_max is None

    def test_kind_param(self):
        flt = filter_from_params(kind="roll")
        assert flt.kinds == {"roll"}

    def test_multiple_kinds(self):
        flt = filter_from_params(kind="roll,state_change")
        assert flt.kinds == {"roll", "state_change"}

    def test_stream_param(self):
        flt = filter_from_params(stream="combat")
        assert flt.stream == "combat"

    def test_stream_empty_string(self):
        flt = filter_from_params(stream="")
        assert flt.stream is None

    def test_seq_range(self):
        flt = filter_from_params(seq_min="5", seq_max="10")
        assert flt.seq_min == 5
        assert flt.seq_max == 10

    def test_invalid_seq_ignored(self):
        flt = filter_from_params(seq_min="abc")
        assert flt.seq_min is None


class TestRewindBoundaryScenario:
    """REWIND_APPLIED boundaries render as visible markers (U13, R15)."""

    def test_rewind_boundary_in_filtered_view(self):
        events = [
            _make_event(0, kind=EventKind.ROLL, roll=_make_roll("combat")),
            _make_event(1, kind=EventKind.ROLL, roll=_make_roll("combat")),
            _make_event(
                2,
                kind=EventKind.REWIND_APPLIED,
                description="Checkpoint rewind applied.",
                changes={"abandoned_branch_events": 2, "rewound_to_seq": 0},
            ),
            _make_event(3, kind=EventKind.ROLL, roll=_make_roll("combat")),
        ]
        state = _make_state_with_events(events)
        view = build_audit_view(state)
        rewind_rows = [r for r in view.rows if r.is_rewind_boundary]
        assert len(rewind_rows) == 1
        assert rewind_rows[0].abandoned_count == 2
        assert rewind_rows[0].rewound_to_seq == 0

    def test_rewind_boundary_survives_kind_filter(self):
        """REWIND_APPLIED shows even when filtering by state_change."""
        events = [
            _make_event(0, kind=EventKind.ROLL),
            _make_event(1, kind=EventKind.REWIND_APPLIED, changes={"abandoned_branch_events": 1}),
        ]
        state = _make_state_with_events(events)
        flt = AuditFilter(kinds={"rewind_applied"})
        view = build_audit_view(state, audit_filter=flt)
        assert len(view.rows) == 1
        assert view.rows[0].is_rewind_boundary
