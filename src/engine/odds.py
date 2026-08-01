"""Pre-commit check-odds computation — the trust pitch surfaced at the decision point.

Computes the success probability and full DM breakdown for a prospective scene
check WITHOUT rolling. Mirrors :meth:`SceneCheckCommand.mutate`'s DM arithmetic
(``char_dm + skill_level + difficulty_dm = total_dm``) and integrates the active
resolution profile's tier logic over the 36-entry 2D6 distribution.

This is a pure read-only function with no mutation and no dice — it violates no
engine-authority invariant (R1). It lives in the engine package so both the
terminal shell and any future web shell share one source of truth for odds
(medium-independent). Inspired by Citizen Sleeper / Disco Elysium: show the odds
at the moment of commitment so the player trusts the engine before the roll.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.engine.skills import skill_level_for
from src.engine.state import Character
from src.rulesets.cepheus import CepheusRuleSet
from src.rulesets.profiles import RESOLUTION_TARGET, clamp_dm

# ---------------------------------------------------------------------------
# The 2D6 distribution.
# ---------------------------------------------------------------------------

#: Number of ways to roll each 2D6 sum, indexed by sum (2..12).
#: ways[2]=1, ways[7]=6, ways[12]=1; total = 36.
_2D6_WAYS: tuple[int, ...] = (0, 0, 1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1)
_2D6_TOTAL: int = 36


def _p_2d6_at_least(threshold: int) -> float:
    """P(2D6 >= threshold), clamped to [0, 1]."""
    if threshold <= 2:
        return 1.0
    if threshold > 12:
        return 0.0
    ways = sum(_2D6_WAYS[threshold:])
    return ways / _2D6_TOTAL


def _p_2d6_le(threshold: int) -> float:
    """P(2D6 <= threshold), clamped to [0, 1]."""
    if threshold >= 12:
        return 1.0
    if threshold < 2:
        return 0.0
    ways = sum(_2D6_WAYS[: threshold + 1])
    return ways / _2D6_TOTAL


# ---------------------------------------------------------------------------
# Result.
# ---------------------------------------------------------------------------


@dataclass
class CheckOdds:
    """Full pre-commit breakdown for one prospective scene check.

    The DM components and ``total_dm`` are always reported honestly (no
    clamping) so the player can verify the arithmetic. The probabilities use
    the profile's resolution rule — Classic is binary; Narrative clamps the
    effective DM to [-3, +3] before tier resolution (the partial-success band
    must not collapse at DM extremes).
    """

    char_dm: int
    skill_level: int
    difficulty_dm: int
    total_dm: int
    trained: bool
    profile: str
    success_probability: float
    strong_hit_probability: float | None = None
    weak_hit_probability: float | None = None
    miss_probability: float | None = None


def compute_check_odds(
    character: Character,
    skill: str,
    characteristic: str,
    difficulty: str,
    profile: str,
    *,
    ruleset: CepheusRuleSet | None = None,
) -> CheckOdds:
    """Compute the odds of a prospective check without rolling (R7, AE6).

    Parameters mirror the inputs :class:`SceneCheckCommand` uses at resolution
    time, so the displayed odds always match the upcoming roll's math.
    """
    rs = ruleset or CepheusRuleSet()
    char_value = character.characteristics.get(characteristic, 7)
    char_dm = rs.characteristic_dm(char_value)
    skill_level, trained = skill_level_for(character, skill)
    difficulty_dm = rs.difficulty_modifier(difficulty)
    total_dm = char_dm + skill_level + difficulty_dm

    if profile == "classic":
        # Binary: success when 2D6 + total_dm >= RESOLUTION_TARGET (8).
        success = _p_2d6_at_least(RESOLUTION_TARGET - total_dm)
        return CheckOdds(
            char_dm=char_dm,
            skill_level=skill_level,
            difficulty_dm=difficulty_dm,
            total_dm=total_dm,
            trained=trained,
            profile=profile,
            success_probability=success,
        )

    # Narrative: tiers on adjusted = 2D6 + clamp_dm(total_dm).
    effective = clamp_dm(total_dm)
    strong = _p_2d6_at_least(10 - effective)
    miss = _p_2d6_le(6 - effective)
    weak = 1.0 - strong - miss
    # success (non-miss) for the generic success_probability field.
    success = strong + weak
    return CheckOdds(
        char_dm=char_dm,
        skill_level=skill_level,
        difficulty_dm=difficulty_dm,
        total_dm=total_dm,
        trained=trained,
        profile=profile,
        success_probability=success,
        strong_hit_probability=strong,
        weak_hit_probability=weak,
        miss_probability=miss,
    )


# ---------------------------------------------------------------------------
# Band label — human-readable probability bucket (Fallen London 9-band style).
# ---------------------------------------------------------------------------


def band_label(probability: float) -> str:
    """Map a probability to a descriptive band label (Fallen London style).

    Used alongside the raw percentage so players who don't map bands to rates
    instinctively (the Citizen Sleeper 2 community objected to bands-only) still
    get the descriptive framing without losing the exact number.
    """
    if probability >= 0.91:
        return "Straightforward"
    if probability >= 0.71:
        return "Favorable"
    if probability >= 0.56:
        return "Modest"
    if probability >= 0.41:
        return "Chancy"
    if probability >= 0.21:
        return "Risky"
    if probability >= 0.06:
        return "High-risk"
    return "Almost impossible"


def _pct(p: float) -> int:
    """Round a probability to a whole-number percentage."""
    return round(p * 100)


def format_odds_line(odds: CheckOdds) -> str:
    """Format a CheckOdds as a compact, player-facing description line.

    Returned strings are plain text (no Rich markup) so any shell — terminal or
    web — can render them. Example output::

        Classic:   "DM +0 vs 8 · 42% Chancy"
        Narrative: "DM +0 · 17% strong / 42% weak / 42% miss · Chancy"

    The total DM is always shown honestly (sign-prefixed) so the player can
    verify the arithmetic against the receipt that will appear after the roll.
    """
    dm = f"DM {odds.total_dm:+d}"
    untrained = " (untrained)" if not odds.trained else ""

    if odds.profile == "classic":
        pct = _pct(odds.success_probability)
        return f"{dm} vs {RESOLUTION_TARGET} · {pct}% {band_label(odds.success_probability)}{untrained}"

    strong = _pct(odds.strong_hit_probability or 0.0)
    weak = _pct(odds.weak_hit_probability or 0.0)
    miss = _pct(odds.miss_probability or 0.0)
    return (
        f"{dm} · {strong}% strong / {weak}% weak / {miss}% miss"
        f" · {band_label(odds.success_probability)}{untrained}"
    )
