"""LLM settings screen — configure API endpoint and key from the TUI.

Lets the player set their provider, model, API key, and optional custom
base URL without leaving the game. Settings persist to disk via the
:mod:`src.tui.settings` module.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
)
from textual.widgets.option_list import Option

from src.tui.settings import (
    MODEL_PRESETS,
    LLMSettings,
    load_settings,
    save_settings,
)


class SettingsScreen(Screen):
    """LLM configuration screen.

    Fields:
        Provider — dropdown (Anthropic, OpenAI, Groq, Custom).
        Model — text input, with preset suggestions per provider.
        API Key — password input (masked).
        Base URL — optional custom endpoint.
    """

    CSS = """
    SettingsScreen {
        align: center middle;
    }
    #settings-container {
        width: 72;
        height: auto;
        max-height: 80%;
        padding: 1 2;
    }
    #settings-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        padding-bottom: 1;
    }
    .field-label {
        text-style: bold;
        padding: 1 0 0 0;
    }
    .field-hint {
        color: $text-muted;
        padding: 0 0 0 1;
        font-style: italic;
    }
    #settings-buttons {
        height: 3;
        padding: 1 0;
    }
    #settings-buttons Button {
        margin: 0 1;
    }
    #settings-status {
        padding: 1 0;
        text-align: center;
    }
    .status-ok { color: $success; }
    .status-warn { color: $warning; }
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._settings = load_settings(self.app.settings_dir)

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="settings-container"):
            yield Static("LLM Settings", id="settings-title")

            yield Label("Provider:", classes="field-label")
            yield Select(
                [
                    ("Anthropic", "anthropic"),
                    ("OpenAI", "openai"),
                    ("Groq", "groq"),
                    ("Custom", "custom"),
                ],
                id="provider-select",
                value=self._settings.provider,
            )

            yield Label("Model:", classes="field-label")
            yield Input(
                value=self._settings.model,
                placeholder="e.g. claude-sonnet-5",
                id="model-input",
            )
            yield Label(
                self._model_hint(self._settings.provider),
                id="model-hint",
                classes="field-hint",
            )

            yield Label("API Key:", classes="field-label")
            yield Input(
                value=self._settings.api_key,
                placeholder="sk-...",
                id="api-key-input",
                password=True,
            )

            yield Label("Base URL (optional):", classes="field-label")
            yield Input(
                value=self._settings.base_url,
                placeholder="https://custom-endpoint.example.com/v1",
                id="base-url-input",
            )
            yield Label(
                "Leave blank for provider defaults. Use for proxies or local LLMs.",
                classes="field-hint",
            )

            yield Static(id="settings-status")

            with Vertical(id="settings-buttons"):
                yield Button("Save", id="save-btn", variant="primary")
                yield Button("Back", id="back-btn", variant="default")

        yield Footer()

    def on_mount(self) -> None:
        self._update_status()

    # ------------------------------------------------------------------
    # Helpers.
    # ------------------------------------------------------------------

    @staticmethod
    def _model_hint(provider: str) -> str:
        presets = MODEL_PRESETS.get(provider, [])
        if presets:
            return f"Suggestions: {', '.join(presets)}"
        return "Enter any model identifier supported by your provider."

    def _update_status(self) -> None:
        widget = self.query_one("#settings-status", Static)
        if self._settings.is_configured:
            widget.update(
                f"[green]✓ LLM configured ({self._settings.provider}:{self._settings.model})[/green]"
            )
        else:
            widget.update(
                "[yellow]⚠ Not configured — template narration will be used[/yellow]"
            )

    def _collect_settings(self) -> LLMSettings:
        """Read form values into a LLMSettings object."""
        provider = self.query_one("#provider-select", Select).value
        model = self.query_one("#model-input", Input).value.strip()
        api_key = self.query_one("#api-key-input", Input).value.strip()
        base_url = self.query_one("#base-url-input", Input).value.strip()
        return LLMSettings(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_retries=self._settings.max_retries,
        )

    # ------------------------------------------------------------------
    # Event handlers.
    # ------------------------------------------------------------------

    def on_select_changed(self, event: Select.Changed) -> None:
        """Update model hint when provider changes."""
        if event.select.id == "provider-select":
            hint = self.query_one("#model-hint", Label)
            hint.update(self._model_hint(str(event.value)))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._settings = self._collect_settings()
            save_settings(self._settings, self.app.settings_dir)
            self.app.apply_llm_settings(self._settings)
            self._update_status()
            self.app.notify("Settings saved.", timeout=3)
        elif event.button.id == "back-btn":
            self.app.pop_screen()
