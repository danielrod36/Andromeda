"""Campaign configuration screen — rule-set, theme pack, profile, death mode (R16)."""

from __future__ import annotations

import hashlib
from typing import ClassVar

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
from src.themepacks.base import discover_packs


class CampaignConfigScreen(Screen):
    """Campaign creation screen.

    Offers implemented options per phase: discoverable theme packs, Classic
    and Narrative resolution profiles (Narrative is the default per the plan's
    Key Decision), and three death modes.
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
    #pack-list, #profile-list, #death-list {
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

    BINDINGS: ClassVar[list[Binding]] = [
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
            yield OptionList(
                id="pack-list",
            )

            yield Label("Resolution Profile:", classes="config-label")
            yield OptionList(
                Option("Narrative [dim](PbtA three-tier)[/dim]", id="narrative"),
                Option("Classic [dim](2D6+DM >= 8)[/dim]", id="classic"),
                id="profile-list",
            )

            yield Label("Death Mode:", classes="config-label")
            yield OptionList(
                Option("Narrative [dim](mishap on failure)[/dim]", id="narrative"),
                Option("Ironman [dim](death on failure)[/dim]", id="ironman"),
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
                yield Button("Start", id="start-btn", variant="primary")

        yield Footer()

    def on_mount(self) -> None:
        # Populate the pack dropdown from discover_packs() (Task 17, AE10/F1).
        # Falls back to the bundled sci-fi pack if discovery finds nothing
        # (defensive — discover_packs() should always find at least scifi).
        pack_ol = self.query_one("#pack-list", OptionList)
        packs = discover_packs()
        if not packs:
            packs = {}
        pack_options = [
            Option(f"{pack.name} [dim]({pid})[/dim]", id=pid) for pid, pack in packs.items()
        ]
        if not pack_options:
            # Defensive default; should never trigger for the shipped app.
            pack_options.append(Option("Sci-Fi (Cepheus Engine SRD)", id="scifi"))
        pack_ol.add_options(pack_options)
        pack_ol.highlighted = 0

        # Pre-select defaults. Narrative is the plan-default profile (Key
        # Decision): the three-tier PbtA resolution keeps play moving and
        # avoids the binary pass/fail of Classic for new campaigns.
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

        pack_ol = self.query_one("#pack-list", OptionList)
        theme_pack = "scifi"
        if pack_ol.highlighted is not None:
            opt = pack_ol.options[pack_ol.highlighted]
            theme_pack = opt.id or "scifi"

        profile_ol = self.query_one("#profile-list", OptionList)
        death_ol = self.query_one("#death-list", OptionList)

        profile = "narrative"
        if profile_ol.highlighted is not None:
            opt = profile_ol.options[profile_ol.highlighted]
            profile = opt.id or "narrative"

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
            theme_pack=theme_pack,
            resolution_profile=profile,
            death_mode=death_mode,
        )

        self.app.start_new_campaign(name, config, seed)
