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
        [4, 2],  # chars
        [3, 2],  # qualification: INT 9 + DM 1 = 5 >= 5 -> success
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
        # Queue for a full term: survival, advancement, 2 skill rolls.
        term_queue = [
            [4, 3],  # survival: END 8 + DM 0 = 7 >= 5 -> success
            [5, 3],  # advancement: INT 9 + DM 1 = 9 >= 7 -> success
            [5, 3],  # skill 1
            [4, 3],  # skill 2
        ]

        # Run via step methods.
        engine_a, runner_a = setup_qualified_engine(list(term_queue), pack)
        result_a = runner_a.start_term("navy", 1)
        runner_a.run_survival_step("navy", result_a)
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
    def test_advancement_success_promotes(self, pack):
        engine, runner = setup_qualified_engine(
            [[4, 3], [5, 3]],
            pack,  # survival, advancement success
        )
        result = runner.start_term("navy", 1)
        runner.run_survival_step("navy", result)
        runner.run_advancement_step("navy", result)

        assert result.advancement_success
        assert result.rank_after == 1
        assert engine.state.character.rank == 1

    def test_advancement_failure_no_promotion(self, pack):
        _engine, runner = setup_qualified_engine(
            [[4, 3], [1, 1]],
            pack,  # survival, advancement fail (2 < 7)
        )
        result = runner.start_term("navy", 1)
        runner.run_survival_step("navy", result)
        runner.run_advancement_step("navy", result)

        assert not result.advancement_success
        assert result.rank_after == 0


# ---------------------------------------------------------------------------
# compute_num_skill_rolls.
# ---------------------------------------------------------------------------


class TestComputeNumSkillRolls:
    def test_base_one_roll(self, pack):
        _engine, runner = setup_qualified_engine([], pack)
        result = TermResult(
            term_number=1,
            career_id="navy",
            career_name="Navy",
            age_before=18,
            age_after=22,
        )
        result.advancement_success = False
        # Rank is 0 (not >= 3).
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

    def test_rank_3_grants_extra(self, pack):
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
        assert runner.compute_num_skill_rolls(result) == 3


# ---------------------------------------------------------------------------
# run_skill_roll_step.
# ---------------------------------------------------------------------------


class TestSkillRollStep:
    def test_single_skill_roll_returns_gain(self, pack):
        _engine, runner = setup_qualified_engine(
            [[4, 3], [5, 3], [5, 3]],
            pack,  # survival, advancement, skill
        )
        result = runner.start_term("navy", 1)
        runner.run_survival_step("navy", result)
        runner.run_advancement_step("navy", result)

        gain = runner.run_skill_roll_step("navy", result, "Personal Development")
        assert gain.table_name == "Personal Development"
        assert len(result.skill_gains) == 1
        assert result.skill_gains[0] is gain

    def test_skill_roll_unknown_table_falls_back(self, pack):
        _engine, runner = setup_qualified_engine([[4, 3], [5, 3], [5, 3]], pack)
        result = runner.start_term("navy", 1)
        runner.run_survival_step("navy", result)
        runner.run_advancement_step("navy", result)

        # Non-existent table name should fall back to first table.
        gain = runner.run_skill_roll_step("navy", result, "Nonexistent")
        assert gain.table_name == pack.careers["navy"].skill_tables[0].name


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
        engine, runner = setup_qualified_engine(
            [[5, 4]],
            pack,  # aging roll 9 >= 8 -> success
        )
        engine.state.character.age = 34
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

    def test_aging_at_34_failure(self, pack):
        engine, runner = setup_qualified_engine(
            [[2, 3]],
            pack,  # aging roll 5 < 8 -> failure
        )
        engine.state.character.age = 34
        result = TermResult(
            term_number=4,
            career_id="navy",
            career_name="Navy",
            age_before=30,
            age_after=34,
        )
        aged = runner.run_aging_step(result)
        assert aged is True
        assert not result.aging_success
        assert len(result.aging_reductions) > 0


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
