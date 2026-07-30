"""LLM settings screen — configure API endpoint, key, and model from the TUI.

Features:
- Provider dropdown (Anthropic, OpenAI, DeepSeek, OpenRouter, Xiaomi MiMo, Groq, Custom)
- API key input (masked)
- Base URL input (auto-filled with provider default)
- "Fetch Models" button that queries the provider's /models endpoint
- Search bar to filter the model list
- Selectable model OptionList with live filtering
- Settings persist to disk via the :mod:`src.tui.settings` module
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import ValidationError
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Select,
    Static,
)
from textual.widgets.option_list import Option

from src.tui.providers import get_provider_config, provider_labels
from src.tui.settings import (
    LLMSettings,
    load_settings,
    save_settings,
)


class SettingsScreen(Screen):
    """LLM configuration screen with searchable model picker."""

    CSS = """
    SettingsScreen {
        align: center middle;
    }
    #settings-container {
        width: 100%;
        max-width: 76;
        height: 100%;
        max-height: 90%;
        padding: 1 2;
        overflow-y: auto;
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
        text-style: italic;
    }
    #model-section {
        height: auto;
        padding: 1 0;
    }
    #model-search-row {
        height: 3;
    }
    #model-search {
        width: 1fr;
    }
    #fetch-btn {
        width: auto;
    }
    #model-list {
        height: 8;
        border: round $primary;
        margin-top: 0;
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
    #fetch-status {
        padding: 0 0 0 1;
        color: $text-muted;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+s", "save_settings", "Save"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._settings = load_settings(self.app.settings_dir)
        self._all_models: list[str] = []
        self._fetching = False

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="settings-container"):
            yield Static("LLM Settings", id="settings-title")

            # --- Provider ---
            yield Label("Provider:", classes="field-label")
            yield Select(
                provider_labels(),
                id="provider-select",
                value=self._settings.provider,
            )

            # --- API Key ---
            yield Label("API Key:", classes="field-label")
            yield Input(
                value=self._settings.api_key,
                placeholder="sk-...",
                id="api-key-input",
                password=True,
            )

            # --- Base URL ---
            yield Label("Base URL (optional):", classes="field-label")
            yield Input(
                value=self._settings.base_url,
                placeholder=self._url_placeholder(self._settings.provider),
                id="base-url-input",
            )
            yield Label(
                "Leave blank for provider defaults. Use for proxies or local LLMs.",
                classes="field-hint",
            )

            # --- Model picker ---
            yield Static("", id="fetch-status")
            with Vertical(id="model-section"):
                yield Label("Model:", classes="field-label")
                with Horizontal(id="model-search-row"):
                    yield Input(
                        placeholder="Search models...",
                        id="model-search",
                    )
                    yield Button("Fetch", id="fetch-btn", variant="primary")
                yield OptionList(id="model-list")

            yield Static(id="settings-status")

            with Horizontal(id="settings-buttons"):
                yield Button("Save", id="save-btn", variant="success")
                yield Button("Back", id="back-btn", variant="default")

        yield Footer()

    def on_mount(self) -> None:
        """Populate model list with presets on mount."""
        self._populate_presets()
        self._update_status()

    # ------------------------------------------------------------------
    # Helpers.
    # ------------------------------------------------------------------

    @staticmethod
    def _url_placeholder(provider: str) -> str:
        cfg = get_provider_config(provider)
        default = cfg.get("default_base_url", "")
        return default or "https://your-endpoint.example.com"

    def _populate_presets(self) -> None:
        """Load preset/fallback models for the current provider."""
        cfg = get_provider_config(self._settings.provider)
        self._all_models = list(cfg.get("presets", []))
        self._render_model_list()

        # Pre-select the current model if it's in the list.
        ol = self.query_one("#model-list", OptionList)
        if self._settings.model:
            for i, opt in enumerate(ol.options):
                if opt.id == self._settings.model:
                    ol.highlighted = i
                    break

    def _render_model_list(self, filter_text: str = "") -> None:
        """Re-render the OptionList with optional filter."""
        ol = self.query_one("#model-list", OptionList)
        ol.clear_options()
        filter_lower = filter_text.lower().strip()
        matched = [m for m in self._all_models if not filter_lower or filter_lower in m.lower()]
        if not matched:
            ol.add_option(Option("[dim]No models found[/dim]", id="empty", disabled=True))
        else:
            for model_id in matched:
                label = model_id
                if model_id == self._settings.model:
                    label = f"[bold]► {model_id}[/bold]"
                ol.add_option(Option(label, id=model_id))

    def _update_status(self) -> None:
        widget = self.query_one("#settings-status", Static)
        if self._settings.is_configured:
            widget.update(
                f"[green]✓ LLM configured ({self._settings.provider}:{self._settings.model})[/green]"
            )
        else:
            widget.update("[yellow]⚠ Not configured — template narration will be used[/yellow]")

    def _set_fetch_status(self, text: str, *, error: bool = False) -> None:
        widget = self.query_one("#fetch-status", Static)
        prefix = "[red]" if error else "[dim]"
        suffix = "[/red]" if error else "[/dim]"
        widget.update(f"{prefix}{text}{suffix}")

    def _collect_settings(self) -> LLMSettings:
        """Read form values into a LLMSettings object."""
        provider = self.query_one("#provider-select", Select).value
        api_key = self.query_one("#api-key-input", Input).value.strip()
        base_url = self.query_one("#base-url-input", Input).value.strip()
        return LLMSettings(
            provider=str(provider),
            model=self._settings.model,
            api_key=api_key,
            base_url=base_url,
            max_retries=self._settings.max_retries,
        )

    # ------------------------------------------------------------------
    # Event handlers.
    # ------------------------------------------------------------------

    def on_select_changed(self, event: Select.Changed) -> None:
        """When provider changes, update defaults and presets."""
        if event.select.id == "provider-select":
            provider = str(event.value)
            self._settings = LLMSettings(
                provider=provider,
                model="",  # Clear model — different provider
                api_key=self.query_one("#api-key-input", Input).value.strip(),
                base_url="",  # Clear — let placeholder show default
                max_retries=self._settings.max_retries,
            )
            # Update URL placeholder.
            url_input = self.query_one("#base-url-input", Input)
            url_input.value = ""
            url_input.placeholder = self._url_placeholder(provider)
            self._populate_presets()
            self._update_status()
            self._set_fetch_status("")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter model list as the user types in the search bar."""
        if event.input.id == "model-search":
            self._render_model_list(event.value)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Select a model from the list."""
        if event.option.id and event.option.id != "empty":
            self._settings.model = event.option.id
            self._render_model_list(self.query_one("#model-search", Input).value)
            self._update_status()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fetch-btn":
            self._do_fetch_models()
        elif event.button.id == "save-btn":
            self._do_save()
        elif event.button.id == "back-btn":
            self.app.pop_screen()

    def action_save_settings(self) -> None:
        """Ctrl+S keyboard shortcut to save settings."""
        self._do_save()

    def _do_save(self) -> None:
        """Persist current settings to disk and apply them."""
        try:
            self._settings = self._collect_settings()
        except ValidationError as exc:
            # e.g. the base_url SSRF guard rejecting a non-http(s) scheme —
            # surface the error in the form instead of crashing the screen.
            msg = exc.errors()[0]["msg"] if exc.errors() else str(exc)
            self._set_fetch_status(f"Not saved: {msg}", error=True)
            self.app.notify(f"Settings not saved: {msg}", severity="error")
            return
        save_settings(self._settings, self.app.settings_dir)
        self.app.apply_llm_settings(self._settings)
        self._update_status()
        self.app.notify("Settings saved.", timeout=3)

    # ------------------------------------------------------------------
    # Model fetching.
    # ------------------------------------------------------------------

    def _do_fetch_models(self) -> None:
        """Launch async model fetch in a worker thread."""
        if self._fetching:
            return

        provider = str(self.query_one("#provider-select", Select).value)
        api_key = self.query_one("#api-key-input", Input).value.strip()
        base_url = self.query_one("#base-url-input", Input).value.strip()

        if not api_key:
            self._set_fetch_status("Enter an API key first.", error=True)
            return

        cfg = get_provider_config(provider)
        if not base_url and not cfg.get("default_base_url"):
            self._set_fetch_status("Enter a base URL first.", error=True)
            return

        self._fetching = True
        self._set_fetch_status(f"Fetching models from {cfg['label']}...")
        self.run_worker(self._fetch_models_task(provider, api_key, base_url))

    async def _fetch_models_task(self, provider: str, api_key: str, base_url: str) -> None:
        """Worker that fetches models and updates the UI."""
        from src.tui.providers import fetch_available_models

        try:
            models = await fetch_available_models(provider, api_key, base_url or None)
            self._all_models = models
            self._render_model_list(self.query_one("#model-search", Input).value)
            self._set_fetch_status(f"Found {len(models)} models.")
        except RuntimeError as exc:
            self._set_fetch_status(str(exc), error=True)
        except Exception as exc:
            self._set_fetch_status(f"Error: {exc}", error=True)
        finally:
            self._fetching = False
