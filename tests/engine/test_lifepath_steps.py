"""Tests for the LifepathRunner individual step methods.

Verifies that ``start_term``, ``run_survival_step``, ``run_advancement_step``,
``compute_num_skill_rolls``, ``run_skill_roll_step``, ``run_aging_step``, and
``finalize_term`` produce identical results to the legacy ``run_term`` when
called in sequence, and that each step can be used independently for the
interactive TUI flow.
"""

from __future__ import annotations

import pytest

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.lifepath import LifepathRunner, TermResult
from src.engine.state import CampaignConfig, GameState
from src.themepacks.base import get_pack

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def pack():
    return get_pack("scifi")


@pytest.fixture
def engine_and_pack():
    """Fresh (engine, pack) for pool/assign tests.

    Tests rebind ``engine._roller`` to a :class:`ForcedRoller` with the
    exact dice sequence they need; the default empty-queue roller is a
    placeholder so the fixture stays generic.
    """
    pack = get_pack("scifi")
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(death_mode="narrative")
    engine = Engine(state, roller=ForcedRoller([]))
    return engine, pack


def make_engine(queue, death_mode="narrative", seed=42):
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(death_mode=death_mode)
    return Engine(state, roller=ForcedRoller(queue))


def setup_qualified_engine(queue, pack, career_id="navy", death_mode="narrative"):
    """Create an engine with characteristics rolled and career qualified."""
    queue = [
        [6, 3],
        [4, 3],
        [5, 3],
        [5, 4],
        [4, 3],
        [4, 2],  # chars (INT = 9)
        [5, 4],  # qualification: INT 9 + DM 1 = 10 >= 6 -> success
        *queue,
    ]
    engine = make_engine(list(queue), death_mode=death_mode)
    runner = LifepathRunner(engine, pack)
    runner.roll_characteristics()
    runner.qualify(career_id)
    return engine, runner


# ---------------------------------------------------------------------------
# Step equivalence: step methods called in sequence == run_term().
# ---------------------------------------------------------------------------


class TestStepEquivalence:
    """Step methods produce the same result as run_term() when sequenced."""

    def test_step_sequence_matches_run_term(self, pack):
        """Calling step methods in order gives identical TermResult as run_term."""
        # Queue for a full term: survival, commission, advancement, skill rolls.
        # Commission fails (low roll) so rank stays 0; advancement succeeds ->
        # rank 1. Skill rolls: hierarchy base 1 + advancement 1 = 2.
        term_queue = [
            [4, 3],  # survival: INT 9 + DM 1 = 8 >= 5 -> success
            [1, 2],  # commission: INT 9 + DM 1 = 4 < 9 -> fail (rank stays 0)
            [5, 3],  # advancement: INT 9 + DM 1 = 9 >= 6 -> success (rank 1)
            [5],  # skill 1 (1D6)
            [4],  # skill 2 (1D6)
        ]

        # Run via step methods.
        engine_a, runner_a = setup_qualified_engine(list(term_queue), pack)
        result_a = runner_a.start_term("navy", 1)
        runner_a.run_survival_step("navy", result_a)
        runner_a.run_commission_step("navy", result_a)
        runner_a.run_advancement_step("navy", result_a)
        num_rolls = runner_a.compute_num_skill_rolls(result_a)
        for i in range(num_rolls):
            table_name = pack.careers["navy"].skill_tables[i].name
            runner_a.run_skill_roll_step("navy", result_a, table_name)
        runner_a.run_aging_step(result_a)
        runner_a.finalize_term("navy", result_a)

        # Run via legacy run_term.
        engine_b, runner_b = setup_qualified_engine(list(term_queue), pack)
        result_b = runner_b.run_term("navy", 1)

        # Key fields should match (state-dependent fields like rank are
        # checked via engine state since both mutate the same way).
        assert result_a.survival_raw == result_b.survival_raw
        assert result_a.survival_total == result_b.survival_total
        assert result_a.survival_success == result_b.survival_success
        assert result_a.advancement_raw == result_b.advancement_raw
        assert result_a.advancement_total == result_b.advancement_total
        assert result_a.advancement_success == result_b.advancement_success
        assert len(result_a.skill_gains) == len(result_b.skill_gains)
        assert result_a.rank_after == result_b.rank_after
        assert result_a.age_after == result_b.age_after

        # Engine state should be identical.
        assert engine_a.state.model_dump_json() == engine_b.state.model_dump_json()


