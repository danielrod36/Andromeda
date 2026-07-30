"""Rule-set and theme-pack plugin interfaces (U2: R5, R6, R20, R21, U6: R7).

Exports the Protocol-based interfaces (RuleSet, ThemePack), the data models
for validated theme-pack content, the CE SRD rule-set implementation, and
the resolution profile strategies.

Theme packs live in ``src/themepacks/`` and satisfy the ThemePack Protocol by
shape — they don't import from this package at runtime.
"""

from src.rulesets.base import (
    BenefitsTable,
    CareerData,
    CheckOutcome,
    CheckRef,
    ComplicationTable,
    MissionTable,
    OracleTable,
    OutcomeQuality,
    RankEntry,
    RuleSet,
    SkillData,
    SkillTable,
    SkillTableEntry,
    TableRange,
    ThemePack,
)
from src.rulesets.cepheus import CepheusRuleSet
from src.rulesets.profiles import (
    ClassicProfile,
    NarrativeProfile,
    ResolutionProfile,
)

__all__ = [
    "BenefitsTable",
    "CareerData",
    "CepheusRuleSet",
    "CheckOutcome",
    "CheckRef",
    "ClassicProfile",
    "ComplicationTable",
    "MissionTable",
    "NarrativeProfile",
    "OracleTable",
    "OutcomeQuality",
    "RankEntry",
    "ResolutionProfile",
    "RuleSet",
    "SkillData",
    "SkillTable",
    "SkillTableEntry",
    "TableRange",
    "ThemePack",
]
