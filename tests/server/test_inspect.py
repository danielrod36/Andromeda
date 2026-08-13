"""Introspection endpoint contract tests (M0.6c)."""

from __future__ import annotations

from tests.server.conftest import write_save


def _create(client, name="The Ruuth Run"):
    resp = client.post(
        "/v1/sessions", json={"kind": "chargen", "name": name, "seed": 42, "pack_id": "scifi"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["session"]


class TestSheet:
    def test_sheet_carries_dms_and_display_names(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara")
        session = client.post(
            "/v1/sessions", json={"kind": "adventure", "name": "x", "from_save": "Mara"}
        ).json()["session"]
        body = client.get(f"/v1/sessions/{session['id']}/sheet").json()
        assert body["character"]["name"] == "TestHero"
        assert set(body["characteristic_dms"]) == {"STR", "DEX", "END", "INT", "EDU", "SOC"}
        assert body["characteristic_dms"]["DEX"] == 1  # DEX 9 → DM +1
        assert "Gun Combat" in body["skill_names"]


class TestRecap:
    def test_recap_shape(self, client):
        session = _create(client)
        body = client.get(f"/v1/sessions/{session['id']}/recap").json()
        assert body["source"] == "template"
        assert isinstance(body["lines"], list)


class TestAudit:
    def test_audit_rows_and_filters(self, client):
        session = _create(client)
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        body = client.get(f"/v1/sessions/{session['id']}/audit").json()
        assert body["total_events"] > 0
        roll_rows = [r for r in body["rows"] if r["kind"] == "roll"]
        assert roll_rows and roll_rows[0]["stream"] == "lifepath"
        # Stream filter.
        filtered = client.get(
            f"/v1/sessions/{session['id']}/audit", params={"stream": "oracle"}
        ).json()
        assert all(r["stream"] == "oracle" for r in filtered["rows"] if r["kind"] == "roll")

    def test_since_filter(self, client):
        session = _create(client)
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        total = client.get(f"/v1/sessions/{session['id']}/audit").json()["total_events"]
        # seq is 0-based and assigned at append time, so `since = total - 1`
        # matches exactly the last event.
        filtered = client.get(
            f"/v1/sessions/{session['id']}/audit", params={"since": total - 1}
        ).json()
        assert filtered["filtered_count"] == 1


class TestLlmContext:
    def test_no_prohibited_keys(self, client):
        session = _create(client)
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        body = client.get(f"/v1/sessions/{session['id']}/llm-context").json()
        assert "view" in body and "never_includes" in body
        import json

        raw = json.dumps(body["view"])
        for key in ("roll", "rolls", "rng", "seed", "events", "stream"):
            assert f'"{key}"' not in raw


class TestOdds:
    def test_narrative_profile_tiers(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara")
        resp = client.post(
            "/v1/sessions",
            json={"kind": "adventure", "name": "x", "from_save": "Mara"},
        )
        session = resp.json()["session"]
        body = client.post(
            f"/v1/sessions/{session['id']}/odds",
            json={"skill": "Gun Combat", "characteristic": "DEX", "difficulty": "average"},
        ).json()
        assert body["profile"] == "narrative"
        assert body["strong_hit_probability"] is not None
        assert body["odds_line"]
        total = (
            body["strong_hit_probability"] + body["weak_hit_probability"] + body["miss_probability"]
        )
        assert abs(total - 1.0) < 1e-9


class TestHash:
    def test_hash_stable_then_changes(self, client):
        session = _create(client)
        first = client.get(f"/v1/sessions/{session['id']}/hash").json()["sha256"]
        assert first == client.get(f"/v1/sessions/{session['id']}/hash").json()["sha256"]
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        assert client.get(f"/v1/sessions/{session['id']}/hash").json()["sha256"] != first


class TestVerify:
    def test_verify_is_501(self, client):
        session = _create(client)
        resp = client.post(f"/v1/sessions/{session['id']}/verify")
        assert resp.status_code == 501
        assert resp.json()["error"]["code"] == "not_implemented"


class TestMemorial:
    def test_memorial_for_dead_character(self, client, tmp_path):
        from src.engine.commands import Engine, SetCharacterDeadCommand
        from src.engine.persistence import load, save

        # Author a dead-character ironman save through the funnel.
        write_save(tmp_path / "saves", "Dead", death_mode="ironman")
        state = load(tmp_path / "saves" / "Dead.json")
        engine = Engine(state)
        engine.apply(SetCharacterDeadCommand(reason="a failed life-threatening check"))
        save(engine.state, tmp_path / "saves" / "Dead.json")

        dead = client.post(
            "/v1/sessions", json={"kind": "adventure", "name": "y", "from_save": "Dead"}
        ).json()["session"]
        assert dead["phase"] == "game_over"
        body = client.get(f"/v1/sessions/{dead['id']}/memorial").json()
        assert body["data"]["character_name"] == "TestHero"
        assert any("In memoriam" in line for line in body["obituary"])
