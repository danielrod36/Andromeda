"""Reconstruction tests for LifepathController (U2, AE2).

Tests that a mid-term save reconstructs correctly when a fresh
``LifepathController`` is constructed — simulating a server restart where
the in-memory session is lost but canonical state is on disk.

AE2 specifically tests reconstruction for a NON-HIERARCHY career (drifter)
whose ``advancement`` is None — the TUI's ``_reconstruct_term_state``
crashes on this because it dereferences ``advancement.target`` unconditionally.
The U2 port guards this.
"""

from __future__ import annotations

import copy

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.state import CampaignConfig, GameState
from src.game.lifepath import LifepathController
from src.themepacks.cepheus_scifi import load_scifi_pack


def _make_state(seed: int = 77) -> GameState:
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(
        theme_pack="scifi",
        resolution_profile="classic",
        death_mode="narrative",
    )
    return state


def _setup_drifter(state: GameState) -> None:
    """Pre-set a non-hierarchy career (drifter) for term testing.

    Drifter has ``advancement=None`` — the critical edge case for the
    reconstruction advancement guard.
    """
    char = state.character
    char.characteristics = {
        "STR": 7,
        "DEX": 8,
        "END": 6,
        "INT": 10,
        "EDU": 9,
        "SOC": 5,
    }
    char.career = "drifter"
    char.alive = True
    char.background_picks_remaining = 0
    char.basic_training_done = True


