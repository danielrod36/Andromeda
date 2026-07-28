"""Tests for the lifepath engine: chargen end-to-end, death mode, aging, mustering out.

Uses ForcedRoller to control every die, making scenarios fully deterministic.
Covers R9 (lifepath playable end-to-end), R10 (death mode honored),
AE2 (Ironman death vs non-Ironman mishap), AE7 (no LLM required).
"""
from __future__ import annotations

import pytest

from src.engine.audit import EventKind, audit_rolls
from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.lifepath import (
    AdvanceTermCommand,
    LifepathResult,
    LifepathRunner,
    apply_skill_result,
    lookup_table_result,
)
from src.engine.state import CampaignConfig, Character, GameState
from src.rulesets.base import SkillTableEntry
from src.rulesets.cepheus import CepheusRuleSet
from src.themepacks.base import get_pack


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def pack():
    return get_pack("scifi")


@pytest.fixture
def ruleset():
    return CepheusRuleSet()


def make_engine(queue, death_mode="narrative", seed=42):
    """Create an engine with ForcedRoller and given death mode."""
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(death_mode=death_mode)
    return Engine(state, roller=ForcedRoller(queue))


# ---------------------------------------------------------------------------
# Helper function tests.
# ---------------------------------------------------------------------------


class TestLookupTableResult:
    def test_finds_matching_entry(self):
        entries = [
            SkillTableEntry(min=2, max=3, result="a"),
            SkillTableEntry(min=4, max=6, result="b"),
            SkillTableEntry(min=7, max=12, result="c"),
        ]
        assert lookup_table_result(entries, 5).result == "b"
        assert lookup_table_result(entries, 2).result == "a"
        assert lookup_table_result(entries, 12).result == "c"

    def test_clamps_overflow(self):
        entries = [
            SkillTableEntry(min=1, max=1, result="x"),
            SkillTableEntry(min=2, max=6, result="y"),
        ]
        assert lookup_table_result(entries, 9).result == "y"

    def test_clamps_underflow(self):
        entries = [
            SkillTableEntry(min=2, max=6, result="y"),
        ]
        assert lookup_table_result(entries, 1).result == "y"


class TestApplySkillResult:
    def test_skill_increment(self):
        char = Character()
        gain_type, name = apply_skill_result(char, "pilot")
        assert gain_type == "skill"
        assert name == "pilot"
        assert char.skills["pilot"] == 1

    def test_skill_increment_existing(self):
        char = Character(skills={"pilot": 2})
        apply_skill_result(char, "pilot")
        assert char.skills["pilot"] == 3

    def test_characteristic_increment(self):
        char = Character(characteristics={"STR": 7})
        gain_type, name = apply_skill_result(char, "+1 STR")
        assert gain_type == "characteristic"
        assert name == "STR"
        assert char.characteristics["STR"] == 8


# ---------------------------------------------------------------------------
# Scenario 1 + AE7: Complete lifepath run, no LLM, all rolls logged.
# ---------------------------------------------------------------------------


