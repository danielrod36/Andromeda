"""Snapshot tests for the engine-derived rules digest (P4.T6, ADR A5)."""

from __future__ import annotations

from src.engine.lifepath_choices import (
    ChoiceOptionView,
    ChoicePointView,
    build_rules_summary,
)
from src.rulesets.cepheus import CepheusRuleSet


def make_choice(dimmed: bool = True) -> ChoicePointView:
    return ChoicePointView(
        choice_id="career_qualification",
        phase="qualify",
        prompt="Choose a career to attempt.",
        options=[
            ChoiceOptionView(
                option_id="navy", label="Navy", odds_line="DM +1 vs 8 · 72% Favorable"
            ),
            ChoiceOptionView(
                option_id="agent",
                label="Agent",
                dimmed=dimmed,
                requirement="INT 8+ required" if dimmed else None,
            ),
        ],
    )


def test_rules_summary_snapshot():
    summary = build_rules_summary(make_choice(), CepheusRuleSet())
    assert summary == (
        "Checks: 2D6 + DM vs 8+.\n"
        "Difficulty ladder: Easy +4, Routine +2, Average +0, Difficult -2, "
        "Very Difficult -4, Formidable -6.\n"
        "Characteristic DM: 0-2: -2, 3-5: -1, 6-8: +0, 9-11: +1, 12-14: +2, 15+: +3.\n"
        "Unavailable here: agent (INT 8+ required)."
    )


def test_rules_summary_all_available():
    summary = build_rules_summary(make_choice(dimmed=False), CepheusRuleSet())
    assert summary.endswith("All listed options are available.")


def test_rules_summary_deterministic_default_ruleset():
    assert build_rules_summary(make_choice()) == build_rules_summary(make_choice())
