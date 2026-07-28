"""Campaign configuration screen — rule-set, theme pack, profile, death mode (R16)."""
from __future__ import annotations

import hashlib

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
)
from textual.widgets.option_list import Option

from src.engine.state import CampaignConfig


class CampaignConfigScreen(Screen):
    """Campaign creation screen.

    Offers implemented options per phase (v0.1: sci-fi pack, Classic and
    Narrative profiles). Unimplemented options are shown disabled.
    """

    CSS = """
    CampaignConfigScreen {
        align: center top;
        padding: 1;
    }
    #config-container {
        width: 100%;
        max-width: 70;
        padding: 1 2;
    }
    .config-label {
        text-style: bold;
        padding: 1 0 0 0;
    }
    .config-hint {
        color: $text-muted;
        padding: 0 0 0 1;
    }
    #name-input {
        margin: 0 0 1 0;
    }
    #profile-list, #death-list {
        height: 5;
        border: round $primary;
        margin: 0 0 1 0;
    }
    #config-buttons {
        height: 3;
        align-horizontal: right;
    }
    #start-btn {
        margin-left: 2;
    }
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="config-container"):
            yield Label("Create New Campaign", classes="config-label")

            yield Label("Campaign Name:", classes="config-label")
            yield Input(
                placeholder="Enter campaign name...",
                id="name-input",
            )

            yield Label("Theme Pack:", classes="config-label")
            yield Label(
                "Sci-Fi (Cepheus Engine SRD) [dim]— only pack available[/dim]",
                classes="config-hint",
            )

            yield Label("Resolution Profile:", classes="config-label")
            yield OptionList(
                Option("Classic [dim](2D6+DM >= 8)[/dim]", id="classic"),
                Option(
                    "Narrative [dim](PbtA three-tier)[/dim]", id="narrative"
                ),
                id="profile-list",
            )

            yield Label("Death Mode:", classes="config-label")
            yield OptionList(
                Option(
                    "Narrative [dim](mishap on failure)[/dim]", id="narrative"
                ),
                Option(
                    "Ironman [dim](death on failure)[/dim]", id="ironman"
                ),
                Option(
                    "Checkpoint [dim](mishap, checkpoint save)[/dim]",
                    id="checkpoint",
                ),
                id="death-list",
            )

            yield Label("Seed (blank for random):", classes="config-label")
            yield Input(
                placeholder="Enter seed or leave blank...",
                id="seed-input",
            )

            with Horizontal(id="config-buttons"):
                yield Button("Back", id="back-btn")
                yield Button(
                    "Start", id="start-btn", variant="primary"
                )

        yield Footer()

    def on_mount(self) -> None:
        # Pre-select defaults.
        self.query_one("#profile-list", OptionList).highlighted = 0
        self.query_one("#death-list", OptionList).highlighted = 0

    # ------------------------------------------------------------------
    # Event handlers.
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "start-btn":
            self._start_campaign()

    def _start_campaign(self) -> None:
        """Gather config values and call app.start_new_campaign."""
        name = self.query_one("#name-input", Input).value.strip()
        if not name:
            name = "Campaign"

        profile_ol = self.query_one("#profile-list", OptionList)
        death_ol = self.query_one("#death-list", OptionList)

        profile = "classic"
        if profile_ol.highlighted is not None:
            opt = profile_ol.options[profile_ol.highlighted]
            profile = opt.id or "classic"

        death_mode = "narrative"
        if death_ol.highlighted is not None:
            opt = death_ol.options[death_ol.highlighted]
            death_mode = opt.id or "narrative"

        seed_text = self.query_one("#seed-input", Input).value.strip()
        if seed_text.isdigit():
            seed = int(seed_text)
        elif seed_text:
            # Stable hash for non-numeric seeds — hashlib, not hash(), which is
            # salted per-process via PYTHONHASHSEED and breaks determinism.
            digest = hashlib.sha256(seed_text.encode()).digest()
            seed = int.from_bytes(digest[:4], "big") % (2**31)
        else:
            seed = self.app.generate_seed()

        config = CampaignConfig(
            ruleset="cepheus",
            theme_pack="scifi",
            resolution_profile=profile,
            death_mode=death_mode,
        )

        self.app.start_new_campaign(name, config, seed)
