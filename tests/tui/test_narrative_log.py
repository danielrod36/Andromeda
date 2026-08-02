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


# ---------------------------------------------------------------------------
# U2 / TUI-6: anchor-aware scroll, bounded log, extended capture.
# ---------------------------------------------------------------------------


class TestAnchorAwareScroll:
    """U2/TUI-6: auto-scroll gating and drifted indicator."""

    def test_max_lines_default_set(self):
        """Widget starts with max_lines bounded to DEFAULT_MAX_LINES."""
        from src.tui.widgets.narrative_log import DEFAULT_MAX_LINES

        log = NarrativeLogWidget()
        assert log.max_lines == DEFAULT_MAX_LINES

    def test_max_lines_custom(self):
        """max_lines can be overridden."""
        log = NarrativeLogWidget(max_lines=50)
        assert log.max_lines == 50

    def test_auto_scroll_starts_true(self):
        """Widget starts anchored (auto_scroll=True)."""
        log = NarrativeLogWidget()
        assert log.auto_scroll is True

    def test_drifted_starts_false(self):
        """Widget starts not drifted."""
        log = NarrativeLogWidget()
        assert log.drifted is False


class TestExtendedCapture:
    """U2/TUI-6: every write method captures source text into captured_lines."""

    def test_add_section_captures(self):
        """add_section captures its title (not markup) into captured_lines."""
        log = NarrativeLogWidget()
        log.add_section("Mission Briefing")
        assert "Mission Briefing" in log.captured_lines

    def test_add_roll_captures(self):
        """add_roll captures a plain-text summary (not markup)."""
        log = NarrativeLogWidget()
        log.add_roll("Survival", "2D6(4+3)", 7, 1, 8, True, "Servicable")
        assert any("Survival" in line for line in log.captured_lines)
        assert all("bold" not in line for line in log.captured_lines if "Survival" in line)

    def test_add_separator_captures(self):
        """add_separator captures a plain-text representation."""
        log = NarrativeLogWidget()
        log.add_separator("Chapter 2")
        assert any("Chapter 2" in line for line in log.captured_lines)

    def test_add_separator_no_label_captures(self):
        """add_separator without label captures a plain divider."""
        log = NarrativeLogWidget()
        log.add_separator()
        assert len(log.captured_lines) == 1

    def test_add_paragraph_captures(self):
        """add_paragraph captures the text and a trailing blank line."""
        log = NarrativeLogWidget()
        log.add_paragraph("The starport hums with activity.")
        assert "The starport hums with activity." in log.captured_lines

    def test_add_result_captures(self):
        """add_result captures the source text (not color markup)."""
        log = NarrativeLogWidget()
        log.add_result("Guards alarmed", success=False)
        assert "Guards alarmed" in log.captured_lines
        assert all("red" not in line for line in log.captured_lines)

    def test_all_write_methods_capture(self):
        """Every public write method appends to captured_lines (U2 goal)."""
        log = NarrativeLogWidget()
        before = len(log.captured_lines)
        log.add_line("line")
        log.add_engine_receipt("2D6 = 7")
        log.add_separator("sep")
        log.add_rewind_divider("scene start")
        log.add_section("section")
        log.add_roll("Roll", "2D6(1+2)", 3, 0, 8, False)
        log.add_paragraph("para")
        log.add_result("result")
        after = len(log.captured_lines)
        # Each method should have captured at least one line.
        assert after > before + 7  # add_section and add_paragraph write extras


class TestCaptureIntegrityUnderTrimming:
    """U2: captured_lines retains everything even when max_lines trims display."""

    def test_captured_lines_exceeds_max_lines(self):
        """captured_lines retains all writes even when max_lines trims rendering."""
        log = NarrativeLogWidget(max_lines=5)
        for i in range(20):
            log.add_line(f"Line {i}")
        # captured_lines has everything; max_lines only bounds rendering.
        assert len(log.captured_lines) == 20
        assert log.captured_lines[0] == "Line 0"
        assert log.captured_lines[-1] == "Line 19"