class TestCompleteLifepath:
    def test_complete_lifepath_two_terms(self, pack, ruleset):
        """Full lifepath: characteristics -> qualification -> 2 terms -> mustering out.

        All rolls go through the funnel and appear in the event log (R9, AE7).
        """
        queue = [
            # Characteristics (6 x 2D6)
            [6, 3],  # STR = 9
            [4, 3],  # DEX = 7
            [5, 3],  # END = 8
            [5, 4],  # INT = 9
            [4, 3],  # EDU = 7
            [4, 2],  # SOC = 6
            # Qualification (INT 9 -> DM +1, target 5)
            [3, 2],  # 5 + 1 = 6 >= 5 -> success
            # Term 1: survival, advancement, 2 skill rolls
            [4, 3],  # Survival: 7 + 0 = 7 >= 5 -> success
            [5, 3],  # Advancement: 8 + 0 = 8 >= 7 -> success (rank 1)
            [5, 3],  # Skill (Personal Dev): 8 -> +1 EDU
            [4, 3],  # Skill (Service): 7 -> pilot_small_craft
            # Term 2
            [3, 3],  # Survival: 6 + 0 = 6 >= 5 -> success
            [4, 4],  # Advancement: 8 + 0 = 8 >= 7 -> success (rank 2)
            [6, 3],  # Skill (Personal Dev): 9 -> +1 EDU
            [6, 4],  # Skill (Service): 10 -> sensor_ops
            # Mustering out (2 terms, rank 2)
            # Cash: DM = 1*2 + 1*2 = 4, 2 rolls
            [1],  # 1 + 4 = 5 -> 40,000 Cr
            [1],  # 1 + 4 = 5 -> 40,000 Cr
            # Material: 2 rolls, DM = 0
            [3],  # 3 -> Middle Passage
            [5],  # 5 -> Ship Share
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack, ruleset)
        result = runner.run_lifepath("navy", num_terms=2)

        # Characteristics rolled.
        assert result.characteristics == {
            "STR": 9, "DEX": 7, "END": 8, "INT": 9, "EDU": 7, "SOC": 6
        }

        # Qualification succeeded.
        assert result.qualification is not None
        assert result.qualification.success
        assert result.qualification.career_id == "navy"

        # Two terms completed.
        assert result.num_terms == 2
        term1 = result.terms[0]
        assert term1.survival_success
        assert term1.advancement_success
        assert term1.rank_after == 1
        assert len(term1.skill_gains) == 2

        # Character alive, skills gained.
        assert result.character_alive
        char = engine.state.character
        assert char.alive
        assert char.terms == 2
        assert char.age == 26  # 18 + 2*4
        assert char.rank == 2
        assert "pilot_small_craft" in char.skills
        # EDU went from 7 -> 8 (term 1) -> 9 (term 2)
        assert char.characteristics["EDU"] == 9

        # Mustering out completed.
        assert result.mustering_out is not None
        assert len(result.mustering_out.cash_benefits) == 2
        assert len(result.mustering_out.material_benefits) == 2

        # All rolls logged via the funnel (R9, AE7).
        rolls = audit_rolls(engine.state.events)
        # 6 chars + 1 qual + (1 surv + 1 adv + 2 skill) * 2 terms + 2 cash + 2 material
        assert len(rolls) == 6 + 1 + 4 * 2 + 2 + 2

    def test_all_events_are_audited(self, pack):
        """Every lifepath roll appears in the audit log with full inputs (AE1)."""
        queue = [
            [5, 3], [4, 3], [5, 3], [4, 3], [4, 3], [4, 2],  # chars
            [4, 3],  # qualification (success)
            [4, 3],  # survival (success)
            [5, 3],  # advancement (success)
            [5, 3],  # skill 1
            [4, 3],  # skill 2 (advancement gives extra)
            # mustering out (1 term, rank 1)
            [1],  # cash
            [2],  # material
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        runner.run_lifepath("navy", num_terms=1)

        for event in audit_rolls(engine.state.events):
            assert event.kind == EventKind.ROLL
            assert event.roll is not None
            assert event.roll.stream == "lifepath"
            assert event.roll.ndice >= 1
            assert event.roll.sides == 6


# ---------------------------------------------------------------------------
# Scenario 2: AE2 Ironman death in chargen.
# ---------------------------------------------------------------------------


class TestIronmanDeath:
    def test_failed_survival_kills_character_ironman(self, pack):
        """Ironman mode: failed survival -> alive=False, lifepath ends (AE2)."""
        queue = [
            [5, 3], [4, 3], [5, 3], [4, 3], [4, 3], [4, 2],  # chars
            [4, 3],  # qualification: INT 7 + DM 0 = 7 >= 5 -> success
            [1, 1],  # survival: END 8 + DM 0 = 2 < 5 -> DEATH
        ]
        engine = make_engine(queue, death_mode="ironman")
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=3)

        assert not result.character_alive
        assert not engine.state.character.alive
        assert len(result.terms) == 1
        assert result.terms[0].died
        assert result.mustering_out is None  # dead characters don't muster out


# ---------------------------------------------------------------------------
# Scenario 3: AE2 Non-Ironman mishap.
# ---------------------------------------------------------------------------


class TestNonIronmanMishap:
    def test_failed_survival_mishap_narrative_mode(self, pack):
        """Narrative mode: failed survival -> mishap, mustering out proceeds (AE2)."""
        queue = [
            [5, 3], [4, 3], [5, 3], [4, 3], [4, 3], [4, 2],  # chars
            [4, 3],  # qualification -> success
            [1, 1],  # survival -> 2 < 5 -> mishap
            # Mustering out (1 term, rank 0)
            # Cash: DM = 1*1 + 1*0 = 1, 1 roll
            [3],  # 3 + 1 = 4 -> 30,000 Cr
            # Material: 1 roll, DM = 0
            [2],  # 2 -> Low Passage
        ]
        engine = make_engine(queue, death_mode="narrative")
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=3)

        assert result.character_alive
        assert engine.state.character.alive
        assert len(result.terms) == 1
        assert result.terms[0].mishap
        assert not result.terms[0].died
        # Mishap ends career but mustering out happens.
        assert result.mustering_out is not None

    def test_failed_survival_mishap_checkpoint_mode(self, pack):
        """Checkpoint mode behaves like narrative for mishap (AE2)."""
        queue = [
            [5, 3], [4, 3], [5, 3], [4, 3], [4, 3], [4, 2],
            [4, 3],  # qual success
            [1, 2],  # survival: 3 < 5 -> mishap
            # Mustering out (1 term, rank 0)
            [3],  # cash: 3 + 1 = 4 -> 30,000 Cr
            [2],  # material: Low Passage
        ]
        engine = make_engine(queue, death_mode="checkpoint")
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=2)

        assert result.character_alive
        assert result.terms[0].mishap


