"""Tests for LLM settings persistence and TUI integration."""

import json
import os

import pytest

from src.tui.settings import (
    MODEL_PRESETS,
    LLMSettings,
    load_settings,
    save_settings,
    settings_path,
)

# ---------------------------------------------------------------------------
# LLMSettings model tests.
# ---------------------------------------------------------------------------


class TestLLMSettings:
    def test_defaults(self):
        s = LLMSettings()
        assert s.provider == "anthropic"
        assert s.model == ""
        assert s.api_key == ""
        assert s.base_url == ""
        assert not s.is_configured

    def test_is_configured_with_model_and_key(self):
        s = LLMSettings(model="claude-sonnet-5", api_key="sk-test")
        assert s.is_configured

    def test_not_configured_without_key(self):
        s = LLMSettings(model="claude-sonnet-5")
        assert not s.is_configured

    def test_not_configured_without_model(self):
        s = LLMSettings(api_key="sk-test")
        assert not s.is_configured

    def test_model_string(self):
        s = LLMSettings(provider="anthropic", model="claude-sonnet-5")
        assert s.model_string == "anthropic:claude-sonnet-5"

    def test_model_string_deepseek_uses_openai_prefix(self):
        s = LLMSettings(provider="deepseek", model="deepseek-chat")
        assert s.model_string == "openai:deepseek-chat"

    def test_model_string_none_when_empty(self):
        s = LLMSettings()
        assert s.model_string is None

    def test_env_overrides_anthropic(self):
        s = LLMSettings(
            provider="anthropic",
            api_key="sk-test",
            base_url="https://custom.example.com",
        )
        env = s.env_overrides()
        assert env["ANTHROPIC_API_KEY"] == "sk-test"
        assert env["ANTHROPIC_BASE_URL"] == "https://custom.example.com"

    def test_env_overrides_openai_uses_default_base_url(self):
        s = LLMSettings(provider="openai", api_key="sk-oai", base_url="")
        env = s.env_overrides()
        assert env["OPENAI_API_KEY"] == "sk-oai"
        # Default base URL is populated when no explicit override.
        assert env["OPENAI_BASE_URL"] == "https://api.openai.com"

    def test_env_overrides_deepseek_sets_openai_vars(self):
        """DeepSeek uses Pydantic AI's OpenAI provider, so OPENAI_* must be set."""
        s = LLMSettings(provider="deepseek", api_key="sk-ds")
        env = s.env_overrides()
        assert env["DEEPSEEK_API_KEY"] == "sk-ds"
        assert env["DEEPSEEK_BASE_URL"] == "https://api.deepseek.com"
        # Also sets OPENAI_* so Pydantic AI's openai prefix finds the endpoint.
        assert env["OPENAI_API_KEY"] == "sk-ds"
        assert env["OPENAI_BASE_URL"] == "https://api.deepseek.com"

    def test_env_overrides_custom_provider(self):
        s = LLMSettings(provider="custom", api_key="key", base_url="http://localhost:8080")
        env = s.env_overrides()
        assert env["CUSTOM_API_KEY"] == "key"
        assert env["CUSTOM_BASE_URL"] == "http://localhost:8080"
        assert env["OPENAI_API_KEY"] == "key"
        assert env["OPENAI_BASE_URL"] == "http://localhost:8080"

    def test_env_overrides_no_key_sets_only_base_url(self):
        """Without an API key, only the base URL env is populated."""
        s = LLMSettings(provider="anthropic")
        env = s.env_overrides()
        assert "ANTHROPIC_API_KEY" not in env
        assert env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"

    def test_base_url_rejects_non_http_scheme(self):
        with pytest.raises(ValueError, match="http or https"):
            LLMSettings(base_url="file:///etc/passwd")

    def test_base_url_rejects_missing_host(self):
        with pytest.raises(ValueError, match="host"):
            LLMSettings(base_url="https://")

    def test_base_url_accepts_https(self):
        s = LLMSettings(base_url="https://proxy.example.com/v1")
        assert s.base_url == "https://proxy.example.com/v1"

    def test_base_url_accepts_localhost_http(self):
        s = LLMSettings(base_url="http://localhost:8080")
        assert s.base_url == "http://localhost:8080"

    def test_base_url_empty_is_valid(self):
        s = LLMSettings()
        assert s.base_url == ""


# ---------------------------------------------------------------------------
# Persistence tests.
# ---------------------------------------------------------------------------


