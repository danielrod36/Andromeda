"""Tests for NarrativeLogWidget rendering helpers (R16, AE3).

Covers the rewind divider (Phase 1 #3 / TUI-4) and the underlying-text capture
(research pitfall: TUI word-wrapping breaks terminal scrollback — retain the
source string, not just rendered rows).
"""

from __future__ import annotations

from src.tui.widgets.narrative_log import NarrativeLogWidget


def test_captured_lines_records_underlying_text():
    """add_line appends the source string to captured_lines (scrollback integrity)."""
    log = NarrativeLogWidget()
    log.add_line("The starport hums.")
    log.add_line("[green]SUCCESS[/green]")
    assert log.captured_lines == ["The starport hums.", "[green]SUCCESS[/green]"]


def test_add_rewind_divider_emits_prominent_marker():
    """A checkpoint rewind produces a distinct, non-dim divider (TUI-4).

    The plan's interstitial decision: 'Checkpoint shows a rewind notice marking
    removed narration (divider line "rewound to scene start") before restoring.'
    A dim add_separator is too subtle — the rewind must read as a hard boundary.
    """
    from src.tui.widgets.narrative_log import rewind_divider_text

    log = NarrativeLogWidget()
    log.add_rewind_divider("scene start")
    assert len(log.captured_lines) == 1
    line = log.captured_lines[0]
    assert "rewound" in line.lower()
    assert "scene start" in line.lower()
    # captured_lines now holds plain source text (no markup); the prominent
    # amber/yellow styling is verified on the rendered markup instead.
    assert "yellow" not in line
    assert "yellow" in rewind_divider_text()


def test_add_rewind_divider_default_label():
    log = NarrativeLogWidget()
    log.add_rewind_divider()
    assert "rewound to scene start" in log.captured_lines[0].lower()


# ---------------------------------------------------------------------------
# Phase 1 #4: engine/LLM provenance coloring — engine facts styled distinctly
# from LLM prose so the trust boundary (engine = fact, LLM = flavor) is visible.
# Sources: NovelAI editor highlighting, Cogmind per-type colors, Claude.ai pills.
# ---------------------------------------------------------------------------


def test_engine_receipt_text_is_bold_and_marked():
    """The styling helper wraps an engine fact in bold + a provenance glyph."""
    from src.tui.widgets.narrative_log import engine_receipt_text

    out = engine_receipt_text("2D6 [4,2] = 6  DM +0 → 6 vs 8 — Failure")
    assert "2D6" in out  # source preserved
    assert "bold" in out  # visually distinct from prose
    # A glyph/tag prefix signals 'this is engine-decided' at a glance.
    assert out.startswith("[bold")


def test_add_engine_receipt_captures_source_not_markup():
    """The widget method writes styled output but captures the source string."""
    log = NarrativeLogWidget()
    log.add_engine_receipt("2D6 [4,2] = 6 vs 8 — Failure")
    assert log.captured_lines == ["2D6 [4,2] = 6 vs 8 — Failure"]


def test_rewind_divider_text_is_bold_and_yellow():
    """The styling helper wraps the rewind boundary in bold + amber styling."""
    from src.tui.widgets.narrative_log import rewind_divider_text

    out = rewind_divider_text("scene start")
    assert "REWOUND TO SCENE START" in out  # source preserved
    assert "bold" in out  # visually distinct from prose
    assert "yellow" in out  # amber, not the dim separator styling
    assert out.startswith("[bold")


def test_add_rewind_divider_captures_source_not_markup():
    """The widget method writes styled output but captures the source string."""
    log = NarrativeLogWidget()
    log.add_rewind_divider("scene start")
    assert log.captured_lines == ["REWOUND TO SCENE START"]
