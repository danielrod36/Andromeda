"""Resolution profile strategies for task checks (U6: R7, AE6).

Two resolution profiles implement a common :class:`ResolutionProfile` interface:

- :class:`ClassicProfile` — Binary 2D6+DM >= 8 with Effect margins.
  Success -> STRONG_HIT, failure -> MISS. No DM clamping.

- :class:`NarrativeProfile` — PbtA-compatible three-tier resolution.
  On the adjusted total (roll + clamped DM):
      10+ -> strong hit  (success, no complication)
      7-9 -> weak hit    (success with complication)
      <=6 -> miss        (failure with consequence)

DM clamping (Narrative only):
    The effective DM is clamped to [-3, +3] for tier resolution so the
    partial-success band (7-9) doesn't collapse at DM extremes. Strong
    characters still see complications; weak characters still see successes.
    Difficulty DMs shift the roll, not the bands.

Design decision (session-settled, user-approved):
    PbtA-compatible tier boundaries on 2D6+DM: 10+ / 7-9 / <=6. This gives
    the canonical PbtA probability distribution (~17% / ~42% / ~42%) at DM 0.

Complication/consequence tables:
    The profile determines *only* the tier (OutcomeQuality). The caller is
    responsible for looking up complications (weak hit) or consequences (miss)
    from the active theme pack's complication tables.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.rulesets.base import CheckOutcome, OutcomeQuality

# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------

#: Classic resolution target (2D6+DM >= TARGET).
RESOLUTION_TARGET: int = 8

#: Narrative-profile DM clamp range.
DM_CLAMP_MIN: int = -3
DM_CLAMP_MAX: int = 3

#: Narrative tier boundaries (on adjusted = roll_total + clamped_dm).
#: Adjusted >= this value -> strong hit.
NARRATIVE_STRONG_HIT_THRESHOLD: int = 10
#: Adjusted >= this value and < strong hit -> weak hit.
NARRATIVE_WEAK_HIT_MIN: int = 7


# ---------------------------------------------------------------------------
# DM clamping helper.
# ---------------------------------------------------------------------------


def clamp_dm(dm: int) -> int:
    """Clamp a difficulty modifier to the narrative-profile range [-3, +3].

    This prevents the partial-success band (7-9) from collapsing at DM
    extremes. Only the NarrativeProfile uses clamping; ClassicProfile passes
    the raw DM through.
    """
    if dm < DM_CLAMP_MIN:
        return DM_CLAMP_MIN
    if dm > DM_CLAMP_MAX:
        return DM_CLAMP_MAX
    return dm


# ---------------------------------------------------------------------------
# Protocol: ResolutionProfile (strategy interface).
# ---------------------------------------------------------------------------


@runtime_checkable
class ResolutionProfile(Protocol):
    """Strategy interface for task-check resolution.

    Both :class:`ClassicProfile` and :class:`NarrativeProfile` satisfy this
    Protocol by shape. The profile encapsulates all resolution logic:
    target number, tier boundaries, DM handling, and effect computation.
    """

    @property
    def name(self) -> str:
        """Profile identifier ('classic' or 'narrative')."""
        ...

    def resolve(self, roll_total: int, dm: int) -> CheckOutcome:
        """Resolve a task check and return the outcome.

        Args:
            roll_total: The raw 2D6 sum (2-12), before difficulty DM.
            dm: Total difficulty modifier (difficulty DM + characteristic DM).

        Returns:
            A :class:`CheckOutcome` with success, effect, and quality tier.
        """
        ...


# ---------------------------------------------------------------------------
# Classic profile — binary pass/fail with Effect margins.
# ---------------------------------------------------------------------------


class ClassicProfile:
    """Binary resolution: 2D6 + DM >= 8.

    Success -> STRONG_HIT, failure -> MISS. No DM clamping.
    Effect = (roll_total + dm) - RESOLUTION_TARGET.
    """

    _name = "classic"

    @property
    def name(self) -> str:
        return self._name

    def resolve(self, roll_total: int, dm: int) -> CheckOutcome:
        adjusted = roll_total + dm
        effect = adjusted - RESOLUTION_TARGET
        success = effect >= 0
        quality = OutcomeQuality.STRONG_HIT if success else OutcomeQuality.MISS
        return CheckOutcome(
            success=success,
            effect=effect,
            quality=quality,
            description=(
                f"Classic: 2D6={roll_total} + DM={dm:+d} = {adjusted} "
                f"vs {RESOLUTION_TARGET} -> "
                f"{'success' if success else 'failure'} "
                f"(effect {effect:+d}, {quality.value})"
            ),
        )


# ---------------------------------------------------------------------------
# Narrative profile — PbtA-compatible three-tier resolution.
# ---------------------------------------------------------------------------


class NarrativeProfile:
    """PbtA-compatible three-tier resolution with DM clamping.

    Tier boundaries on the adjusted total (roll + clamped DM):
        10+ -> strong hit  (success, no complication)
        7-9 -> weak hit    (success with complication)
        <=6 -> miss        (failure with consequence)

    The effective DM is clamped to [-3, +3] so the partial-success band
    doesn't collapse at DM extremes. Difficulty DMs shift the roll,
    not the bands.
    """

    _name = "narrative"

    @property
    def name(self) -> str:
        return self._name

    def resolve(self, roll_total: int, dm: int) -> CheckOutcome:
        effective_dm = clamp_dm(dm)
        adjusted = roll_total + effective_dm
        effect = adjusted - RESOLUTION_TARGET

        if adjusted >= NARRATIVE_STRONG_HIT_THRESHOLD:
            quality = OutcomeQuality.STRONG_HIT
            success = True
        elif adjusted >= NARRATIVE_WEAK_HIT_MIN:
            # 7-9: success with complication.
            quality = OutcomeQuality.WEAK_HIT
            success = True
        else:
            # <= 6: failure with consequence.
            quality = OutcomeQuality.MISS
            success = False

        # Note DM clamping in description when it occurs.
        clamp_note = f" (DM clamped {dm:+d} -> {effective_dm:+d})" if effective_dm != dm else ""

        return CheckOutcome(
            success=success,
            effect=effect,
            quality=quality,
            description=(
                f"Narrative: 2D6={roll_total} + DM={effective_dm:+d}"
                f"{clamp_note} = {adjusted} -> {quality.value}"
            ),
        )