# ---------------------------------------------------------------------------
# Scenario 5: Qualification failure -> drifter fallback.
# ---------------------------------------------------------------------------


class TestQualificationFailure:
    def test_qualification_failure_falls_back_to_drifter(self, pack):
        """Failed qualification for navy -> tries drifter (easy target 3)."""
        queue = [
            [2, 1],  # STR = 3
            [2, 1],  # DEX = 3
            [2, 1],  # END = 3
            [2, 1],  # INT = 3 -> DM -1
            [2, 1],  # EDU = 3
            [2, 1],  # SOC = 3
            # Navy qualification: INT 3, DM -1, target 5
            [2, 1],  # 3 + (-1) = 2 < 5 -> fail
            # Drifter qualification: END 3, DM -1, target 3
            [3, 2],  # 5 + (-1) = 4 >= 3 -> success
            # Term 1 (drifter)
            [4, 3],  # Survival: END 3 + DM -1 = 6 >= 5 -> success
            [5, 3],  # Advancement: END 3 + DM -1 = 7 >= 7 -> success
            [5, 3],  # Skill 1
            [4, 3],  # Skill 2 (advancement success -> extra roll)
            # Mustering out (1 term, rank 0, drifter has no ranks)
            [1],  # cash
            [1],  # material
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=1)

        # Navy qualification failed, fell back to drifter which succeeded.
        # result.qualification holds the drifter result (the final attempt).
        assert result.qualification.career_id == "drifter"
        assert result.qualification.success
        assert result.career_id == "drifter"
        assert len(result.terms) == 1


# ---------------------------------------------------------------------------
# Scenario 6: Aging effects at age 34+.
# ---------------------------------------------------------------------------


