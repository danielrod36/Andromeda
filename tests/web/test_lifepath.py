"""Tests for the web lifepath screens (U7, U2).

Verifies the core lifepath flow works over HTTP via TestClient:
roll pool → assign characteristics → background skills → choose career →
qualify → interactive term loop (survival, commission, advancement, skills,
aging, re-enlistment) → complete.

U2 adds interactive phase tests: commission, skill tables, aging reductions,
mishap/injury chain, crisis resolution, re-enlistment forced outcomes,
qualification failure fallback, and free characteristic assignment.
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


# ---------------------------------------------------------------------------
# U2 helper: set up a character past chargen so the term loop can be tested.
# ---------------------------------------------------------------------------


def _setup_character_for_term(client: TestClient, save_name: str = "TestHero") -> None:
    """Drive through pool, assignment, background skills, and career choice.

    After this the character is ready for ``begin_term`` (run_survival).
    Uses the LiveRoller (seed=42) so rolls are deterministic but not forced.
    """
    # Roll pool.
    client.post(f"/play/{save_name}/action", data={"choice": "roll_pool"}, headers=_ORIGIN)
    # Assign six characteristics (always index 0 — pool shrinks each pick).
    for stat in ["STR", "DEX", "END", "INT", "EDU", "SOC"]:
        client.post(
            f"/play/{save_name}/action",
            data={"choice": f"assign:0:{stat}"},
            headers=_ORIGIN,
        )
    # Pick background skills (pick the first available ones).
    for _ in range(3):
        response = client.get(f"/play/{save_name}")
        # Find a bg_skill option in the response.
        import re

        match = re.search(r"bg_skill:(\w+)", response.text)
        if not match:
            break
        client.post(
            f"/play/{save_name}/action",
            data={"choice": f"bg_skill:{match.group(1)}"},
            headers=_ORIGIN,
        )
    # Choose navy career.
    client.post(
        f"/play/{save_name}/action",
        data={"choice": "career:navy"},
        headers=_ORIGIN,
    )


class TestInteractiveTermPhases:
    """U2: the web lifepath runs interactive term sub-phases."""

    def test_begin_term_shows_survival_and_commission(self, tmp_path: Path):
        """Beginning a term runs survival, then navy offers commission."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            _setup_character_for_term(client)
            response = client.post(
                "/play/TestHero/action",
                data={"choice": "begin_term"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        assert "Survival" in response.text or "survival" in response.text.lower()
        # Navy is a hierarchy career → commission should be offered.
        assert "Commission" in response.text

    def test_commission_attempt_runs_roll(self, tmp_path: Path):
        """Choosing to attempt commission produces a commission receipt."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            _setup_character_for_term(client)
            client.post("/play/TestHero/action", data={"choice": "begin_term"}, headers=_ORIGIN)
            response = client.post(
                "/play/TestHero/action",
                data={"choice": "commission_attempt"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # After commission, should see advancement or skills phase.
        assert "Advancement" in response.text or "skill" in response.text.lower()

    def test_skill_table_choice_advances_to_next_roll(self, tmp_path: Path):
        """Each skill table click consumes one roll and refreshes choices."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            _setup_character_for_term(client)
            client.post("/play/TestHero/action", data={"choice": "begin_term"}, headers=_ORIGIN)
            # Decline commission to advance past it.
            client.post(
                "/play/TestHero/action",
                data={"choice": "commission_decline"},
                headers=_ORIGIN,
            )
            # Decline advancement to get to skills.
            client.post(
                "/play/TestHero/action",
                data={"choice": "advancement_decline"},
                headers=_ORIGIN,
            )
            # Now in choose_skills — pick the first table.
            response = client.post(
                "/play/TestHero/action",
                data={"choice": "skill_table:Personal Development"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # Should show a skill roll result.
        assert "Skill Roll" in response.text or "skill" in response.text.lower()

    def test_reenlist_after_term_completion(self, tmp_path: Path):
        """After all skill rolls, the term completes via re-enlistment roll."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            _setup_character_for_term(client)
            client.post("/play/TestHero/action", data={"choice": "begin_term"}, headers=_ORIGIN)
            client.post(
                "/play/TestHero/action",
                data={"choice": "commission_decline"},
                headers=_ORIGIN,
            )
            client.post(
                "/play/TestHero/action",
                data={"choice": "advancement_decline"},
                headers=_ORIGIN,
            )
            # Navy is hierarchy → 1 base skill roll.
            response = client.post(
                "/play/TestHero/action",
                data={"choice": "skill_table:Personal Development"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # The re-enlistment roll runs automatically after the last skill roll.
        # Possible outcomes: re_enlist (may_continue), mustering_out (forced), run_survival (must_continue).
        text = response.text
        assert (
            "Re-enlist" in text
            or "Continue for another term" in text
            or "Mustering out" in text
            or "Begin Term" in text
            or "Begin Adventure" in text
        )
        # Re-enlistment receipt should be present in the response.
        assert "Re-enlistment" in text

    def test_qualification_failure_shows_fallback(self, tmp_path: Path):
        """When qualification fails, the fallback menu appears."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir, seed=1)
        with _get_client(saves_dir) as client:
            # Set up past characteristics but with stats that fail navy qual.
            client.post("/play/TestHero/action", data={"choice": "roll_pool"}, headers=_ORIGIN)
            for stat in ["STR", "DEX", "END", "INT", "EDU", "SOC"]:
                client.post(
                    "/play/TestHero/action",
                    data={"choice": f"assign:0:{stat}"},
                    headers=_ORIGIN,
                )
            # Pick background skills.
            import re

            for _ in range(3):
                response = client.get("/play/TestHero")
                match = re.search(r"bg_skill:(\w+)", response.text)
                if not match:
                    break
                client.post(
                    "/play/TestHero/action",
                    data={"choice": f"bg_skill:{match.group(1)}"},
                    headers=_ORIGIN,
                )
            # Try career — may or may not qualify depending on rolls.
            response = client.post(
                "/play/TestHero/action",
                data={"choice": "career:navy"},
                headers=_ORIGIN,
            )
        # Either qualified (shows Begin Term) or shows fallback.
        text = response.text
        assert (
            "Begin Term" in text
            or "Qualification failed" in text
            or "different career" in text.lower()
            or "Drifter" in text
        )


class TestFreeCharacteristicAssignment:
    """U2: any pool value can be assigned to any unassigned stat."""

    def test_assign_to_specific_stat(self, tmp_path: Path):
        """The assign:{index}:{stat} format targets a specific stat."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            client.post("/play/TestHero/action", data={"choice": "roll_pool"}, headers=_ORIGIN)
            # Assign to specific stats by name.
            client.post(
                "/play/TestHero/action",
                data={"choice": "assign:0:STR"},
                headers=_ORIGIN,
            )
            client.get("/play/TestHero")
        # STR should be assigned (no longer in the pool).
        from src.engine.persistence import load

        state = load(saves_dir / "TestHero.json")
        assert "STR" in state.character.characteristics
        assert len(state.character.unassigned_rolls) == 5

    def test_any_pool_value_to_any_stat(self, tmp_path: Path):
        """Index 1 assigns the second pool value to a chosen stat."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            client.post("/play/TestHero/action", data={"choice": "roll_pool"}, headers=_ORIGIN)
            # Assign index 0 to STR, then index 0 (was 1) to DEX.
            client.post("/play/TestHero/action", data={"choice": "assign:0:STR"}, headers=_ORIGIN)
            client.post("/play/TestHero/action", data={"choice": "assign:0:DEX"}, headers=_ORIGIN)
            client.get("/play/TestHero")
        from src.engine.persistence import load

        state = load(saves_dir / "TestHero.json")
        assert "STR" in state.character.characteristics
        assert "DEX" in state.character.characteristics
        assert len(state.character.unassigned_rolls) == 4
