"""Tests for pre-commit check-odds computation (R7, AE6, mechanics-inspectable).

The odds helper mirrors SceneCheckCommand.mutate's DM arithmetic
(char_dm + skill_level + difficulty_dm = total_dm) and integrates the active
profile's tier logic over the 36-entry 2D6 distribution WITHOUT rolling. It is
a pure read-only function usable from any shell (terminal or web).
"""

from __future__ import annotations

import math

from src.engine.odds import band_label, compute_check_odds, format_odds_line
from src.engine.state import Character

# 2D6 way-counts: 2:1 3:2 4:3 5:4 6:5 7:6 8:5 9:4 10:3 11:2 12:1 (total 36)


def _approx(p: float, over36: int) -> bool:
    return math.isclose(p, over36 / 36, rel_tol=1e-9)


def _char(skills: dict[str, int] | None = None, **characteristics) -> Character:
    return Character(characteristics=dict(characteristics), skills=dict(skills or {}))


def test_classic_untrained_average_stat7():
    """Classic, STR 7, untrained mechanic, average: total_dm -3 → P(>=11) = 3/36."""
    odds = compute_check_odds(
        _char(STR=7),
        skill="mechanic",
        characteristic="STR",
        difficulty="average",
        profile="classic",
    )
    assert odds.total_dm == -3
    assert odds.trained is False
    assert _approx(odds.success_probability, 3)


def test_classic_trained_level0_average_is_15_over_36():
    """Classic, trained skill level 0, average, stat 7 → DM 0 → P(>=8)=15/36."""
    odds = compute_check_odds(
        _char({"mechanic": 0}, STR=7),
        skill="mechanic",
        characteristic="STR",
        difficulty="average",
        profile="classic",
    )
    assert odds.total_dm == 0
    assert odds.trained is True
    assert _approx(odds.success_probability, 15)


def test_narrative_dm_zero_matches_plan_tiers():
    """Narrative, effective DM 0: 10+ / 7-9 / <=6 → 6/15/15 over 36.

    The plan cites ~17% / ~42% / ~42% for DM 0; 6/36, 15/36, 15/36 match.
    """
    odds = compute_check_odds(
        _char({"science": 0}, INT=7),
        skill="science",
        characteristic="INT",
        difficulty="average",
        profile="narrative",
    )
    assert odds.total_dm == 0
    assert _approx(odds.strong_hit_probability, 6)
    assert _approx(odds.weak_hit_probability, 15)
    assert _approx(odds.miss_probability, 15)


def test_narrative_dm_clamps_to_plus3():
    """A huge total_dm is clamped to +3 for tier resolution (NarrativeProfile)."""
    odds = compute_check_odds(
        _char({"science": 3}, EDU=15),  # char +3, skill +3, easy +4 → 10, clamp 3
        skill="science",
        characteristic="EDU",
        difficulty="easy",
        profile="narrative",
    )
    assert odds.total_dm > 3  # reported honestly
    # effective +3: strong = P(2D6 >= 7) = 21/36; miss = P(<=3) = 3/36.
    assert _approx(odds.strong_hit_probability, 21)
    assert _approx(odds.miss_probability, 3)


def test_breakdown_components_sum_to_total_dm():
    odds = compute_check_odds(
        _char({"gun_combat_slug_rifle": 2}, DEX=12),  # char +2, skill +2
        skill="gun_combat_slug_rifle",
        characteristic="DEX",
        difficulty="difficult",  # diff -2
        profile="classic",
    )
    assert (odds.char_dm, odds.skill_level, odds.difficulty_dm) == (2, 2, -2)
    assert odds.total_dm == 2


def test_band_label_buckets_probability():
    assert band_label(0.95) == "Straightforward"
    assert band_label(0.75) == "Favorable"
    assert band_label(0.42) == "Chancy"
    assert band_label(0.10) == "High-risk"
    assert band_label(0.03) == "Almost impossible"


def test_format_odds_line_classic_shows_total_dm_target_pct_and_band():
    odds = compute_check_odds(
        _char({"mechanic": 0}, STR=7),
        skill="mechanic",
        characteristic="STR",
        difficulty="average",
        profile="classic",
    )
    line = format_odds_line(odds)
    assert "DM +0" in line  # total_dm reported honestly with sign
    assert "8" in line  # the classic target
    assert "42%" in line  # 15/36 rounded
    assert "Chancy" in line  # band label


def test_format_odds_line_narrative_shows_three_tier_percentages():
    odds = compute_check_odds(
        _char({"science": 0}, INT=7),
        skill="science",
        characteristic="INT",
        difficulty="average",
        profile="narrative",
    )
    line = format_odds_line(odds)
    assert "17%" in line  # strong 6/36
    assert "42%" in line  # weak + miss 15/36 each
    assert "miss" in line.lower()


def test_format_odds_line_marks_untrained():
    odds = compute_check_odds(
        _char(STR=7),  # no mechanic skill → untrained -3
        skill="mechanic",
        characteristic="STR",
        difficulty="average",
        profile="classic",
    )
    assert odds.trained is False
    assert "untrained" in format_odds_line(odds).lower()
