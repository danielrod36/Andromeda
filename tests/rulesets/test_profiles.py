"""Tests for resolution profiles: ClassicProfile and NarrativeProfile (U6: R7, AE6).

Verifies:
- PbtA-compatible band probabilities at DM 0 (~17% / ~42% / ~42%)
- Difficulty DM effects with clamping
- AE6 cross-profile comparison (same roll, different resolution)
- DM clamping prevents band collapse at extremes
- Complication/consequence table lookup pattern (caller responsibility)
- Integration with CepheusRuleSet.resolve_check delegation
"""

from __future__ import annotations

from src.rulesets.base import (
    CheckOutcome,
    ComplicationTable,
    OutcomeQuality,
    SkillTableEntry,
    TableRange,
)
from src.rulesets.cepheus import CepheusRuleSet
from src.rulesets.profiles import (
    ClassicProfile,
    NarrativeProfile,
    ResolutionProfile,
    clamp_dm,
)

# ---------------------------------------------------------------------------
# Scenario 1: Band probabilities — PbtA-compatible distribution at DM +0.
# ---------------------------------------------------------------------------


def test_narrative_band_probabilities_at_dm_zero():
    """At DM +0, enumerate all 36 2D6 outcomes and verify tier distribution.

    PbtA-compatible distribution:
      Strong hit (10+):  6/36 = 16.7%  (rolls 10,11,12 -> 3+2+1)
      Weak hit   (7-9): 15/36 = 41.7%  (rolls 7,8,9  -> 6+5+4)
      Miss       (<=6): 15/36 = 41.7%  (rolls 2-6    -> 1+2+3+4+5)
    """
    profile = NarrativeProfile()
    counts = {
        OutcomeQuality.STRONG_HIT: 0,
        OutcomeQuality.WEAK_HIT: 0,
        OutcomeQuality.MISS: 0,
    }
    for d1 in range(1, 7):
        for d2 in range(1, 7):
            outcome = profile.resolve(d1 + d2, dm=0)
            counts[outcome.quality] += 1

    total = sum(counts.values())
    assert total == 36

    # Exact outcome counts.
    assert counts[OutcomeQuality.STRONG_HIT] == 6
    assert counts[OutcomeQuality.WEAK_HIT] == 15
    assert counts[OutcomeQuality.MISS] == 15

    # Approximate percentages (spec: ~17%, ~42%, ~42%).
    assert abs(counts[OutcomeQuality.STRONG_HIT] / 36 - 0.167) < 0.01
    assert abs(counts[OutcomeQuality.WEAK_HIT] / 36 - 0.417) < 0.01
    assert abs(counts[OutcomeQuality.MISS] / 36 - 0.417) < 0.01


# ---------------------------------------------------------------------------
# Scenario 2: Difficulty DM effects — shifting and clamping.
# ---------------------------------------------------------------------------


def test_routine_dm_shifts_bands_up():
    """Routine +2 DM shifts all bands up by 2."""
    profile = NarrativeProfile()
    # Roll 8 + DM 2 = 10 -> strong hit (would be weak hit at DM 0)
    assert profile.resolve(8, dm=2).quality == OutcomeQuality.STRONG_HIT
    # Roll 5 + DM 2 = 7 -> weak hit (would be miss at DM 0)
    assert profile.resolve(5, dm=2).quality == OutcomeQuality.WEAK_HIT
    # Roll 4 + DM 2 = 6 -> miss
    assert profile.resolve(4, dm=2).quality == OutcomeQuality.MISS


def test_formidable_dm_clamped_partial_band_exists():
    """Formidable -6 is clamped to -3 so the weak-hit band still exists.

    Without clamping: roll 12 + (-6) = 6 -> miss (partial band collapsed).
    With clamping:    roll 12 + (-3) = 9 -> weak hit (partial band preserved).
    """
    profile = NarrativeProfile()
    outcome = profile.resolve(12, dm=-6)
    assert outcome.quality == OutcomeQuality.WEAK_HIT
    assert outcome.success is True


