"""Tests for the scene engine: oracle scaffolding, options, resolution, free-text.

Covers AE14 (scene scaffold determinism), R12/R13 (structured options
pre-mapped to checks), R15 (consequences persist), AE5 (free-text
classification), R22 (oracle scaffolding), R24/AE9 (fact registration +
stat generation).
"""
from __future__ import annotations

import pytest

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.scene import (
    AddInjuryCommand,
    FreeTextClassification,
    OracleRollCommand,
    RegisterFactCommand,
    SceneCheckCommand,
    SceneEngine,
    SceneOption,
    SceneScaffold,
)
from src.engine.state import CampaignConfig, GameState, Injury, NarrativeFact
from src.rulesets.cepheus import CepheusRuleSet
from src.rulesets.profiles import ClassicProfile, NarrativeProfile
from src.themepacks.base import get_pack


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def pack():
    return get_pack("scifi")


@pytest.fixture
def ruleset():
    return CepheusRuleSet()


def make_engine(queue, profile="narrative", seed=42):
    """Create an engine with ForcedRoller and given resolution profile."""
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(resolution_profile=profile)
    # Give the character some skills and characteristics for checks.
    state.character.characteristics = {
        "STR": 7, "DEX": 9, "END": 6,
        "INT": 8, "EDU": 10, "SOC": 5,
    }
    state.character.skills = {
        "Gun Combat": 1, "Persuade": 0,
        "Stealth": 2, "Investigate": 1,
    }
    return Engine(state, roller=ForcedRoller(queue))


# ---------------------------------------------------------------------------
# AE14: Scene scaffold determinism.
# ---------------------------------------------------------------------------