# ---------------------------------------------------------------------------
# start_term.
# ---------------------------------------------------------------------------


class TestStartTerm:
    def test_creates_term_result_with_career_info(self, pack):
        _engine, runner = setup_qualified_engine([], pack)
        result = runner.start_term("navy", 1)
        assert result.term_number == 1
        assert result.career_id == "navy"
        assert result.career_name == "Navy"
        assert result.age_before == 18
        assert result.age_after == 22
        assert result.rank_before == 0
        assert result.survival_target == pack.careers["navy"].survival.target
        assert result.advancement_target == pack.careers["navy"].advancement.target

    def test_start_term_does_not_roll(self, pack):
        """start_term should not consume any dice from the queue."""
        _engine, runner = setup_qualified_engine([], pack)
        # The ForcedRoller queue should be empty and unused.
        result = runner.start_term("navy", 1)
        assert result.survival_raw == 0  # Not rolled yet.


# ---------------------------------------------------------------------------
# run_survival_step.
# ---------------------------------------------------------------------------


class TestSurvivalStep:
    def test_survival_success_advances_term(self, pack):
        engine, runner = setup_qualified_engine(
            [[4, 3]],
            pack,  # END 8 -> roll 7 -> success
        )
        result = runner.start_term("navy", 1)
        runner.run_survival_step("navy", result)

        assert result.survival_success
        assert not result.died
        assert not result.mishap
        assert engine.state.character.terms == 1
        assert engine.state.character.age == 22

    def test_survival_mishap_narrative_mode(self, pack):
        engine, runner = setup_qualified_engine([[1, 1]], pack, death_mode="narrative")
        result = runner.start_term("navy", 1)
        runner.run_survival_step("navy", result)

        assert not result.survival_success
        assert result.mishap
        assert not result.died
        # Term still advances even on mishap.
        assert engine.state.character.terms == 1

    def test_survival_death_ironman_mode(self, pack):
        engine, runner = setup_qualified_engine([[1, 1]], pack, death_mode="ironman")
        result = runner.start_term("navy", 1)
        runner.run_survival_step("navy", result)

        assert not result.survival_success
        assert result.died
        assert not engine.state.character.alive


# ---------------------------------------------------------------------------
# run_advancement_step.
# ---------------------------------------------------------------------------


