"""Meta + config endpoint contract tests (M0.6a)."""

from __future__ import annotations


class TestHealth:
    def test_health_shape(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["contract_versions"] == {"chargen": 1, "adventure": 1}


class TestErrorEnvelope:
    def test_unknown_route_uses_envelope(self, client):
        resp = client.get("/v1/sessions/nope")
        assert resp.status_code == 404
        body = resp.json()
        assert "error" in body and "code" in body["error"] and "message" in body["error"]
        # Task 8 adds GET /v1/sessions/{id}; unknown ids then return the
        # precise code "session_not_found".


class TestLlmStatus:
    def test_unconfigured_by_default(self, client):
        resp = client.get("/v1/llm/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is False
        assert body["model"] is None
        assert body["key_backend"] in ("", "file", "keyring")


class TestConfig:
    def test_packs(self, client):
        resp = client.get("/v1/config/packs")
        assert resp.status_code == 200
        packs = {p["id"]: p for p in resp.json()["packs"]}
        assert "scifi" in packs and "fantasy" in packs
        scifi = packs["scifi"]
        assert scifi["career_count"] == 25
        assert scifi["has_cascades"] is True
        assert scifi["theme"] == {"motif": "✦", "accent": "amber", "ambience": ["meteors", "birds"]}
        assert scifi["has_intro"] is True

    def test_rulesets(self, client):
        resp = client.get("/v1/config/rulesets")
        assert resp.status_code == 200
        rulesets = resp.json()["rulesets"]
        cepheus = next(r for r in rulesets if r["id"] == "cepheus")
        assert cepheus["resolution_profiles"] == ["classic", "narrative"]
        assert sorted(cepheus["death_modes"]) == ["checkpoint", "ironman", "narrative"]
        assert "average" in cepheus["difficulty_ladder"]

    def test_providers(self, client):
        resp = client.get("/v1/config/providers")
        assert resp.status_code == 200
        providers = {p["id"]: p for p in resp.json()["providers"]}
        assert "anthropic" in providers
        assert providers["anthropic"]["label"] == "Anthropic"
        assert "claude-sonnet-5" in providers["anthropic"]["presets"]
