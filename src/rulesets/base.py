"""Protocol-based plugin interfaces for rule-sets and theme packs (R5, R20).

These Protocols define the *shape* that rule-set implementations and theme-pack
loaders must satisfy. Theme packs are pure data — they don't inherit from engine
classes; they satisfy the Protocol structurally, so YAML-loaded packs work
without any import coupling to engine code.

Data models (CareerData, SkillData, etc.) are Pydantic BaseModels used at
load time for validation. The loaded pack object exposes them through the
ThemePack Protocol's properties.
"""
from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enums shared across rule-sets.
# ---------------------------------------------------------------------------


class OutcomeQuality(str, Enum):
    """Quality of a check outcome.

    In the *classic* resolution profile, success → STRONG_HIT and failure → MISS.
    In the *narrative* profile, marginal successes (effect 0–3) become WEAK_HIT,
    which triggers complication tables — the solo-RPG oracle layer.
    """

    STRONG_HIT = "strong_hit"
    WEAK_HIT = "weak_hit"
    MISS = "miss"


# ---------------------------------------------------------------------------
# Table entry helpers (shared by career skill tables, oracle tables, etc.).
# ---------------------------------------------------------------------------


class SkillTableEntry(BaseModel):
    """One row of a 2D6 die table — a result for a roll range.

    ``result`` is an opaque string: a skill name (e.g. "Pilot"), a characteristic
    increase ("+1 STR"), or a narrative prompt. The engine interprets the prefix.
    """

    min: int = Field(alias="min")
    max: int = Field(alias="max")
    result: str

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _check_range(self) -> SkillTableEntry:
        if self.min > self.max:
            raise ValueError(
                f"Table entry min ({self.min}) > max ({self.max}) "
                f"for result '{self.result}'"
            )
        return self


class TableRange(BaseModel):
    """A collection of table entries with contiguous-range validation.

    All die tables in Cepheus (skill tables, oracle tables, benefit tables) use
    2D6 (range 2–12). This model validates that entries tile the full range
    without gaps or overlaps.
    """

    entries: list[SkillTableEntry]
    die_size: int = 6
    num_dice: int = 2

    def is_contiguous(self) -> bool:
        """Return True if entries tile the full range without gaps or overlaps."""
        if not self.entries:
            return False
        expected_min = self.num_dice  # minimum roll on Ndx = N
        expected_max = self.num_dice * self.die_size
        sorted_entries = sorted(self.entries, key=lambda e: e.min)
        # First entry must start at the minimum roll.
        if sorted_entries[0].min != expected_min:
            return False
        # Last entry must end at the maximum roll.
        if sorted_entries[-1].max != expected_max:
            return False
        # Each entry's max + 1 == next entry's min (no gaps, no overlaps).
        for i in range(len(sorted_entries) - 1):
            if sorted_entries[i].max + 1 != sorted_entries[i + 1].min:
                return False
        return True


# ---------------------------------------------------------------------------
# Theme-pack data models (loaded from YAML, validated at load time).
# ---------------------------------------------------------------------------


class CheckRef(BaseModel):
    """A characteristic-based check reference (qualification, survival, etc.).

    Represents: roll 2D6 + characteristic DM >= target.
    """

    characteristic: str
    target: int


class SkillTable(BaseModel):
    """One of a career's three skill tables (Personal Dev, Service, Advanced Ed)."""

    name: str
    entries: TableRange


class BenefitsTable(BaseModel):
    """Mustering-out benefits table (cash or material), rolled on 1D6 or 2D6.

    ``dm_per_term`` and ``dm_per_rank`` add +1 per term/rank to the roll,
    matching the CE SRD mustering-out rules.
    """

    name: str
    entries: TableRange
    dm_per_term: int = 0
    dm_per_rank: int = 0


class RankEntry(BaseModel):
    """A rank/title within a career hierarchy."""

    rank: int
    title: str


class CareerData(BaseModel):
    """Full career definition loaded from a theme pack's careers.yaml.

    A career in CE SRD has three skill tables (Personal Development, Service
    Skills, Advanced Education), qualification/survival/ advancement checks,
    optional ranks, and mustering-out benefit tables.
    """

    id: str
    name: str
    description: str
    qualification: CheckRef
    survival: CheckRef
    advancement: CheckRef
    skill_tables: list[SkillTable]
    ranks: list[RankEntry] = Field(default_factory=list)
    mustering_out_cash: BenefitsTable | None = None
    mustering_out_material: BenefitsTable | None = None


class SkillData(BaseModel):
    """A skill definition with an optional career association.

    The ``career`` field is used for referential-integrity validation: every
    non-empty value must match a career id in the same pack.
    """

    id: str
    name: str
    description: str = ""
    career: str = ""


class OracleTable(BaseModel):
    """An oracle table for scene scaffolding / solo play prompts."""

    id: str
    name: str
    description: str = ""
    entries: TableRange


class ComplicationTable(BaseModel):
    """A complication table rolled on Narrative-profile weak hits."""

    id: str
    name: str
    description: str = ""
    entries: TableRange


class MissionTable(BaseModel):
    """A mission hook table for generating adventure seeds."""

    id: str
    name: str
    description: str = ""
    entries: TableRange


# ---------------------------------------------------------------------------
# Check outcome (returned by RuleSet.resolve_check).
# ---------------------------------------------------------------------------


class CheckOutcome(BaseModel):
    """Result of a task check: success/failure, effect margin, quality tier.

    ``effect`` = adjusted total − resolution target (can be negative).
    ``quality`` categorises the outcome for complication triggering.
    """

    success: bool
    effect: int
    quality: OutcomeQuality
    description: str = ""


# ---------------------------------------------------------------------------
# Protocol: RuleSet
# ---------------------------------------------------------------------------


@runtime_checkable
class RuleSet(Protocol):
    """Protocol for a rule-set implementation (R5).

    A rule-set defines the mechanical resolution system: which characteristics
    exist, the difficulty ladder and its modifiers, the target number, supported
    death modes and resolution profiles, and the check-resolution logic.

    Implementations satisfy this Protocol by shape — no inheritance required.
    """

    @property
    def id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def characteristics(self) -> tuple[str, ...]: ...
    @property
    def difficulty_ladder(self) -> dict[str, int]: ...
    @property
    def resolution_target(self) -> int: ...
    @property
    def resolution_profiles(self) -> tuple[str, ...]: ...
    @property
    def death_modes(self) -> tuple[str, ...]: ...

    def difficulty_modifier(self, difficulty: str) -> int: ...
    def characteristic_dm(self, value: int) -> int: ...
    def resolve_check(
        self,
        roll_total: int,
        difficulty: str,
        *,
        profile: str = "classic",
    ) -> CheckOutcome: ...


# ---------------------------------------------------------------------------
# Protocol: ThemePack
# ---------------------------------------------------------------------------


@runtime_checkable
class ThemePack(Protocol):
    """Protocol for a theme-pack content bundle (R20).

    A theme pack provides careers, skills, oracle tables, complication tables,
    and mission tables as validated data. Packs are discovered via the
    directory-scan registry over ``src/themepacks/data/``.

    Packs satisfy this Protocol by shape — they can be plain objects wrapping
    YAML-loaded Pydantic models, with no inheritance from engine classes.
    """

    @property
    def id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def careers(self) -> dict[str, CareerData]: ...
    @property
    def skills(self) -> dict[str, SkillData]: ...
    @property
    def oracle_tables(self) -> dict[str, OracleTable]: ...
    @property
    def complication_tables(self) -> dict[str, ComplicationTable]: ...
    @property
    def mission_tables(self) -> dict[str, MissionTable]: ...