class TestAdvancementStep:
    """B1: advancement requires rank 1+ (P1.T1); B5 caps rank at 6 (P1.T3)."""

    def test_advancement_rejected_at_rank_0(self, pack):
        """Term-1 rank-0 advancement is no longer offered (B1).

        The runner no-ops (no roll consumed, no rank change); the command
        itself raises so a direct ``Engine.apply`` is also gated.
        """
        engine, runner = setup_qualified_engine(
            [[4, 3]],
            pack,  # survival only — advancement must not consume a roll
        )
        result = runner.start_term("navy", 1)
        runner.run_survival_step("navy", result)
        runner.run_advancement_step("navy", result)  # no-op at rank 0 (B1)

        assert not result.advancement_success
        assert result.rank_after == 0
        assert engine.state.character.rank == 0

    def test_advancement_command_raises_at_rank_0(self, engine_and_pack):
        """The command gate is client-proof: validate rejects rank 0 (B1)."""
        from src.engine.lifepath import AdvancementCommand

        engine, _pack = engine_and_pack
        engine.state.character.career = "navy"
        with pytest.raises(ValueError, match="rank 1"):
            engine.apply(AdvancementCommand(career_id="navy", characteristic="EDU", target=6))

    def test_advancement_success_promotes_after_commission(self, pack):
        """A commissioned (rank 1) character advances normally."""
        engine, runner = setup_qualified_engine(
            [[4, 3], [4, 4], [5, 3]],
            pack,  # survival, commission (SOC 6: 8 >= 7), advancement (EDU 7: 8 >= 6)
        )
        result = runner.start_term("navy", 1)
        runner.run_survival_step("navy", result)
        runner.run_commission_step("navy", result)
        runner.run_advancement_step("navy", result)

        assert result.commission_success
        assert result.advancement_success
        assert result.rank_after == 2
        assert engine.state.character.rank == 2

    def test_advancement_failure_no_promotion(self, pack):
        engine, runner = setup_qualified_engine(
            [[4, 3], [4, 4], [1, 1]],
            pack,  # survival, commission success, advancement fail (2 < 6)
        )
        result = runner.start_term("navy", 1)
        runner.run_survival_step("navy", result)
        runner.run_commission_step("navy", result)
        runner.run_advancement_step("navy", result)

        assert not result.advancement_success
        assert result.rank_after == 1


# ---------------------------------------------------------------------------
# compute_num_skill_rolls.
# ---------------------------------------------------------------------------


