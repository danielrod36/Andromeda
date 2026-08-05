"""Parity test: web controller vs engine batch path (U2, AE1).

Drives a career through the web ``LifepathController`` and the engine's batch
``run_term`` path with the same seed and identical ForcedRoller queues. Asserts
the final character sheets match: same characteristics, skills, rank, terms,
age, and alive status.

The scripted choices keep roll counts aligned between paths so the
ForcedRoller FIFO never shifts from count divergence.
"""

from __future__ import annotations

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.lifepath import LifepathRunner
from src.engine.state import CampaignConfig, GameState
from src.game.lifepath import LifepathController
from src.themepacks.cepheus_scifi import load_scifi_pack


def _make_state(seed: int = 99) -> GameState:
    """Fresh state with scifi theme and narrative death mode."""
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(
        theme_pack="scifi",
        resolution_profile="classic",
        death_mode="narrative",
    )
    state.character.name = "ParityHero"
    return state


def _setup_char(state: GameState) -> None:
    """Pre-set characteristics, career, and background to skip pre-career phases.

    SOC 7 ensures navy commission (target 7) succeeds on a 2D6=7+ forced roll.
    """
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


def _navy_one_term_rolls() -> list[list[int]]:
    """Forced rolls for 1 navy term matching run_term's exact roll sequence.

    run_term calls (in order):
    1. run_survival_step → 2D6
    2. run_commission_step → 2D6 (commission_available is True at rank 0)
    3. run_advancement_step → 2D6
    4. run_skill_roll_step × N → 1D6 each
       N = compute_num_skill_rolls = 1 (base) + commission + advancement
       With both succeeding: 1 + 1 + 1 = 3 skill rolls
    5. run_aging_step → 2D6 (only if age >= 34; at age 18 it's skipped)
       _auto_apply_aging → no pending slots → no-op
    6. run_reenlistment_step → 2D6 (called separately, not by run_term)
    """
    return [
        [4, 3],  # survival 2D6=7 (pass vs 5)
        [4, 4],  # commission 2D6=8 (pass vs 7) → rank 1, +1 skill roll
        [4, 3],  # advancement 2D6=7 (pass vs 6) → rank 2, +1 skill roll
        [3],  # skill 1D6=3 (Personal Development)
        [5],  # skill 1D6=5 (Service Skills)
        [2],  # skill 1D6=2 (Specialist Skills)
        [5, 5],  # reenlistment 2D6=10 (may_continue vs 5)
    ]


_SKILL_TABLES = ["Personal Development", "Service Skills", "Specialist Skills"]


