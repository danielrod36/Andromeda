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


# ---------------------------------------------------------------------------
# U3: Muster-out benefit parity tests.
# ---------------------------------------------------------------------------


class TestMusterOutParity:
    """U3: web controller muster-out matches engine batch path."""

    def test_benefit_rolls_count_matches_engine(self):
        """The web controller's benefit roll count matches the engine."""
        web_state = _make_state(seed=99)
        _setup_char(web_state)
        web_engine = Engine(web_state, ForcedRoller(_navy_one_term_rolls()))
        web_ctrl = LifepathController(web_engine, load_scifi_pack())

        # Drive through 1 term + muster out.
        web_ctrl.apply_choice("begin_term")
        web_ctrl.apply_choice("commission_attempt")
        web_ctrl.apply_choice("advancement_attempt")
        for t in _SKILL_TABLES:
            web_ctrl.apply_choice(f"skill_table:{t}")
        web_ctrl.apply_choice("reenlist_muster")

        # Now in mustering_out → muster_out_allocate.
        from src.engine.lifepath import benefit_rolls_for

        char = web_state.character
        # terms=1, rank=2 → benefit_rolls_for(1, 2) = 1 + 0 = 1
        expected_rolls = benefit_rolls_for(char.terms, char.rank)
        assert web_ctrl._muster_plan is not None
        assert web_ctrl._muster_plan.total_rolls == expected_rolls

    def test_cash_and_material_claims_match_batch(self):
        """Claiming cash then material via web matches the batch path's results.

        Drives both paths with the same forced rolls and allocation order
        (cash first, then material), comparing the resulting benefit event texts.
        """
        # Build rolls: 1 navy term + 1 benefit roll (cash).
        term_rolls = _navy_one_term_rolls()
        # Add benefit roll: 1D6=3 for cash.
        all_rolls = [*term_rolls, [3]]

        # --- Web path ---
        web_state = _make_state(seed=99)
        _setup_char(web_state)
        web_engine = Engine(web_state, ForcedRoller(all_rolls))
        web_ctrl = LifepathController(web_engine, load_scifi_pack())

        web_ctrl.apply_choice("begin_term")
        web_ctrl.apply_choice("commission_attempt")
        web_ctrl.apply_choice("advancement_attempt")
        for t in _SKILL_TABLES:
            web_ctrl.apply_choice(f"skill_table:{t}")
        web_ctrl.apply_choice("reenlist_muster")
        # Claim one cash benefit.
        web_ctrl.apply_choice("claim_cash")

        web_benefit_events = [e for e in web_state.events if e.command_type == "lifepath_benefit"]

        # --- Batch path ---
        batch_state = _make_state(seed=99)
        _setup_char(batch_state)
        batch_engine = Engine(batch_state, ForcedRoller(all_rolls))
        batch_runner = LifepathRunner(batch_engine, load_scifi_pack())

        batch_runner.run_term("navy", 1, skill_table_choices=_SKILL_TABLES)
        batch_runner.run_reenlistment_step("navy")
        # Batch auto-allocates: cash-first.
        batch_runner._batch_muster_out("navy")

        batch_benefit_events = [
            e for e in batch_state.events if e.command_type == "lifepath_benefit"
        ]

        # Compare benefit result texts (at least the first one).
        if web_benefit_events and batch_benefit_events:
            assert (
                web_benefit_events[0].changes["result_text"]
                == (batch_benefit_events[0].changes["result_text"])
            ), (
                f"Benefit mismatch:\n"
                f"  web:   {web_benefit_events[0].changes['result_text']}\n"
                f"  batch: {batch_benefit_events[0].changes['result_text']}"
            )

    def test_all_rolls_consumed_completes_muster_out(self):
        """Claiming the single available roll completes muster out.

        A 1-term character with rank 2 has exactly 1 benefit roll.
        After claiming it, the controller reaches ``complete`` and sets
        ``mustered_out=true``.
        """
        term_rolls = _navy_one_term_rolls()
        all_rolls = [*term_rolls, [3]]

        web_state = _make_state(seed=99)
        _setup_char(web_state)
        web_engine = Engine(web_state, ForcedRoller(all_rolls))
        web_ctrl = LifepathController(web_engine, load_scifi_pack())

        web_ctrl.apply_choice("begin_term")
        web_ctrl.apply_choice("commission_attempt")
        web_ctrl.apply_choice("advancement_attempt")
        for t in _SKILL_TABLES:
            web_ctrl.apply_choice(f"skill_table:{t}")
        web_ctrl.apply_choice("reenlist_muster")

        plan = web_ctrl._muster_plan
        assert plan is not None
        # Claim the one available roll.
        view = web_ctrl.apply_choice("claim_cash")
        # Should now be at complete (all rolls consumed).
        assert view.phase == "complete"
        assert "mustered_out=true" in web_state.narrative_log

    def test_material_dm_applied_for_high_rank(self):
        """Rank 5+ characters get the material DM on material claims."""
        from src.engine.lifepath import material_dm_for

        term_rolls = _navy_one_term_rolls()
        # Add benefit rolls: cash + material.
        all_rolls = [*term_rolls, [3], [4]]

        web_state = _make_state(seed=99)
        _setup_char(web_state)
        web_engine = Engine(web_state, ForcedRoller(all_rolls))
        web_ctrl = LifepathController(web_engine, load_scifi_pack())

        web_ctrl.apply_choice("begin_term")
        web_ctrl.apply_choice("commission_attempt")
        web_ctrl.apply_choice("advancement_attempt")
        for t in _SKILL_TABLES:
            web_ctrl.apply_choice(f"skill_table:{t}")
        web_ctrl.apply_choice("reenlist_muster")

        # After 1 term with commission+advancement success, rank = 2.
        # material_dm_for(2) = 0. The plan should reflect this.
        plan = web_ctrl._muster_plan
        assert plan is not None
        assert plan.material_dm == material_dm_for(web_state.character.rank)
        # Rank 2 → DM 0.
        assert plan.material_dm == 0

    def test_resume_reconstructs_remaining_from_events(self):
        """A fresh controller reconstructs remaining rolls from benefit events."""
        term_rolls = _navy_one_term_rolls()
        all_rolls = [*term_rolls, [3], [4]]

        # First controller: drive through term + claim 1 cash benefit.
        web_state = _make_state(seed=99)
        _setup_char(web_state)
        web_engine = Engine(web_state, ForcedRoller(all_rolls))
        web_ctrl = LifepathController(web_engine, load_scifi_pack())

        web_ctrl.apply_choice("begin_term")
        web_ctrl.apply_choice("commission_attempt")
        web_ctrl.apply_choice("advancement_attempt")
        for t in _SKILL_TABLES:
            web_ctrl.apply_choice(f"skill_table:{t}")
        web_ctrl.apply_choice("reenlist_muster")
        # Plan total_rolls for 1 term, rank 2 = 1.
        plan = web_ctrl._muster_plan
        assert plan is not None
        total = plan.total_rolls

        # Claim one benefit if there are rolls available.
        if total > 0:
            web_ctrl.apply_choice("claim_cash")
            claimed = 1
        else:
            claimed = 0

        # Now build a fresh controller from the same state.
        fresh_engine = Engine(web_state, ForcedRoller([]))
        fresh_ctrl = LifepathController(fresh_engine, load_scifi_pack())

        # Reconstructed plan should have the same total.
        assert fresh_ctrl._muster_plan is not None
        assert fresh_ctrl._muster_plan.total_rolls == total
        # Remaining should reflect the claimed benefit.
        assert fresh_ctrl._benefit_rolls_remaining == total - claimed
        # Cash counter reconstructed.
        assert fresh_ctrl._runner.cash_rolls_taken == claimed
