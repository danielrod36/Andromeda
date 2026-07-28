"""Tests for LLM settings persistence and TUI integration."""
import json
import os
from pathlib import Path

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

    def test_env_overrides_openai(self):
        s = LLMSettings(provider="openai", api_key="sk-oai", base_url="")
        env = s.env_overrides()
        assert env["OPENAI_API_KEY"] == "sk-oai"
        assert "OPENAI_BASE_URL" not in env

    def test_env_overrides_custom_provider(self):
        s = LLMSettings(provider="custom", api_key="key", base_url="http://localhost:8080")
        env = s.env_overrides()
        assert env["API_KEY"] == "key"
        assert env["BASE_URL"] == "http://localhost:8080"

    def test_env_overrides_empty_when_no_key(self):
        s = LLMSettings()
        assert s.env_overrides() == {}


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
