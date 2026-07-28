"""Narrative log main panel — scrolling RichLog for lifepath narration (R16)."""
from __future__ import annotations

from textual.widgets import RichLog


class NarrativeLogWidget(RichLog):
    """Scrolling narrative log panel.

    Wraps :class:`RichLog` with convenience methods and custom CSS.
    Supports PageUp/PageDown and Home/End for scrolling (inherited from
    RichLog's scroll actions, also bound at the screen level).
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

    def add_line(self, text: str) -> None:
        """Append a line of narrative text to the log."""
        self.write(text)

    def add_lines(self, lines: list[str]) -> None:
        """Append multiple lines of narrative text."""
        for line in lines:
            self.add_line(line)