# ---------------------------------------------------------------------------
# Scenario 3: AE6 — cross-profile comparison with same roll.
# ---------------------------------------------------------------------------


def test_ae6_cross_profile_roll_10():
    """Roll 10 at DM 0: Classic -> success/STRONG_HIT; Narrative -> strong hit."""
    classic = ClassicProfile()
    narrative = NarrativeProfile()

    c = classic.resolve(10, dm=0)
    n = narrative.resolve(10, dm=0)

    # Classic: binary pass with effect margin.
    assert c.success is True
    assert c.quality == OutcomeQuality.STRONG_HIT
    assert c.effect == 2

    # Narrative: strong hit (adjusted 10+).
    assert n.quality == OutcomeQuality.STRONG_HIT
    assert n.success is True


def test_ae6_cross_profile_roll_9():
    """Roll 9 at DM 0: Classic -> success/STRONG_HIT; Narrative -> weak hit.

    This is the key AE6 scenario: the same action succeeds cleanly under
    Classic rules but succeeds-with-complication under Narrative rules.
    """
    classic = ClassicProfile()
    narrative = NarrativeProfile()

    c = classic.resolve(9, dm=0)
    n = narrative.resolve(9, dm=0)

    # Classic: binary pass, no weak-hit tier.
    assert c.success is True
    assert c.quality == OutcomeQuality.STRONG_HIT

    # Narrative: weak hit (7-9), success with complication.
    assert n.quality == OutcomeQuality.WEAK_HIT
    assert n.success is True


def test_ae6_cross_profile_roll_5():
    """Roll 5 at DM 0: Classic -> failure/MISS; Narrative -> miss."""
    classic = ClassicProfile()
    narrative = NarrativeProfile()

    c = classic.resolve(5, dm=0)
    n = narrative.resolve(5, dm=0)

    assert c.success is False
    assert c.quality == OutcomeQuality.MISS

    assert n.success is False
    assert n.quality == OutcomeQuality.MISS


def test_ae6_classic_never_produces_weak_hit():
    """Classic profile only produces STRONG_HIT or MISS, never WEAK_HIT."""
    classic = ClassicProfile()
    for roll_total in range(2, 13):
        for dm in range(-6, 3):
            outcome = classic.resolve(roll_total, dm=dm)
            assert outcome.quality in (
                OutcomeQuality.STRONG_HIT,
                OutcomeQuality.MISS,
            ), f"roll={roll_total} dm={dm} produced {outcome.quality}"


# ---------------------------------------------------------------------------
# Scenario 4 & 5: Complication/consequence table lookup pattern.
# ---------------------------------------------------------------------------


def _make_complication_table() -> ComplicationTable:
    """Build a minimal complication table for testing the lookup pattern."""
    return ComplicationTable(
        id="test_complications",
        name="Test Complications",
        description="For unit testing",
        entries=TableRange(
            entries=[
                SkillTableEntry(min=2, max=4, result="Minor setback"),
                SkillTableEntry(min=5, max=8, result="Complication arises"),
                SkillTableEntry(min=9, max=12, result="Major consequence"),
            ],
        ),
    )


def test_weak_hit_signals_complication_lookup():
    """Weak hit quality signals the caller to roll on the complication table.

    The profile determines the tier; the caller (engine) looks up the
    complication from the active theme pack's complication table.
    """
    profile = NarrativeProfile()
    table = _make_complication_table()

    outcome = profile.resolve(9, dm=0)  # adjusted 9 -> weak hit
    assert outcome.quality == OutcomeQuality.WEAK_HIT

    # Caller pattern: on WEAK_HIT, roll on complication table.
    # (Simulated here with a fixed roll of 7.)
    complication_roll = 7
    entry = next(e for e in table.entries.entries if e.min <= complication_roll <= e.max)
    assert entry.result == "Complication arises"