class TestAging:
    def test_aging_reduces_physical_stats_on_failure(self, pack):
        """At age 34+, failed aging roll reduces STR/DEX/END by 1 each."""
        queue = [
            [5, 3],  # STR = 8
            [5, 3],  # DEX = 8
            [5, 3],  # END = 8
            [2, 1],  # INT = 3, DM -1, qualification target 3 -> need 4+
            [2, 1],  # EDU = 3
            [4, 2],  # SOC = 6
            # Drifter qualification: END 8, DM 0, target 3
            [3, 2],  # 5 >= 3 -> success
        ]
        # Terms 1-3 (ages 18->30): survival, advancement, skills each.
        # No aging checks (age < 34).
        for _term in range(3):
            queue.extend([
                [4, 3],  # Survival: END 8 + DM 0 = 7 >= 5 -> success
                [4, 3],  # Advancement: END 8 + DM 0 = 7 >= 7 -> success
                [5, 3],  # Skill 1
                [5, 3],  # Skill 2 (advancement -> extra)
            ])
        # Term 4 (age 30->34): survival, advancement, skills, THEN aging.
        queue.extend([
            [4, 3],  # Survival
            [4, 3],  # Advancement
            [5, 3],  # Skill 1
            [5, 3],  # Skill 2 (advancement -> extra)
            # Aging check: roll 2D6 vs 8
            [2, 3],  # 5 < 8 -> aging! Physical stats reduced.
        ])
        # Mustering out (4 terms, rank 0 since drifter has no ranks)
        queue.extend([
            [1], [1], [1],  # Cash: 3 rolls
            [1], [1], [1], [1],  # Material: 4 rolls
        ])
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("drifter", num_terms=4)

        assert result.num_terms == 4
        term4 = result.terms[3]
        assert term4.age_after == 34
        assert not term4.aging_success
        assert "STR" in term4.aging_reductions
        assert "DEX" in term4.aging_reductions
        assert "END" in term4.aging_reductions
        # INT and EDU should NOT be reduced (not exceptional failure).
        assert "INT" not in term4.aging_reductions

        # Verify state was mutated.
        char = engine.state.character
        assert char.characteristics["STR"] == 7  # 8 - 1
        assert char.characteristics["DEX"] == 7
        assert char.characteristics["END"] == 7

    def test_aging_exceptional_failure_reduces_all(self, pack):
        """Natural 2 on aging roll reduces ALL characteristics."""
        queue = [
            [5, 3], [5, 3], [5, 3], [2, 1], [2, 1], [4, 2],  # chars
            [3, 2],  # Drifter qualification success
        ]
        for _term in range(3):
            queue.extend([[4, 3], [4, 3], [5, 3], [5, 3]])
        # Term 4 with exceptional aging failure.
        queue.extend([
            [4, 3],  # survival
            [4, 3],  # advancement
            [5, 3],  # skill 1
            [5, 3],  # skill 2
            [1, 1],  # aging: natural 2 < 8 -> ALL reduced
        ])
        queue.extend([
            [1], [1], [1],  # cash
            [1], [1], [1], [1],  # material
        ])
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("drifter", num_terms=4)

        term4 = result.terms[3]
        assert not term4.aging_success
        assert term4.aging_raw == 2
        # All six characteristics reduced.
        assert len(term4.aging_reductions) == 6

    def test_aging_success_no_reduction(self, pack):
        """Successful aging roll (>= 8) causes no reductions."""
        queue = [
            [5, 3], [5, 3], [5, 3], [2, 1], [2, 1], [4, 2],
            [3, 2],  # qual
        ]
        for _term in range(3):
            queue.extend([[4, 3], [4, 3], [5, 3], [5, 3]])
        queue.extend([
            [4, 3], [4, 3], [5, 3], [5, 3],
            [5, 4],  # aging: 9 >= 8 -> no effect
        ])
        queue.extend([
            [1], [1], [1],
            [1], [1], [1], [1],
        ])
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("drifter", num_terms=4)

        term4 = result.terms[3]
        assert term4.aging_success
        assert term4.aging_reductions == {}
        # Stats unchanged.
        char = engine.state.character
        assert char.characteristics["STR"] == 8


# ---------------------------------------------------------------------------
# Scenario 7: Mustering out benefits computed from career and rank.
# ---------------------------------------------------------------------------


class TestMusteringOut:
    def test_cash_benefits_with_dm_per_term_and_rank(self, pack):
        """Cash benefit rolls include DM per term and per rank."""
        queue = [
            [5, 3], [4, 3], [5, 3], [5, 4], [4, 3], [4, 2],  # chars
            [4, 3],  # qual: INT 9 + DM 1 = 7 >= 5 -> success
        ]
        # 2 terms with successful advancement each.
        for _term in range(2):
            queue.extend([
                [4, 3],  # survival
                [5, 3],  # advancement -> rank up
                [5, 3],  # skill 1
                [5, 3],  # skill 2 (advancement -> extra)
            ])
        # Mustering out: 2 terms, rank 2.
        # Navy cash: dm_per_term=1, dm_per_rank=1. DM = 2 + 2 = 4.
        # min(2, 3) = 2 rolls.
        queue.extend([
            [1],  # 1 + 4 = 5 -> "40,000 Cr"
            [2],  # 2 + 4 = 6 -> "50,000 Cr"
        ])
        # Material: 2 rolls, DM = 0.
        queue.extend([
            [1],  # Weapon
            [6],  # TAS Membership
        ])
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=2)

        mo = result.mustering_out
        assert mo is not None
        assert mo.terms_served == 2
        assert mo.final_rank == 2
        assert len(mo.cash_benefits) == 2
        assert "40,000 Cr" in mo.cash_benefits
        assert "50,000 Cr" in mo.cash_benefits
        assert len(mo.material_benefits) == 2

    def test_zero_terms_mustering_out(self, pack):
        """Character with 0 terms gets no benefits."""
        queue = [
            [5, 3], [4, 3], [5, 3], [2, 1], [2, 1], [4, 2],  # chars
            # Qualification: INT 3, DM -1, target 5 -> fail
            [1, 1],  # 2 + (-1) = 1 < 5 -> fail
            # Drifter qual: END 8, DM 0, target 3
            [1, 1],  # 2 < 3 -> fail (even drifter fails!)
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=3)

        assert result.num_terms == 0
        assert result.mustering_out is not None
        assert result.mustering_out.cash_benefits == []
        assert result.mustering_out.material_benefits == []


