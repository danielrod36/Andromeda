"""Narrative log main panel — scrolling RichLog for game narration (R16).

Wraps RichLog with formatting helpers for section headers, separators,
roll results, and paragraph breaks so the log reads as structured prose
rather than a monolith of text.

U2/TUI-6: anchor-aware scrolling stops the log from yanking the player to
the bottom while they re-read during streaming (RichLog issue #6311).
``max_lines`` bounds rendering cost on long sessions; ``captured_lines``
retains the full source-text scrollback regardless of display trimming.
"""

from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import RichLog

#: Cap on rendered lines to bound memory/render cost on long sessions (U2).
#: ``captured_lines`` retains the full source scrollback regardless.
DEFAULT_MAX_LINES = 1000

# ---------------------------------------------------------------------------
# Provenance styling (Phase 1 #4).
#
# The trust boundary made visible: engine-decided facts (dice, DMs, outcomes)
# must never share typography with LLM-narrated prose. Engine receipts are bold
# and glyph-prefixed so the player can scan the scrollback and tell at a glance
# what is mechanical ground truth vs narrative flavor. Inspired by NovelAI's
# editor-highlight-by-origin and Cogmind's per-message-type color schemes.


def engine_receipt_text(text: str) -> str:
    """Wrap an engine-decided fact in bold provenance styling.

    Returns Rich markup. The source ``text`` is embedded verbatim so the
    receipt's numbers are exactly what the engine produced.
    """
    return f"[bold cyan]⚙ {text}[/bold cyan]"


def rewind_divider_text(label: str = "scene start") -> str:
    """Wrap a rewind boundary in prominent provenance styling.

    Returns Rich markup. The divider reads as a hard state boundary, not a
    soft visual break (mirrors :func:`engine_receipt_text` so styling is
    separable from the captured source text).
    """
    return f"[bold yellow]══ REWOUND TO {label.upper()} ══[/bold yellow]"


