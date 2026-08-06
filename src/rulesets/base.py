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

    # Schema v2 additive fields (P3.T1, A6) — all default away.
    effects: list[dict[str, str | int]] | None = None
    """Mechanical effects: ``[{"type": "debt", "amount": 10000}, {"type": "lose_benefits"}]``."""

    once: bool = False
    """If True, this material benefit can only be claimed once per character."""

    on_duplicate: str | None = None
    """When a non-once material benefit repeats: ``"skill:<skill_id>"`` grants a
    skill level instead, or ``"reroll"`` rerolls once on the lifepath stream."""

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _check_range(self) -> SkillTableEntry:
        if self.min > self.max:
            raise ValueError(
                f"Table entry min ({self.min}) > max ({self.max}) for result '{self.result}'"
            )
        return self


class TableRange(BaseModel):
    """A collection of table entries with contiguous-range validation.

    Die tables declare their dice explicitly (``num_dice`` × ``die_size``);
    entries must tile the full rollable range. ``max_extension`` permits
    additional rows only reachable via positive DM (e.g. mustering-out
    benefit row 7 via rank DM, B15).
    """

    entries: list[SkillTableEntry]
    die_size: int = 6
    num_dice: int = 2
    max_extension: int = 0

    def is_contiguous(self) -> bool:
        """Return True if entries tile the full range without gaps or overlaps."""
        if not self.entries:
            return False
        expected_min = self.num_dice  # minimum roll on Ndx = N
        expected_max = self.num_dice * self.die_size + self.max_extension
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
    """One of a career's skill tables (Personal Development, Service Skills,
    Specialist, Advanced Education). Skill tables roll 1D6 (range 1–6)."""

    name: str
    entries: TableRange


class BenefitsTable(BaseModel):
    """Mustering-out benefits table (cash or material), rolled on 1D6.

    Row count and DM reach are SRD data (B15): seven rows, row 7 reachable
    only via rank DM (``max_extension >= 1`` on the entries). Extra benefit
    *rolls* come from rank (O4 +1, O5 +2, O6 +3), computed by the engine —
    never from per-term/per-rank DM fields (removed: N3).
    """

    name: str
    entries: TableRange


class RankEntry(BaseModel):
    """A rank/title within a career hierarchy (schema v2: bonus_skills)."""

    rank: int
    title: str
    bonus_skills: list[dict[str, int | str]] = Field(default_factory=list)
    """List of ``{"skill": <skill_id>, "level": <int>}`` granted at this rank (P3.T1)."""


class CareerData(BaseModel):
    """Full career definition loaded from a theme pack's careers.yaml.

    Hierarchy careers (has_hierarchy=True) have commission and advancement
    checks; non-hierarchy careers (Athlete, Barbarian, Belter, Drifter,
    Entertainer, Hunter, Scout) have neither and grant 2 skill rolls per
    term instead (B5, B8, B9).
    """

    id: str
    name: str
    description: str
    qualification: CheckRef
    survival: CheckRef
    advancement: CheckRef | None = None
    commission: CheckRef | None = None
    re_enlistment: int | None = None
    has_hierarchy: bool = True
    mishap_table: TableRange | None = None
    skill_tables: list[SkillTable]
    ranks: list[RankEntry] = Field(default_factory=list)
    mustering_out_cash: BenefitsTable | None = None
    mustering_out_material: BenefitsTable | None = None

    @model_validator(mode="after")
    def _check_hierarchy_consistency(self) -> CareerData:
        if not self.has_hierarchy and (self.advancement or self.commission):
            raise ValueError(
                f"Career '{self.id}': non-hierarchy careers must not define "
                "advancement or commission (B5)"
            )
        return self


class SkillData(BaseModel):
    """A skill definition with an optional career association.

    The ``career`` field is used for referential-integrity validation: every
    non-empty value must match a career id in the same pack. ``background``
    flags skills available during the pre-career background-skills phase (B10).
    """

    id: str
    name: str
    description: str = ""
    career: str = ""
    background: bool = False


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
