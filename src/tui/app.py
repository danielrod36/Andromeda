"""Main Textual App for Andromeda (U4).

Screen-based navigation: MainMenu -> CampaignConfig -> Lifepath -> Adventure.

The engine is a plain sync Python package. The TUI is a client that calls
``engine.apply(cmd)`` through the LifepathRunner and updates panels via
reactive ``watch_*`` methods. Auto-save runs after every lifepath step (AE8).
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from textual.app import App
from textual.binding import Binding

from src.engine.checkpoint import CheckpointManager
from src.engine.commands import Engine
from src.engine.lifepath import LifepathRunner
from src.engine.narration import Narrator
from src.engine.persistence import load, save
from src.engine.state import CampaignConfig, GameState
from src.themepacks.base import get_pack
from src.themepacks.cepheus_scifi import load_scifi_pack
from src.tui.screens.adventure import AdventureScreen
from src.tui.screens.lifepath import LifepathScreen
from src.tui.screens.main_menu import MainMenuScreen
from src.tui.settings import LLMSettings, load_settings

# ---------------------------------------------------------------------------
# Save metadata.
# ---------------------------------------------------------------------------


@dataclass
class SaveInfo:
    """Metadata for a save file, used by the main menu save picker."""

    path: Path
    name: str
    theme_pack: str
    character_name: str
    terms: int
    career: str
    alive: bool
    mtime: float


# ---------------------------------------------------------------------------
# Main application.
# ---------------------------------------------------------------------------


class CepheusApp(App):
    """Andromeda TUI application.

    Owns the :class:`Engine`, :class:`LifepathRunner`, and :class:`Narrator`.
    Screens are pushed/popped for navigation. Auto-save fires after every
    lifepath step so quit-and-resume preserves exact state (AE8).
    """

    TITLE = "Andromeda"
    SUB_TITLE = "A deterministic-rules CYOA RPG"

    CSS = """
    Screen {
        background: $background;
    }
    #app-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        padding: 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+s", "save_game", "Save"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        saves_dir: str | Path = "saves",
        settings_dir: str | Path = "settings",
    ) -> None:
        super().__init__()
        self.saves_dir = Path(saves_dir)
        self.saves_dir.mkdir(parents=True, exist_ok=True)
        self.settings_dir = Path(settings_dir)
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.engine: Engine | None = None
        self.runner: LifepathRunner | None = None
        self.narrator = Narrator()
        self.pack = None
        self.campaign_name: str = ""
        self.checkpoint_mgr: CheckpointManager = CheckpointManager()
        self.llm_settings: LLMSettings = load_settings(self.settings_dir)
        self._apply_llm_env(self.llm_settings)

    # ------------------------------------------------------------------
    # Lifecycle.
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Start at the main menu."""
        self.push_screen(MainMenuScreen())

    # ------------------------------------------------------------------
    # Campaign management.
    # ------------------------------------------------------------------

    def start_new_campaign(
        self,
        name: str,
        config: CampaignConfig,
        seed: int,
    ) -> None:
        """Create a new game state and enter the lifepath screen."""
        state = GameState.new(seed=seed)
        state.campaign = config
        state.character.name = name
        self.engine = Engine(state)
        self.pack = (
            load_scifi_pack() if config.theme_pack == "scifi" else get_pack(config.theme_pack)
        )
        self.runner = LifepathRunner(self.engine, self.pack)
        self.campaign_name = name or "unnamed"

        # Pop config screen and main menu, push lifepath.
        self.pop_screen()  # CampaignConfigScreen
        self.push_screen(LifepathScreen())

    def restart_lifepath(self) -> None:
        """Discard the current (dead) character and start a fresh lifepath
        with the same campaign configuration and character name (AE2, ironman).

        A fresh seed is drawn with ``secrets`` so the new character does not
        replay the dead one's roll sequence.
        """
        old = self.engine.state
        config = old.campaign
        name = old.character.name
        new_seed = secrets.randbelow(2**31)
        state = GameState.new(seed=new_seed)
        state.campaign = config
        state.character.name = name
        self.engine = Engine(state)
        self.pack = (
            load_scifi_pack() if config.theme_pack == "scifi" else get_pack(config.theme_pack)
        )
        self.runner = LifepathRunner(self.engine, self.pack)
        # Replace the lifepath screen (the one showing the death/complete state)
        # with a fresh instance so phase determination starts clean.
        self.pop_screen()
        self.push_screen(LifepathScreen())

    def load_campaign(self, save_path: str | Path) -> None:
        """Load a saved game and enter the lifepath screen."""
        state = load(save_path)
        self.engine = Engine(state)
        self.pack = (
            load_scifi_pack()
            if state.campaign.theme_pack == "scifi"
            else get_pack(state.campaign.theme_pack)
        )
        self.runner = LifepathRunner(self.engine, self.pack)
        self.campaign_name = Path(save_path).stem

        # Load checkpoint snapshot for checkpoint death mode (AE3).
        if state.campaign.death_mode == "checkpoint":
            self.checkpoint_mgr.load_snapshot(save_path)

        # A mustered-out, living character goes straight to the adventure
        # loop; anything else resumes (or restarts) character generation.
        mustered_out = "mustered_out=true" in state.narrative_log
        if mustered_out and state.character.alive:
            self.push_screen(AdventureScreen())
        else:
            self.push_screen(LifepathScreen())

    def start_adventure(self) -> None:
        """Enter the adventure loop with the current (mustered-out) character.

        Called from the lifepath screen's completion choices. Saves first so
        the adventure begins from the persisted post-chargen state.
        """
        self.save_game()
        self.push_screen(AdventureScreen())

    def return_to_main_menu(self) -> None:
        """Pop back to the main menu from the lifepath screen."""
        # Pop until we reach MainMenuScreen (or stack is empty).
        while self.screen_stack and not isinstance(self.screen, MainMenuScreen):
            self.pop_screen()
        # Refresh save list on the main menu.
        if isinstance(self.screen, MainMenuScreen):
            self.screen.refresh_saves()

    # ------------------------------------------------------------------
    # Save / resume (AE8).
    # ------------------------------------------------------------------

    def save_game(self) -> Path | None:
        """Auto-save current game state. Returns the save path or None."""
        if self.engine is None:
            return None
        safe_name = self.campaign_name.replace(" ", "_").replace("/", "_") or "unnamed"
        path = self.saves_dir / f"{safe_name}.json"
        save(self.engine.state, path)

        # Persist checkpoint snapshot for checkpoint death mode (AE3).
        if self.engine.state.campaign.death_mode == "checkpoint":
            self.checkpoint_mgr.save_snapshot(path)

        return path

    def list_saves(self) -> list[SaveInfo]:
        """Return metadata for all save files, sorted by mtime (newest first)."""
        results: list[SaveInfo] = []
        if not self.saves_dir.is_dir():
            return results
        for path in sorted(self.saves_dir.glob("*.json")):
            if path.name.endswith(".checkpoint.json"):
                continue  # Checkpoint sidecar, not a loadable campaign save.
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                campaign = data.get("campaign", {})
                character = data.get("character", {})
                stat = path.stat()
                results.append(
                    SaveInfo(
                        path=path,
                        name=path.stem,
                        theme_pack=campaign.get("theme_pack", "unknown"),
                        character_name=character.get("name", ""),
                        terms=character.get("terms", 0),
                        career=character.get("career", ""),
                        alive=character.get("alive", True),
                        mtime=stat.st_mtime,
                    )
                )
            except (json.JSONDecodeError, OSError):
                continue
        results.sort(key=lambda s: s.mtime, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Actions.
    # ------------------------------------------------------------------

    def action_save_game(self) -> None:
        """Save-game action bound to Ctrl+S."""
        path = self.save_game()
        if path:
            self.notify(f"Saved: {path.name}", timeout=3)
        else:
            self.notify("No active game to save.", timeout=3)

    # ------------------------------------------------------------------
    # Helpers for lifepath screen.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # LLM settings.
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_llm_env(settings: LLMSettings) -> None:
        """Populate provider-specific env vars from settings.

        Pydantic AI's provider clients read ``ANTHROPIC_API_KEY``,
        ``OPENAI_API_KEY``, etc. We set them so the adapter can construct
        agents without explicit key passing.
        """
        for key, value in settings.env_overrides().items():
            if value:
                os.environ[key] = value

    def apply_llm_settings(self, settings: LLMSettings) -> None:
        """Update LLM settings at runtime (called by the settings screen).

        Re-applies environment variables and stores the settings so the next
        adapter creation picks them up.
        """
        self.llm_settings = settings
        self._apply_llm_env(settings)

    def create_llm_adapter(self):
        """Build an :class:`LLMAdapter` from current settings.

        Returns a configured adapter when settings are complete, or ``None``
        when no model/key is set (caller should use template narration).
        """
        if not self.llm_settings.is_configured:
            return None
        from src.llm.adapter import AdapterConfig, LLMAdapter

        return LLMAdapter(
            AdapterConfig(
                model=self.llm_settings.model_string,
                max_retries=self.llm_settings.max_retries,
            )
        )

    @staticmethod
    def generate_seed() -> int:
        """Generate a random campaign seed using ``secrets`` for entropy."""
        return secrets.randbelow(2**31)
