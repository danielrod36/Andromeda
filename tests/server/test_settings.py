"""Settings endpoint contract tests (M0.6c + M0.7)."""

from __future__ import annotations

import json


class TestGetSettings:
    def test_defaults(self, client):
        body = client.get("/v1/settings/llm").json()
        assert body["provider"] == "anthropic"
        assert body["is_configured"] is False
        assert body["key_tail"] == ""
        assert body["key_backend"] in ("", "file", "keyring")


class TestPutSettings:
    def test_put_stores_key_outside_the_file(self, client, tmp_path):
        resp = client.put(
            "/v1/settings/llm",
            json={
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "api_key": "sk-ant-testkey99",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["is_configured"] is True
        assert body["key_tail"] == "…ey99"
        assert body["key_backend"] in ("file", "keyring")
        # The settings file on disk never contains the key (M0.7).
        raw = json.loads((tmp_path / "settings" / "llm.json").read_text())
        assert not raw.get("api_key")
        # And the response never echoes the key.
        assert "sk-ant-testkey99" not in resp.text

    def test_put_without_key_keeps_stored_key(self, client):
        client.put(
            "/v1/settings/llm",
            json={"provider": "anthropic", "model": "m", "api_key": "sk-keepme1"},
        )
        body = client.put("/v1/settings/llm", json={"provider": "anthropic", "model": "m2"}).json()
        assert body["key_tail"] == "…pme1"

    def test_put_empty_key_deletes(self, client):
        client.put(
            "/v1/settings/llm",
            json={"provider": "anthropic", "model": "m", "api_key": "sk-deleteme1"},
        )
        body = client.put(
            "/v1/settings/llm", json={"provider": "anthropic", "model": "m", "api_key": ""}
        ).json()
        assert body["key_tail"] == ""
        assert body["is_configured"] is False

    def test_bad_base_url_is_422(self, client):
        resp = client.put("/v1/settings/llm", json={"base_url": "ftp://nope"})
        assert resp.status_code == 422


class TestTestEndpoint:
    def test_no_key_returns_ok_false(self, client):
        body = client.post("/v1/settings/llm/test").json()
        assert body["ok"] is False
        assert body["error"]
