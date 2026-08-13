"""Gameplay endpoint contract tests (M0.6b)."""

from __future__ import annotations

import json


def _create(client, name="The Ruuth Run", **overrides):
    body = {"kind": "chargen", "name": name, "seed": 42, "pack_id": "scifi"}
    body.update(overrides)
    resp = client.post("/v1/sessions", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["session"]


class TestCreateAndView:
    def test_create_chargen(self, client):
        session = _create(client)
        assert session["kind"] == "chargen"
        assert session["phase"] == "roll_characteristics"
        assert session["contract_version"] == 1
        assert session["view"]["options"][0]["option_id"] == "roll_pool"

    def test_create_writes_autosave(self, client, tmp_path):
        _create(client)
        assert (tmp_path / "saves" / "The_Ruuth_Run.autosave.json").exists()

    def test_list_and_get(self, client):
        session = _create(client)
        listing = client.get("/v1/sessions").json()["sessions"]
        assert [s["id"] for s in listing] == [session["id"]]
        fetched = client.get(f"/v1/sessions/{session['id']}").json()["session"]
        assert fetched["phase"] == "roll_characteristics"

    def test_delete(self, client):
        session = _create(client)
        assert client.delete(f"/v1/sessions/{session['id']}").status_code == 204
        resp = client.get(f"/v1/sessions/{session['id']}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "session_not_found"


class TestChoose:
    def test_choose_returns_structured_events(self, client):
        session = _create(client)
        resp = client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["result"]["contract_version"] == 1
        # Structured roll events power the client's graphical readouts (D5).
        rolls = [e for e in body["events"] if e["kind"] == "roll"]
        assert rolls, "expected roll events in the choose response"
        assert rolls[0]["roll"]["rolls"]  # pip values present
        assert rolls[0]["roll"]["stream"] == "lifepath"

    def test_choose_invalid_option_is_422_verbatim(self, client):
        session = _create(client)
        resp = client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "nope"})
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "invalid_choice"
        assert "nope" in body["error"]["message"]  # engine message verbatim


class TestName:
    def test_set_name(self, client):
        session = _create(client)
        resp = client.post(f"/v1/sessions/{session['id']}/name", json={"name": "Mara Voss"})
        assert resp.status_code == 200
        state_resp = client.get(f"/v1/sessions/{session['id']}/sheet")
        assert state_resp.json()["character"]["name"] == "Mara Voss"


class TestNarrate:
    @staticmethod
    def _blocks(resp) -> list[dict]:
        return [json.loads(line) for line in resp.text.splitlines() if line.strip()]

    def test_world_intro_template_streams_blocks(self, client):
        session = _create(client)
        resp = client.post(f"/v1/sessions/{session['id']}/narrate", json={"beat": "world_intro"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        blocks = self._blocks(resp)
        assert blocks[-1]["type"] == "done"
        narration = " ".join(b["content"] for b in blocks if b["type"] == "narration")
        assert "frontier" in narration.lower()  # the scifi pack intro text

    def test_world_intro_replays_without_recalling(self, client):
        session = _create(client)
        first = self._blocks(
            client.post(f"/v1/sessions/{session['id']}/narrate", json={"beat": "world_intro"})
        )
        second = self._blocks(
            client.post(f"/v1/sessions/{session['id']}/narrate", json={"beat": "world_intro"})
        )
        first_text = [b["content"] for b in first if b["type"] == "narration"]
        second_text = [b["content"] for b in second if b["type"] == "narration"]
        assert first_text == second_text  # replayed record, byte-identical

    def test_steering_is_recorded(self, client, tmp_path):
        session = _create(client)
        client.post(f"/v1/sessions/{session['id']}/narrate", json={"beat": "world_intro"})
        resp = client.post(
            f"/v1/sessions/{session['id']}/narrate",
            json={"beat": "world_intro", "steering": "lean into the loneliness"},
        )
        assert resp.status_code == 200
        # Steering and shipped prose are canonical funnel events — visible in
        # the autosave document (the /audit endpoint lands in Task 10).
        auto = json.loads((tmp_path / "saves" / "The_Ruuth_Run.autosave.json").read_text())
        kinds = {e["command_type"] for e in auto["events"]}
        assert "record_story_direction" in kinds
        assert "record_narration" in kinds

    def test_scene_beat_after_choose(self, client):
        session = _create(client)
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        resp = client.post(f"/v1/sessions/{session['id']}/narrate", json={"beat": "chargen_beat"})
        assert resp.status_code == 200
        blocks = self._blocks(resp)
        assert blocks[-1]["type"] == "done"


class TestSuggest:
    def test_suggest_without_advisor_is_422(self, client):
        session = _create(client)
        resp = client.post(f"/v1/sessions/{session['id']}/suggest")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "advisor_unavailable"


class TestPromote:
    def test_promote_before_completion_is_422(self, client):
        session = _create(client)
        resp = client.post(f"/v1/sessions/{session['id']}/promote")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "invalid_phase"

    def test_promote_non_chargen_is_422(self, client, tmp_path):
        from tests.server.conftest import write_save

        write_save(tmp_path / "saves", "Mara")
        created = _create(client, name="x", kind="adventure", from_save="Mara")
        assert created["kind"] == "adventure"
        resp = client.post(f"/v1/sessions/{created['id']}/promote")
        assert resp.status_code == 422


class TestAdventureFlow:
    def test_resume_adventure_and_play_a_scene(self, client, tmp_path):
        from tests.server.conftest import write_save

        write_save(tmp_path / "saves", "Mara")
        session = _create(client, name="x", kind="adventure", from_save="Mara")
        assert session["kind"] == "adventure"
        assert session["phase"] == "hook_offered"

        resp = client.post(
            f"/v1/sessions/{session['id']}/choose", json={"option_id": "accept_mission"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["session"]["phase"] == "scene_active"

        # B4 through the wire: the dimmed push is a 422, not a crash.
        resp = client.post(
            f"/v1/sessions/{session['id']}/choose", json={"option_id": "push_for_ending"}
        )
        assert resp.status_code == 422

    def test_freetext_outside_scene_is_422(self, client, tmp_path):
        from tests.server.conftest import write_save

        write_save(tmp_path / "saves", "Mara")
        session = _create(client, name="x", kind="adventure", from_save="Mara")
        resp = client.post(f"/v1/sessions/{session['id']}/freetext", json={"text": "I look around"})
        assert resp.status_code == 422  # hook phase — no scaffold to interpret
