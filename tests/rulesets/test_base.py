"""Tests for RuleSet/ThemePack protocols, data models, and CE SRD rule-set (R5, R6).

Covers protocol conformance, difficulty ladder correctness, resolution mechanics,
characteristic DMs, death modes, and data model validation.
"""

from __future__ import annotations

import pytest

from src.rulesets.base import (
    OutcomeQuality,
    RuleSet,
    SkillTableEntry,
    TableRange,
    ThemePack,
)
from src.rulesets.cepheus import CepheusRuleSet

# ---------------------------------------------------------------------------
# Scenario 1: Protocol conformance — CE SRD rule-set satisfies RuleSet protocol.
# ---------------------------------------------------------------------------


def test_cepheus_ruleset_satisfies_ruleset_protocol():
    """CepheusRuleSet satisfies the RuleSet Protocol by structural subtyping."""
    rs = CepheusRuleSet()
    assert isinstance(rs, RuleSet)


def test_cepheus_ruleset_id():
    rs = CepheusRuleSet()
    assert rs.id == "cepheus"


def test_cepheus_ruleset_name_mentions_cepheus():
    rs = CepheusRuleSet()
    assert "Cepheus" in rs.name


# ---------------------------------------------------------------------------
# Scenario 6: Difficulty ladder — Routine +2 through Formidable -6 (CE SRD).
# ---------------------------------------------------------------------------


def test_difficulty_ladder_modifiers_match_ce_srd():
    """All six difficulty modifiers match the CE SRD specification."""
    rs = CepheusRuleSet()
    assert rs.difficulty_modifier("easy") == 4
    assert rs.difficulty_modifier("routine") == 2
    assert rs.difficulty_modifier("average") == 0
    assert rs.difficulty_modifier("difficult") == -2
    assert rs.difficulty_modifier("very_difficult") == -4
    assert rs.difficulty_modifier("formidable") == -6


def test_difficulty_ladder_has_exactly_six_entries():
    rs = CepheusRuleSet()
    expected = {"routine", "easy", "average", "difficult", "very_difficult", "formidable"}
    assert set(rs.difficulty_ladder.keys()) == expected


def test_difficulty_ladder_values():
    rs = CepheusRuleSet()
    assert rs.difficulty_ladder == {
        "easy": 4,
        "routine": 2,
        "average": 0,
        "difficult": -2,
        "very_difficult": -4,
        "formidable": -6,
    }


def test_unknown_difficulty_raises():
    rs = CepheusRuleSet()
    with pytest.raises(KeyError, match="nonexistent"):
        rs.difficulty_modifier("nonexistent")


# ---------------------------------------------------------------------------
# Resolution mechanic — 2D6 + DM >= 8, Effect = total - target.
# ---------------------------------------------------------------------------


def test_resolution_target_is_8():
    rs = CepheusRuleSet()
    assert rs.resolution_target == 8


def test_resolve_check_success_above_target():
    rs = CepheusRuleSet()
    # Total 10 vs average difficulty (DM=0), target=8 → success, effect=2
    outcome = rs.resolve_check(10, "average")
    assert outcome.success is True
    assert outcome.effect == 2


def test_resolve_check_success_exactly_at_target():
    rs = CepheusRuleSet()
    # Total 8 vs average → success, effect=0
    outcome = rs.resolve_check(8, "average")
    assert outcome.success is True
    assert outcome.effect == 0


def test_resolve_check_failure_below_target():
    rs = CepheusRuleSet()
    # Total 7 vs average → fail, effect=-1
    outcome = rs.resolve_check(7, "average")
    assert outcome.success is False
    assert outcome.effect == -1


def test_resolve_check_with_difficulty_modifier():
    rs = CepheusRuleSet()
    # Total 10, formidable (-6) → effective 4, miss
    outcome = rs.resolve_check(10, "formidable")
    assert outcome.success is False
    assert outcome.effect == -4


def test_resolve_check_routine_bonus():
    rs = CepheusRuleSet()
    # Total 6, routine (+2) → effective 8, success at target
    outcome = rs.resolve_check(6, "routine")
    assert outcome.success is True
    assert outcome.effect == 0


def test_narrative_profile_strong_hit():
    """Narrative profile: high effect → strong hit quality."""
    rs = CepheusRuleSet()
    # Total 12, average → effect=4, strong hit in narrative
    outcome = rs.resolve_check(12, "average", profile="narrative")
    assert outcome.success is True
    assert outcome.quality == OutcomeQuality.STRONG_HIT


def test_narrative_profile_weak_hit():
    """Narrative profile: marginal success → weak hit (triggers complications)."""
    rs = CepheusRuleSet()
    # Total 9, average → effect=1, weak hit in narrative
    outcome = rs.resolve_check(9, "average", profile="narrative")
    assert outcome.success is True
    assert outcome.quality == OutcomeQuality.WEAK_HIT


def test_narrative_profile_miss():
    """Narrative profile: failure → miss quality."""
    rs = CepheusRuleSet()
    outcome = rs.resolve_check(5, "average", profile="narrative")
    assert outcome.success is False
    assert outcome.quality == OutcomeQuality.MISS


