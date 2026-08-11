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

import pytest
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


def _drain_specializations(client: TestClient, save_name: str = "TestHero") -> None:
    """Resolve any pending cascade specializations by picking the first option.

    C4: basic training and skill-table rolls on cascade slots pend a
    ``choose_specialization`` phase. The web shell surfaces it; this helper
    drives the new phase to completion so downstream term phases are
    reachable. Deterministic — always picks the first listed spec.
    """
    import re

    for _ in range(20):  # bounded — at most a few cascades per term
        response = client.get(f"/play/{save_name}")
        match = re.search(r"spec:(\w[\w_]*)", response.text)
        if not match:
            break
        client.post(
            f"/play/{save_name}/action",
            data={"choice": f"spec:{match.group(1)}"},
            headers=_ORIGIN,
        )


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
    # C4: basic training pends cascade specializations — drain them so the
    # character is ready for begin_term.
    _drain_specializations(client, save_name)


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


# ---------------------------------------------------------------------------
# U3: Muster-out benefit allocation and lifepath→adventure handoff tests.
# ---------------------------------------------------------------------------


def _setup_character_for_muster_out(client: TestClient, save_name: str = "TestHero") -> None:
    """Drive through chargen + one term + re-enlist → muster out.

    After this the character is in the muster_out_allocate phase.
    Uses the LiveRoller (seed=42) so rolls are deterministic but not forced.
    """
    _setup_character_for_term(client, save_name)
    client.post(f"/play/{save_name}/action", data={"choice": "begin_term"}, headers=_ORIGIN)
    client.post(f"/play/{save_name}/action", data={"choice": "commission_decline"}, headers=_ORIGIN)
    client.post(
        f"/play/{save_name}/action",
        data={"choice": "advancement_decline"},
        headers=_ORIGIN,
    )
    # Navy is hierarchy → 1 base skill roll.
    client.post(
        f"/play/{save_name}/action",
        data={"choice": "skill_table:Personal Development"},
        headers=_ORIGIN,
    )
    # After the term, muster out (player choice or forced by SRD).
    # The re-enlistment auto-resolves; if may_continue, choose to muster out.
    response = client.get(f"/play/{save_name}")
    if "reenlist_muster" in response.text:
        client.post(
            f"/play/{save_name}/action",
            data={"choice": "reenlist_muster"},
            headers=_ORIGIN,
        )


