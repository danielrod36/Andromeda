"""Save endpoint contract tests (M0.6c)."""

from __future__ import annotations

from tests.server.conftest import write_save


def _create(client, name="The Ruuth Run"):
    resp = client.post(
        "/v1/sessions", json={"kind": "chargen", "name": name, "seed": 42, "pack_id": "scifi"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["session"]


class TestListSaves:
    def test_autosave_flagged_with_base_name(self, client, tmp_path):
        _create(client)
        saves = client.get("/v1/saves").json()["saves"]
        auto = next(s for s in saves if s["autosave"])
        assert auto["base_name"] == "The_Ruuth_Run"
        assert auto["theme_pack"] == "scifi"

    def test_empty_when_no_saves(self, client):
        assert client.get("/v1/saves").json()["saves"] == []


class TestManualSave:
    def test_save_writes_main_file_and_retargets(self, client, tmp_path):
        session = _create(client)
        resp = client.post(f"/v1/sessions/{session['id']}/save", json={"name": "Mara Voss"})
        assert resp.status_code == 200, resp.text
        assert (tmp_path / "saves" / "Mara_Voss.json").exists()
        # Subsequent beats autosave under the new name.
        client.post(f"/v1/sessions/{session['id']}/choose", json={"option_id": "roll_pool"})
        assert (tmp_path / "saves" / "Mara_Voss.autosave.json").exists()


class TestDuplicateDeleteExportImport:
    def test_duplicate(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara")
        resp = client.post("/v1/saves/Mara/duplicate", json={"new_name": "Mara Copy"})
        assert resp.status_code == 201, resp.text
        assert (tmp_path / "saves" / "Mara_Copy.json").exists()

    def test_delete_removes_main_autosave_and_sidecars(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara")
        write_save(tmp_path / "saves", "Mara.autosave")
        resp = client.delete("/v1/saves/Mara")
        assert resp.status_code == 200
        assert not list((tmp_path / "saves").glob("Mara*"))

    def test_export_returns_document(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara")
        resp = client.get("/v1/saves/Mara/export")
        assert resp.status_code == 200
        assert resp.json()["character"]["name"] == "TestHero"

    def test_import_round_trip(self, client, tmp_path):
        write_save(tmp_path / "saves", "Mara")
        document = client.get("/v1/saves/Mara/export").json()
        resp = client.post("/v1/saves/import", json={"name": "Imported", "document": document})
        assert resp.status_code == 201, resp.text
        assert (tmp_path / "saves" / "Imported.json").exists()

    def test_import_invalid_document_is_422(self, client):
        resp = client.post("/v1/saves/import", json={"name": "Bad", "document": {"not": "a save"}})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "invalid_save"

    def test_path_traversal_rejected(self, client):
        resp = client.get("/v1/saves/..%2F..%2Fetc/export")
        assert resp.status_code in (404, 422)