class NarrativeLogWidget(RichLog):
    """Scrolling narrative log panel.

    Supports PageUp/PageDown and Home/End for scrolling (inherited from
    RichLog's scroll actions, also bound at the screen level).
    Rich markup ([bold], [dim], [green], etc.) is enabled so formatted
    text renders correctly.

    U2/TUI-6: anchor-aware scrolling. When the player is at the bottom
    (anchored), new writes auto-scroll. When they've scrolled up
    (drifted), new writes hold position and the border tints yellow as a
    "new content below — press End" hint. Scrolling back to the bottom
    re-anchors.
    """

    DEFAULT_CSS = """
    NarrativeLogWidget {
        height: 1fr;
        border: round $accent;
        margin: 0;
        padding: 0 1;
        background: $surface;
    }
    /* U2/TUI-6: yellow border when drifted = "new content below". */
    NarrativeLogWidget.drifted {
        border: round $warning;
    }
    """

    #: True when the user has scrolled away from the bottom (U2/TUI-6).
    drifted = reactive(False)

    def __init__(self, *args, **kwargs):
        """Enable Rich markup, word wrapping, anchor-aware auto-scroll, and bounded rendering.

        Args:
            max_lines: Cap on rendered lines (default :data:`DEFAULT_MAX_LINES`).
                ``captured_lines`` retains the full source scrollback regardless.
        """
        kwargs.setdefault("markup", True)
        kwargs.setdefault("wrap", True)
        kwargs.setdefault("auto_scroll", True)
        kwargs.setdefault("max_lines", DEFAULT_MAX_LINES)
        super().__init__(*args, **kwargs)
        # Underlying source text for each beat written to the log. RichLog only
        # retains rendered terminal rows (up to max_lines), so on resize/scrollback
        # the source is lost (research pitfall: TUI word-wrapping breaks scrollback).
        # Keeping the original strings also makes the log assertion-testable.
        self.captured_lines: list[str] = []

    # ------------------------------------------------------------------
    # Anchor-aware scroll logic (U2/TUI-6).
    # ------------------------------------------------------------------

    def watch_scroll_y(self, value: float) -> None:
        """Update drifted state when the scroll position changes (U2/TUI-6).

        At or near the bottom → anchored (drifted=False, auto_scroll=True).
        Away from the bottom → drifted (drifted=True, auto_scroll=False).
        """
        at_bottom = self.max_scroll_y <= 0 or value >= self.max_scroll_y - 0.5
        self.drifted = not at_bottom
        self.auto_scroll = at_bottom

    def watch_drifted(self, drifted: bool) -> None:
        """Toggle the visual hint CSS class (U2/TUI-6)."""
        if drifted:
            self.add_class("drifted")
        else:
            self.remove_class("drifted")

    def scroll_end(self, *args, **kwargs) -> None:
        """Scroll to the bottom and re-anchor (U2/TUI-6).

        Forwards all arguments to the parent ``scroll_end`` (RichLog calls
        it internally with ``animate``, ``immediate``, ``x_axis`` kwargs).
        """
        super().scroll_end(*args, **kwargs)
        self.drifted = False
        self.auto_scroll = True

    def _write_anchored(self, content: str, *, capture: str | None = None) -> None:
        """Write with anchor-aware auto-scroll gating (U2/TUI-6).

        Before each write, checks whether the player is at the bottom. If
        yes, keeps ``auto_scroll=True`` so the new content scrolls into
        view. If no (drifted), sets ``auto_scroll=False`` so the view
        holds position while new content accumulates below.

        Args:
            content: The Rich markup string to render.
            capture: Source text to append to ``captured_lines``. When
                ``None``, the rendered ``content`` itself is captured.
        """
        was_at_bottom = self.max_scroll_y <= 0 or self.scroll_y >= self.max_scroll_y - 0.5
        self.auto_scroll = was_at_bottom
        self.write(content)
        if capture is not None:
            self.captured_lines.append(capture)
        else:
            self.captured_lines.append(content)

    # ------------------------------------------------------------------
    # Public write API — all routes go through _write_anchored (U2).
    # ------------------------------------------------------------------

    def add_line(self, text: str) -> None:
        """Append a line of narrative text to the log."""
        self._write_anchored(text)

    def add_engine_receipt(self, text: str) -> None:
        """Render an engine-decided fact with distinct provenance styling.

        Engine receipts (dice rolls, DMs, outcomes, state changes) are bold and
        glyph-prefixed so the player can distinguish mechanical ground truth
        from LLM-narrated prose at a glance. The source ``text`` (not the
        markup) is captured into :attr:`captured_lines` for scrollback integrity
        and assertions.
        """
        self._write_anchored(engine_receipt_text(text), capture=text)

    def add_lines(self, lines: list[str]) -> None:
        """Append multiple lines of narrative text."""
        for line in lines:
            self.add_line(line)

    def add_separator(self, label: str = "") -> None:
        """Add a visual separator line with an optional label."""
        if label:
            markup = f"[dim]── {label} {'─' * max(1, 50 - len(label))}[/dim]"
        else:
            markup = "[dim]" + "─" * 60 + "[/dim]"
        self._write_anchored(markup, capture=f"── {label}" if label else "─" * 60)

    def add_rewind_divider(self, label: str = "scene start") -> None:
        """Add a prominent rewind boundary for Checkpoint mode (AE3, TUI-4).

        Distinct from :meth:`add_separator` (which is dim): the rewind is a hard
        state boundary, not a soft visual break. Amber/yellow signals
        "engine rewound here" so the player can distinguish the abandoned branch
        below from the replayed scene. Plan interstitial decision: show a rewind
        notice marking removed narration ("rewound to scene start") before
        restoring.

        The source text (not the markup) is captured into
        :attr:`captured_lines` for scrollback integrity and assertions, matching
        :meth:`add_engine_receipt`.
        """
        source = f"REWOUND TO {label.upper()}"
        self._write_anchored(rewind_divider_text(label), capture=source)

    def add_section(self, title: str) -> None:
        """Add a section header."""
        self._write_anchored("", capture="")
        self._write_anchored(f"[bold cyan]{title}[/bold cyan]", capture=title)
        self._write_anchored("", capture="")

    def add_roll(
        self, label: str, dice: str, total: int, dm: int, target: int, success: bool, tier: str = ""
    ) -> None:
        """Add a formatted dice roll result line.

        Example output:
          [Survival] 2D6(4+3)=7 + DM(+1) = 8 vs 8 → [green]SUCCESS[/green]
        """
        dm_str = f"+{dm}" if dm >= 0 else str(dm)
        result = "SUCCESS" if success else "FAILURE"
        color = "green" if success else "red"
        tier_str = f" [yellow]({tier})[/yellow]" if tier else ""
        markup = (
            f"[dim]{label}[/dim] [bold]{dice}={total}[/bold]"
            f" + DM({dm_str}) = {total + dm} vs {target}"
            f" → [{color}]{result}[/{color}]{tier_str}"
        )
        source = (
            f"{label} {dice}={total} DM({dm_str}) = {total + dm} vs {target} {result}{tier_str}"
        )
        self._write_anchored(markup, capture=source)

    def add_paragraph(self, text: str) -> None:
        """Add a paragraph of narrative prose with a blank line after."""
        self._write_anchored(text)
        self._write_anchored("", capture="")

    def add_result(self, text: str, success: bool = True) -> None:
        """Add a result line with success/failure coloring."""
        color = "green" if success else "red"
        self._write_anchored(f"[{color}]► {text}[/{color}]", capture=text)