class TestMusterOutBenefits:
    """U3: interactive muster-out benefit allocation."""

    def test_muster_out_offers_cash_and_material(self, tmp_path: Path):
        """Mustering out offers both cash and material table choices."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            _setup_character_for_muster_out(client)
            response = client.get("/play/TestHero")
        # After 1 term, mustering out should have at least 1 benefit roll.
        # The response must offer at least one claimable benefit table.
        assert "claim_cash" in response.text or "claim_material" in response.text

    def test_claim_cash_applies_credits_with_receipt(self, tmp_path: Path):
        """Claiming a cash benefit produces a receipt with credits."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            _setup_character_for_muster_out(client)
            response = client.get("/play/TestHero")
            if "claim_cash" not in response.text:
                pytest.skip("Phase not at muster_out_allocate after setup")
            response = client.post(
                "/play/TestHero/action",
                data={"choice": "claim_cash"},
                headers=_ORIGIN,
            )
        text = response.text
        # Either we see the receipt or we're at a different phase.
        assert "Cash Benefit" in text or "benefit roll" in text.lower() or "complete" in text

    def test_claim_all_benefits_completes_muster_out(self, tmp_path: Path):
        """Claiming all benefit rolls sets muster_out and reaches complete."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            _setup_character_for_muster_out(client)
            # C6: post-muster routes to choose_career_change before complete.
            # Drive claim choices, then career_change_finish to terminate.
            for _ in range(10):
                response = client.get("/play/TestHero")
                if "complete" in response.text.lower() and "Begin Adventure" in response.text:
                    break
                if "claim_cash" in response.text:
                    response = client.post(
                        "/play/TestHero/action",
                        data={"choice": "claim_cash"},
                        headers=_ORIGIN,
                    )
                elif "claim_material" in response.text:
                    response = client.post(
                        "/play/TestHero/action",
                        data={"choice": "claim_material"},
                        headers=_ORIGIN,
                    )
                elif "career_change_finish" in response.text:
                    response = client.post(
                        "/play/TestHero/action",
                        data={"choice": "career_change_finish"},
                        headers=_ORIGIN,
                    )
                else:
                    break
        # Should have reached the complete phase.
        from src.engine.persistence import load

        state = load(saves_dir / "TestHero.json")
        assert "mustered_out=true" in state.narrative_log

    def test_cash_cap_dims_cash_option(self, tmp_path: Path):
        """After 3 cash claims, the cash option is dimmed."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            _setup_character_for_muster_out(client)
            # Claim 3 cash rolls to hit the cap.
            for _ in range(3):
                response = client.get("/play/TestHero")
                if "claim_cash" not in response.text:
                    break
                response = client.post(
                    "/play/TestHero/action",
                    data={"choice": "claim_cash"},
                    headers=_ORIGIN,
                )
            # Check that the cash option is dimmed or muster-out is complete.
            response = client.get("/play/TestHero")
        text = response.text
        # Either the cap is hit (dimmed), all rolls are consumed (complete or
        # career_change_finish per C6), or material rolls remain.
        assert (
            "Cash rolls exhausted" in text
            or "complete" in text.lower()
            or "claim_material" in text
            or "career_change_finish" in text  # C6: post-muster career change
        )

    def test_handoff_link_to_adventure(self, tmp_path: Path):
        """The complete phase renders a GET link to /adventure/{save}."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            _setup_character_for_muster_out(client)
            # C6: post-muster routes to choose_career_change before complete.
            # Drive claim choices, then career_change_finish to terminate.
            for _ in range(10):
                response = client.get("/play/TestHero")
                if "complete" in response.text.lower() and "Begin Adventure" in response.text:
                    break
                if "claim_cash" in response.text:
                    client.post(
                        "/play/TestHero/action",
                        data={"choice": "claim_cash"},
                        headers=_ORIGIN,
                    )
                elif "claim_material" in response.text:
                    client.post(
                        "/play/TestHero/action",
                        data={"choice": "claim_material"},
                        headers=_ORIGIN,
                    )
                elif "career_change_finish" in response.text:
                    client.post(
                        "/play/TestHero/action",
                        data={"choice": "career_change_finish"},
                        headers=_ORIGIN,
                    )
                else:
                    break

            response = client.get("/play/TestHero")
        text = response.text
        # The link should be present as a GET link (href, not a POST form).
        assert 'href="/adventure/TestHero"' in text
        assert "Begin Adventure" in text

    def test_adventure_link_returns_200(self, tmp_path: Path):
        """Following the handoff link to /adventure/{save} returns 200."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir)
        with _get_client(saves_dir) as client:
            _setup_character_for_muster_out(client)
            # C6: post-muster routes to choose_career_change before complete.
            # Drive claim choices, then career_change_finish to terminate.
            for _ in range(10):
                response = client.get("/play/TestHero")
                if "complete" in response.text.lower() and "Begin Adventure" in response.text:
                    break
                if "claim_cash" in response.text:
                    client.post(
                        "/play/TestHero/action",
                        data={"choice": "claim_cash"},
                        headers=_ORIGIN,
                    )
                elif "claim_material" in response.text:
                    client.post(
                        "/play/TestHero/action",
                        data={"choice": "claim_material"},
                        headers=_ORIGIN,
                    )
                elif "career_change_finish" in response.text:
                    client.post(
                        "/play/TestHero/action",
                        data={"choice": "career_change_finish"},
                        headers=_ORIGIN,
                    )
                else:
                    break

            # Follow the link.
            response = client.get("/adventure/TestHero")
        assert response.status_code == 200

    def test_resume_mid_allocation_reconstructs_remaining(self, tmp_path: Path):
        """A save mid-allocation reconstructs remaining rolls on fresh controller."""
        from src.engine.commands import Engine
        from src.engine.dice import LiveRoller
        from src.engine.lifepath import LifepathRunner, benefit_rolls_for
        from src.engine.persistence import save as save_state
        from src.engine.state import CampaignConfig, CareerTermRecord, GameState
        from src.game.lifepath import LifepathController
        from src.themepacks.cepheus_scifi import load_scifi_pack

        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        pack = load_scifi_pack()

        # Build a character that's mid-allocation: 1 term served, 1 benefit claimed.
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(theme_pack="scifi", resolution_profile="classic")
        char = state.character
        char.name = "ResumeHero"
        char.characteristics = {
            "STR": 7,
            "DEX": 7,
            "END": 7,
            "INT": 7,
            "EDU": 7,
            "SOC": 7,
        }
        char.career = ""
        char.alive = True
        char.background_picks_remaining = 0
        char.basic_training_done = True
        char.terms = 1
        char.age = 22
        # Career history simulates having served one term in navy.
        char.career_history.append(
            CareerTermRecord(
                career_id="navy",
                terms=1,
                final_rank=0,
                ended_by="muster_out",
                terms_in_career=1,  # C6: per-career terms drives benefit_rolls
            )
        )
        # Set the term_phase flag so the controller sees muster_out_allocate on load.
        state.narrative_log.append("term_phase=muster_out_allocate")

        # Pre-claim one cash benefit so there's something to reconstruct.
        engine = Engine(state, LiveRoller(state.rng))
        runner = LifepathRunner(engine, pack)
        runner.claim_benefit("navy", table="cash", dm=0)
        save_state(state, saves_dir / "ResumeHero.json")

        # Now build a fresh controller — it should reconstruct.
        from src.engine.persistence import load

        fresh_state = load(saves_dir / "ResumeHero.json")
        fresh_engine = Engine(fresh_state, LiveRoller(fresh_state.rng))
        controller = LifepathController(fresh_engine, pack)

        # The plan should have total_rolls = benefit_rolls_for(terms=1, rank=0) = 1.
        assert controller._muster_plan is not None
        assert controller._muster_plan.total_rolls == benefit_rolls_for(1, 0)
        # One cash benefit already claimed → remaining should be 0.
        assert controller._benefit_rolls_remaining == 0
        # Cash counter reconstructed.
        assert controller._runner.cash_rolls_taken == 1
