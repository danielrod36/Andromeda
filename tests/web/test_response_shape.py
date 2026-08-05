"""Response-shape regression tests for htmx POST routes (U5, R10/R11, AE5).

Asserts that every action POST returns a clean fragment — not a full
document — so htmx swaps never nest duplicate ``#spine`` / ``#main-row``
regions or wipe the client-managed drawer.

Covers:
- AE5 (server half): action responses contain no ``<html>``/``<body>``/``<head>``
  tags and no ``id="spine"`` (the fragment is inner content only).
- R10: exactly one ``#status-strip`` (the OOB block); no duplicate ``#main-row``.
- R11: no ``id="drawer"`` in any action response (client-managed, persists).
- Lifepath drawer pin: travels as ``data-drawer-pinned`` on the OOB status strip.
- Status strip OOB: the block carries ``hx-swap-oob="true"``.
- Regression: GET pages still render as full documents.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Test helpers — mirror the existing per-test patching pattern.
# ---------------------------------------------------------------------------


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


def _create_adventure_save(
    saves_dir: Path, name: str = "Hero", death_mode: str = "narrative"
) -> Path:
    """Create a mustered-out character save ready for adventure."""
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState

    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(
        theme_pack="scifi", resolution_profile="narrative", death_mode=death_mode
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
        "Gun Combat": 1,
        "Persuade": 0,
        "Stealth": 2,
        "Investigate": 1,
    }
    state.character.career = "navy"
    state.character.terms = 2
    state.character.alive = True
    state.narrative_log.append("mustered_out=true")
    path = saves_dir / f"{name}.json"
    save(state, path)
    return path


def _create_lifepath_save(saves_dir: Path, name: str = "TestHero", seed: int = 42) -> Path:
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState

    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(theme_pack="scifi", resolution_profile="classic")
    state.character.name = name
    path = saves_dir / f"{name}.json"
    save(state, path)
    return path


_ORIGIN = {"Origin": "http://127.0.0.1"}


# ---------------------------------------------------------------------------
# Adventure POST shape (R10/R11, AE5).
# ---------------------------------------------------------------------------


class TestAdventureActionShape:
    """Adventure action POSTs return clean fragments, not full documents."""

    def test_action_response_has_no_document_tags(self, tmp_path: Path):
        """AE5: no <html>, <body>, or <head> in the POST body."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
        body = response.text
        assert "<html" not in body.lower(), "POST body must not contain <html>"
        assert "<body" not in body.lower(), "POST body must not contain <body>"
        assert "<head>" not in body.lower(), "POST body must not contain <head>"
        assert "<head " not in body.lower(), "POST body must not contain <head"
        assert "<!doctype" not in body.lower(), "POST body must not contain a doctype"

    def test_action_response_has_no_nested_spine(self, tmp_path: Path):
        """AE5: no id="spine" — the fragment is inner content only."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
        assert 'id="spine"' not in response.text, (
            'POST body must not contain id="spine" — the fragment replaces '
            "the existing #spine's innerHTML"
        )

    def test_action_response_has_no_main_row(self, tmp_path: Path):
        """R10: no duplicate #main-row in the POST body."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
        assert 'id="main-row"' not in response.text

    def test_action_response_has_no_drawer(self, tmp_path: Path):
        """R11: no drawer markup — the drawer is client-managed and persists."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
        assert 'id="drawer"' not in response.text, (
            "POST body must not contain the drawer — it is client-managed"
        )

    def test_action_response_has_oob_status_strip(self, tmp_path: Path):
        """R10: the OOB status strip is present exactly once."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
        body = response.text
        assert body.count('id="status-strip"') == 1, (
            "Expected exactly one #status-strip (the OOB block)"
        )
        assert 'hx-swap-oob="true"' in body, 'Status strip must carry hx-swap-oob="true"'

    def test_action_response_status_strip_carries_drawer_pin(self, tmp_path: Path):
        """Adventure status strip carries data-drawer-pinned (always false)."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
        # The status strip header should carry the data-drawer-pinned attribute.
        assert "data-drawer-pinned" in response.text

    def test_freetext_response_has_no_document_tags(self, tmp_path: Path):
        """AE5: free-text POST body is also a clean fragment."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            # Accept mission first to enter scene_active phase.
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
        body = response.text
        assert "<html" not in body.lower()
        assert "<body" not in body.lower()
        assert "<head>" not in body.lower()
        assert "<head " not in body.lower()
        assert 'id="spine"' not in body
        assert 'id="drawer"' not in body

    def test_freetext_response_has_oob_status_strip(self, tmp_path: Path):
        """Free-text POST also carries the OOB status strip."""
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
        body = response.text
        assert body.count('id="status-strip"') == 1
        assert 'hx-swap-oob="true"' in body


# ---------------------------------------------------------------------------
# Lifepath POST shape (R10/R11, AE5).
# ---------------------------------------------------------------------------


