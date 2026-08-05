"""Tests for web menu, config, saves, and resume routes (U6)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient


@contextmanager
def _get_client(saves_dir: Path | None = None) -> Iterator[TestClient]:
    """Create a test client with an isolated saves directory.

    Restores ``DEFAULT_SAVES_DIR`` on exit so tests can't leak paths into
    later tests that call this helper without an explicit ``saves_dir``.
    """
    from src.web.app import create_app
    from src.web.routes import menu as menu_module

    original = menu_module.DEFAULT_SAVES_DIR
    if saves_dir is not None:
        menu_module.DEFAULT_SAVES_DIR = saves_dir
        saves_dir.mkdir(parents=True, exist_ok=True)

    try:
        with TestClient(create_app(), base_url="http://127.0.0.1") as client:
            yield client
    finally:
        menu_module.DEFAULT_SAVES_DIR = original


class TestMainMenu:
    """U6: the main menu renders."""

    def test_menu_page_returns_200(self, tmp_path: Path):
        with _get_client(tmp_path / "saves") as client:
            response = client.get("/menu")
        assert response.status_code == 200
        assert "Andromeda" in response.text

    def test_menu_shows_new_campaign_link(self, tmp_path: Path):
        with _get_client(tmp_path / "saves") as client:
            response = client.get("/menu")
        assert "/config" in response.text

    def test_menu_shows_load_save_when_saves_exist(self, tmp_path: Path):
        # Create a save first.
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        state = GameState.new(seed=42)
        state.campaign = CampaignConfig()
        state.character.name = "Hero"
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        save(state, saves_dir / "Hero.json")

        with _get_client(saves_dir) as client:
            response = client.get("/menu")
        assert "/saves" in response.text


class TestCampaignConfig:
    """U6: campaign config form and submission."""

    def test_config_form_returns_200(self, tmp_path: Path):
        with _get_client(tmp_path / "saves") as client:
            response = client.get("/config")
        assert response.status_code == 200
        assert "Character Name" in response.text

    def test_config_post_creates_campaign(self, tmp_path: Path):
        """Valid config POST creates a save and redirects to play route."""
        saves_dir = tmp_path / "saves"
        with _get_client(saves_dir) as client:
            response = client.post(
                "/config",
                data={
                    "name": "TestHero",
                    "seed": "42",
                    "theme_pack": "scifi",
                    "resolution_profile": "narrative",
                    "death_mode": "narrative",
                },
                headers={"Origin": "http://127.0.0.1"},
                follow_redirects=False,
            )
        # Should redirect (303) to the play route.
        assert response.status_code == 303
        assert "/play/" in response.headers.get("location", "")

        # The save file should exist.
        assert (saves_dir / "TestHero.json").exists()

    def test_config_post_invalid_name_rerenders(self, tmp_path: Path):
        """Missing name re-renders the form with an error."""
        with _get_client(tmp_path / "saves") as client:
            response = client.post(
                "/config",
                data={"name": "", "theme_pack": "scifi"},
                headers={"Origin": "http://127.0.0.1"},
            )
        assert response.status_code == 200
        assert "error" in response.text.lower() or "required" in response.text

    def test_config_post_invalid_seed_rerenders(self, tmp_path: Path):
        """Non-numeric seed re-renders with an error."""
        with _get_client(tmp_path / "saves") as client:
            response = client.post(
                "/config",
                data={"name": "Hero", "seed": "not_a_number"},
                headers={"Origin": "http://127.0.0.1"},
            )
        assert response.status_code == 200
        assert "number" in response.text.lower() or "error" in response.text.lower()

    def test_config_post_invalid_theme_pack_rerenders(self, tmp_path: Path):
        """Unknown theme pack re-renders the form with an error."""
        with _get_client(tmp_path / "saves") as client:
            response = client.post(
                "/config",
                data={"name": "Hero", "theme_pack": "nonexistent"},
                headers={"Origin": "http://127.0.0.1"},
            )
        assert response.status_code == 200
        assert "theme pack" in response.text.lower()

    def test_config_post_invalid_resolution_profile_rerenders(self, tmp_path: Path):
        """Unknown resolution profile re-renders the form with an error."""
        with _get_client(tmp_path / "saves") as client:
            response = client.post(
                "/config",
                data={"name": "Hero", "resolution_profile": "bogus"},
                headers={"Origin": "http://127.0.0.1"},
            )
        assert response.status_code == 200
        assert "resolution profile" in response.text.lower()

    def test_config_post_invalid_death_mode_rerenders(self, tmp_path: Path):
        """Unknown death mode re-renders the form with an error."""
        with _get_client(tmp_path / "saves") as client:
            response = client.post(
                "/config",
                data={"name": "Hero", "death_mode": "bogus"},
                headers={"Origin": "http://127.0.0.1"},
            )
        assert response.status_code == 200
        assert "death mode" in response.text.lower()

    def test_config_post_name_with_spaces_sanitized(self, tmp_path: Path):
        """A name with spaces is sanitized to underscores in the save filename."""
        saves_dir = tmp_path / "saves"
        with _get_client(saves_dir) as client:
            response = client.post(
                "/config",
                data={"name": "Han Solo", "seed": "42"},
                headers={"Origin": "http://127.0.0.1"},
                follow_redirects=False,
            )
        assert response.status_code == 303
        # Filename should use underscores, not spaces.
        assert (saves_dir / "Han_Solo.json").exists()
        assert not (saves_dir / "Han Solo.json").exists()


class TestSavesList:
    """U6: the saves page renders save metadata."""

    def test_empty_saves_shows_placeholder(self, tmp_path: Path):
        """An empty save directory renders the empty state."""
        with _get_client(tmp_path / "saves") as client:
            response = client.get("/saves")
        assert response.status_code == 200
        assert "No saved campaigns" in response.text

    def test_saves_list_shows_existing_save(self, tmp_path: Path):
        """A save appears in the list with character metadata."""
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(theme_pack="scifi")
        state.character.name = "Ace"
        state.character.career = "navy"
        state.character.terms = 2
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        save(state, saves_dir / "Ace.json")

        with _get_client(saves_dir) as client:
            response = client.get("/saves")
        assert response.status_code == 200
        assert "Ace" in response.text
        assert "navy" in response.text

    def test_checkpoint_sidecar_not_in_list(self, tmp_path: Path):
        """Checkpoint sidecars never appear as loadable entries."""
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        # Create a sidecar file without a main save.
        (saves_dir / "orphan.checkpoint.json").write_text('{"death_mode": "checkpoint"}')

        with _get_client(saves_dir) as client:
            response = client.get("/saves")
        assert response.status_code == 200
        assert "orphan" not in response.text.lower() or "No saved" in response.text


class TestResumeRouting:
    """U6: resume routes to the correct phase via the predicate."""

    def test_resume_mid_lifepath_routes_to_play(self, tmp_path: Path):
        """A mid-lifepath save routes to the lifepath play route."""
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        state = GameState.new(seed=42)
        state.campaign = CampaignConfig()
        state.character.name = "Rookie"
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        save(state, saves_dir / "Rookie.json")

        with _get_client(saves_dir) as client:
            response = client.post(
                "/resume",
                data={"save": "Rookie"},
                headers={"Origin": "http://127.0.0.1"},
                follow_redirects=False,
            )
        assert response.status_code == 303
        assert "/play/" in response.headers.get("location", "")

    def test_resume_dead_character_routes_to_memorial(self, tmp_path: Path):
        """A dead-character save routes to the memorial, never into play."""
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(death_mode="ironman")
        state.character.name = "Fallen"
        state.character.alive = False
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        save(state, saves_dir / "Fallen.json")

        with _get_client(saves_dir) as client:
            response = client.post(
                "/resume",
                data={"save": "Fallen"},
                headers={"Origin": "http://127.0.0.1"},
                follow_redirects=False,
            )
        assert response.status_code == 303
        assert "/memorial/" in response.headers.get("location", "")

    def test_resume_pending_freetext_routes_to_adventure(self, tmp_path: Path):
        """U4: a save with pending_freetext routes to the adventure screen
        (not the lifepath shell) so the interpretation prompt is restored."""
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        state = GameState.new(seed=42)
        state.campaign = CampaignConfig()
        state.character.name = "Pending"
        state.character.alive = True
        state.pending_freetext = {
            "text": "bribe",
            "check": {
                "label": "Bribe",
                "skill": "broker",
                "characteristic": "SOC",
                "difficulty": "average",
            },
            "scaffold": {},
            "options": [],
        }
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        save(state, saves_dir / "Pending.json")

        with _get_client(saves_dir) as client:
            response = client.post(
                "/resume",
                data={"save": "Pending"},
                headers={"Origin": "http://127.0.0.1"},
                follow_redirects=False,
            )
        assert response.status_code == 303
        assert "/adventure/" in response.headers.get("location", "")

    def test_resume_mustered_out_with_freetext_routes_to_adventure(self, tmp_path: Path):
        """U4: a mustered-out character with pending free-text resumes to the
        adventure screen with the interpretation prompt restored, not the
        lifepath shell."""
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        state = GameState.new(seed=42)
        state.campaign = CampaignConfig()
        state.character.name = "MusteredPending"
        state.character.alive = True
        state.character.career = "navy"
        state.character.characteristics = {
            "STR": 7,
            "DEX": 6,
            "END": 5,
            "INT": 8,
            "EDU": 9,
            "SOC": 6,
        }
        state.narrative_log.append("mustered_out=true")
        state.pending_freetext = {
            "text": "I sneak past the guard",
            "check": {
                "label": "Sneak",
                "skill": "stealth",
                "characteristic": "DEX",
                "difficulty": "average",
            },
            "scaffold": {
                "focus": "Corridor",
                "focus_description": "Dim",
                "situation": "Guarded",
                "npc_hint": "",
            },
            "options": [],
        }
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        save(state, saves_dir / "MusteredPending.json")

        with _get_client(saves_dir) as client:
            response = client.post(
                "/resume",
                data={"save": "MusteredPending"},
                headers={"Origin": "http://127.0.0.1"},
                follow_redirects=False,
            )
        assert response.status_code == 303
        location = response.headers.get("location", "")
        assert "/adventure/" in location, f"Expected /adventure/ in location, got {location}"
        assert "/play/" not in location, (
            f"Mustered-out free-text save must NOT route to /play/, got {location}"
        )

    def test_resume_mustered_out_routes_to_adventure(self, tmp_path: Path):
        """A mustered-out character with full characteristics routes to adventure."""
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        state = GameState.new(seed=42)
        state.campaign = CampaignConfig()
        state.character.name = "Veteran"
        state.character.alive = True
        state.character.career = "navy"
        state.character.characteristics = {
            "STR": 7,
            "DEX": 6,
            "END": 5,
            "INT": 8,
            "EDU": 9,
            "SOC": 6,
        }
        state.narrative_log.append("mustered_out=true")
        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        save(state, saves_dir / "Veteran.json")

        with _get_client(saves_dir) as client:
            response = client.post(
                "/resume",
                data={"save": "Veteran"},
                headers={"Origin": "http://127.0.0.1"},
                follow_redirects=False,
            )
        assert response.status_code == 303
        assert "/adventure/" in response.headers.get("location", "")

    def test_resume_nonexistent_save_redirects_to_saves(self, tmp_path: Path):
        """A nonexistent save name redirects back to the saves list."""
        with _get_client(tmp_path / "saves") as client:
            response = client.post(
                "/resume",
                data={"save": "Ghost"},
                headers={"Origin": "http://127.0.0.1"},
                follow_redirects=False,
            )
        assert response.status_code == 303
        assert "/saves" in response.headers.get("location", "")

    def test_resume_empty_save_redirects_to_saves(self, tmp_path: Path):
        """An empty save field redirects back to the saves list."""
        with _get_client(tmp_path / "saves") as client:
            response = client.post(
                "/resume",
                data={"save": ""},
                headers={"Origin": "http://127.0.0.1"},
                follow_redirects=False,
            )
        assert response.status_code == 303
        assert "/saves" in response.headers.get("location", "")


class TestPathTraversalProtection:
    """U6 security: save names from POST data are sanitized against path traversal."""

    def test_dotdot_in_name_sanitized(self, tmp_path: Path):
        """A name with '..' cannot escape the saves directory."""
        from src.game.saves import resolve_save_path

        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        path = resolve_save_path(saves_dir, "../../etc/passwd")
        assert path.is_relative_to(saves_dir.resolve())
        assert ".." not in path.name

    def test_absolute_path_sanitized(self, tmp_path: Path):
        """An absolute path is reduced to its filename component."""
        from src.game.saves import resolve_save_path

        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        path = resolve_save_path(saves_dir, "/etc/shadow")
        assert path.is_relative_to(saves_dir.resolve())

    def test_backslash_sanitized(self, tmp_path: Path):
        """Backslash path traversal is blocked."""
        from src.game.saves import safe_save_name

        name = safe_save_name("..\\..\\windows\\system32")
        assert ".." not in name
        assert "\\" not in name