class TestSettingsPersistence:
    def test_save_and_load_round_trip(self, tmp_path):
        original = LLMSettings(
            provider="openai",
            model="gpt-4o",
            api_key="sk-test-123",
            base_url="https://proxy.example.com",
        )
        save_settings(original, tmp_path)
        loaded = load_settings(tmp_path)
        assert loaded == original

    def test_load_returns_defaults_when_no_file(self, tmp_path):
        loaded = load_settings(tmp_path)
        assert loaded.provider == "anthropic"
        assert loaded.model == ""

    def test_load_returns_defaults_on_corrupt_json(self, tmp_path):
        path = settings_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken json", encoding="utf-8")
        loaded = load_settings(tmp_path)
        assert loaded.provider == "anthropic"
        assert loaded.model == ""

    def test_save_creates_directory(self, tmp_path):
        nested = tmp_path / "deeply" / "nested" / "settings"
        s = LLMSettings(model="test-model", api_key="key")
        save_settings(s, nested)
        assert settings_path(nested).exists()

    def test_save_is_atomic(self, tmp_path):
        """No temp file left after a successful save."""
        s = LLMSettings(model="test", api_key="key")
        save_settings(s, tmp_path)
        assert not (tmp_path / "llm.json.tmp").exists()
        assert (tmp_path / "llm.json").exists()

    def test_save_sets_restrictive_permissions(self, tmp_path):
        """Settings file must be owner-only (0600) — it contains an API key."""
        import stat

        s = LLMSettings(model="test", api_key="sk-secret")
        save_settings(s, tmp_path)
        mode = settings_path(tmp_path).stat().st_mode
        # Extract just the permission bits (lower 9).
        perms = stat.S_IMODE(mode)
        assert perms == 0o600, f"Expected 0600, got {oct(perms)}"

    def test_save_file_contains_expected_fields(self, tmp_path):
        s = LLMSettings(
            provider="anthropic",
            model="claude-sonnet-5",
            api_key="sk-secret",
        )
        save_settings(s, tmp_path)
        data = json.loads(settings_path(tmp_path).read_text())
        assert data["provider"] == "anthropic"
        assert data["model"] == "claude-sonnet-5"
        assert data["api_key"] == "sk-secret"


# ---------------------------------------------------------------------------
# Model presets.
# ---------------------------------------------------------------------------


class TestModelPresets:
    def test_anthropic_has_presets(self):
        assert "claude-sonnet-5" in MODEL_PRESETS["anthropic"]

    def test_openai_has_presets(self):
        assert len(MODEL_PRESETS["openai"]) > 0

    def test_deepseek_has_presets(self):
        assert "deepseek-chat" in MODEL_PRESETS["deepseek"]

    def test_openrouter_has_presets(self):
        assert len(MODEL_PRESETS["openrouter"]) > 0

    def test_xiaomi_mimo_has_presets(self):
        assert len(MODEL_PRESETS["xiaomi_mimo"]) > 0


# ---------------------------------------------------------------------------
# Provider config tests.
# ---------------------------------------------------------------------------


class TestProviderConfigs:
    def test_all_expected_providers_present(self):
        from src.tui.providers import PROVIDER_CONFIGS

        expected = {
            "anthropic",
            "openai",
            "deepseek",
            "openrouter",
            "xiaomi_mimo",
            "groq",
            "custom",
        }
        assert expected <= set(PROVIDER_CONFIGS.keys())

    def test_each_provider_has_required_fields(self):
        from src.tui.providers import PROVIDER_CONFIGS

        required = {
            "label",
            "pydantic_prefix",
            "key_env",
            "base_url_env",
            "default_base_url",
            "models_path",
            "auth_header",
            "auth_prefix",
            "presets",
        }
        for key, cfg in PROVIDER_CONFIGS.items():
            missing = required - set(cfg.keys())
            assert not missing, f"Provider {key} missing fields: {missing}"

    def test_openai_compatible_providers_use_openai_prefix(self):
        from src.tui.providers import PROVIDER_CONFIGS

        for key in ("deepseek", "openrouter", "xiaomi_mimo", "groq", "custom"):
            assert PROVIDER_CONFIGS[key]["pydantic_prefix"] == "openai", (
                f"{key} should use openai prefix for Pydantic AI compatibility"
            )

    def test_models_endpoint_builds_url(self):
        from src.tui.providers import models_endpoint

        url = models_endpoint("deepseek")
        assert url == "https://api.deepseek.com/v1/models"

    def test_models_endpoint_with_custom_base_url(self):
        from src.tui.providers import models_endpoint

        url = models_endpoint("custom", "https://my-proxy.com")
        assert url == "https://my-proxy.com/v1/models"

    def test_models_endpoint_empty_for_no_base_url(self):
        from src.tui.providers import models_endpoint

        url = models_endpoint("custom")  # Custom has no default base URL
        assert url == ""

    def test_models_endpoint_xiaomi_mimo(self):
        from src.tui.providers import models_endpoint

        url = models_endpoint("xiaomi_mimo")
        assert url == "https://api.xiaomimimo.com/v1/models"

    def test_provider_labels_for_dropdown(self):
        from src.tui.providers import provider_labels

        labels = provider_labels()
        assert all(isinstance(label, tuple) and len(label) == 2 for label in labels)
        keys = [k for _, k in labels]
        assert "anthropic" in keys
        assert "deepseek" in keys


