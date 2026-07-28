"""Main menu screen — new campaign / continue (R16)."""
from __future__ import annotations

import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Middle, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Label,
    OptionList,
    Static,
)
from textual.widgets.option_list import Option


class MainMenuScreen(Screen):
    """Main menu with new-campaign button and save picker.

    The save picker lists per-campaign saves with name, theme pack, and
    last-played timestamp. The 'Continue' state is disabled when no saves
    exist.
    """

    CSS = """
    MainMenuScreen {
        align: center middle;
    }
    #menu-container {
        width: 60;
        height: auto;
        padding: 2 4;
    }
    #app-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        padding: 1;
        width: 100%;
    }
    #subtitle {
        text-align: center;
        color: $text-muted;
        padding-bottom: 1;
        width: 100%;
    }
    #new-campaign {
        margin: 1 0;
        width: 100%;
    }
    #quit-btn {
        margin-top: 1;
        width: 100%;
    }
    #save-list {
        height: 10;
        margin: 1 0;
        border: round $primary;
    }
    .section-label {
        text-style: bold;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("q", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="menu-container"):
            yield Static("CEPHEUS ADVENTURE", id="app-title")
            yield Static("A deterministic-rules CYOA RPG", id="subtitle")
            yield Button(
                "New Campaign", id="new-campaign", variant="primary"
            )
            yield Label("Saved Campaigns:", classes="section-label")
            yield OptionList(id="save-list")
            yield Button("Quit", id="quit-btn", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_saves()

    def refresh_saves(self) -> None:
        """Reload the save picker from the saves directory."""
        ol = self.query_one("#save-list", OptionList)
        ol.clear_options()
        saves = self.app.list_saves()
        if not saves:
            ol.add_option(
                Option("[dim]No saved campaigns[/dim]", id="empty", disabled=True)
            )
        else:
            for s in saves:
                label = self._format_save_label(s)
                ol.add_option(Option(label, id=str(s.path)))

    @staticmethod
    def _format_save_label(s) -> str:
        """Format a SaveInfo into a display string for the picker."""
        from src.tui.app import SaveInfo  # noqa: F811 — circular safe

        parts: list[str] = [s.name]
        if s.character_name:
            parts.append(f"[{s.character_name}]")
        parts.append(f"({s.theme_pack})")
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.mtime))
        parts.append(ts)
        if not s.alive:
            parts.append("[DEAD]")
        elif s.terms > 0:
            parts.append(f"T{s.terms}")
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Event handlers.
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-campaign":
            from src.tui.screens.campaign_config import CampaignConfigScreen

            self.app.push_screen(CampaignConfigScreen())
        elif event.button.id == "quit-btn":
            self.app.exit()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Load the selected save."""
        if event.option.id == "empty":
            return
        save_path = event.option.id
        if save_path and save_path != "empty":
            try:
                self.app.load_campaign(save_path)
            except Exception as exc:
                self.app.notify(
                    f"Failed to load: {exc}", severity="error", timeout=5
                )
