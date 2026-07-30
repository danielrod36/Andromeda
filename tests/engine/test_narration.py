"""Tests for template narration: coherent prose per term outcome (AE7).

Verifies that the Narrator produces contextual one-line prose referencing
the mechanical outcome — no LLM required.
"""

from __future__ import annotations

import pytest

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.lifepath import (
    LifepathRunner,
    MusteringOutResult,
    QualificationResult,
    SkillGain,
    TermResult,
)
from src.engine.narration import Narrator
from src.engine.state import CampaignConfig, GameState
from src.themepacks.base import get_pack


@pytest.fixture
def pack():
    return get_pack("scifi")


@pytest.fixture
def narrator():
    return Narrator()


def make_engine(queue, death_mode="narrative", seed=42):
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(death_mode=death_mode)
    return Engine(state, roller=ForcedRoller(queue))


# ---------------------------------------------------------------------------
# Qualification narration.
# ---------------------------------------------------------------------------


class TestNarrateQualification:
    def test_success_comfortable(self, narrator):
        result = QualificationResult(
            career_id="navy",
            career_name="Navy",
            characteristic="INT",
            char_value=10,
            char_dm=1,
            raw_roll=8,
            adjusted_total=9,
            target=5,
            success=True,
        )
        line = narrator.narrate_qualification(result)
        assert "Navy" in line
        assert "honors" in line  # margin >= 3

    def test_success_narrow(self, narrator):
        result = QualificationResult(
            career_id="navy",
            career_name="Navy",
            characteristic="INT",
            char_value=7,
            char_dm=0,
            raw_roll=6,
            adjusted_total=6,
            target=5,
            success=True,
        )
        line = narrator.narrate_qualification(result)
        assert "Navy" in line
        assert "pass" in line.lower()

    def test_failure(self, narrator):
        result = QualificationResult(
            career_id="navy",
            career_name="Navy",
            characteristic="INT",
            char_value=5,
            char_dm=-1,
            raw_roll=3,
            adjusted_total=2,
            target=5,
            success=False,
        )
        line = narrator.narrate_qualification(result)
        assert "rejected" in line
        assert "2 vs 5" in line


# ---------------------------------------------------------------------------
# Term narration.
# ---------------------------------------------------------------------------


class TestNarrateTerm:
    def test_normal_term_with_promotion_and_skills(self, narrator):
        result = TermResult(
            term_number=1,
            career_id="navy",
            career_name="Navy",
            age_before=18,
            age_after=22,
            survival_total=8,
            survival_target=5,
            survival_success=True,
            advancement_total=10,
            advancement_target=7,
            advancement_success=True,
            rank_after=1,
            rank_title="Ensign",
            skill_gains=[
                SkillGain("Personal Development", 8, "+1 EDU", "characteristic", "EDU"),
                SkillGain("Service Skills", 7, "pilot_small_craft", "skill", "pilot_small_craft"),
            ],
        )
        line = narrator.narrate_term(result)
        assert "Term 1" in line
        assert "Navy" in line
        assert "promoted" in line
        assert "Ensign" in line
        assert "pilot_small_craft" in line
        assert "EDU" in line

    def test_narrow_survival(self, narrator):
        result = TermResult(
            term_number=2,
            career_id="navy",
            career_name="Navy",
            age_before=22,
            age_after=26,
            survival_total=6,
            survival_target=5,
            survival_success=True,
        )
        line = narrator.narrate_term(result)
        assert "narrowly" in line.lower()

    def test_comfortable_survival(self, narrator):
        result = TermResult(
            term_number=1,
            career_id="navy",
            career_name="Navy",
            age_before=18,
            age_after=22,
            survival_total=10,
            survival_target=5,
            survival_success=True,
        )
        line = narrator.narrate_term(result)
        assert "without major incident" in line

    def test_death_terminates_line(self, narrator):
        result = TermResult(
            term_number=3,
            career_id="navy",
            career_name="Navy",
            age_before=26,
            age_after=30,
            survival_total=3,
            survival_target=5,
            survival_success=False,
            died=True,
        )
        line = narrator.narrate_term(result)
        assert "do not survive" in line
        # Death line should not contain advancement/skill info.
        assert "promoted" not in line

    def test_mishap_terminates_line(self, narrator):
        result = TermResult(
            term_number=1,
            career_id="navy",
            career_name="Navy",
            age_before=18,
            age_after=22,
            survival_total=3,
            survival_target=5,
            survival_success=False,
            mishap=True,
        )
        line = narrator.narrate_term(result)
        assert "mishap" in line.lower()

    def test_aging_effect_in_narration(self, narrator):
        result = TermResult(
            term_number=4,
            career_id="drifter",
            career_name="Drifter",
            age_before=30,
            age_after=34,
            survival_total=7,
            survival_target=5,
            survival_success=True,
            advancement_total=8,
            advancement_target=7,
            advancement_success=True,
            aging_success=False,
            aging_reductions={"STR": 1, "DEX": 1, "END": 1},
        )
        line = narrator.narrate_term(result)
        assert "years" in line.lower() or "toll" in line.lower()
        assert "STR" in line


# ---------------------------------------------------------------------------
# Mustering out narration.
# ---------------------------------------------------------------------------


class TestNarrateMusteringOut:
    def test_basic_mustering_out(self, narrator):
        result = MusteringOutResult(
            terms_served=3,
            final_rank=2,
            career_name="Navy",
            cash_benefits=["40,000 Cr", "50,000 Cr"],
            material_benefits=["Weapon", "High Passage"],
        )
        line = narrator.narrate_mustering_out(result)
        assert "3 term" in line
        assert "Navy" in line
        assert "40,000 Cr" in line
        assert "Weapon" in line


# ---------------------------------------------------------------------------
# Full lifepath narration.
# ---------------------------------------------------------------------------


class TestNarrateLifepath:
    def test_full_lifepath_produces_multiple_lines(self, pack):
        """End-to-end lifepath with narration produces coherent prose (AE7)."""
        queue = [
            [6, 3],
            [4, 3],
            [5, 3],
            [5, 4],
            [4, 3],
            [4, 2],  # chars
            [3, 2],  # qual
            [4, 3],
            [5, 3],
            [5, 3],
            [4, 3],  # term 1: surv + adv + 2 skills
            [3, 3],
            [4, 4],
            [6, 3],
            [6, 4],  # term 2: surv + adv + 2 skills
            [1],
            [1],  # cash
            [3],
            [5],  # material
        ]
        engine = make_engine(queue)
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=2)

        narrator = Narrator()
        lines = narrator.narrate_lifepath(result)

        assert len(lines) >= 4  # chars, qual, 2 terms, mustering out
        # Characteristics line.
        assert any("STR" in line for line in lines)
        # Qualification line.
        assert any("Navy" in line for line in lines)
        # Term lines.
        assert any("Term 1" in line for line in lines)
        assert any("Term 2" in line for line in lines)
        # Mustering out line.
        assert any("muster out" in line.lower() for line in lines)

    def test_death_lifepath_narration(self, pack):
        """Ironman death produces death narration."""
        queue = [
            [5, 3],
            [4, 3],
            [5, 3],
            [4, 3],
            [4, 3],
            [4, 2],
            [4, 3],  # qual success
            [1, 1],  # survival -> death
        ]
        engine = make_engine(queue, death_mode="ironman")
        runner = LifepathRunner(engine, pack)
        result = runner.run_lifepath("navy", num_terms=3)

        narrator = Narrator()
        lines = narrator.narrate_lifepath(result)

        assert any("do not survive" in line for line in lines)
        assert any("did not survive" in line for line in lines)