class TestLifepathParity:
    """AE1: web controller matches engine batch path for the same seed + choices."""

    def test_one_term_navy_character_sheet_matches(self):
        """Drive navy for 1 term via both paths; compare final character sheets.

        Both paths get the same ForcedRoller queue and the same skill table
        choices. The web path attempts commission (matching run_term's auto
        behavior). The final character state must match.
        """
        # --- Web controller path ---
        web_state = _make_state(seed=99)
        _setup_char(web_state)
        web_engine = Engine(web_state, ForcedRoller(_navy_one_term_rolls()))
        web_ctrl = LifepathController(web_engine, load_scifi_pack())

        web_ctrl.apply_choice("begin_term")
        # Attempt commission (matching run_term's auto-commission).
        web_ctrl.apply_choice("commission_attempt")
        web_ctrl.apply_choice("advancement_attempt")
        for table in _SKILL_TABLES:
            web_ctrl.apply_choice(f"skill_table:{table}")
        # After last skill roll, reenlistment auto-resolves (may_continue).
        web_ctrl.apply_choice("reenlist_continue")

        web_char = web_state.character

        # --- Engine batch path ---
        batch_state = _make_state(seed=99)
        _setup_char(batch_state)
        batch_engine = Engine(batch_state, ForcedRoller(_navy_one_term_rolls()))
        batch_runner = LifepathRunner(batch_engine, load_scifi_pack())

        batch_runner.run_term("navy", 1, skill_table_choices=_SKILL_TABLES)
        batch_runner.run_reenlistment_step("navy")

        batch_char = batch_state.character

        # --- Compare ---
        assert web_char.characteristics == batch_char.characteristics, (
            f"Characteristics mismatch:\n"
            f"  web:   {web_char.characteristics}\n"
            f"  batch: {batch_char.characteristics}"
        )
        assert web_char.skills == batch_char.skills, (
            f"Skills mismatch:\n  web: {web_char.skills}\n  batch: {batch_char.skills}"
        )
        assert web_char.rank == batch_char.rank
        assert web_char.terms == batch_char.terms
        assert web_char.age == batch_char.age
        assert web_char.alive == batch_char.alive

    def test_audit_event_types_match(self):
        """Both paths produce the same audit event types (excluding set_flag)."""
        # Web
        web_state = _make_state(seed=99)
        _setup_char(web_state)
        web_engine = Engine(web_state, ForcedRoller(_navy_one_term_rolls()))
        web_ctrl = LifepathController(web_engine, load_scifi_pack())
        web_ctrl.apply_choice("begin_term")
        web_ctrl.apply_choice("commission_attempt")
        web_ctrl.apply_choice("advancement_attempt")
        for t in _SKILL_TABLES:
            web_ctrl.apply_choice(f"skill_table:{t}")
        web_ctrl.apply_choice("reenlist_continue")

        web_types = [e.command_type for e in web_state.events if e.command_type != "set_flag"]

        # Batch
        batch_state = _make_state(seed=99)
        _setup_char(batch_state)
        batch_engine = Engine(batch_state, ForcedRoller(_navy_one_term_rolls()))
        batch_runner = LifepathRunner(batch_engine, load_scifi_pack())
        batch_runner.run_term("navy", 1, skill_table_choices=_SKILL_TABLES)
        batch_runner.run_reenlistment_step("navy")

        batch_types = [e.command_type for e in batch_state.events if e.command_type != "set_flag"]

        assert web_types == batch_types, (
            f"Event type mismatch:\n  web:   {web_types}\n  batch: {batch_types}"
        )

    def test_reenlistment_event_present(self):
        """The web path produces a reenlistment roll event (R4)."""
        web_state = _make_state(seed=99)
        _setup_char(web_state)
        web_engine = Engine(web_state, ForcedRoller(_navy_one_term_rolls()))
        web_ctrl = LifepathController(web_engine, load_scifi_pack())
        web_ctrl.apply_choice("begin_term")
        web_ctrl.apply_choice("commission_attempt")
        web_ctrl.apply_choice("advancement_attempt")
        for t in _SKILL_TABLES:
            web_ctrl.apply_choice(f"skill_table:{t}")
        # Reenlistment auto-resolves after the last skill roll.

        event_types = [e.command_type for e in web_state.events]
        assert "lifepath_reenlistment" in event_types

    def test_no_extra_rolls_consumed_across_paths(self):
        """Both paths consume exactly the same number of dice rolls."""
        rolls = _navy_one_term_rolls()

        # Web
        web_state = _make_state(seed=99)
        _setup_char(web_state)
        web_roller = ForcedRoller(rolls)
        web_engine = Engine(web_state, web_roller)
        web_ctrl = LifepathController(web_engine, load_scifi_pack())
        web_ctrl.apply_choice("begin_term")
        web_ctrl.apply_choice("commission_attempt")
        web_ctrl.apply_choice("advancement_attempt")
        for t in _SKILL_TABLES:
            web_ctrl.apply_choice(f"skill_table:{t}")
        web_ctrl.apply_choice("reenlist_continue")
        web_remaining = web_roller.remaining

        # Batch
        batch_state = _make_state(seed=99)
        _setup_char(batch_state)
        batch_roller = ForcedRoller(rolls)
        batch_engine = Engine(batch_state, batch_roller)
        batch_runner = LifepathRunner(batch_engine, load_scifi_pack())
        batch_runner.run_term("navy", 1, skill_table_choices=_SKILL_TABLES)
        batch_runner.run_reenlistment_step("navy")
        batch_remaining = batch_roller.remaining

        assert web_remaining == batch_remaining, (
            f"Roll count mismatch: web={web_remaining}, batch={batch_remaining}"
        )
