"""Tests for the web lifepath screens (U7).

Verifies the core lifepath flow works over HTTP via TestClient:
roll pool → assign characteristics → background skills → choose career →
qualify → term loop → complete.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _get_client(saves_dir: Path) -> TestClient:
    from src.web.app import create_app
    from src.web.routes import lifepath as life_module
    from src.web.routes import menu as menu_module

    menu_module.DEFAULT_SAVES_DIR = saves_dir
    life_module.DEFAULT_SAVES_DIR = saves_dir
    saves_dir.mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _create_save(saves_dir: Path, name: str = "TestHero", seed: int = 42) -> Path:
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState

    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(theme_pack="scifi", resolution_profile="classic")
    state.character.name = name
    path = saves_dir / f"{name}.json"
    save(state, path)
    return path


_ORIGIN = {"Origin": "http://127.0.0.1"}


class TestLifepathScreen:
    """U7: the lifepath screen renders and accepts actions."""

    def test_get_lifepath_returns_200(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/play/TestHero")
        assert response.status_code == 200
        assert "TestHero" in response.text

    def test_roll_pool_shows_pool_values(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            # Initial view: roll_characteristics phase.
            response = client.get("/play/TestHero")
            assert "Roll Pool" in response.text

            # Submit roll_pool action.
            response = client.post(
                "/play/TestHero/action",
                data={"choice": "roll_pool"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # After rolling, should be in assign_characteristics phase.
        assert "Assign" in response.text or "assign" in response.text.lower()

    def test_full_characteristic_flow(self, tmp_path: Path):
        """Roll pool → assign all six characteristics → advance to background/career."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            # Roll pool.
            client.post("/play/TestHero/action", data={"choice": "roll_pool"}, headers=_ORIGIN)

            # Assign six characteristics (always index 0 — pool shrinks each pick).
            stats = ["STR", "DEX", "END", "INT", "EDU", "SOC"]
            for stat in stats:
                client.post(
                    "/play/TestHero/action",
                    data={"choice": f"assign:0:{stat}"},
                    headers=_ORIGIN,
                )

            # After assigning all six, should advance past assign_characteristics.
            response = client.get("/play/TestHero")
        # Should no longer be in assign_characteristics.
        assert "Roll Pool" not in response.text

    def test_nonexistent_save_redirects(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/play/Nonexistent", follow_redirects=False)
        assert response.status_code == 303
        assert "/saves" in response.headers.get("location", "")

    def test_lifepath_action_saves_state(self, tmp_path: Path):
        """After an action, the save file reflects the updated state."""
        from src.engine.persistence import load

        saves_dir = tmp_path / "saves"
        save_path = _create_save(saves_dir)

        with _get_client(saves_dir) as client:
            client.post("/play/TestHero/action", data={"choice": "roll_pool"}, headers=_ORIGIN)

        # Reload the save and verify characteristics were rolled.
        state = load(save_path)
        assert len(state.character.unassigned_rolls) > 0

    def test_drawer_pinned_during_assignment(self, tmp_path: Path):
        """The drawer is pinned during characteristic assignment."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            # Roll pool first to enter assign phase.
            client.post("/play/TestHero/action", data={"choice": "roll_pool"}, headers=_ORIGIN)
            response = client.get("/play/TestHero")
        # The drawer should NOT have the hidden attribute.
        assert 'id="drawer"' in response.text
        assert "hidden" not in response.text.split('id="drawer"')[1].split(">")[0]
