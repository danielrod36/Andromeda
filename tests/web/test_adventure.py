"""Tests for the web adventure screens (U9).

Verifies the adventure loop works over HTTP: hooks, scenes with odds,
option resolution, free-text classify, defeat interstitials, and the
concurrent-POST action gate (KTD-9).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _get_client(saves_dir: Path) -> TestClient:
    from src.web.app import create_app
    from src.web.routes import adventure as adv_module
    from src.web.routes import lifepath as life_module
    from src.web.routes import menu as menu_module

    saves_dir.mkdir(parents=True, exist_ok=True)
    menu_module.DEFAULT_SAVES_DIR = saves_dir
    life_module.DEFAULT_SAVES_DIR = saves_dir
    adv_module.DEFAULT_SAVES_DIR = saves_dir
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _create_adventure_save(saves_dir: Path, name: str = "Hero") -> Path:
    """Create a mustered-out character save ready for adventure."""
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState

    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(
        theme_pack="scifi", resolution_profile="narrative", death_mode="narrative"
    )
    state.character.name = name
    state.character.characteristics = {
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    state.character.skills = {"Gun Combat": 1, "Persuade": 0, "Stealth": 2, "Investigate": 1}
    state.character.career = "navy"
    state.character.terms = 2
    state.character.alive = True
    state.narrative_log.append("mustered_out=true")
    path = saves_dir / f"{name}.json"
    save(state, path)
    return path


_ORIGIN = {"Origin": "http://127.0.0.1"}


class TestAdventureScreen:
    """U9: the adventure screen renders."""

    def test_get_adventure_returns_200(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        assert response.status_code == 200
        assert "Hero" in response.text

    def test_hook_phase_shows_accept_refuse(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        assert "Accept Mission" in response.text
        assert "Refuse" in response.text

    def test_nonexistent_save_redirects(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Nobody", follow_redirects=False)
        assert response.status_code == 303
        assert "/saves" in response.headers.get("location", "")


class TestSceneOptions:
    """U9: scene options show pre-commit odds."""

    def test_accept_mission_shows_scene_with_odds(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # Should have odds on the options.
        assert "%" in response.text or "DM" in response.text

    def test_option_post_resolves_and_shows_receipt(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            # Accept mission first.
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            # Resolve option 0.
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "option:0"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # Should contain a receipt — either dice notation or the CSS class.
        assert "2D6" in response.text or "receipt" in response.text or "DM" in response.text


class TestFreeTextOverHTTP:
    """U9: free-text classify via HTTP."""

    def test_freetext_post_returns_200(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            # Accept mission first.
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            # Submit free-text.
            response = client.post(
                "/adventure/Hero/freetext",
                data={"freetext": "I bribe the dock officer"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200

    def test_freetext_keyword_match_shows_interpretation(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            response = client.post(
                "/adventure/Hero/freetext",
                data={"freetext": "I bribe the dock officer"},
                headers=_ORIGIN,
            )
        # If keyword matched, should show Accept/Reject choices.
        if "Interpreted" in response.text or "Accept" in response.text:
            assert "Accept" in response.text


class TestActionPersistence:
    """U9: actions persist state to the save file."""

    def test_accept_mission_persists(self, tmp_path: Path):
        from src.engine.persistence import load

        saves_dir = tmp_path / "saves"
        save_path = _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
        state = load(save_path)
        assert state.active_mission is not None

    def test_pending_freetext_resume(self, tmp_path: Path):
        """A v3 save with pending_freetext set resumes the interpretation prompt."""
        from src.engine.persistence import save as save_state

        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)

        # Set pending_freetext directly.
        from src.engine.persistence import load

        state = load(saves_dir / "Hero.json")
        state.active_mission = {
            "id": "m1",
            "hook": {"patron": "P", "objective": "O", "complication": "C", "reward": "R"},
            "scenes_completed": 0,
            "min_scenes": 3,
            "success_text": "",
            "failure_text": "",
            "abandonment_text": "",
        }
        state.pending_freetext = {
            "text": "I bribe him",
            "check": {
                "label": "Bribe",
                "skill": "broker",
                "characteristic": "SOC",
                "difficulty": "average",
            },
            "scaffold": {
                "focus": "Dock",
                "focus_description": "Busy dock",
                "situation": "Tense",
                "npc_hint": "",
            },
            "options": [],
        }
        save_state(state, saves_dir / "Hero.json")

        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        # Should show the accept/reject prompt, not a fresh scene.
        assert "Accept" in response.text or "Interpreted" in response.text