# ---------------------------------------------------------------------------
# Model fetcher tests.
# ---------------------------------------------------------------------------


class TestFetchAvailableModels:
    @pytest.mark.asyncio
    async def test_fetch_parses_openai_format(self):
        """Mock httpx to return OpenAI-style /models response."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"id": "gpt-4o"},
                {"id": "gpt-4o-mini"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from src.tui.providers import fetch_available_models

            models = await fetch_available_models("openai", "sk-test")
            assert models == ["gpt-4o", "gpt-4o-mini"]

    @pytest.mark.asyncio
    async def test_fetch_handles_auth_error(self):
        """RuntimeError on 401."""
        from unittest.mock import AsyncMock, MagicMock, patch

        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_resp
        )

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from src.tui.providers import fetch_available_models

            with pytest.raises(RuntimeError, match="Authentication failed"):
                await fetch_available_models("openai", "bad-key")

    @pytest.mark.asyncio
    async def test_fetch_raises_on_missing_base_url(self):
        from src.tui.providers import fetch_available_models

        with pytest.raises(RuntimeError, match="base URL"):
            await fetch_available_models("custom", "key")

    @pytest.mark.asyncio
    async def test_fetch_raises_on_empty_response(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from src.tui.providers import fetch_available_models

            with pytest.raises(RuntimeError, match="No models found"):
                await fetch_available_models("openai", "sk-test")


# ---------------------------------------------------------------------------
# TUI integration — app creates adapter from settings.
# ---------------------------------------------------------------------------


class TestAppLLMIntegration:
    def test_create_adapter_returns_none_when_unconfigured(self):
        from src.tui.app import CepheusApp
        from src.tui.settings import LLMSettings

        app = CepheusApp(saves_dir="/tmp/test-saves", settings_dir="/tmp/test-settings")
        app.llm_settings = LLMSettings()  # unconfigured
        assert app.create_llm_adapter() is None

    def test_create_adapter_when_configured(self):
        from src.tui.app import CepheusApp
        from src.tui.settings import LLMSettings

        app = CepheusApp(saves_dir="/tmp/test-saves", settings_dir="/tmp/test-settings")
        app.llm_settings = LLMSettings(
            provider="anthropic",
            model="claude-sonnet-5",
            api_key="sk-test",
        )
        adapter = app.create_llm_adapter()
        assert adapter is not None
        assert adapter.llm_configured

    def test_apply_llm_env_sets_env_vars(self):
        from src.tui.app import CepheusApp
        from src.tui.settings import LLMSettings

        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            app = CepheusApp(saves_dir="/tmp/test-saves", settings_dir="/tmp/test-settings")
            settings = LLMSettings(
                provider="anthropic",
                api_key="sk-from-settings",
                base_url="https://custom.example.com",
            )
            app.apply_llm_settings(settings)
            assert os.environ.get("ANTHROPIC_API_KEY") == "sk-from-settings"
            assert os.environ.get("ANTHROPIC_BASE_URL") == "https://custom.example.com"
        finally:
            if old_key is not None:
                os.environ["ANTHROPIC_API_KEY"] = old_key
            else:
                os.environ.pop("ANTHROPIC_API_KEY", None)
                os.environ.pop("ANTHROPIC_BASE_URL", None)


# ---------------------------------------------------------------------------
# Regression: saving settings with an invalid base_url doesn't crash.
# ---------------------------------------------------------------------------


class TestSettingsScreenSaveValidation:
    """_do_save catches ValidationError instead of crashing the screen.

    Before the fix, entering a non-http(s) base_url and pressing Ctrl+S
    raised an uncaught pydantic ValidationError.
    """

    async def test_invalid_base_url_does_not_crash(self, tmp_path):
        """Saving with a bad base_url shows an error, not a crash."""
        from textual.widgets import Input

        from src.tui.app import CepheusApp
        from src.tui.screens.settings_screen import SettingsScreen

        app = CepheusApp(saves_dir=tmp_path / "saves", settings_dir=tmp_path / "settings")
        async with app.run_test() as pilot:
            app.push_screen(SettingsScreen())
            await pilot.pause()

            screen = app.screen
            # Enter a bad base URL (ftp scheme is rejected by the validator).
            base_url_input = screen.query_one("#base-url-input", Input)
            base_url_input.value = "ftp://bad.example.com"
            await pilot.pause()

            # Trigger save — should not raise.
            screen._do_save()
            await pilot.pause()

            # App should still be running (no crash).
            assert app._exit is False