def test_classic_profile_only_success_or_miss():
    """Classic profile: success is strong_hit, failure is miss (no weak hits)."""
    rs = CepheusRuleSet()
    # Success
    outcome = rs.resolve_check(9, "average", profile="classic")
    assert outcome.success is True
    assert outcome.quality == OutcomeQuality.STRONG_HIT
    # Failure
    outcome = rs.resolve_check(7, "average", profile="classic")
    assert outcome.success is False
    assert outcome.quality == OutcomeQuality.MISS


def test_default_profile_is_classic():
    """Without specifying a profile, classic resolution applies."""
    rs = CepheusRuleSet()
    outcome = rs.resolve_check(9, "average")
    assert outcome.quality == OutcomeQuality.STRONG_HIT


# ---------------------------------------------------------------------------
# Characteristic DMs.
# ---------------------------------------------------------------------------


def test_characteristic_dm_ladder():
    rs = CepheusRuleSet()
    assert rs.characteristic_dm(0) == -2
    assert rs.characteristic_dm(1) == -2
    assert rs.characteristic_dm(2) == -2
    assert rs.characteristic_dm(3) == -1
    assert rs.characteristic_dm(5) == -1
    assert rs.characteristic_dm(6) == 0
    assert rs.characteristic_dm(8) == 0
    assert rs.characteristic_dm(9) == 1
    assert rs.characteristic_dm(11) == 1
    assert rs.characteristic_dm(12) == 2
    assert rs.characteristic_dm(14) == 2
    assert rs.characteristic_dm(15) == 3
    assert rs.characteristic_dm(17) == 3
    assert rs.characteristic_dm(18) == 4
    assert rs.characteristic_dm(20) == 4
    assert rs.characteristic_dm(21) == 5
    assert rs.characteristic_dm(23) == 5
    assert rs.characteristic_dm(24) == 6
    assert rs.characteristic_dm(26) == 6


# ---------------------------------------------------------------------------
# Six characteristics.
# ---------------------------------------------------------------------------


def test_characteristics_are_the_ce_srd_six():
    rs = CepheusRuleSet()
    assert rs.characteristics == ("STR", "DEX", "END", "INT", "EDU", "SOC")


# ---------------------------------------------------------------------------
# Death modes and resolution profiles.
# ---------------------------------------------------------------------------


def test_death_modes_include_narrative_and_ironman():
    rs = CepheusRuleSet()
    assert "narrative" in rs.death_modes
    assert "ironman" in rs.death_modes


def test_resolution_profiles_include_classic_and_narrative():
    rs = CepheusRuleSet()
    assert "classic" in rs.resolution_profiles
    assert "narrative" in rs.resolution_profiles


# ---------------------------------------------------------------------------
# Data model validation.
# ---------------------------------------------------------------------------


def test_skill_table_entry_valid():
    entry = SkillTableEntry(min=2, max=5, result="Pilot")
    assert entry.min == 2
    assert entry.max == 5
    assert entry.result == "Pilot"


def test_skill_table_entry_rejects_min_greater_than_max():
    with pytest.raises(ValueError, match=r"min.*max"):
        SkillTableEntry(min=6, max=3, result="Pilot")


def test_table_range_contiguous_validation():
    """TableRange validates that entries form a contiguous 2-12 range."""
    entries = [
        SkillTableEntry(min=2, max=4, result="A"),
        SkillTableEntry(min=5, max=7, result="B"),
        SkillTableEntry(min=8, max=12, result="C"),
    ]
    tr = TableRange(entries=entries, die_size=6, num_dice=2)
    assert tr.is_contiguous()


def test_table_range_detects_gap():
    """TableRange flags non-contiguous ranges (e.g., missing 5)."""
    entries = [
        SkillTableEntry(min=2, max=4, result="A"),
        SkillTableEntry(min=6, max=12, result="B"),
    ]
    tr = TableRange(entries=entries, die_size=6, num_dice=2)
    assert not tr.is_contiguous()


def test_table_range_detects_overlap():
    entries = [
        SkillTableEntry(min=2, max=5, result="A"),
        SkillTableEntry(min=4, max=12, result="B"),
    ]
    tr = TableRange(entries=entries, die_size=6, num_dice=2)
    assert not tr.is_contiguous()


# ---------------------------------------------------------------------------
# ThemePack protocol — can a loaded pack satisfy the protocol by shape?
# ---------------------------------------------------------------------------


class _DummyPack:
    """Minimal object satisfying ThemePack Protocol by shape (structural typing)."""

    id = "dummy"
    name = "Dummy Pack"
    description = "For testing"

    @property
    def careers(self):
        return {}

    @property
    def skills(self):
        return {}

    @property
    def oracle_tables(self):
        return {}

    @property
    def complication_tables(self):
        return {}

    @property
    def mission_tables(self):
        return {}


def test_dummy_pack_satisfies_themepack_protocol():
    dp = _DummyPack()
    assert isinstance(dp, ThemePack)
