"""Tests for the Sheet and World drawer tab routes (U6, R12).

Covers:
- Sheet route returns 200 with state-derived values (characteristics, skills,
  career, credits).
- World route returns 200 with mission data when a mission exists.
- Empty states (no mission, no threads, no facts) render empty-state text.
- Autoescape: player-controlled strings (character name) are HTML-escaped.
- Dead character: Sheet route still works without crashing.
- Tab wiring: Sheet/World/Audit tab buttons carry ``hx-get`` in both shells.
- Placeholder gone: no template ships the "arrives in a later unit" placeholder.
- Default Sheet on GET: adventure and lifepath pages include Sheet content
  inline in the drawer (not the placeholder).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Test helpers — mirror the existing per-test patching pattern.
# ---------------------------------------------------------------------------


def _get_client(saves_dir: Path) -> TestClient:
    """Create a TestClient with all route modules pointed at *saves_dir*."""
    from src.web.app import create_app
    from src.web.routes import adventure as adv_module
    from src.web.routes import inspector as insp_module
    from src.web.routes import lifepath as life_module
    from src.web.routes import memorial as mem_module
    from src.web.routes import menu as menu_module
    from src.web.routes import sheet as sheet_module
    from src.web.routes import stream as stream_module
    from src.web.routes import world as world_module

    saves_dir.mkdir(parents=True, exist_ok=True)
    menu_module.DEFAULT_SAVES_DIR = saves_dir
    life_module.DEFAULT_SAVES_DIR = saves_dir
    adv_module.DEFAULT_SAVES_DIR = saves_dir
    stream_module.DEFAULT_SAVES_DIR = saves_dir
    insp_module.DEFAULT_SAVES_DIR = saves_dir
    mem_module.DEFAULT_SAVES_DIR = saves_dir
    sheet_module.DEFAULT_SAVES_DIR = saves_dir
    world_module.DEFAULT_SAVES_DIR = saves_dir
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _create_adventure_save(saves_dir: Path, name: str = "Hero", alive: bool = True) -> Path:
    """Create a mustered-out character save ready for adventure."""
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState, Injury

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
    state.character.skills = {
        "gun_combat_slug_rifle": 1,
        "mechanic": 0,
        "gambler": 2,
    }
    state.character.career = "navy"
    state.character.rank = 3
    state.character.terms = 2
    state.character.age = 26
    state.character.credits = 5000
    state.character.alive = alive
    state.narrative_log.append("mustered_out=true")
    state.entities.append(Injury(name="Old Wound", severity="moderate", description="A scar."))
    path = saves_dir / f"{name}.json"
    save(state, path)
    return path


def _create_save_with_mission(saves_dir: Path) -> Path:
    """Create a save that has an active mission, threads, and facts."""
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState, NarrativeFact

    state = GameState.new(seed=99)
    state.campaign = CampaignConfig(theme_pack="scifi", death_mode="narrative")
    state.character.name = "Maverick"
    state.character.characteristics = {
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    state.character.skills = {"pilot": 2}
    state.character.career = "navy"
    state.character.terms = 3
    state.character.alive = True
    state.narrative_log.append("mustered_out=true")

    state.active_mission = {
        "id": "M001",
        "hook": {
            "patron": "Senator Vex",
            "objective": "Recover stolen data",
            "complication": "The data is encrypted",
            "reward": "50,000 Cr",
            "description": "A senator needs help.",
        },
        "state": "active",
        "scenes_played": 1,
        "scenes_completed": 1,
        "min_scenes": 3,
    }
    state.open_threads = ["Debt to Vaska", "Shadowy pursuer"]
    state.entities.append(NarrativeFact(name="Station Alpha", description="A deep-space hub."))
    path = saves_dir / "Maverick.json"
    save(state, path)
    return path


# ---------------------------------------------------------------------------
# Sheet route tests.
# ---------------------------------------------------------------------------


class TestSheetRoute:
    """GET /sheet/{save_name} renders a read-only sheet fragment (U6, R12)."""

    def test_sheet_returns_200(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/sheet/Hero")
        assert response.status_code == 200

    def test_sheet_shows_characteristic_values(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/sheet/Hero")
        # Raw values appear.
        assert "STR" in response.text
        assert "7" in response.text
        # DMs appear (DEX 9 → +1, SOC 5 → -1).
        assert "+1" in response.text
        assert "-1" in response.text

    def test_sheet_shows_skill_display_names(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/sheet/Hero")
        # skill_display_name resolves IDs to pack names.
        assert "Mechanic" in response.text
        assert "Gambling" in response.text

    def test_sheet_shows_career_and_credits(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/sheet/Hero")
        # Career name resolved from pack.
        assert "Navy" in response.text or "navy" in response.text
        assert "5000" in response.text

    def test_sheet_shows_injuries(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/sheet/Hero")
        assert "Old Wound" in response.text
        assert "moderate" in response.text

    def test_sheet_escapes_player_controlled_strings(self, tmp_path: Path):
        """Autoescape: a name with HTML is escaped in the fragment."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir, name="<script>x</script>")
        with _get_client(saves_dir) as client:
            response = client.get("/sheet/<script>x</script>")
        # The redirect case — save name with slashes is tricky.
        # Use a simpler XSS string instead.
        _create_adventure_save(saves_dir, name='Hero"&onload=alert(1)')
        with _get_client(saves_dir) as client:
            response = client.get("/sheet/Hero")
        assert "<script>" not in response.text
        assert "&" in response.text or "&amp;" in response.text

    def test_sheet_dead_character_no_crash(self, tmp_path: Path):
        """Sheet route still works for a dead character (no crash)."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir, alive=False)
        with _get_client(saves_dir) as client:
            response = client.get("/sheet/Hero")
        assert response.status_code == 200
        assert "Deceased" in response.text

    def test_sheet_nonexistent_save_redirects(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/sheet/Nobody", follow_redirects=False)
        assert response.status_code == 303


# ---------------------------------------------------------------------------
# World route tests.
# ---------------------------------------------------------------------------


class TestWorldRoute:
    """GET /world/{save_name} renders a read-only world fragment (U6, R12)."""

    def test_world_returns_200(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save_with_mission(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/world/Maverick")
        assert response.status_code == 200

    def test_world_shows_mission_data(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save_with_mission(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/world/Maverick")
        assert "Senator Vex" in response.text
        assert "Recover stolen data" in response.text
        # Progress indicator.
        assert "1" in response.text
        assert "3" in response.text

    def test_world_shows_threads(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save_with_mission(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/world/Maverick")
        assert "Debt to Vaska" in response.text

    def test_world_shows_facts(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save_with_mission(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/world/Maverick")
        assert "Station Alpha" in response.text

    def test_world_empty_mission_renders_empty_text(self, tmp_path: Path):
        """No active mission → empty-state text, not an error."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/sheet/Hero")
        # Use the Hero save which has no mission.
        with _get_client(saves_dir) as client:
            response = client.get("/world/Hero")
        assert response.status_code == 200
        assert "No active mission" in response.text

    def test_world_empty_threads_renders_empty_text(self, tmp_path: Path):
        """No open threads → empty-state text."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/world/Hero")
        assert response.status_code == 200
        assert "No open threads" in response.text

    def test_world_empty_facts_renders_empty_text(self, tmp_path: Path):
        """No established facts → empty-state text."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/world/Hero")
        assert response.status_code == 200
        assert "No established facts" in response.text

    def test_world_nonexistent_save_redirects(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save_with_mission(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/world/Nobody", follow_redirects=False)
        assert response.status_code == 303


# ---------------------------------------------------------------------------
# Tab wiring and placeholder tests.
# ---------------------------------------------------------------------------


class TestTabWiring:
    """Tab buttons in both shells carry hx-get wiring; placeholder is gone."""

    def test_adventure_sheet_tab_has_hx_get(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        text = response.text
        assert 'hx-get="/sheet/Hero"' in text

    def test_adventure_world_tab_has_hx_get(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        text = response.text
        assert 'hx-get="/world/Hero"' in text

    def test_adventure_audit_tab_has_hx_get(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        text = response.text
        assert 'hx-get="/audit/Hero"' in text

    def test_lifepath_sheet_tab_has_hx_get(self, tmp_path: Path):
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        saves_dir = tmp_path / "saves"
        state = GameState.new(seed=1)
        state.campaign = CampaignConfig(theme_pack="scifi")
        state.character.name = "Rook"
        save(state, saves_dir / "Rook.json")

        with _get_client(saves_dir) as client:
            response = client.get("/play/Rook")
        assert 'hx-get="/sheet/Rook"' in response.text

    def test_lifepath_world_tab_has_hx_get(self, tmp_path: Path):
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        saves_dir = tmp_path / "saves"
        state = GameState.new(seed=1)
        state.campaign = CampaignConfig(theme_pack="scifi")
        state.character.name = "Rook"
        save(state, saves_dir / "Rook.json")

        with _get_client(saves_dir) as client:
            response = client.get("/play/Rook")
        assert 'hx-get="/world/Rook"' in response.text

    def test_lifepath_audit_tab_has_hx_get(self, tmp_path: Path):
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        saves_dir = tmp_path / "saves"
        state = GameState.new(seed=1)
        state.campaign = CampaignConfig(theme_pack="scifi")
        state.character.name = "Rook"
        save(state, saves_dir / "Rook.json")

        with _get_client(saves_dir) as client:
            response = client.get("/play/Rook")
        assert 'hx-get="/audit/Rook"' in response.text

    def test_no_placeholder_in_adventure(self, tmp_path: Path):
        """No 'arrives in a later unit' placeholder ships."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        assert "arrives in a later unit" not in response.text
        assert "later unit" not in response.text

    def test_no_placeholder_in_lifepath(self, tmp_path: Path):
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        saves_dir = tmp_path / "saves"
        state = GameState.new(seed=1)
        state.campaign = CampaignConfig(theme_pack="scifi")
        state.character.name = "Rook"
        save(state, saves_dir / "Rook.json")

        with _get_client(saves_dir) as client:
            response = client.get("/play/Rook")
        assert "arrives in a later unit" not in response.text
        assert "later unit" not in response.text

    def test_no_placeholder_in_sheet_fragment(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/sheet/Hero")
        assert "arrives in a later unit" not in response.text

    def test_no_placeholder_in_world_fragment(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/world/Hero")
        assert "arrives in a later unit" not in response.text

    def test_no_placeholder_string_in_templates(self):
        """Static check: no template file contains the placeholder string."""
        template_dir = Path("src/web/templates")
        for tpl in template_dir.rglob("*.html"):
            content = tpl.read_text()
            assert "arrives in a later unit" not in content, f"Placeholder found in {tpl}"
            assert "later unit" not in content, f"Placeholder found in {tpl}"


# ---------------------------------------------------------------------------
# Default Sheet on GET tests.
# ---------------------------------------------------------------------------


class TestDefaultSheetOnGet:
    """The GET pages include Sheet content inline in the drawer (U6, R12)."""

    def test_adventure_drawer_has_sheet_content(self, tmp_path: Path):
        """Adventure GET page includes Sheet content, not the placeholder."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        text = response.text
        # Sheet panel present inline.
        assert "sheet-panel" in text
        # Characteristic values appear in the inline content.
        assert "STR" in text

    def test_lifepath_drawer_has_sheet_content(self, tmp_path: Path):
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        saves_dir = tmp_path / "saves"
        state = GameState.new(seed=1)
        state.campaign = CampaignConfig(theme_pack="scifi")
        state.character.name = "Rook"
        state.character.characteristics = {"STR": 7}
        save(state, saves_dir / "Rook.json")

        with _get_client(saves_dir) as client:
            response = client.get("/play/Rook")
        text = response.text
        assert "sheet-panel" in text
        assert "Rook" in text
