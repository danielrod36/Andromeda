"""Narrative log main panel — scrolling RichLog for game narration (R16).

Wraps RichLog with formatting helpers for section headers, separators,
roll results, and paragraph breaks so the log reads as structured prose
rather than a monolith of text.
"""

from __future__ import annotations

from textual.widgets import RichLog


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

    def add_line(self, text: str) -> None:
        """Append a line of narrative text to the log."""
        self.write(text)

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
