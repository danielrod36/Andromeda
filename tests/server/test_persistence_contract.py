"""Autosave cadence + stale-write contract tests (M0.6c, spec §5)."""

from __future__ import annotations

from tests.server.conftest import write_save


def _create(client, name="The Ruuth Run"):
    resp = client.post(
        "/v1/sessions", json={"kind": "chargen", "name": name, "seed": 42, "pack_id": "scifi"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["session"]


class TestAutosaveCadence:
    def test_every_beat_updates_the_autosave(self, client, tmp_path):
        session = _create(client)
        import json

        auto = tmp_path / "saves" / "The_Ruuth_Run.autosave.json"
        before = json.loads(auto.read_text())
        events_before = len(before["events"])

        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})

        after = json.loads(auto.read_text())
        assert len(after["events"]) > events_before

    def test_checkpoint_mode_writes_sidecar(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara", death_mode="checkpoint")
        session = client.post(
            "/v1/sessions",
            json={"kind": "adventure", "name": "x", "from_save": "Mara"},
        ).json()["session"]
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "accept_mission"})
        # Scene start takes the snapshot; autosave persists it as sidecar.
        sidecar = tmp_path / "saves" / "Mara.autosave.json.checkpoint.json"
        assert sidecar.exists()


class TestStaleWrite:
    def test_external_modification_conflicts(self, client, tmp_path):
        # Create writes the autosave (registry.create_chargen autosaves).
        session = _create(client)
        auto = tmp_path / "saves" / "The_Ruuth_Run.autosave.json"
        # Another "session" writes to the file — the session's stored hash
        # no longer matches the disk.
        auto.write_text(auto.read_text() + "\n")

        # roll_pool is still the first (unused) choice, so the choice itself
        # is valid; the conflict must surface at autosave time, after the
        # mutation — proving stale-write detection guards every beat.
        resp = client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "save_conflict"