# ---------------------------------------------------------------------------
# Scenario: Career with no ranks (Scout/Drifter).
# ---------------------------------------------------------------------------


class TestNoRanksCareer:
    def test_scout_advancement_no_rank_increase(self, pack):
        """Scout has empty ranks — advancement succeeds but rank stays 0."""
        queue = [
            [5, 3], [4, 3], [5, 3], [5, 4], [4, 3], [4, 2],  # chars
            # Scout qualification: INT 9, DM +1, target 6
            [4, 3],  # 7 + 1 = 8 >= 6 -> success
            # Term 1
            [4, 3],  # Survival: END 8 + 0 = 7 >= 5 -> success
            [5, 4],  # Advancement: INT 9 + 1 = 10 >= 7 -> success, but no rank
            [5, 3],  # Skill 1
            [4, 3],  # Skill 2 (advancement -> extra)
            # Mustering out (1 term, rank 0)
            [1],  # cash
            [1],  # material
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("scout", num_terms=1)

        term1 = result.terms[0]
        assert term1.advancement_success
        assert term1.rank_after == 0  # no ranks -> stays 0
        assert engine.state.character.rank == 0


# ---------------------------------------------------------------------------
# Scenario: Determinism — same seed + same queue = same result.
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_queue_produces_identical_state(self, pack):
        """Two runners with the same ForcedRoller queue produce identical state."""
        queue = [
            [5, 3], [4, 3], [5, 3], [5, 4], [4, 3], [4, 2],
            [4, 3],
            [4, 3], [5, 3], [5, 3], [4, 3],
            [3], [2],
        ]
        engine_a = make_engine(list(queue))
        engine_b = make_engine(list(queue))
        runner_a = LifepathRunner(engine_a, pack)
        runner_b = LifepathRunner(engine_b, pack)

        result_a = runner_a.run_lifepath("navy", num_terms=1)
        result_b = runner_b.run_lifepath("navy", num_terms=1)

        assert (
            engine_a.state.model_dump_json()
            == engine_b.state.model_dump_json()
        )


# ---------------------------------------------------------------------------
# AdvanceTermCommand — funnel-routed age/terms advancement (Fix #2C).
# ---------------------------------------------------------------------------


class TestAdvanceTermCommand:
    """Age and terms advance through the command funnel (Fix #2C)."""

    def test_advance_term_bumps_age_and_terms(self):
        """AdvanceTermCommand increments age by 4 and terms by 1."""
        state = GameState.new(seed=99)
        state.character.age = 22
        state.character.terms = 1
        engine = Engine(state, roller=ForcedRoller([]))

        event = engine.apply(AdvanceTermCommand())

        assert state.character.age == 26
        assert state.character.terms == 2
        assert event.command_type == "lifepath_advance_term"
        assert event.changes["age_before"] == 22
        assert event.changes["age_after"] == 26
        assert event.changes["terms_before"] == 1
        assert event.changes["terms_after"] == 2

    def test_advance_term_produces_audit_event(self):
        """The term advancement is recorded in the event log."""
        state = GameState.new(seed=99)
        state.character.age = 18
        state.character.terms = 0
        engine = Engine(state, roller=ForcedRoller([]))
        initial_events = len(state.events)

        engine.apply(AdvanceTermCommand())

        assert len(state.events) == initial_events + 1
        event = state.events[-1]
        assert event.kind == EventKind.STATE_CHANGE
        assert "age 18 -> 22" in event.description
        assert "terms 0 -> 1" in event.description

    def test_run_term_uses_funnel_for_advancement(self, pack):
        """run_term routes age/terms advancement through the funnel."""
        # Set up a character that has already qualified for navy.
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(death_mode="narrative")
        state.character.characteristics = {
            "STR": 7, "DEX": 9, "END": 8,
            "INT": 8, "EDU": 10, "SOC": 5,
        }
        state.character.career = "navy"
        # Queue: survival roll (low roll -> mishap, returns early after advance).
        queue = [[1, 1]]  # END 8 -> DM 1, roll 2+1=3 < 5 -> mishap
        engine = Engine(state, roller=ForcedRoller(queue))
        runner = LifepathRunner(engine, pack)

        initial_events = len(engine.state.events)
        runner.run_term("navy", term_number=1)

        # The advance_term event should be in the log.
        advance_events = [
            e for e in engine.state.events[initial_events:]
            if e.command_type == "lifepath_advance_term"
        ]
        assert len(advance_events) == 1
        assert engine.state.character.age == 22  # 18 + 4
        assert engine.state.character.terms == 1
