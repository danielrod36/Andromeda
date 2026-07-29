"""Cepheus Engine SRD rule-set implementation (R6).

The Cepheus Engine (CE) SRD is the 2D6 OGL rule-set that Cepheus Adventure is
built on. This module implements the :class:`RuleSet` Protocol with CE-specific
data: six characteristics (STR/DEX/END/INT/EDU/SOC), the six-step difficulty
ladder (Routine +2 through Formidable -6), classic resolution (2D6+DM >= 8),
and the narrative resolution profile (strong hit / weak hit / miss tiers).

The characteristic DM ladder maps raw stat values (0-24+) to dice modifiers
per the CE SRD.
"""
from __future__ import annotations

from src.rulesets.base import CheckOutcome, OutcomeQuality
from src.rulesets.profiles import (
    ClassicProfile,
    NarrativeProfile,
    ResolutionProfile,
)


class CepheusRuleSet:
    """Cepheus Engine SRD rule-set — satisfies :class:`RuleSet` Protocol.

    All data is baked into the class as it comes from the published SRD. There
    are no constructor parameters — the rule-set is a fixed set of constants
    and resolution logic.

    Difficulty ladder (DM applied to 2D6 roll):

    ==============  ===
    Easy            +4
    Routine         +2
    Average          0
    Difficult       -2
    Very Difficult  -4
    Formidable      -6
    ==============  ===

    Characteristic DM ladder:

    ========  ===
    0–2       -2
    3–5       -1
    6–8        0
    9–11      +1
    12–14     +2
    15–17     +3
    18–20     +4
    21–23     +5
    24+       +6
    ========  ===
    """

    _id = "cepheus"
    _name = "Cepheus Engine SRD"

    _characteristics: tuple[str, ...] = ("STR", "DEX", "END", "INT", "EDU", "SOC")

    _difficulty_ladder: dict[str, int] = {
        "easy": 4,
        "routine": 2,
        "average": 0,
        "difficult": -2,
        "very_difficult": -4,
        "formidable": -6,
    }

    _resolution_target = 8
    _resolution_profiles: tuple[str, ...] = ("classic", "narrative")
    _death_modes: tuple[str, ...] = ("narrative", "ironman", "checkpoint")

    #: Profile strategy instances keyed by profile name (U6 strategy pattern).
    _profile_instances: dict[str, ResolutionProfile] = {
        "classic": ClassicProfile(),
        "narrative": NarrativeProfile(),
    }

    # ------------------------------------------------------------------
    # Protocol properties.
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def characteristics(self) -> tuple[str, ...]:
        return self._characteristics

    @property
    def difficulty_ladder(self) -> dict[str, int]:
        return dict(self._difficulty_ladder)

    @property
    def resolution_target(self) -> int:
        return self._resolution_target

    @property
    def resolution_profiles(self) -> tuple[str, ...]:
        return self._resolution_profiles

    @property
    def death_modes(self) -> tuple[str, ...]:
        return self._death_modes

    # ------------------------------------------------------------------
    # Resolution logic.
    # ------------------------------------------------------------------

    def difficulty_modifier(self, difficulty: str) -> int:
        """Return the dice modifier for the named difficulty level.

        Raises ``KeyError`` for unknown difficulty names.
        """
        if difficulty not in self._difficulty_ladder:
            raise KeyError(
                f"Unknown difficulty '{difficulty}'. "
                f"Known: {sorted(self._difficulty_ladder)}"
            )
        return self._difficulty_ladder[difficulty]

    def characteristic_dm(self, value: int) -> int:
        """Return the characteristic dice modifier for a raw stat value.

        Uses the CE SRD ladder:
        0–2: -2, 3–5: -1, 6–8: 0, 9–11: +1, 12–14: +2, 15–17: +3,
        18–20: +4, 21–23: +5, 24+: +6.
        """
        if value <= 2:
            return -2
        elif value <= 5:
            return -1
        elif value <= 8:
            return 0
        elif value <= 11:
            return 1
        elif value <= 14:
            return 2
        elif value <= 17:
            return 3
        elif value <= 20:
            return 4
        elif value <= 23:
            return 5
        else:
            return 6

    def resolve_check(
        self,
        roll_total: int,
        difficulty: str,
        *,
        profile: str = "classic",
    ) -> CheckOutcome:
        """Resolve a task check: roll_total + difficulty DM vs target (8).

        ``roll_total`` is the raw 2D6 sum (before difficulty DM). The difficulty
        modifier is applied internally. Effect = adjusted_total - target.

        Resolution is delegated to the appropriate :class:`ResolutionProfile`
        strategy (U6):

        - *classic* profile: binary 2D6+DM >= 8. Success -> STRONG_HIT,
          failure -> MISS. No DM clamping.
        - *narrative* profile: PbtA-compatible three-tier. 10+ -> strong hit,
          7-9 -> weak hit (complication), <=6 -> miss (consequence).
          DM clamped to [-3, +3] for tier resolution.

        Raises ``ValueError`` for unknown profile names.
        """
        if profile not in self._profile_instances:
            raise ValueError(
                f"Unknown resolution profile '{profile}'. "
                f"Known: {sorted(self._profile_instances)}"
            )
        dm = self.difficulty_modifier(difficulty)
        return self._profile_instances[profile].resolve(roll_total, dm)