class TestSceneScaffoldDeterminism:
    """Scene scaffold derivable from oracle table rolls; same inputs -> same scaffold."""

    def test_scaffold_has_focus_and_situation(self, pack):
        """Scaffold contains focus and situation from oracle tables."""
        # Queue: scene_focus roll (7), action_outcome roll (8).
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        assert scaffold.focus is not None
        assert len(scaffold.focus) > 0
        assert scaffold.situation is not None
        assert len(scaffold.situation) > 0
        assert len(scaffold.oracle_rolls) == 2

    def test_same_rolls_produce_same_scaffold(self, pack):
        """Same oracle rolls produce identical scaffolds (AE14)."""
        engine1 = make_engine([[3, 4], [4, 4]])
        engine2 = make_engine([[3, 4], [4, 4]])

        se1 = SceneEngine(engine1, pack)
        se2 = SceneEngine(engine2, pack)

        s1 = se1.generate_scaffold()
        s2 = se2.generate_scaffold()

        assert s1.focus == s2.focus
        assert s1.focus_description == s2.focus_description
        assert s1.situation == s2.situation
        assert s1.oracle_rolls == s2.oracle_rolls

    def test_different_rolls_produce_different_scaffold(self, pack):
        """Different oracle rolls produce different scaffolds (AE14)."""
        engine1 = make_engine([[1, 1], [1, 1]])  # roll 2, 2
        engine2 = make_engine([[6, 6], [6, 6]])  # roll 12, 12

        se1 = SceneEngine(engine1, pack)
        se2 = SceneEngine(engine2, pack)

        s1 = se1.generate_scaffold()
        s2 = se2.generate_scaffold()

        assert s1.oracle_rolls != s2.oracle_rolls

    def test_oracle_rolls_recorded_in_audit(self, pack):
        """Oracle rolls are recorded in the event log via the funnel."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        se.generate_scaffold()

        oracle_events = [
            e for e in engine.state.events
            if e.command_type == "oracle_roll"
        ]
        assert len(oracle_events) == 2


# ---------------------------------------------------------------------------
# R12/R13: Structured options pre-mapped to engine-known checks.
# ---------------------------------------------------------------------------


class TestStructuredOptions:
    """Structured options map to engine-known checks before display."""

    def test_generates_2_to_4_options(self, pack):
        """Options are within the 2-4 range (R12)."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        assert 2 <= len(options) <= 4

    def test_each_option_has_skill_and_difficulty(self, pack):
        """Each option pre-maps to a skill + difficulty (R13)."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        for opt in options:
            assert opt.skill is not None and len(opt.skill) > 0
            assert opt.difficulty is not None
            assert opt.characteristic is not None
            assert opt.label is not None and len(opt.label) > 0

    def test_combat_focus_options(self, pack):
        """Combat focus produces combat-related options."""
        # Roll 2 on scene_focus -> "Combat" focus.
        engine = make_engine([[1, 1], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        assert "combat" in scaffold.focus.lower()
        # Should have Gun Combat option.
        skills = [o.skill for o in options]
        assert "Gun Combat" in skills

    def test_social_focus_options(self, pack):
        """Social focus produces social-related options."""
        # Roll 4 on scene_focus -> "Social" focus.
        engine = make_engine([[2, 2], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        assert "social" in scaffold.focus.lower()
        skills = [o.skill for o in options]
        assert "Persuade" in skills


# ---------------------------------------------------------------------------
# R13/R15: Check resolution and consequence persistence.
# ---------------------------------------------------------------------------


class TestCheckResolution:
    """Check resolution through the command funnel and consequence persistence."""

    def test_resolve_scene_produces_outcome(self, pack):
        """Resolving a scene check produces a SceneCheckResult."""
        # Queue: oracle rolls for scaffold, then check roll.
        engine = make_engine([[3, 4], [4, 4], [5, 5]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        result = se.resolve_scene(scaffold, options[0])

        assert result.skill == options[0].skill
        assert result.raw_roll == 10  # 5+5
        assert result.quality in ("strong_hit", "weak_hit", "miss")

    def test_classic_profile_resolution(self, pack):
        """Classic profile produces binary success/fail."""
        # Queue: oracle rolls, then a high roll for success.
        engine = make_engine([[3, 4], [4, 4], [5, 6]], profile="classic")
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        result = se.resolve_scene(scaffold, options[0])
        # Roll 11 + DMs should easily succeed in classic (target 8).
        assert result.success is True
        assert result.quality == "strong_hit"

    def test_consequences_persist_injuries(self, pack):
        """Failed checks can produce injuries that persist in state (R15)."""
        # Queue: oracle rolls, then a very low roll for severe miss.
        engine = make_engine([[3, 4], [4, 4], [1, 1]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        result = se.resolve_scene(scaffold, options[0])
        consequences = se.apply_consequences(result, scaffold)

        # Check if injury was added.
        injuries = [
            e for e in engine.state.entities if isinstance(e, Injury)
        ]
        # A roll of 2 with average difficulty and low DMs should miss badly.
        if result.effect <= -2:
            assert len(injuries) > 0

    def test_consequences_persist_facts(self, pack):
        """Strong hits register narrative facts (R24)."""
        # Queue: oracle rolls, then a high roll for strong hit.
        engine = make_engine([[3, 4], [4, 4], [6, 6]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        result = se.resolve_scene(scaffold, options[0])
        se.apply_consequences(result, scaffold)

        facts = [
            e for e in engine.state.entities
            if isinstance(e, NarrativeFact)
        ]
        if result.quality == "strong_hit":
            assert len(facts) > 0

    def test_check_recorded_in_audit(self, pack):
        """Scene checks are recorded in the event log."""
        engine = make_engine([[3, 4], [4, 4], [5, 5]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)
        se.resolve_scene(scaffold, options[0])

        check_events = [
            e for e in engine.state.events
            if e.command_type == "scene_check"
        ]
        assert len(check_events) == 1


# ---------------------------------------------------------------------------
# AE5: Free-text classification.
# ---------------------------------------------------------------------------


class TestFreeTextClassification:
    """Free-text input classified into engine-known check, shown before resolution."""

    def test_bribe_classified(self, pack):
        """'I bribe the dock officer' produces an interpreted check (AE5)."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        classification = se.classify_freetext(
            "I bribe the dock officer", scaffold
        )

        assert classification is not None
        assert classification.original_text == "I bribe the dock officer"
        check = classification.interpreted_check
        assert check.skill == "Broker"
        assert check.characteristic == "SOC"

    def test_fight_classified(self, pack):
        """'I fight the guard' produces a combat check."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        classification = se.classify_freetext(
            "I fight the guard", scaffold
        )

        assert classification is not None
        assert classification.interpreted_check.skill == "Gun Combat"

    def test_unknown_freetext_returns_none(self, pack):
        """Uninterpretable text returns None."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        classification = se.classify_freetext(
            "xyzzy frobnicate", scaffold
        )
        assert classification is None

    def test_freetext_can_be_resolved(self, pack):
        """The interpreted check can be resolved through the funnel."""
        # Queue: oracle rolls + check roll.
        engine = make_engine([[3, 4], [4, 4], [5, 5]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        classification = se.classify_freetext(
            "I bribe the dock officer", scaffold
        )
        assert classification is not None

        result = se.resolve_scene(
            scaffold, classification.interpreted_check
        )
        assert result.skill == "Broker"
        assert result.raw_roll == 10


# ---------------------------------------------------------------------------
# R24/AE9: Narrative fact registration + NPC stat generation.
# ---------------------------------------------------------------------------


class TestNarrativeFactRegistration:
    """LLM-introduced NPCs registered as facts; engine generates stats (AE9)."""

    def test_register_fact_command(self, pack):
        """RegisterFactCommand adds a NarrativeFact to state."""
        engine = make_engine([])
        engine.apply(
            RegisterFactCommand(
                name="Dock Officer Vex",
                description="A corrupt official at the starport.",
            )
        )

        facts = [
            e for e in engine.state.entities
            if isinstance(e, NarrativeFact)
        ]
        assert len(facts) == 1
        assert facts[0].name == "Dock Officer Vex"
        assert "corrupt" in facts[0].description

    def test_register_empty_fact_rejected(self, pack):
        """Empty fact name is rejected by validation."""
        engine = make_engine([])
        with pytest.raises(ValueError, match="non-empty"):
            engine.apply(RegisterFactCommand(name="", description=""))

    def test_npc_stats_generated_when_targeted(self, pack):
        """Engine generates stats when a check targets a fact NPC (AE9)."""
        from src.engine.retrieval import generate_npc_stats

        engine = make_engine([])
        engine.apply(
            RegisterFactCommand(
                name="Captain Rho",
                description="A merchant captain.",
            )
        )

        stats = generate_npc_stats("Captain Rho")
        assert stats["name"] == "Captain Rho"
        assert "STR" in stats["characteristics"]
        assert stats["skill_level"] >= 0

    def test_ratify_fact_adds_stats(self, pack):
        """Ratifying a fact as NPC updates its description with stats."""
        from src.engine.retrieval import ratify_fact_as_npc

        engine = make_engine([])
        engine.apply(
            RegisterFactCommand(
                name="Bounty Hunter Kell",
                description="A dangerous hunter.",
            )
        )

        fact = next(
            e for e in engine.state.entities
            if isinstance(e, NarrativeFact) and e.name == "Bounty Hunter Kell"
        )

        stats = ratify_fact_as_npc(engine.state, fact)
        assert stats["skill_level"] >= 0
        assert "NPC stats" in fact.description


# ---------------------------------------------------------------------------
# R22: Oracle scaffolding from oracle tables.
# ---------------------------------------------------------------------------


class TestOracleScaffolding:
    """Scene scaffold from oracle rolls, deterministic (R22)."""

    def test_scaffold_uses_scene_focus_table(self, pack):
        """The scaffold's focus comes from the scene_focus oracle table."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        # Roll 7 on scene_focus -> "Exploration" focus.
        # The result text should contain one of the known focus keywords.
        known_keywords = ["combat", "social", "exploration", "technical",
                          "political", "plot twist"]
        assert any(k in scaffold.focus.lower() for k in known_keywords)

    def test_scaffold_uses_action_outcome_table(self, pack):
        """The scaffold's situation comes from the action_outcome oracle table."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        # Situation should be a non-empty string from the oracle table.
        assert len(scaffold.situation) > 10

    def test_missing_oracle_table_raises(self, pack):
        """Missing oracle table raises KeyError."""
        # Create a pack without scene_focus table.
        from src.themepacks.base import LoadedThemePack
        from src.rulesets.base import OracleTable, TableRange, SkillTableEntry

        # Build a minimal pack with only one oracle table.
        entries = [
            SkillTableEntry(min=2, max=12, result="Test"),
        ]
        minimal_oracle = {
            "action_outcome": OracleTable(
                id="action_outcome",
                name="Action",
                entries=TableRange(entries=entries),
            )
        }
        minimal_pack = LoadedThemePack(
            pack_id="test",
            name="Test",
            description="",
            careers={},
            skills={},
            oracle_tables=minimal_oracle,
            complication_tables={},
            mission_tables={},
        )
        engine = make_engine([[3, 4]])
        se = SceneEngine(engine, minimal_pack)
        with pytest.raises(KeyError, match="scene_focus"):
            se.generate_scaffold()


# ---------------------------------------------------------------------------
# Integration: full scene cycle.
# ---------------------------------------------------------------------------


class TestFullSceneCycle:
    """Full scene cycle: scaffold -> options -> resolve -> consequences."""

    def test_run_scene_produces_scaffold_and_options(self, pack):
        """run_scene returns scaffold and options."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        result = se.run_scene()

        assert result.scaffold is not None
        assert len(result.options) >= 2

    def test_consequences_persist_across_scenes(self, pack):
        """Consequences from one scene persist to the next (R15)."""
        # Scene 1: oracle rolls + check roll (low -> miss -> injury).
        # Scene 2: oracle rolls (no check, just scaffold).
        engine = make_engine([
            [3, 4], [4, 4],  # Scene 1 oracle
            [1, 1],           # Scene 1 check (roll 2, severe miss)
            [5, 5], [3, 3],  # Scene 2 oracle
        ])
        se = SceneEngine(engine, pack)

        # Scene 1.
        result1 = se.run_scene()
        check1 = se.resolve_scene(result1.scaffold, result1.options[0])
        se.apply_consequences(check1, result1.scaffold)

        injuries_after_scene1 = len([
            e for e in engine.state.entities if isinstance(e, Injury)
        ])

        # Scene 2.
        result2 = se.run_scene()

        # Injuries from scene 1 still present.
        injuries_after_scene2 = len([
            e for e in engine.state.entities if isinstance(e, Injury)
        ])
        assert injuries_after_scene2 >= injuries_after_scene1