class TestComputeNumSkillRolls:
    """Skill rolls per term: 2 non-hierarchy else 1, +1 commission, +1 advancement.

    The rank>=3 bonus has no SRD basis and was removed (N2). Hierarchy careers
    grant commission/advancement rolls; non-hierarchy careers (scout, drifter)
    grant a flat 2 rolls instead (B8/B9).
    """

    def test_non_hierarchy_career_gets_two_skill_rolls(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.career = "scout"
        runner = LifepathRunner(engine, pack)
        result = TermResult(
            term_number=1,
            career_id="scout",
            career_name="Scout",
            age_before=18,
            age_after=22,
        )
        assert runner.compute_num_skill_rolls(result) == 2

    def test_hierarchy_career_base_one_roll_no_rank_bonus(self, engine_and_pack):
        """Rank no longer grants skill rolls (N2); hierarchy base is 1."""
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"
        engine.state.character.rank = 5  # rank no longer grants skill rolls (N2)
        runner = LifepathRunner(engine, pack)
        result = TermResult(
            term_number=1,
            career_id="navy",
            career_name="Navy",
            age_before=18,
            age_after=22,
        )
        assert runner.compute_num_skill_rolls(result) == 1
        result.commission_success = True
        result.advancement_success = True
        assert runner.compute_num_skill_rolls(result) == 3

    def test_hierarchy_base_one_roll(self, pack):
        _engine, runner = setup_qualified_engine([], pack)
        result = TermResult(
            term_number=1,
            career_id="navy",
            career_name="Navy",
            age_before=18,
            age_after=22,
        )
        result.advancement_success = False
        result.commission_success = False
        assert runner.compute_num_skill_rolls(result) == 1

    def test_advancement_grants_extra(self, pack):
        _engine, runner = setup_qualified_engine([], pack)
        result = TermResult(
            term_number=1,
            career_id="navy",
            career_name="Navy",
            age_before=18,
            age_after=22,
        )
        result.advancement_success = True
        assert runner.compute_num_skill_rolls(result) == 2

    def test_rank_3_grants_no_extra(self, pack):
        """Rank>=3 no longer grants a bonus skill roll (N2 removal)."""
        engine, runner = setup_qualified_engine([], pack)
        engine.state.character.rank = 3
        result = TermResult(
            term_number=1,
            career_id="navy",
            career_name="Navy",
            age_before=18,
            age_after=22,
        )
        result.advancement_success = True
        # Hierarchy base 1 + advancement 1 = 2 (no rank bonus).
        assert runner.compute_num_skill_rolls(result) == 2


# ---------------------------------------------------------------------------
# Commission step (B8 — hierarchy careers, rank 0 only).
# ---------------------------------------------------------------------------


class TestCommissionStep:
    """Commission: success sets rank 1 and grants +1 skill roll (B8).

    Available only for hierarchy careers with a commission block, at rank 0,
    not by a draftee in their first term of the drafted career. The command
    itself enforces alive + rank 0; the runner-level ``commission_available``
    enforces the rest.
    """

    def test_commission_success_sets_rank_1_and_grants_roll(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"
        engine.state.character.characteristics = {"INT": 9}
        engine._roller = ForcedRoller([[4, 4]])
        runner = LifepathRunner(engine, pack)
        result = TermResult(
            term_number=1,
            career_id="navy",
            career_name="Navy",
            age_before=18,
            age_after=22,
        )
        runner.run_commission_step("navy", result)
        assert result.commission_success is True
        assert engine.state.character.rank == 1
        assert runner.compute_num_skill_rolls(result) == 2

    def test_commission_not_available_above_rank_0(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.rank = 2
        runner = LifepathRunner(engine, pack)
        assert runner.commission_available("navy") is False

    def test_draftee_no_commission_first_term(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.drafted = True
        engine.state.character.terms = 0
        runner = LifepathRunner(engine, pack)
        assert runner.commission_available("army") is False


# ---------------------------------------------------------------------------
# run_skill_roll_step.
# ---------------------------------------------------------------------------


class TestSkillRollStep:
    def test_single_skill_roll_returns_gain(self, pack):
        _engine, runner = setup_qualified_engine(
            [[4, 3], [5, 3], [5]],
            pack,  # survival, advancement, skill (1D6)
        )
        result = runner.start_term("navy", 1)
        runner.run_survival_step("navy", result)
        runner.run_advancement_step("navy", result)

        gain = runner.run_skill_roll_step("navy", result, "Personal Development")
        assert gain.table_name == "Personal Development"
        assert len(result.skill_gains) == 1
        assert result.skill_gains[0] is gain

    def test_skill_roll_unknown_table_raises(self, pack):
        _engine, runner = setup_qualified_engine([[4, 3], [5, 3], [5]], pack)
        result = runner.start_term("navy", 1)
        runner.run_survival_step("navy", result)
        runner.run_advancement_step("navy", result)

        # Non-existent table name should raise KeyError, not fall back.
        with pytest.raises(KeyError, match="Unknown skill table"):
            runner.run_skill_roll_step("navy", result, "Nonexistent")


# ---------------------------------------------------------------------------
# run_aging_step.
# ---------------------------------------------------------------------------


class TestAgingStep:
    def test_no_aging_under_34(self, pack):
        engine, runner = setup_qualified_engine([], pack)
        engine.state.character.age = 30
        result = TermResult(
            term_number=1,
            career_id="navy",
            career_name="Navy",
            age_before=26,
            age_after=30,
        )
        aged = runner.run_aging_step(result)
        assert aged is False
        assert result.aging_success is True  # default

    def test_aging_at_34_success(self, pack):
        """Adjusted roll >= 1 produces no pending slots."""
        engine, runner = setup_qualified_engine(
            [[5, 4]],
            pack,
        )
        engine.state.character.age = 34
        engine.state.character.terms = 4  # adjusted = 9 - 4 = 5 >= 1 -> no effect
        result = TermResult(
            term_number=4,
            career_id="navy",
            career_name="Navy",
            age_before=30,
            age_after=34,
        )
        aged = runner.run_aging_step(result)
        assert aged is True
        assert result.aging_success
        assert engine.state.character.pending_aging == []

    def test_aging_at_34_graduated_reduction(self, pack):
        """Adjusted roll < 1 produces pending slots for the player to assign."""
        engine, runner = setup_qualified_engine(
            [[2, 3]],
            pack,
        )
        engine.state.character.age = 34
        engine.state.character.terms = 5  # adjusted = 5 - 5 = 0 -> one physical x1
        result = TermResult(
            term_number=5,
            career_id="navy",
            career_name="Navy",
            age_before=34,
            age_after=38,
        )
        aged = runner.run_aging_step(result)
        assert aged is True
        assert not result.aging_success
        assert result.aging_reductions == {"physical": 1}
        slots = engine.state.character.pending_aging
        assert [(s.group, s.points) for s in slots] == [("physical", 1)]


# ---------------------------------------------------------------------------
# finalize_term.
# ---------------------------------------------------------------------------


class TestFinalizeTerm:
    def test_sets_rank_title(self, pack):
        engine, runner = setup_qualified_engine([], pack)
        engine.state.character.rank = 1
        result = TermResult(
            term_number=1,
            career_id="navy",
            career_name="Navy",
            age_before=18,
            age_after=22,
        )
        runner.finalize_term("navy", result)
        # Navy rank 1 should have a title.
        assert result.rank_title != ""

    def test_no_ranks_career_empty_title(self, pack):
        engine, runner = setup_qualified_engine([], pack)
        engine.state.character.rank = 0
        result = TermResult(
            term_number=1,
            career_id="scout",
            career_name="Scout",
            age_before=18,
            age_after=22,
        )
        runner.finalize_term("scout", result)
        # Scout has no ranks, so title stays empty.
        assert result.rank_title == ""


# ---------------------------------------------------------------------------
# Characteristic pool: roll-six-then-assign (Task 4 — player agency).
# ---------------------------------------------------------------------------


class TestCharacteristicPool:
    """Roll a pool of six 2D6 values the player assigns to characteristics.

    Design principle: the engine rolls dice; the player decides which rolled
    value goes to which characteristic. One optional full-pool reroll is
    allowed before any assignment (R-task-4).
    """

    def test_pool_roll_then_player_assigns(self, engine_and_pack):
        engine, pack = engine_and_pack
        from src.engine.dice import ForcedRoller

        engine._roller = ForcedRoller([[3, 4], [1, 2], [6, 6], [2, 2], [5, 5], [4, 3]])
        runner = LifepathRunner(engine, pack)
        pool = runner.roll_pool()
        assert pool == [7, 3, 12, 4, 10, 7]
        assert engine.state.character.characteristics == {}
        runner.assign_characteristic("INT", 2)  # assign the 12
        assert engine.state.character.characteristics == {"INT": 12}
        assert engine.state.character.unassigned_rolls == [7, 3, 4, 10, 7]

    def test_assign_rejects_taken_characteristic_and_bad_index(self, engine_and_pack):
        import pytest

        engine, pack = engine_and_pack
        engine._roller = ForcedRoller([[3, 4]] * 6)
        runner = LifepathRunner(engine, pack)
        runner.roll_pool()
        runner.assign_characteristic("STR", 0)
        with pytest.raises(ValueError):
            runner.assign_characteristic("STR", 0)
        with pytest.raises(ValueError):
            runner.assign_characteristic("DEX", 99)

    def test_reroll_once_before_first_assignment(self, engine_and_pack):
        import pytest

        engine, pack = engine_and_pack
        engine._roller = ForcedRoller([[1, 1]] * 6 + [[6, 6]] * 6)
        runner = LifepathRunner(engine, pack)
        runner.roll_pool()
        runner.reroll_pool()
        assert engine.state.character.unassigned_rolls == [12] * 6
        with pytest.raises(ValueError, match="reroll"):
            runner.reroll_pool()

    def test_reroll_rejected_after_assignment(self, engine_and_pack):
        import pytest

        engine, pack = engine_and_pack
        engine._roller = ForcedRoller([[1, 1]] * 6)
        runner = LifepathRunner(engine, pack)
        runner.roll_pool()
        runner.assign_characteristic("STR", 0)
        with pytest.raises(ValueError, match="reroll"):
            runner.reroll_pool()


# ---------------------------------------------------------------------------
# Re-enlistment roll at term end (Task 8 — B12).
# ---------------------------------------------------------------------------


class TestReenlistmentStep:
    """SRD re-enlistment rules (B12): 7+ terms -> must_retire (no roll);
    natural 12 -> must_continue; total < target -> must_leave; else may_continue.
    Careers without ``re_enlistment`` data -> may_continue (no roll).
    """

    def test_reenlist_natural_12_forces_continue(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"  # re_enlistment target = 6
        engine._roller = ForcedRoller([[6, 6]])
        runner = LifepathRunner(engine, pack)
        assert runner.run_reenlistment_step("navy") == "must_continue"

    def test_reenlist_below_target_forces_leave(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"  # target 6
        engine._roller = ForcedRoller([[1, 1]])  # total 2 < 6 -> must_leave
        runner = LifepathRunner(engine, pack)
        assert runner.run_reenlistment_step("navy") == "must_leave"

    def test_reenlist_player_choice_when_at_or_above_target(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"  # target 6
        engine._roller = ForcedRoller([[6, 4]])  # total 10 >= 6 -> may_continue
        runner = LifepathRunner(engine, pack)
        assert runner.run_reenlistment_step("navy") == "may_continue"

    def test_seven_terms_forces_retirement_without_roll(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"
        engine.state.character.terms = 7
        # Empty queue — must_retire must not consume any dice.
        engine._roller = ForcedRoller([])
        runner = LifepathRunner(engine, pack)
        assert runner.run_reenlistment_step("navy") == "must_retire"

    def test_reenlist_no_target_is_player_choice_no_roll(self, engine_and_pack):
        """A career without ``re_enlistment`` data yields may_continue, no roll.

        Tests the command directly (bypassing the runner, which reads the
        target from the shared cached pack) to avoid mutating pack state.
        """
        from src.engine.lifepath import ReenlistmentCommand

        engine, _pack = engine_and_pack
        engine.state.character.career = "navy"
        engine._roller = ForcedRoller([])  # empty queue — no roll may happen
        event = engine.apply(ReenlistmentCommand(career_id="navy", target=None))
        assert event.changes["outcome"] == "may_continue"
        assert event.roll is None

    def test_reenlist_event_kind_is_roll_when_rolled(self, engine_and_pack):
        """When dice are rolled, the event is a ROLL; otherwise STATE_CHANGE."""
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"
        engine._roller = ForcedRoller([[6, 4]])
        runner = LifepathRunner(engine, pack)
        runner.run_reenlistment_step("navy")
        from src.engine.audit import EventKind

        last = engine.state.events[-1]
        assert last.kind == EventKind.ROLL
        assert last.changes["outcome"] == "may_continue"
        assert last.changes["career_id"] == "navy"

    def test_reenlist_no_roll_event_kind_is_state_change(self, engine_and_pack):
        """must_retire produces a STATE_CHANGE event (no dice rolled)."""
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"
        engine.state.character.terms = 7
        engine._roller = ForcedRoller([])
        runner = LifepathRunner(engine, pack)
        runner.run_reenlistment_step("navy")
        from src.engine.audit import EventKind

        last = engine.state.events[-1]
        assert last.kind == EventKind.STATE_CHANGE
        assert last.changes["outcome"] == "must_retire"
        assert last.changes["roll_total"] is None

    def test_reenlist_natural_12_uses_raw_sum_not_adjusted_total(self, engine_and_pack):
        """The natural-12 check uses the RAW 2D6 sum, not adjusted by modifiers.

        Re-enlistment has no characteristic DM per SRD, so ``total`` equals the
        raw sum; but the implementation must check ``sum(rolls)`` to remain
        correct if modifiers are ever introduced.
        """
        engine, pack = engine_and_pack
        engine.state.character.career = "navy"
        engine._roller = ForcedRoller([[6, 6]])
        runner = LifepathRunner(engine, pack)
        outcome = runner.run_reenlistment_step("navy")
        assert outcome == "must_continue"
        # Verify the raw 2D6 sum (not an "adjusted" value) drove the outcome.
        last = engine.state.events[-1]
        assert sum(last.roll.rolls) == 12


# ---------------------------------------------------------------------------
# Task 9: Background skills, basic training, Advanced Education EDU-8 gate.
# ---------------------------------------------------------------------------


class TestBackgroundSkills:
    """Background skills (B10): 3 + EDU DM picks at level 0 from
    ``pack.background_skills``. ``start_background_phase`` computes the pick
    count once and stores it in ``background_picks_remaining``.
    """

    def test_background_skills_count_is_3_plus_edu_dm(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.characteristics = {"EDU": 10}  # DM +1 -> 4 picks
        runner = LifepathRunner(engine, pack)
        picks = runner.start_background_phase()
        assert picks == 4
        assert engine.state.character.background_picks_remaining == 4

    def test_background_skills_floor_zero(self, engine_and_pack):
        """EDU 2 (DM -2) would give 1; EDU 1 still floors at 0 picks."""
        engine, pack = engine_and_pack
        engine.state.character.characteristics = {"EDU": 1}  # DM -2 -> max(0, 1) = 1
        runner = LifepathRunner(engine, pack)
        picks = runner.start_background_phase()
        # 3 + (-2) = 1, still non-negative.
        assert picks == 1

    def test_start_background_phase_idempotent(self, engine_and_pack):
        """Re-calling start_background_phase returns the stored count."""
        engine, pack = engine_and_pack
        engine.state.character.characteristics = {"EDU": 7}  # DM 0 -> 3
        runner = LifepathRunner(engine, pack)
        first = runner.start_background_phase()
        second = runner.start_background_phase()
        assert first == second == 3

    def test_pick_background_skill_grants_level_0(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.characteristics = {"EDU": 7}
        runner = LifepathRunner(engine, pack)
        runner.start_background_phase()
        # Pick the first background skill.
        skill_id = pack.background_skills[0]
        runner.pick_background_skill(skill_id)
        assert engine.state.character.skills[skill_id] == 0
        assert engine.state.character.background_picks_remaining == 2

    def test_pick_background_skill_rejects_non_background(self, engine_and_pack):
        """Picking a skill not in background_skills raises."""
        engine, pack = engine_and_pack
        runner = LifepathRunner(engine, pack)
        runner.start_background_phase()
        # "astrogation" is a Navy service skill, not a background skill.
        with pytest.raises(ValueError, match="background"):
            runner.pick_background_skill("astrogation")


class TestGainSkillCommand:
    """GainSkillCommand sets skills[id] = max(current, level).

    Level-0 grants never stack: applying (id, 0) when the skill exists at
    level 1 leaves it at 1. Applying (id, 0) to a missing skill sets it to 0.
    """

    def test_gain_skill_level_0_not_stacking(self, engine_and_pack):
        from src.engine.lifepath import GainSkillCommand

        engine, _pack = engine_and_pack
        engine.state.character.skills = {"mechanic": 1}
        engine.apply(GainSkillCommand(skill_id="mechanic", level=0))
        assert engine.state.character.skills["mechanic"] == 1
        engine.apply(GainSkillCommand(skill_id="pilot_small_craft", level=0))
        assert engine.state.character.skills["pilot_small_craft"] == 0

    def test_gain_skill_higher_level_wins(self, engine_and_pack):
        from src.engine.lifepath import GainSkillCommand

        engine, _pack = engine_and_pack
        engine.state.character.skills = {"mechanic": 2}
        engine.apply(GainSkillCommand(skill_id="mechanic", level=1))
        assert engine.state.character.skills["mechanic"] == 2
        engine.apply(GainSkillCommand(skill_id="mechanic", level=3))
        assert engine.state.character.skills["mechanic"] == 3

    def test_gain_skill_event_recorded(self, engine_and_pack):
        from src.engine.lifepath import GainSkillCommand

        engine, _pack = engine_and_pack
        engine.apply(GainSkillCommand(skill_id="pilot_small_craft", level=0))
        last = engine.state.events[-1]
        assert last.changes["skill_id"] == "pilot_small_craft"
        assert last.changes["level"] == 0


class TestBasicTraining:
    """Basic training (B11): first career's first term → ALL Service Skills at
    level 0; later careers → one player-chosen Service skill at level 0.

    Tracked by ``character.basic_training_done`` (once per character lifetime).
    """

    def test_basic_training_first_career_grants_all_service_skills(self, engine_and_pack):
        engine, pack = engine_and_pack
        runner = LifepathRunner(engine, pack)
        runner.run_basic_training("navy")
        service = next(t for t in pack.careers["navy"].skill_tables if t.name == "Service Skills")
        for entry in service.entries.entries:
            if not entry.result.startswith("+"):
                assert engine.state.character.skills.get(entry.result) == 0
        assert engine.state.character.basic_training_done is True

    def test_basic_training_later_career_grants_one_chosen(self, engine_and_pack):
        from src.engine.state import CareerTermRecord

        engine, pack = engine_and_pack
        engine.state.character.career_history = [
            CareerTermRecord(career_id="army", terms=2, final_rank=1, ended_by="muster_out")
        ]
        runner = LifepathRunner(engine, pack)
        # The player must choose a Service skill from the new career's table.
        runner.run_basic_training("navy", chosen_skill="engineer")
        assert engine.state.character.skills.get("engineer") == 0
        # Other Navy service skills are NOT granted for a later career.
        assert engine.state.character.skills.get("electronics_comms") is None

    def test_basic_training_later_career_rejects_non_service_skill(self, engine_and_pack):
        from src.engine.state import CareerTermRecord

        engine, pack = engine_and_pack
        engine.state.character.career_history = [
            CareerTermRecord(career_id="army", terms=2, final_rank=1, ended_by="muster_out")
        ]
        runner = LifepathRunner(engine, pack)
        # "gamble" is not a Navy Service Skill.
        with pytest.raises(ValueError, match="Service skill"):
            runner.run_basic_training("navy", chosen_skill="gamble")

    def test_basic_training_done_is_one_shot(self, engine_and_pack):
        """Once basic_training_done is True, subsequent calls are no-ops."""
        engine, pack = engine_and_pack
        engine.state.character.basic_training_done = True
        runner = LifepathRunner(engine, pack)
        runner.run_basic_training("navy")
        # No service skills were granted.
        assert engine.state.character.skills == {}


class TestAdvancedEducationGate:
    """B7: The Advanced Education table requires EDU ≥ 8. Enforced in
    ``run_skill_roll_step`` (engine-side) and hidden in the TUI.
    """

    def test_advanced_education_requires_edu_8(self, engine_and_pack):
        engine, pack = engine_and_pack
        engine.state.character.characteristics = {"EDU": 7}
        engine.state.character.career = "navy"
        runner = LifepathRunner(engine, pack)
        result = TermResult(
            term_number=1, career_id="navy", career_name="Navy", age_before=18, age_after=22
        )
        with pytest.raises(ValueError, match="EDU 8"):
            runner.run_skill_roll_step("navy", result, "Advanced Education")

    def test_advanced_education_allows_edu_8(self, engine_and_pack):
        """EDU exactly 8 is allowed (boundary)."""
        engine, pack = engine_and_pack
        engine.state.character.characteristics = {"EDU": 8}
        engine.state.character.career = "navy"
        engine._roller = ForcedRoller([[3]])
        runner = LifepathRunner(engine, pack)
        result = TermResult(
            term_number=1, career_id="navy", career_name="Navy", age_before=18, age_after=22
        )
        # Should not raise.
        gain = runner.run_skill_roll_step("navy", result, "Advanced Education")
        assert gain.table_name == "Advanced Education"
