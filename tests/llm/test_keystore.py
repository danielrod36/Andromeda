"""Key storage tests (M0.7): keychain primary, owner-only file fallback."""

from __future__ import annotations

import json

from src.llm.keystore import FileKeyStore, get_keystore, masked_tail
from src.llm.settings import (
    LLMSettings,
    load_settings,
    save_settings,
)


class TestFileKeyStore:
    def test_round_trip_and_permissions(self, tmp_path):
        store = FileKeyStore(tmp_path)
        store.set("anthropic", "sk-ant-secret1234")
        assert store.get("anthropic") == "sk-ant-secret1234"
        mode = (tmp_path / "llm.keys.json").stat().st_mode & 0o777
        assert mode == 0o600

    def test_missing_key_returns_empty(self, tmp_path):
        assert FileKeyStore(tmp_path).get("anthropic") == ""

    def test_delete(self, tmp_path):
        store = FileKeyStore(tmp_path)
        store.set("openai", "sk-x")
        store.delete("openai")
        assert store.get("openai") == ""

    def test_backend_name(self, tmp_path):
        assert FileKeyStore(tmp_path).backend_name == "file"


class TestMaskedTail:
    def test_mask_shows_last_four_only(self):
        assert masked_tail("sk-ant-secret1234") == "…1234"

    def test_short_key_masks_fully(self):
        assert masked_tail("abc") == "…"

    def test_empty(self):
        assert masked_tail("") == ""


class TestSettingsIntegration:
    def test_saved_file_never_contains_key(self, tmp_path):
        settings = LLMSettings(provider="anthropic", model="claude-sonnet-5", api_key="sk-ant-9999")
        save_settings(settings, tmp_path)
        raw = json.loads((tmp_path / "llm.json").read_text())
        assert "api_key" not in raw or not raw["api_key"]
        assert raw["key_backend"] in ("file", "keyring")

    def test_load_resolves_key_back(self, tmp_path):
        settings = LLMSettings(provider="anthropic", model="claude-sonnet-5", api_key="sk-ant-9999")
        save_settings(settings, tmp_path)
        loaded = load_settings(tmp_path)
        assert loaded.api_key == "sk-ant-9999"
        assert loaded.is_configured

    def test_legacy_plaintext_migrates_on_load(self, tmp_path):
        # A v0.1 file: key in plaintext, no key_backend.
        (tmp_path / "llm.json").write_text(
            json.dumps({"provider": "anthropic", "model": "m", "api_key": "sk-legacy-777"})
        )
        loaded = load_settings(tmp_path)
        assert loaded.api_key == "sk-legacy-777"
        # The file was rewritten without the key.
        raw = json.loads((tmp_path / "llm.json").read_text())
        assert not raw.get("api_key")
        assert raw.get("key_backend") in ("file", "keyring")

    def test_get_keystore_returns_a_working_store(self, tmp_path):
        store = get_keystore(tmp_path)
        store.set("p", "s3cr3t")
        assert store.get("p") == "s3cr3t"
        assert store.backend_name in ("file", "keyring")
