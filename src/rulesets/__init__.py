"""Rule-set and theme-pack plugin interfaces (U2: R5, R6, R20, R21).

Exports the Protocol-based interfaces (RuleSet, ThemePack), the data models
for validated theme-pack content, and the CE SRD rule-set implementation.

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
    OutcomeQuality,
    OracleTable,
    RankEntry,
    RuleSet,
    SkillData,
    SkillTable,
    SkillTableEntry,
    TableRange,
    ThemePack,
)
from src.rulesets.cepheus import CepheusRuleSet

__all__ = [
    "BenefitsTable",
    "CareerData",
    "CepheusRuleSet",
    "CheckOutcome",
    "CheckRef",
    "ComplicationTable",
    "MissionTable",
    "OracleTable",
    "OutcomeQuality",
    "RankEntry",
    "RuleSet",
    "SkillData",
    "SkillTable",
    "SkillTableEntry",
    "TableRange",
    "ThemePack",
]