class TestReconstruction:
    """AE2: mid-term reconstruction from event log."""

    def test_reconstruct_mid_choose_skills_drifter(self):
        """Reconstruct a mid-choose_skills save for drifter (advancement=None).

        Build a controller, drive it to mid-choose_skills, snapshot the RNG,
        then construct a fresh controller. Assert:
        - same pending table choices
        - same rolls-remaining
        - no new rolls consumed (RNG byte-identical)
        """
        state = _make_state(seed=77)
        _setup_drifter(state)

        # Drifter is non-hierarchy: survival(2D6) + 2 skill rolls (1D6 each).
        # No commission, no advancement.
        roller = ForcedRoller(
            [
                [5, 3],  # survival 2D6=8 (pass)
                [4],  # skill 1D6=4 (first roll)
                [2],  # skill 1D6=2 (second roll — not consumed yet)
                [5, 5],  # reenlistment 2D6=10 (not consumed yet)
            ]
        )
        engine = Engine(state, roller)
        ctrl = LifepathController(engine, load_scifi_pack())

        # Drive to mid-choose_skills: begin term, then take 1 of 2 skill rolls.
        ctrl.apply_choice("begin_term")
        # No commission (drifter is non-hierarchy), no advancement.
        assert ctrl.determine_phase() == "choose_skills"
        assert ctrl._skill_rolls_remaining == 2

        # Take one skill roll.
        ctrl.apply_choice("skill_table:Personal Development")
        assert ctrl._skill_rolls_remaining == 1

        # Snapshot the RNG state and remaining controller state.
        rng_before = copy.deepcopy(state.rng)
        rolls_before = ctrl._skill_rolls_remaining
        result_before = ctrl._current_term_result

        # Construct a fresh controller — simulates server restart.
        ctrl2 = LifepathController(engine, load_scifi_pack())

        # The fresh controller should reconstruct the same state.
        assert ctrl2._current_term_result is not None
        assert ctrl2._skill_rolls_remaining == rolls_before
        # TermResult fields match.
        assert ctrl2._current_term_result.career_id == result_before.career_id
        assert ctrl2._current_term_result.survival_raw == result_before.survival_raw
        assert len(ctrl2._current_term_result.skill_gains) == len(result_before.skill_gains)

        # RNG should be byte-identical (no new rolls consumed by reconstruction).
        rng_after = state.rng
        assert rng_after.lifepath.internalstate == rng_before.lifepath.internalstate, (
            "Reconstruction consumed extra RNG rolls"
        )

        # C4: the skill roll hit a cascade slot (drifter Personal Development
        # slot 4 = cascade:melee), so a specialization choice interrupts
        # choose_skills. The fresh controller must reconstruct the same
        # interrupt — the pending cascade, not choose_skills.
        assert ctrl2.determine_phase() == "choose_specialization"
        assert ctrl2._current_term_result is not None

    def test_reconstruct_non_hierarchy_advancement_guard(self):
        """The advancement=None guard doesn't crash for non-hierarchy careers.

        Drifter's ``career.advancement`` is None. The TUI's
        ``_reconstruct_term_state`` crashes here; the U2 port guards it.
        """
        state = _make_state(seed=77)
        _setup_drifter(state)

        roller = ForcedRoller(
            [
                [4, 3],  # survival 2D6=7 (pass)
                [3],  # skill 1D6=3
                [4],  # skill 1D6=4
                [4, 4],  # reenlistment 2D6=8
            ]
        )
        engine = Engine(state, roller)
        ctrl = LifepathController(engine, load_scifi_pack())

        # Drive to mid-choose_skills.
        ctrl.apply_choice("begin_term")
        ctrl.apply_choice("skill_table:Personal Development")

        # Fresh controller — should not crash.
        ctrl2 = LifepathController(engine, load_scifi_pack())
        assert ctrl2._current_term_result is not None
        # advancement_target should be 0 (guarded).
        assert ctrl2._current_term_result.advancement_target == 0

    def test_reconstruct_mid_choose_skills_navy(self):
        """Reconstruction works for hierarchy careers too (navy).

        Navy has advancement and commission. After beginning a term and
        declining commission, then taking some skill rolls, reconstruction
        should restore the correct rolls-remaining.
        """
        state = _make_state(seed=55)
        char = state.character
        char.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 7,
        }
        char.career = "navy"
        char.alive = True
        char.background_picks_remaining = 0
        char.basic_training_done = True

        roller = ForcedRoller(
            [
                [4, 3],  # survival 2D6=7 (pass vs 5)
                [4, 4],  # commission 2D6=8 (pass vs 7)
                [4, 3],  # advancement 2D6=7 (pass vs 6)
                [3],  # skill 1D6=3 (first of 3 rolls)
                [5],  # skill 1D6=5 (second — not consumed yet)
                [2],  # skill 1D6=2 (third — not consumed yet)
                [5, 5],  # reenlistment 2D6=10 (not consumed yet)
            ]
        )
        engine = Engine(state, roller)
        ctrl = LifepathController(engine, load_scifi_pack())

        # Drive to mid-choose_skills.
        ctrl.apply_choice("begin_term")
        ctrl.apply_choice("commission_attempt")
        ctrl.apply_choice("advancement_attempt")
        assert ctrl._skill_rolls_remaining == 3  # 1 base + 1 commission + 1 advancement

        # Take one skill roll (leaving 2 remaining).
        ctrl.apply_choice("skill_table:Personal Development")
        assert ctrl._skill_rolls_remaining == 2

        rolls_before = ctrl._skill_rolls_remaining

        # Fresh controller.
        ctrl2 = LifepathController(engine, load_scifi_pack())
        assert ctrl2._skill_rolls_remaining == rolls_before
        assert ctrl2.determine_phase() == "choose_skills"

        # Commission and advancement results should be reconstructed.
        result = ctrl2._current_term_result
        assert result is not None
        assert result.commission_success
        assert result.advancement_success

    def test_reconstruct_rng_byte_identical(self):
        """RNG snapshot is byte-identical before and after reconstruction.

        This is the core AE2 guarantee: no extra dice are consumed.
        """
        state = _make_state(seed=77)
        _setup_drifter(state)

        roller = ForcedRoller(
            [
                [5, 3],  # survival
                [3],  # skill (1 of 2)
                [5],  # skill (2 of 2 — not consumed)
                [5, 5],  # reenlist (not consumed)
            ]
        )
        engine = Engine(state, roller)
        ctrl = LifepathController(engine, load_scifi_pack())

        ctrl.apply_choice("begin_term")
        ctrl.apply_choice("skill_table:Personal Development")

        # Snapshot RNG before reconstruction.
        lifepath_state_before = list(state.rng.lifepath.internalstate)

        # Fresh controller reconstructs from events.
        LifepathController(engine, load_scifi_pack())

        # RNG should be unchanged.
        lifepath_state_after = list(state.rng.lifepath.internalstate)
        assert lifepath_state_before == lifepath_state_after

    def test_reconstruct_with_no_survival_event_is_safe(self):
        """Construction when no survival events exist is safe (no crash).

        If term_phase is in TERM_PHASES but no survival event is found
        (edge case during testing), reconstruction silently returns without
        crashing.
        """
        state = _make_state(seed=77)
        _setup_drifter(state)

        # Set a term_phase flag without running any term events.
        engine = Engine(state)
        from src.engine.commands import SetFlagCommand

        engine.apply(SetFlagCommand(key="term_phase", value="choose_skills"))

        # Should not crash.
        ctrl = LifepathController(engine, load_scifi_pack())
        # Without survival events, _current_term_result stays None.
        assert ctrl._current_term_result is None