class TestLifepathActionShape:
    """Lifepath action POSTs return clean fragments with the drawer pin."""

    def test_action_response_has_no_document_tags(self, tmp_path: Path):
        """AE5: no <html>, <body>, or <head> in the POST body."""
        saves_dir = tmp_path / "saves"
        _create_lifepath_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/play/TestHero/action",
                data={"choice": "roll_pool"},
                headers=_ORIGIN,
            )
        body = response.text
        assert "<html" not in body.lower()
        assert "<body" not in body.lower()
        assert "<head>" not in body.lower()
        assert "<head " not in body.lower()
        assert "<!doctype" not in body.lower()

    def test_action_response_has_no_nested_spine(self, tmp_path: Path):
        """AE5: no id="spine" — the fragment is inner content only."""
        saves_dir = tmp_path / "saves"
        _create_lifepath_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/play/TestHero/action",
                data={"choice": "roll_pool"},
                headers=_ORIGIN,
            )
        assert 'id="spine"' not in response.text

    def test_action_response_has_no_drawer(self, tmp_path: Path):
        """R11: no drawer markup — the drawer is client-managed and persists."""
        saves_dir = tmp_path / "saves"
        _create_lifepath_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/play/TestHero/action",
                data={"choice": "roll_pool"},
                headers=_ORIGIN,
            )
        assert 'id="drawer"' not in response.text, (
            "POST body must not contain the drawer — it is client-managed"
        )

    def test_action_response_has_oob_status_strip(self, tmp_path: Path):
        """R10: the OOB status strip is present exactly once."""
        saves_dir = tmp_path / "saves"
        _create_lifepath_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/play/TestHero/action",
                data={"choice": "roll_pool"},
                headers=_ORIGIN,
            )
        body = response.text
        assert body.count('id="status-strip"') == 1
        assert 'hx-swap-oob="true"' in body

    def test_action_response_status_strip_carries_drawer_pin(self, tmp_path: Path):
        """Lifepath status strip carries data-drawer-pinned with correct state."""
        saves_dir = tmp_path / "saves"
        _create_lifepath_save(saves_dir)
        with _get_client(saves_dir) as client:
            # roll_pool action → next phase is assign_characteristics (pinned).
            response = client.post(
                "/play/TestHero/action",
                data={"choice": "roll_pool"},
                headers=_ORIGIN,
            )
        body = response.text
        assert "data-drawer-pinned" in body
        # After roll_pool, the view enters assign_characteristics (pinned=True).
        assert 'data-drawer-pinned="true"' in body, (
            'Expected data-drawer-pinned="true" on the status strip during '
            "the assign_characteristics phase"
        )


# ---------------------------------------------------------------------------
# GET regression — full documents survive.
# ---------------------------------------------------------------------------


class TestGetPageShape:
    """GET pages still render as full documents (regression)."""

    def test_adventure_get_is_full_document(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        body = response.text
        assert "<html" in body.lower()
        assert "<body" in body.lower()
        assert "<head" in body.lower()
        assert "<!doctype" in body.lower()
        assert 'id="spine"' in body
        assert 'id="drawer"' in body
        assert 'id="status-strip"' in body
        assert 'id="main-row"' in body

    def test_lifepath_get_is_full_document(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_lifepath_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/play/TestHero")
        body = response.text
        assert "<html" in body.lower()
        assert "<body" in body.lower()
        assert "<head" in body.lower()
        assert "<!doctype" in body.lower()
        assert 'id="spine"' in body
        assert 'id="drawer"' in body
        assert 'id="status-strip"' in body
        assert 'id="main-row"' in body

    def test_adventure_get_drawer_has_no_oob(self, tmp_path: Path):
        """U5: the adventure drawer no longer carries hx-swap-oob."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        # Find the drawer element and verify it does NOT have hx-swap-oob.
        assert 'id="drawer"' in response.text
        drawer_start = response.text.index('id="drawer"')
        drawer_tag = response.text[drawer_start : drawer_start + 200]
        assert "hx-swap-oob" not in drawer_tag, (
            "Adventure drawer must not carry hx-swap-oob — it is client-managed"
        )

    def test_lifepath_get_drawer_has_no_oob(self, tmp_path: Path):
        """U5: the lifepath drawer no longer carries hx-swap-oob."""
        saves_dir = tmp_path / "saves"
        _create_lifepath_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/play/TestHero")
        assert 'id="drawer"' in response.text
        drawer_start = response.text.index('id="drawer"')
        drawer_tag = response.text[drawer_start : drawer_start + 200]
        assert "hx-swap-oob" not in drawer_tag, (
            "Lifepath drawer must not carry hx-swap-oob — it is client-managed"
        )

    def test_adventure_get_status_strip_has_no_oob(self, tmp_path: Path):
        """U5: the GET status strip does not carry hx-swap-oob (only POST does)."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        strip_start = response.text.index('id="status-strip"')
        strip_tag = response.text[strip_start : strip_start + 200]
        assert "hx-swap-oob" not in strip_tag

    def test_adventure_get_forms_have_no_hx_select(self, tmp_path: Path):
        """U5: action forms drop hx-select (the response IS the fragment)."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        assert "hx-select" not in response.text, (
            "Adventure forms must not carry hx-select — the response is the fragment now"
        )

    def test_lifepath_get_forms_have_no_hx_select(self, tmp_path: Path):
        """U5: action forms drop hx-select."""
        saves_dir = tmp_path / "saves"
        _create_lifepath_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/play/TestHero")
        assert "hx-select" not in response.text
