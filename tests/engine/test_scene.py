"""Tests for the scene engine: oracle scaffolding, options, resolution, free-text.

Covers AE14 (scene scaffold determinism), R12/R13 (structured options
pre-mapped to checks), R15 (consequences persist), AE5 (free-text
classification), R22 (oracle scaffolding), R24/AE9 (fact registration +
stat generation), AE10 (pack-driven options), R13 (degradation fallback),
R7 (complications/consequences rolled from theme-pack tables — Task 18).
"""

from __future__ import annotations

import pytest

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.scene import (
    RegisterFactCommand,
    SceneEngine,
    SceneOption,
    SceneScaffold,
)
from src.engine.state import CampaignConfig, GameState, Injury, NarrativeFact
from src.rulesets.cepheus import CepheusRuleSet
from src.themepacks.base import LoadedThemePack, get_pack
from src.themepacks.fantasy import load_fantasy_pack

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
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    state.character.skills = {
        "gun_combat_slug_rifle": 1,
        "persuade": 0,
        "stealth": 2,
        "investigate": 1,
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

        oracle_events = [e for e in engine.state.events if e.command_type == "oracle_roll"]
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
        """Combat focus produces combat-related options with real skill IDs."""
        # Roll 2 on scene_focus -> "Combat" focus.
        engine = make_engine([[1, 1], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        assert "combat" in scaffold.focus.lower()
        # Options should reference real pack skill IDs (not display names).
        skills = [o.skill for o in options]
        pack_skill_ids = set(pack.skills.keys())
        for s in skills:
            assert s in pack_skill_ids, f"Skill {s!r} is not a real pack id"
        # Combat focus should include a gun_combat_* id.
        assert any(s.startswith("gun_combat") for s in skills)

    def test_social_focus_options(self, pack):
        """Social focus produces social-related options with real skill IDs."""
        # Roll 4 on scene_focus -> "Social" focus.
        engine = make_engine([[2, 2], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        assert "social" in scaffold.focus.lower()
        skills = [o.skill for o in options]
        pack_skill_ids = set(pack.skills.keys())
        for s in skills:
            assert s in pack_skill_ids, f"Skill {s!r} is not a real pack id"
        assert "persuade" in skills


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
        # Queue: oracle rolls, then a very low roll for severe miss, plus a
        # consequence-table roll (Task 18 — misses now roll the pack table).
        engine = make_engine([[3, 4], [4, 4], [1, 1], [2, 2]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        result = se.resolve_scene(scaffold, options[0])
        se.apply_consequences(result, scaffold)

        # Check if injury was added.
        injuries = [e for e in engine.state.entities if isinstance(e, Injury)]
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

        facts = [e for e in engine.state.entities if isinstance(e, NarrativeFact)]
        if result.quality == "strong_hit":
            assert len(facts) > 0

    def test_check_recorded_in_audit(self, pack):
        """Scene checks are recorded in the event log."""
        engine = make_engine([[3, 4], [4, 4], [5, 5]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)
        se.resolve_scene(scaffold, options[0])

        check_events = [e for e in engine.state.events if e.command_type == "scene_check"]
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

        classification = se.classify_freetext("I bribe the dock officer", scaffold)

        assert classification is not None
        assert classification.original_text == "I bribe the dock officer"
        check = classification.interpreted_check
        assert check.skill == "broker"
        assert check.characteristic == "SOC"

    def test_fight_classified(self, pack):
        """'I fight the guard' produces a combat check."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        classification = se.classify_freetext("I fight the guard", scaffold)

        assert classification is not None
        assert classification.interpreted_check.skill == "gun_combat_slug_rifle"

    def test_unknown_freetext_returns_none(self, pack):
        """Uninterpretable text returns None."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        classification = se.classify_freetext("xyzzy frobnicate", scaffold)
        assert classification is None

    def test_freetext_can_be_resolved(self, pack):
        """The interpreted check can be resolved through the funnel."""
        # Queue: oracle rolls + check roll.
        engine = make_engine([[3, 4], [4, 4], [5, 5]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        classification = se.classify_freetext("I bribe the dock officer", scaffold)
        assert classification is not None

        result = se.resolve_scene(scaffold, classification.interpreted_check)
        assert result.skill == "broker"
        assert result.raw_roll == 10

    def test_freetext_combat_sets_life_threatening(self, pack):
        """Combat keywords set life_threatening so free-text can trigger defeat (F5)."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        for keyword in ("fight", "attack", "shoot"):
            classification = se.classify_freetext(f"I {keyword} the guard", scaffold)
            assert classification is not None
            assert classification.interpreted_check.life_threatening is True

    def test_freetext_noncombat_not_life_threatening(self, pack):
        """Non-combat keywords do not set life_threatening."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        for keyword in ("bribe", "persuade", "hack", "investigate"):
            classification = se.classify_freetext(f"I {keyword} the target", scaffold)
            assert classification is not None
            assert classification.interpreted_check.life_threatening is False


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

        facts = [e for e in engine.state.entities if isinstance(e, NarrativeFact)]
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
            e
            for e in engine.state.entities
            if isinstance(e, NarrativeFact) and e.name == "Bounty Hunter Kell"
        )

        stats = ratify_fact_as_npc(fact, engine=engine)
        assert stats["skill_level"] >= 0
        assert "NPC stats" in fact.description

    def test_check_targeting_fact_ratifies_it(self, pack):
        """A check whose option text names an unratified fact ratifies it (AE9)."""
        engine = make_engine([[4, 4], [6, 6]])  # check roll + npc_reaction roll (G6)
        engine.apply(RegisterFactCommand(name="Dock Officer", description="bribable"))
        se = SceneEngine(engine, pack)
        option = SceneOption(
            label="Bribe the Dock Officer",
            skill="broker",
            characteristic="SOC",
            difficulty="average",
        )
        scaffold = SceneScaffold(focus="social", focus_description="", situation="")
        result = se.resolve_scene(scaffold, option)

        # Ratify event was logged through the funnel.
        assert any(e.command_type == "ratify_fact" for e in engine.state.events)
        # Fact description now carries generated NPC stats.
        fact = next(e for e in engine.state.entities if isinstance(e, NarrativeFact))
        assert "NPC stats" in fact.description
        # Ratified name is surfaced on the check result.
        assert "Dock Officer" in result.ratified

    def test_check_not_targeting_fact_does_not_ratify(self, pack):
        """A check whose text names no fact produces no ratification."""
        engine = make_engine([[4, 4]])
        engine.apply(RegisterFactCommand(name="Hidden NPC", description="unseen"))
        se = SceneEngine(engine, pack)
        option = SceneOption(
            label="Hack the terminal",
            skill="computers",
            characteristic="INT",
            difficulty="average",
        )
        scaffold = SceneScaffold(focus="technical", focus_description="", situation="")
        se.resolve_scene(scaffold, option)
        assert not any(e.command_type == "ratify_fact" for e in engine.state.events)

    def test_already_ratified_fact_not_re_ratified(self, pack):
        """An already-ratified fact is not ratified a second time."""
        engine = make_engine([[4, 4]])
        engine.apply(RegisterFactCommand(name="Sergeant Rho", description="gruff"))
        # Pre-ratify: append "[NPC stats" marker to description.
        fact = next(e for e in engine.state.entities if isinstance(e, NarrativeFact))
        fact.description = f"{fact.description} [NPC stats: all 7, skill 1]"
        se = SceneEngine(engine, pack)
        option = SceneOption(
            label="Confront Sergeant Rho",
            skill="persuade",
            characteristic="SOC",
            difficulty="average",
        )
        scaffold = SceneScaffold(focus="social", focus_description="", situation="")
        se.resolve_scene(scaffold, option)
        # No new ratify_fact event — already ratified.
        ratify_events = [e for e in engine.state.events if e.command_type == "ratify_fact"]
        assert len(ratify_events) == 0


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
        known_keywords = ["combat", "social", "exploration", "technical", "political", "plot twist"]
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
        from src.rulesets.base import OracleTable, SkillTableEntry, TableRange
        from src.themepacks.base import LoadedThemePack

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
        # Scene 1: oracle rolls + check roll (low -> miss -> injury) +
        # consequence-table roll (Task 18 — misses now roll the pack table).
        # Scene 2: oracle rolls (no check, just scaffold).
        engine = make_engine(
            [
                [3, 4],
                [4, 4],  # Scene 1 oracle
                [1, 1],  # Scene 1 check (roll 2, severe miss)
                [2, 2],  # Scene 1 consequence-table roll
                [5, 5],
                [3, 3],  # Scene 2 oracle
            ]
        )
        se = SceneEngine(engine, pack)

        # Scene 1.
        result1 = se.run_scene()
        check1 = se.resolve_scene(result1.scaffold, result1.options[0])
        se.apply_consequences(check1, result1.scaffold)

        injuries_after_scene1 = len([e for e in engine.state.entities if isinstance(e, Injury)])

        # Scene 2.
        se.run_scene()

        # Injuries from scene 1 still present.
        injuries_after_scene2 = len([e for e in engine.state.entities if isinstance(e, Injury)])
        assert injuries_after_scene2 >= injuries_after_scene1


# ---------------------------------------------------------------------------
# FR1: Scene checks must use lifepath-stored skill IDs (regression).
# ---------------------------------------------------------------------------


class TestSkillIDCanonicalization:
    """FR1 regression: scene checks resolve against lifepath-stored skill IDs.

    Before the fix, ``SceneCheckCommand`` looked up ``self.skill`` directly in
    ``state.character.skills`` with ``.get(..., 0)``. The option/freetext maps
    used display names like "Gun Combat" while the lifepath stores IDs like
    ``gun_combat_slug_rifle`` — so every adventure check was effectively
    untrained (level 0). These tests pin the canonicalization contract.
    """

    def test_check_uses_exact_skill_id(self, pack):
        """A character with gun_combat_slug_rifle:2 resolves at skill_level 2."""
        engine = make_engine([[4, 4]])
        engine.state.character.skills = {"gun_combat_slug_rifle": 2}
        engine.state.character.characteristics = {"DEX": 9}  # +1 DM
        se = SceneEngine(engine, pack)
        scaffold = SceneScaffold(focus="combat", focus_description="x", situation="x")
        option = SceneOption(
            label="Engage",
            skill="gun_combat_slug_rifle",
            characteristic="DEX",
            difficulty="average",
        )
        result = se.resolve_scene(scaffold, option)
        assert result.skill_level == 2  # was 0 before the fix
        # DEX 9 -> +1, skill 2, average -> 0 = +3 total DM.
        assert result.total_dm == 2 + 1 + 0

    def test_check_cascades_to_specialization(self, pack):
        """A check for 'gun_combat' cascades to the best gun_combat_* level."""
        engine = make_engine([[4, 4]])
        engine.state.character.skills = {
            "gun_combat_slug_rifle": 2,
            "gun_combat_energy_rifle": 1,
        }
        engine.state.character.characteristics = {"DEX": 7}  # +0 DM
        se = SceneEngine(engine, pack)
        scaffold = SceneScaffold(focus="combat", focus_description="x", situation="x")
        option = SceneOption(
            label="Engage",
            skill="gun_combat",  # cascade parent
            characteristic="DEX",
            difficulty="average",
        )
        result = se.resolve_scene(scaffold, option)
        assert result.skill_level == 2
        assert result.total_dm == 2 + 0 + 0

    def test_check_untrained_applies_minus_3(self, pack):
        """A skill with no match resolves at the CE SRD untrained DM (-3)."""
        engine = make_engine([[4, 4]])
        engine.state.character.skills = {"mechanic": 1}  # unrelated skill
        engine.state.character.characteristics = {"INT": 7}  # +0 DM
        se = SceneEngine(engine, pack)
        scaffold = SceneScaffold(focus="social", focus_description="x", situation="x")
        option = SceneOption(
            label="Hack",
            skill="computers",  # character has no computers skill
            characteristic="INT",
            difficulty="average",
        )
        result = se.resolve_scene(scaffold, option)
        assert result.skill_level == -3
        assert result.total_dm == -3 + 0 + 0

    def test_check_records_dice_and_trained_flag(self, pack):
        """The event changes include dice rolls and the trained flag (audit)."""
        from src.engine.audit import EventKind

        engine = make_engine([[4, 4]])
        engine.state.character.skills = {"gun_combat_slug_rifle": 2}
        engine.state.character.characteristics = {"DEX": 9}
        se = SceneEngine(engine, pack)
        scaffold = SceneScaffold(focus="combat", focus_description="x", situation="x")
        option = SceneOption(
            label="Engage",
            skill="gun_combat_slug_rifle",
            characteristic="DEX",
            difficulty="average",
        )
        se.resolve_scene(scaffold, option)

        check_events = [
            e
            for e in engine.state.events
            if e.command_type == "scene_check" and e.kind == EventKind.ROLL
        ]
        assert len(check_events) == 1
        changes = check_events[0].changes
        assert changes["dice"] == [4, 4]
        assert changes["trained"] is True

    def test_check_untrained_records_trained_false(self, pack):
        """An untrained check records trained=False in the event."""
        from src.engine.audit import EventKind

        engine = make_engine([[4, 4]])
        engine.state.character.skills = {}
        engine.state.character.characteristics = {"INT": 7}
        se = SceneEngine(engine, pack)
        scaffold = SceneScaffold(focus="x", focus_description="x", situation="x")
        option = SceneOption(
            label="Hack",
            skill="computers",
            characteristic="INT",
            difficulty="average",
        )
        se.resolve_scene(scaffold, option)

        check_events = [
            e
            for e in engine.state.events
            if e.command_type == "scene_check" and e.kind == EventKind.ROLL
        ]
        assert len(check_events) == 1
        assert check_events[0].changes["trained"] is False


# ---------------------------------------------------------------------------
# AE10/R13 (Task 17): pack-driven options + degradation fallback.
# ---------------------------------------------------------------------------


class TestPackDrivenOptions:
    """Structured options come from pack `option_templates` data, not hardcoded maps.

    AE10: every pack produces genre-appropriate options using its own skill
    ids. R13: when option data is missing the engine degrades deterministically
    and logs a `flag_degradation` audit event so the path is inspectable.
    """

    def test_options_come_from_pack_data(self, pack):
        """Every generated option references a real skill id in the pack (AE10)."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        assert 2 <= len(options) <= 4
        pack_skill_ids = set(pack.skills.keys())
        for opt in options:
            assert opt.skill in pack_skill_ids, f"Skill {opt.skill!r} is not a real pack id"
            assert opt.difficulty in {
                "easy",
                "routine",
                "average",
                "difficult",
                "very_difficult",
                "formidable",
            }

    def test_fantasy_pack_produces_fantasy_options(self):
        """Fantasy pack produces fantasy-flavored options (no Gun Combat/Sensors)."""
        fantasy = load_fantasy_pack()
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, fantasy)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)

        labels = " ".join(o.label for o in options).lower()
        skills = " ".join(o.skill for o in options).lower()
        assert "gun combat" not in labels
        assert "sensors" not in labels
        # No sci-fi-only skill ids leak into fantasy options.
        assert "gun_combat" not in skills
        assert "electronics_sensors" not in skills
        # Every skill is a real fantasy pack id.
        pack_skill_ids = set(fantasy.skills.keys())
        for opt in options:
            assert opt.skill in pack_skill_ids

    def test_degradation_flagged_when_option_data_missing(self):
        """Pack with no option_templates yields generic options + flag_degradation (R13)."""
        # Build a minimal pack with oracle tables but no option_templates.
        from src.rulesets.base import (
            OracleTable,
            SkillData,
            SkillTableEntry,
            TableRange,
        )

        entries = [
            SkillTableEntry(min=2, max=12, result="Test"),
        ]
        minimal_oracle = {
            "scene_focus": OracleTable(
                id="scene_focus",
                name="Focus",
                entries=TableRange(entries=entries),
            ),
            "action_outcome": OracleTable(
                id="action_outcome",
                name="Action",
                entries=TableRange(entries=entries),
            ),
        }
        minimal_pack = LoadedThemePack(
            pack_id="test",
            name="Test",
            description="",
            careers={},
            skills={
                "athletics": SkillData(id="athletics", name="Athletics"),
                "stealth": SkillData(id="stealth", name="Stealth"),
            },
            oracle_tables=minimal_oracle,
            complication_tables={},
            mission_tables={},
        )
        engine = make_engine([])
        se = SceneEngine(engine, minimal_pack)
        scaffold = SceneScaffold(focus="combat", focus_description="x", situation="y")
        options = se.generate_options(scaffold)

        # Generic deterministic fallback yields at least 2 options.
        assert len(options) >= 2
        # Degradation flagged in the audit log.
        kinds = [e.command_type for e in engine.state.events]
        assert "flag_degradation" in kinds

    def test_degradation_flagged_when_pack_yields_too_few_options(self):
        """A pack whose focus_options entry has <2 valid options degrades (R13)."""
        from src.rulesets.base import (
            OracleTable,
            SkillData,
            SkillTableEntry,
            TableRange,
        )
        from src.themepacks.base import OptionTemplate, OptionTemplates

        entries = [
            SkillTableEntry(min=2, max=12, result="Test"),
        ]
        minimal_oracle = {
            "scene_focus": OracleTable(
                id="scene_focus",
                name="Focus",
                entries=TableRange(entries=entries),
            ),
            "action_outcome": OracleTable(
                id="action_outcome",
                name="Action",
                entries=TableRange(entries=entries),
            ),
        }
        # Only one option for the focus: triggers degradation fallback.
        sparse_templates = OptionTemplates(
            focus_options={
                "combat": [
                    OptionTemplate(
                        label="Only choice",
                        skill="athletics",
                        characteristic="STR",
                        difficulty="average",
                    )
                ]
            }
        )
        minimal_pack = LoadedThemePack(
            pack_id="test",
            name="Test",
            description="",
            careers={},
            skills={
                "athletics": SkillData(id="athletics", name="Athletics"),
                "stealth": SkillData(id="stealth", name="Stealth"),
            },
            oracle_tables=minimal_oracle,
            complication_tables={},
            mission_tables={},
            option_templates=sparse_templates,
        )
        engine = make_engine([])
        se = SceneEngine(engine, minimal_pack)
        scaffold = SceneScaffold(focus="combat", focus_description="x", situation="y")
        options = se.generate_options(scaffold)

        # Filled up to >= 2 options via generic fallback.
        assert len(options) >= 2
        # Degradation flagged.
        kinds = [e.command_type for e in engine.state.events]
        assert "flag_degradation" in kinds

    def test_unmatched_focus_falls_back_to_default_options(self):
        """An unmatched focus keyword falls back to pack `default_options` (no flag)."""
        from src.rulesets.base import (
            OracleTable,
            SkillData,
            SkillTableEntry,
            TableRange,
        )
        from src.themepacks.base import OptionTemplate, OptionTemplates

        entries = [
            SkillTableEntry(min=2, max=12, result="Test"),
        ]
        minimal_oracle = {
            "scene_focus": OracleTable(
                id="scene_focus",
                name="Focus",
                entries=TableRange(entries=entries),
            ),
            "action_outcome": OracleTable(
                id="action_outcome",
                name="Action",
                entries=TableRange(entries=entries),
            ),
        }
        templates = OptionTemplates(
            focus_options={
                "combat": [
                    OptionTemplate(
                        label="Fight",
                        skill="athletics",
                        characteristic="STR",
                        difficulty="average",
                    )
                ]
            },
            default_options=[
                OptionTemplate(
                    label="Default act",
                    skill="stealth",
                    characteristic="DEX",
                    difficulty="average",
                ),
                OptionTemplate(
                    label="Default other",
                    skill="athletics",
                    characteristic="END",
                    difficulty="difficult",
                ),
            ],
        )
        minimal_pack = LoadedThemePack(
            pack_id="test",
            name="Test",
            description="",
            careers={},
            skills={
                "athletics": SkillData(id="athletics", name="Athletics"),
                "stealth": SkillData(id="stealth", name="Stealth"),
            },
            oracle_tables=minimal_oracle,
            complication_tables={},
            mission_tables={},
            option_templates=templates,
        )
        engine = make_engine([])
        se = SceneEngine(engine, minimal_pack)
        # Focus "diplomacy" is not in focus_options; should use default_options.
        scaffold = SceneScaffold(focus="diplomacy", focus_description="x", situation="y")
        options = se.generate_options(scaffold)
        # Default options used, no degradation flag.
        labels = [o.label for o in options]
        assert "Default act" in labels
        assert "Default other" in labels
        kinds = [e.command_type for e in engine.state.events]
        assert "flag_degradation" not in kinds


class TestFreetextPackDriven:
    """Free-text classifier iterates pack freetext_keywords (longest first)."""

    def test_freetext_keyword_uses_pack_data(self, pack):
        """The classifier resolves keywords via pack freetext_keywords."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        classification = se.classify_freetext("I bribe the dock officer", scaffold)
        assert classification is not None
        assert classification.interpreted_check.skill == "broker"

    def test_freetext_longest_keyword_first(self):
        """Longer keywords win over their substrings (R14, AE5)."""
        from src.rulesets.base import (
            OracleTable,
            SkillData,
            SkillTableEntry,
            TableRange,
        )
        from src.themepacks.base import (
            FreeTextTemplate,
            OptionTemplates,
        )

        entries = [
            SkillTableEntry(min=2, max=12, result="Test"),
        ]
        minimal_oracle = {
            "scene_focus": OracleTable(
                id="scene_focus",
                name="Focus",
                entries=TableRange(entries=entries),
            ),
            "action_outcome": OracleTable(
                id="action_outcome",
                name="Action",
                entries=TableRange(entries=entries),
            ),
        }
        # "hide" (stealth) and "hide the bribe money" (broker): the longer
        # keyword must win so the broker interpretation is chosen.
        templates = OptionTemplates(
            freetext_keywords=[
                FreeTextTemplate(
                    keyword="hide",
                    label="Hide",
                    skill="stealth",
                    characteristic="DEX",
                    difficulty="average",
                ),
                FreeTextTemplate(
                    keyword="hide the bribe money",
                    label="Conceal the bribe",
                    skill="broker",
                    characteristic="SOC",
                    difficulty="difficult",
                ),
            ]
        )
        minimal_pack = LoadedThemePack(
            pack_id="test",
            name="Test",
            description="",
            careers={},
            skills={
                "stealth": SkillData(id="stealth", name="Stealth"),
                "broker": SkillData(id="broker", name="Broker"),
            },
            oracle_tables=minimal_oracle,
            complication_tables={},
            mission_tables={},
            option_templates=templates,
        )
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, minimal_pack)
        scaffold = se.generate_scaffold()

        classification = se.classify_freetext("I hide the bribe money in the locker", scaffold)
        assert classification is not None
        assert classification.interpreted_check.skill == "broker"

    def test_freetext_returns_none_when_pack_has_no_keywords(self):
        """Pack without freetext_keywords returns None (no hardcoded fallback)."""
        from src.rulesets.base import OracleTable, SkillTableEntry, TableRange

        entries = [
            SkillTableEntry(min=2, max=12, result="Test"),
        ]
        minimal_oracle = {
            "scene_focus": OracleTable(
                id="scene_focus",
                name="Focus",
                entries=TableRange(entries=entries),
            ),
            "action_outcome": OracleTable(
                id="action_outcome",
                name="Action",
                entries=TableRange(entries=entries),
            ),
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
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, minimal_pack)
        scaffold = se.generate_scaffold()

        assert se.classify_freetext("fight the guard", scaffold) is None


# ---------------------------------------------------------------------------
# R7 (Task 18): Complications and consequences rolled from theme-pack tables.
# ---------------------------------------------------------------------------


class TestComplicationRollCommand:
    """The ComplicationRollCommand rolls 2D6 on the oracle stream and registers
    a NarrativeFact (R15 persistence) plus returns the rolled entry text (R7)."""

    def test_command_records_roll_and_fact(self, pack):
        """ComplicationRollCommand appends a ROLL event + NarrativeFact entity."""
        from src.engine.scene import ComplicationRollCommand

        entries = pack.complication_tables["combat_complication"].entries.entries
        engine = make_engine([[3, 4]])  # roll 7
        engine.apply(ComplicationRollCommand(table_id="combat_complication", entries=entries))

        roll_events = [e for e in engine.state.events if e.command_type == "complication_roll"]
        assert len(roll_events) == 1
        changes = roll_events[0].changes
        assert changes["table_id"] == "combat_complication"
        assert changes["roll_total"] == 7
        # NarrativeFact persisted (R15).
        facts = [e for e in engine.state.entities if isinstance(e, NarrativeFact)]
        assert len(facts) == 1
        assert facts[0].name == changes["result_text"]

    def test_command_uses_oracle_stream(self, pack):
        """Complication rolls go on the oracle stream so determinism holds."""
        from src.engine.scene import ComplicationRollCommand

        entries = pack.complication_tables["combat_complication"].entries.entries
        engine = make_engine([[5, 5]])
        engine.apply(ComplicationRollCommand(table_id="combat_complication", entries=entries))
        roll_events = [e for e in engine.state.events if e.command_type == "complication_roll"]
        assert roll_events[0].roll is not None
        assert roll_events[0].roll.stream == "oracle"


class TestWeakHitRollsComplication:
    """R7: a weak hit (narrative profile) rolls the focus-mapped complication table."""

    def test_weak_hit_rolls_complication_from_pack_table(self, pack):
        """Weak hit on a combat focus yields a complication_roll event from
        the focus-mapped combat_complication table."""
        # Queue: oracle rolls, check roll (7 → weak hit), complication roll (6).
        engine = make_engine([[1, 1], [4, 4], [3, 4], [3, 3]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()  # "Combat" focus + situation
        options = se.generate_options(scaffold)
        result = se.resolve_scene(scaffold, options[0])
        # Confirm we landed in the weak-hit band (guard for option-skill drift).
        assert result.quality == "weak_hit", (
            f"Expected weak_hit, got {result.quality} (raw={result.raw_roll} "
            f"total_dm={result.total_dm})"
        )

        consequences = se.apply_consequences(result, scaffold)

        rolls = [e for e in engine.state.events if e.command_type == "complication_roll"]
        assert len(rolls) == 1
        # The hardcoded "Success with a complication." string is gone (R7).
        assert "Success with a complication." not in consequences
        # Consequence text comes from the rolled table entry.
        assert len(consequences) >= 1
        assert rolls[0].changes["table_id"] == "combat_complication"
        # NarrativeFact persisted (R15).
        facts = [e for e in engine.state.entities if isinstance(e, NarrativeFact)]
        assert any(f.name == rolls[0].changes["result_text"] for f in facts)

    def test_weak_hit_consequence_text_matches_rolled_entry(self, pack):
        """The consequence string returned is exactly the rolled table entry."""
        # Roll 2 on the complication table → entry min=2,max=2.
        engine = make_engine([[1, 1], [4, 4], [3, 4], [1, 1]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)
        result = se.resolve_scene(scaffold, options[0])
        assert result.quality == "weak_hit"

        consequences = se.apply_consequences(result, scaffold)
        roll_events = [e for e in engine.state.events if e.command_type == "complication_roll"]
        expected = roll_events[0].changes["result_text"]
        assert expected in consequences


class TestMissRollsConsequence:
    """R7: a miss (narrative profile) rolls the focus-mapped consequence table
    AND retains the injury-by-effect tiers for severe misses."""

    def test_miss_rolls_consequence_table(self, pack):
        """A miss produces a complication_roll event from the consequence map."""
        # Roll 4 (1+3) + total_dm +2 = 6 → miss. Complication roll queued after.
        engine = make_engine([[1, 1], [4, 4], [1, 3], [2, 2]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)
        result = se.resolve_scene(scaffold, options[0])
        assert result.quality == "miss", (
            f"Expected miss, got {result.quality} (raw={result.raw_roll} "
            f"total_dm={result.total_dm})"
        )

        se.apply_consequences(result, scaffold)

        rolls = [e for e in engine.state.events if e.command_type == "complication_roll"]
        assert len(rolls) == 1
        assert "complication_roll" in [e.command_type for e in engine.state.events]

    def test_severe_miss_still_injures(self, pack):
        """Severe misses still apply injuries in addition to consequence text."""
        # Roll 2 + total_dm +2 = 4 → effect -4 → severe miss.
        engine = make_engine([[1, 1], [4, 4], [1, 1], [2, 2]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()
        options = se.generate_options(scaffold)
        result = se.resolve_scene(scaffold, options[0])
        assert result.quality == "miss"
        assert result.effect <= -4

        se.apply_consequences(result, scaffold)

        injuries = [e for e in engine.state.entities if isinstance(e, Injury)]
        assert len(injuries) >= 1
        # Consequence table was also rolled.
        rolls = [e for e in engine.state.events if e.command_type == "complication_roll"]
        assert len(rolls) == 1


class TestNoTableFallback:
    """When no pack table is available, apply_consequences flags degradation (R13)."""

    def test_weak_hit_without_table_flags_degradation(self):
        """Pack without a complication table for the focus → FlagDegradationCommand."""
        from src.rulesets.base import (
            OracleTable,
            SkillData,
            SkillTableEntry,
            TableRange,
        )
        from src.themepacks.base import OptionTemplate, OptionTemplates

        entries = [
            SkillTableEntry(min=2, max=12, result="Test"),
        ]
        minimal_oracle = {
            "scene_focus": OracleTable(
                id="scene_focus", name="Focus", entries=TableRange(entries=entries)
            ),
            "action_outcome": OracleTable(
                id="action_outcome", name="Action", entries=TableRange(entries=entries)
            ),
        }
        templates = OptionTemplates(
            default_options=[
                OptionTemplate(
                    label="Act",
                    skill="athletics",
                    characteristic="STR",
                    difficulty="average",
                )
            ]
        )
        # No complication_tables and no complication_map.
        minimal_pack = LoadedThemePack(
            pack_id="test",
            name="Test",
            description="",
            careers={},
            skills={"athletics": SkillData(id="athletics", name="Athletics")},
            oracle_tables=minimal_oracle,
            complication_tables={},
            mission_tables={},
            option_templates=templates,
        )
        engine = make_engine([])
        engine.state.character.skills = {"athletics": 0}
        engine.state.character.characteristics = {"STR": 7}
        se = SceneEngine(engine, minimal_pack)
        scaffold = SceneScaffold(focus="unknown", focus_description="x", situation="y")
        from src.engine.scene import SceneCheckResult

        check = SceneCheckResult(
            skill="athletics",
            difficulty="average",
            raw_roll=8,
            char_dm=0,
            skill_level=0,
            difficulty_dm=0,
            total_dm=0,
            success=True,
            effect=0,
            quality="weak_hit",
            description="x",
        )
        se.apply_consequences(check, scaffold)
        kinds = [e.command_type for e in engine.state.events]
        assert "flag_degradation" in kinds


class TestComplicationMapLoader:
    """Pack option_templates now carries a complication_map (focus → table id)."""

    def test_scifi_pack_has_complication_map(self, pack):
        """Sci-fi pack loads a complication_map covering every focus."""
        cmap = pack.complication_map
        assert cmap is not None
        assert cmap.complication, "complication map is empty"
        assert cmap.consequence, "consequence map is empty"
        # Every focus-keyword in the scifi scene_focus oracle table has an entry.
        for focus in ("combat", "social", "exploration", "technical", "default"):
            assert focus in cmap.complication, (
                f"complication map missing focus {focus!r}: {cmap.complication}"
            )

    def test_fantasy_pack_has_complication_map_with_magic(self):
        """Fantasy pack maps the 'magic' focus to magic_complication (was unreachable)."""
        fantasy = load_fantasy_pack()
        cmap = fantasy.complication_map
        assert cmap is not None
        assert cmap.complication["magic"] == "magic_complication"

    def test_complication_map_only_references_real_tables(self, pack):
        """Referential integrity: every table id in complication_map exists."""
        cmap = pack.complication_map
        assert cmap is not None
        table_ids = set(pack.complication_tables.keys())
        for kind in ("complication", "consequence"):
            kind_map = getattr(cmap, kind, {}) or {}
            for focus, table_id in kind_map.items():
                assert table_id in table_ids, (
                    f"{kind}[{focus!r}] references unknown table {table_id!r}; "
                    f"known: {sorted(table_ids)}"
                )


# ---------------------------------------------------------------------------
# R14/AE5: LLM classifier integration on SceneEngine.classify_freetext.
# ---------------------------------------------------------------------------


class TestFreetextLLMClassifier:
    """classify_freetext accepts an optional LLM classifier callable.

    When provided and it returns a result, the LLM classification is used.
    When it returns None (exhaustion, failure), the keyword map is the fallback.
    """

    def test_llm_classifier_result_used(self, pack):
        """LLM classifier returns a FreeTextCheck → SceneEngine wraps it."""
        from src.llm.adapter import FreeTextCheck

        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        def mock_classifier(text, scaffold):
            return FreeTextCheck(
                skill_id="investigate",
                difficulty="difficult",
                label="Search the cargo manifest",
                characteristic="INT",
                life_threatening=False,
            )

        result = se.classify_freetext(
            "I search the cargo manifest", scaffold, llm_classifier=mock_classifier
        )
        assert result is not None
        assert result.interpreted_check.skill == "investigate"
        assert result.interpreted_check.difficulty == "difficult"
        assert result.interpreted_check.characteristic == "INT"
        assert result.original_text == "I search the cargo manifest"

    def test_llm_classifier_none_falls_back_to_keyword(self, pack):
        """LLM classifier returns None → keyword map is used."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        def failing_classifier(text, scaffold):
            return None

        result = se.classify_freetext(
            "I bribe the dock officer", scaffold, llm_classifier=failing_classifier
        )
        assert result is not None
        assert result.interpreted_check.skill == "broker"

    def test_llm_classifier_none_no_keyword_match_returns_none(self, pack):
        """LLM returns None and no keyword matches → None."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        def failing_classifier(text, scaffold):
            return None

        result = se.classify_freetext(
            "xyzzy frobnicate", scaffold, llm_classifier=failing_classifier
        )
        assert result is None

    def test_no_llm_classifier_uses_keyword_only(self, pack):
        """Without llm_classifier, keyword map is used (existing behavior)."""
        engine = make_engine([[3, 4], [4, 4]])
        se = SceneEngine(engine, pack)
        scaffold = se.generate_scaffold()

        result = se.classify_freetext("I bribe the dock officer", scaffold)
        assert result is not None
        assert result.interpreted_check.skill == "broker"


# ---------------------------------------------------------------------------
# U3 / TUI-6: SetPendingFreetextCommand + SceneCheckCommand atomic clear.
# ---------------------------------------------------------------------------


class TestSetPendingFreetextCommand:
    """U3/TUI-6: set/clear pending_freetext via command funnel."""

    def test_sets_pending_freetext(self):
        """SetPendingFreetextCommand stores the payload in state."""
        from src.engine.scene import SetPendingFreetextCommand

        state = GameState.new(seed=42)
        engine = Engine(state)
        payload = {
            "text": "I bribe the guard",
            "check": {
                "label": "Bribe",
                "skill": "broker",
                "characteristic": "SOC",
                "difficulty": "average",
            },
            "scaffold": {
                "focus": "Dock",
                "focus_description": "Busy",
                "situation": "Tense",
                "npc_hint": "",
            },
            "options": [],
        }
        engine.apply(SetPendingFreetextCommand(payload=payload))
        assert state.pending_freetext == payload

    def test_clears_pending_freetext(self):
        """SetPendingFreetextCommand with payload=None clears the field."""
        from src.engine.scene import SetPendingFreetextCommand

        state = GameState.new(seed=42)
        engine = Engine(state)
        state.pending_freetext = {"text": "old", "check": {}, "scaffold": {}, "options": []}
        engine.apply(SetPendingFreetextCommand(payload=None))
        assert state.pending_freetext is None

    def test_invalid_payload_raises_in_validate(self):
        """Payload missing required keys raises ValueError; state untouched."""
        from src.engine.scene import SetPendingFreetextCommand

        state = GameState.new(seed=42)
        engine = Engine(state)
        with pytest.raises(ValueError, match="missing required keys"):
            engine.apply(SetPendingFreetextCommand(payload={"text": "incomplete"}))
        assert state.pending_freetext is None

    def test_invalid_check_raises_in_validate(self):
        """Check missing required keys raises ValueError; state untouched."""
        from src.engine.scene import SetPendingFreetextCommand

        state = GameState.new(seed=42)
        engine = Engine(state)
        with pytest.raises(ValueError, match="check missing"):
            engine.apply(
                SetPendingFreetextCommand(
                    payload={"text": "x", "check": {"label": "ok"}, "scaffold": {}, "options": []}
                )
            )
        assert state.pending_freetext is None


class TestSceneCheckClearsPending:
    """U3/TUI-6: SceneCheckCommand with clear_pending_freetext=True clears atomically."""

    def test_clear_pending_on_resolve(self):
        """Resolving a free-text check clears pending_freetext in the same mutate."""
        from src.engine.scene import SetPendingFreetextCommand

        state = GameState.new(seed=42)
        state.character.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        state.character.skills = {"Persuade": 1}
        engine = Engine(state)

        # Set pending state.
        engine.apply(
            SetPendingFreetextCommand(
                payload={
                    "text": "x",
                    "check": {
                        "label": "L",
                        "skill": "Persuade",
                        "characteristic": "SOC",
                        "difficulty": "average",
                    },
                    "scaffold": {},
                    "options": [],
                }
            )
        )
        assert state.pending_freetext is not None

        # Resolve with clear_pending_freetext=True.
        from src.engine.scene import SceneCheckCommand

        engine.apply(
            SceneCheckCommand(
                skill="Persuade",
                characteristic="SOC",
                difficulty="average",
                clear_pending_freetext=True,
            )
        )
        assert state.pending_freetext is None

    def test_no_clear_without_flag(self):
        """Normal SceneCheckCommand does NOT clear pending_freetext."""
        from src.engine.scene import SceneCheckCommand, SetPendingFreetextCommand

        state = GameState.new(seed=42)
        state.character.characteristics = {
            "STR": 7,
            "DEX": 8,
            "END": 6,
            "INT": 10,
            "EDU": 9,
            "SOC": 5,
        }
        state.character.skills = {"Persuade": 1}
        engine = Engine(state)
        engine.apply(
            SetPendingFreetextCommand(
                payload={
                    "text": "x",
                    "check": {
                        "label": "L",
                        "skill": "Persuade",
                        "characteristic": "SOC",
                        "difficulty": "average",
                    },
                    "scaffold": {},
                    "options": [],
                }
            )
        )
        engine.apply(
            SceneCheckCommand(skill="Persuade", characteristic="SOC", difficulty="average")
        )
        # pending_freetext is still set because clear flag was False.
        assert state.pending_freetext is not None
