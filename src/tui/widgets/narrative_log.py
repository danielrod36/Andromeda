"""Narrative log main panel — scrolling RichLog for game narration (R16).

Wraps RichLog with formatting helpers for section headers, separators,
roll results, and paragraph breaks so the log reads as structured prose
rather than a monolith of text.
"""

from __future__ import annotations

from textual.widgets import RichLog

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
    """

    DEFAULT_CSS = """
    NarrativeLogWidget {
        height: 1fr;
        border: round $accent;
        margin: 0;
        padding: 0 1;
        background: $surface;
    }
    """

    def __init__(self, *args, **kwargs):
        """Enable Rich markup and word wrapping by default."""
        kwargs.setdefault("markup", True)
        kwargs.setdefault("wrap", True)
        super().__init__(*args, **kwargs)
        # Underlying source text for each beat written to the log. RichLog only
        # retains rendered terminal rows, so on resize/scrollback the source is
        # lost (research pitfall: TUI word-wrapping breaks scrollback). Keeping
        # the original strings also makes the log assertion-testable.
        self.captured_lines: list[str] = []

    def add_line(self, text: str) -> None:
        """Append a line of narrative text to the log."""
        self.captured_lines.append(text)
        self.write(text)

    def add_engine_receipt(self, text: str) -> None:
        """Render an engine-decided fact with distinct provenance styling.

        Engine receipts (dice rolls, DMs, outcomes, state changes) are bold and
        glyph-prefixed so the player can distinguish mechanical ground truth
        from LLM-narrated prose at a glance. The source ``text`` (not the
        markup) is captured into :attr:`captured_lines` for scrollback integrity
        and assertions.
        """
        self.captured_lines.append(text)
        self.write(engine_receipt_text(text))

    def add_lines(self, lines: list[str]) -> None:
        """Append multiple lines of narrative text."""
        for line in lines:
            self.add_line(line)

    def add_separator(self, label: str = "") -> None:
        """Add a visual separator line with an optional label."""
        if label:
            self.write(f"[dim]── {label} {'─' * max(1, 50 - len(label))}[/dim]")
        else:
            self.write("[dim]" + "─" * 60 + "[/dim]")

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
        self.captured_lines.append(f"REWOUND TO {label.upper()}")
        self.write(rewind_divider_text(label))

    def add_section(self, title: str) -> None:
        """Add a section header."""
        self.write("")
        self.write(f"[bold cyan]{title}[/bold cyan]")
        self.write("")

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
        self.write(
            f"[dim]{label}[/dim] [bold]{dice}={total}[/bold]"
            f" + DM({dm_str}) = {total + dm} vs {target}"
            f" → [{color}]{result}[/{color}]{tier_str}"
        )

    def add_paragraph(self, text: str) -> None:
        """Add a paragraph of narrative prose with a blank line after."""
        self.write(text)
        self.write("")

    def add_result(self, text: str, success: bool = True) -> None:
        """Add a result line with success/failure coloring."""
        color = "green" if success else "red"
        self.write(f"[{color}]► {text}[/{color}]")