def test_miss_signals_consequence_lookup():
    """Miss quality signals the caller to roll on the consequence table."""
    profile = NarrativeProfile()
    table = _make_complication_table()

    outcome = profile.resolve(5, dm=0)  # adjusted 5 -> miss
    assert outcome.quality == OutcomeQuality.MISS
    assert outcome.success is False

    # Caller pattern: on MISS, roll on consequence table.
    consequence_roll = 3
    entry = next(e for e in table.entries.entries if e.min <= consequence_roll <= e.max)
    assert entry.result == "Minor setback"


def test_strong_hit_needs_no_table_lookup():
    """Strong hit quality means no complication/consequence lookup needed."""
    profile = NarrativeProfile()
    outcome = profile.resolve(12, dm=0)  # adjusted 12 -> strong hit
    assert outcome.quality == OutcomeQuality.STRONG_HIT
    assert outcome.success is True


# ---------------------------------------------------------------------------
# Scenario 6: DM clamping — prevents band collapse at DM extremes.
# ---------------------------------------------------------------------------


def test_dm_clamping_high_dm():
    """DM +10 and DM +3 produce the same tier for every possible 2D6 roll."""
    profile = NarrativeProfile()
    for roll_total in range(2, 13):
        outcome_10 = profile.resolve(roll_total, dm=10)
        outcome_3 = profile.resolve(roll_total, dm=3)
        assert outcome_10.quality == outcome_3.quality, (
            f"Roll {roll_total}: DM+10 gave {outcome_10.quality.value}, "
            f"DM+3 gave {outcome_3.quality.value}"
        )


def test_dm_clamping_low_dm():
    """DM -10 and DM -3 produce the same tier for every possible 2D6 roll."""
    profile = NarrativeProfile()
    for roll_total in range(2, 13):
        outcome_neg10 = profile.resolve(roll_total, dm=-10)
        outcome_neg3 = profile.resolve(roll_total, dm=-3)
        assert outcome_neg10.quality == outcome_neg3.quality, (
            f"Roll {roll_total}: DM-10 gave {outcome_neg10.quality.value}, "
            f"DM-3 gave {outcome_neg3.quality.value}"
        )


def test_clamp_dm_function():
    """clamp_dm clamps to the [-3, +3] range."""
    assert clamp_dm(0) == 0
    assert clamp_dm(3) == 3
    assert clamp_dm(-3) == -3
    assert clamp_dm(10) == 3
    assert clamp_dm(-10) == -3
    assert clamp_dm(1) == 1
    assert clamp_dm(-1) == -1
    assert clamp_dm(2) == 2
    assert clamp_dm(-2) == -2


def test_clamping_prevents_total_band_collapse():
    """With clamping, Formidable (-6) does not collapse all rolls to one tier.

    Without clamping at DM -6: every roll 2-12 gives adjusted -4..6, all misses.
    With clamping to -3: rolls 10-12 give adjusted 7-9, preserving weak-hit band.
    """
    profile = NarrativeProfile()

    tiers: set[OutcomeQuality] = set()
    for roll_total in range(2, 13):
        outcome = profile.resolve(roll_total, dm=-6)
        tiers.add(outcome.quality)

    assert OutcomeQuality.MISS in tiers
    assert OutcomeQuality.WEAK_HIT in tiers
    assert len(tiers) >= 2


# ---------------------------------------------------------------------------
# Protocol conformance and interface.
# ---------------------------------------------------------------------------


def test_classic_profile_satisfies_protocol():
    assert isinstance(ClassicProfile(), ResolutionProfile)


def test_narrative_profile_satisfies_protocol():
    assert isinstance(NarrativeProfile(), ResolutionProfile)


def test_classic_profile_name():
    assert ClassicProfile().name == "classic"


def test_narrative_profile_name():
    assert NarrativeProfile().name == "narrative"


