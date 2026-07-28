"""Choice menu bottom panel — OptionList with number-key selection (R16).

Options display fiction label + compact mechanics suffix (skill, difficulty,
characteristic) so players make informed decisions. Number keys 1-9 select
directly; Tab cycles focus between panels.
"""
from __future__ import annotations

from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


class ChoiceMenuWidget(Container):
    """Bottom panel with a prompt label and OptionList for player choices.

    Number keys 1-9 select the corresponding option when this widget (or
    its child OptionList) has focus. Tab/Shift-Tab navigates between panels.
    """

    DEFAULT_CSS = """
    ChoiceMenuWidget {
        height: 9;
        border: round $warning;
        padding: 0 1;
        background: $surface;
    }
    ChoiceMenuWidget Label {
        height: 1;
        color: $text;
        text-style: bold;
    }
    ChoiceMenuWidget OptionList {
        height: 1fr;
    }
    """

    # Number-key bindings for direct option selection.
    BINDINGS = [
        Binding(str(n), f"select_number({n - 1})", show=False)
        for n in range(1, 10)
    ]

    def compose(self) -> None:
        yield Label("Choices", id="choice-prompt")
        yield OptionList(id="choice-list")

    # ------------------------------------------------------------------
    # Public API.
    # ------------------------------------------------------------------

    @property
    def option_list(self) -> OptionList:
        """Return the inner OptionList widget."""
        return self.query_one("#choice-list", OptionList)

    def set_choices(
        self,
        prompt: str,
        choices: list[tuple[str, str]],
        descriptions: list[str] | None = None,
    ) -> None:
        """Populate the choice menu.

        Args:
            prompt: Label text shown above the options.
            choices: List of (display_text, option_id) tuples.
            descriptions: Optional list of description strings, one per
                choice. When provided, each option shows the display text
                on the first line and the description (dimmed) below it.
        """
        self.query_one("#choice-prompt", Label).update(prompt)
        ol = self.option_list
        ol.clear_options()
        for i, (display, oid) in enumerate(choices):
            if descriptions and i < len(descriptions) and descriptions[i]:
                # Multi-line option: main label + dimmed description.
                desc = descriptions[i]
                label = f"{display}\n  [dim]{desc}[/dim]"
            else:
                label = display
            ol.add_option(Option(label, id=oid))

    def clear_choices(self) -> None:
        """Remove all choices."""
        self.query_one("#choice-prompt", Label).update("Waiting...")
        self.option_list.clear_options()

    # ------------------------------------------------------------------
    # Number-key selection.
    # ------------------------------------------------------------------

    def action_select_number(self, index: int) -> None:
        """Select option by number key (internally 0-indexed)."""
        ol = self.option_list
        if 0 <= index < ol.option_count:
            ol.highlighted = index
            ol.action_select()