def test_resolve_returns_check_outcome():
    profile = NarrativeProfile()
    outcome = profile.resolve(7, dm=0)
    assert isinstance(outcome, CheckOutcome)


# ---------------------------------------------------------------------------
# Classic profile specifics.
# ---------------------------------------------------------------------------


def test_classic_success_effect_margin():
    """Classic profile computes effect = (roll + dm) - 8."""
    classic = ClassicProfile()
    assert classic.resolve(10, dm=0).effect == 2
    assert classic.resolve(8, dm=0).effect == 0
    assert classic.resolve(7, dm=0).effect == -1


def test_classic_no_clamping():
    """Classic profile does NOT clamp DM — the full DM range is used."""
    classic = ClassicProfile()
    # DM -6, roll 12 -> adjusted 6, effect -2 (not clamped to -3)
    outcome = classic.resolve(12, dm=-6)
    assert outcome.effect == -2  # 12 + (-6) - 8 = -2
    assert outcome.success is False


def test_classic_boundary_exact_target():
    """Classic profile: adjusted exactly 8 is a success (effect 0)."""
    classic = ClassicProfile()
    outcome = classic.resolve(8, dm=0)
    assert outcome.success is True
    assert outcome.effect == 0
    assert outcome.quality == OutcomeQuality.STRONG_HIT


# ---------------------------------------------------------------------------
# Narrative profile tier boundaries.
# ---------------------------------------------------------------------------


def test_narrative_strong_hit_boundary():
    """Adjusted 10 is the lowest strong hit; 9 is the highest weak hit."""
    profile = NarrativeProfile()
    assert profile.resolve(10, dm=0).quality == OutcomeQuality.STRONG_HIT
    assert profile.resolve(9, dm=0).quality == OutcomeQuality.WEAK_HIT


def test_narrative_weak_hit_boundary():
    """Adjusted 7 is the lowest weak hit; 6 is the highest miss."""
    profile = NarrativeProfile()
    assert profile.resolve(7, dm=0).quality == OutcomeQuality.WEAK_HIT
    assert profile.resolve(6, dm=0).quality == OutcomeQuality.MISS


def test_narrative_success_flags():
    """Strong hit and weak hit are successes; miss is failure."""
    profile = NarrativeProfile()
    assert profile.resolve(11, dm=0).success is True  # strong
    assert profile.resolve(8, dm=0).success is True  # weak
    assert profile.resolve(4, dm=0).success is False  # miss


# ---------------------------------------------------------------------------
# Integration: CepheusRuleSet delegates to profiles.
# ---------------------------------------------------------------------------


def test_ruleset_classic_default():
    """CepheusRuleSet.resolve_check uses classic profile by default."""
    rs = CepheusRuleSet()
    outcome = rs.resolve_check(9, "average")
    assert outcome.quality == OutcomeQuality.STRONG_HIT  # binary, not weak hit


def test_ruleset_narrative_weak_hit():
    """CepheusRuleSet with narrative profile produces three-tier resolution."""
    rs = CepheusRuleSet()
    outcome = rs.resolve_check(9, "average", profile="narrative")
    assert outcome.quality == OutcomeQuality.WEAK_HIT


def test_ruleset_formidable_narrative_clamped():
    """Formidable (-6 DM) is clamped to -3 in narrative profile via resolve_check."""
    rs = CepheusRuleSet()
    # roll 12, formidable (-6 clamped to -3) -> adjusted 9 -> weak hit
    outcome = rs.resolve_check(12, "formidable", profile="narrative")
    assert outcome.quality == OutcomeQuality.WEAK_HIT


def test_ruleset_classic_unclamped_effect():
    """Classic profile via resolve_check does not clamp DM."""
    rs = CepheusRuleSet()
    # roll 10, formidable (-6) -> adjusted 4, effect -4 (unclamped)
    outcome = rs.resolve_check(10, "formidable")
    assert outcome.effect == -4
    assert outcome.success is False
