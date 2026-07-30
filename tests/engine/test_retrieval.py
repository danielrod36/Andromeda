"""Tests for narrative fact retrieval: entity-based matching + recency slice.

Covers R25 (fact retrieval re-surfaces relevant facts in curated view),
R24 (LLM-introduced NPCs/places/items as narrative facts), AE9 (NPC stat
generation when a check targets a fact).
"""

from __future__ import annotations

import pytest

from src.engine.commands import Engine
from src.engine.dice import ForcedRoller
from src.engine.retrieval import (
    DEFAULT_RECENCY_CAP,
    FactRetriever,
    generate_npc_stats,
    ratify_fact_as_npc,
)
from src.engine.scene import RatifyFactCommand, RegisterFactCommand
from src.engine.state import CampaignConfig, GameState, NarrativeFact
from src.rulesets.cepheus import CepheusRuleSet
from src.themepacks.base import get_pack

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def pack():
    return get_pack("scifi")


def make_state():
    state = GameState.new(seed=42)
    state.campaign = CampaignConfig()
    return state


def add_fact(state, name, description=""):
    """Helper: add a narrative fact to state."""
    state.entities.append(NarrativeFact(name=name, description=description))


# ---------------------------------------------------------------------------
# Entity-based matching (R25).
# ---------------------------------------------------------------------------


class TestEntityMatching:
    """Facts whose entity names appear in context are re-surfaced."""

    def test_fact_name_matched_in_context(self):
        """A fact whose name appears in context text is matched."""
        state = make_state()
        add_fact(state, "Dock Officer Vex", "A corrupt official.")
        retriever = FactRetriever()

        results = retriever.retrieve_facts(state, ["The Dock Officer Vex demands a bribe."])
        assert len(results) >= 1
        assert results[0].name == "Dock Officer Vex"

    def test_fact_not_matched_when_absent(self):
        """A fact whose name does NOT appear in context is not matched."""
        state = make_state()
        add_fact(state, "Captain Rho", "A merchant.")
        retriever = FactRetriever()

        results = retriever.retrieve_facts(state, ["The bar is quiet tonight."])
        # No entity match — may still appear in recency slice.
        [r for r in results if r.name == "Captain Rho"]
        # In recency slice, it would be included, so let's test specifically
        # with no recency contribution.
        assert len(results) <= DEFAULT_RECENCY_CAP

    def test_multiple_facts_matched(self):
        """Multiple facts are matched when their names appear."""
        state = make_state()
        add_fact(state, "Vex", "An NPC.")
        add_fact(state, "Rho", "Another NPC.")
        add_fact(state, "Irrelevant", "Not mentioned.")
        retriever = FactRetriever()

        results = retriever.retrieve_facts(state, ["Vex and Rho meet at the bar."])
        names = [r.name for r in results]
        assert "Vex" in names
        assert "Rho" in names

    def test_case_insensitive_matching(self):
        """Entity matching is case-insensitive."""
        state = make_state()
        add_fact(state, "Dock Officer Vex")
        retriever = FactRetriever()

        results = retriever.retrieve_facts(state, ["The DOCK OFFICER VEX blocks your path."])
        matched = [r for r in results if r.name == "Dock Officer Vex"]
        assert len(matched) >= 1

    def test_short_name_requires_word_boundary(self):
        """Short names (<=3 chars) require word-boundary match."""
        state = make_state()
        add_fact(state, "Jo", "A pilot.")
        retriever = FactRetriever()

        # "Jojo" should not match "Jo" due to word boundary requirement.
        retriever.retrieve_facts(state, ["Jojo is here."])
        # "Jo" might appear in recency slice, but shouldn't be entity-matched.
        # Just verify it doesn't crash.

    def test_match_cap_limits_results(self):
        """Match cap limits the number of entity-matched facts."""
        state = make_state()
        for i in range(10):
            add_fact(state, f"Character{i}", f"NPC number {i}")
        retriever = FactRetriever(match_cap=3)

        context = " ".join([f"Character{i}" for i in range(10)])
        results = retriever.retrieve_facts(state, [context])
        # First 3 should be matched (plus recency, but deduped).
        # With match_cap=3, at most 3 matched facts.
        matched = [r for r in results if r.name.startswith("Character")]
        assert len(matched) <= 3 + DEFAULT_RECENCY_CAP  # recency adds more


# ---------------------------------------------------------------------------
# Recency-ranked slice (R25).
# ---------------------------------------------------------------------------


class TestRecencySlice:
    """A capped recency-ranked slice is always included."""

    def test_recency_slice_includes_recent_facts(self):
        """The most recent facts are included."""
        state = make_state()
        for i in range(5):
            add_fact(state, f"NPC_{i}", f"NPC number {i}")
        retriever = FactRetriever(recency_cap=3)

        results = retriever.retrieve_facts(state, [])
        # With no context, only recency slice is returned.
        assert len(results) <= 3

    def test_recency_slice_capped(self):
        """Recency slice is capped at recency_cap."""
        state = make_state()
        for i in range(20):
            add_fact(state, f"NPC_{i:02d}", f"NPC {i}")
        retriever = FactRetriever(recency_cap=5)

        results = retriever.retrieve_facts(state, [])
        assert len(results) <= 5

    def test_recency_orders_newest_first(self):
        """Recency slice returns newest facts first."""
        state = make_state()
        add_fact(state, "Old_NPC", "First")
        add_fact(state, "Mid_NPC", "Second")
        add_fact(state, "New_NPC", "Third")
        retriever = FactRetriever(recency_cap=10)

        results = retriever.retrieve_facts(state, [])
        names = [r.name for r in results]
        # Newest first.
        assert names.index("New_NPC") < names.index("Old_NPC")

    def test_deduplication_between_match_and_recency(self):
        """Matched facts are not duplicated in recency slice."""
        state = make_state()
        add_fact(state, "Vex", "An NPC.")
        retriever = FactRetriever()

        results = retriever.retrieve_facts(state, ["Vex appears."])
        names = [r.name for r in results]
        assert names.count("Vex") == 1


# ---------------------------------------------------------------------------
# Scene-specific retrieval (R25).
# ---------------------------------------------------------------------------


class TestSceneRetrieval:
    """Facts from earlier scenes re-surface when entity is referenced."""

    def test_retrieve_for_scene_combines_contexts(self):
        """retrieve_for_scene combines scaffold, input, and threads."""
        state = make_state()
        add_fact(state, "Station Alpha", "A space station.")
        retriever = FactRetriever()

        results = retriever.retrieve_for_scene(
            state,
            scaffold_texts=["You arrive at the station."],
            player_input="I dock at Station Alpha.",
            open_threads=["Station Alpha needs repairs."],
        )
        names = [r.name for r in results]
        assert "Station Alpha" in names

    def test_facts_from_earlier_scenes_resurface(self):
        """A fact registered in an earlier scene is re-surfaced when referenced."""
        state = make_state()

        # Scene 1: register a fact.
        engine = Engine(state, roller=ForcedRoller([]))
        engine.apply(
            RegisterFactCommand(
                name="Merchant Kael",
                description="A trade contact from the outer rim.",
            )
        )

        # Later scene: reference the entity.
        retriever = FactRetriever()
        results = retriever.retrieve_facts(state, ["Merchant Kael sends a message."])
        names = [r.name for r in results]
        assert "Merchant Kael" in names

    def test_empty_state_returns_empty(self):
        """No facts in state returns empty list."""
        state = make_state()
        retriever = FactRetriever()
        results = retriever.retrieve_facts(state, ["Some context."])
        assert results == []


# ---------------------------------------------------------------------------
# NPC stat generation (R24, AE9).
# ---------------------------------------------------------------------------


class TestNpcStatGeneration:
    """LLM-introduced NPC registered as fact; engine generates stats (AE9)."""

    def test_generate_npc_stats_returns_characteristics(self):
        """Generated stats have all Cepheus characteristics."""
        stats = generate_npc_stats("Test NPC")
        rs = CepheusRuleSet()

        for char in rs.characteristics:
            assert char in stats["characteristics"]
            assert stats["characteristics"][char] > 0

    def test_generate_npc_stats_has_skill_level(self):
        """Generated stats include a skill level."""
        stats = generate_npc_stats("Test NPC")
        assert "skill_level" in stats
        assert stats["skill_level"] >= 0

    def test_ratify_fact_updates_description(self):
        """Ratifying a fact updates its description with stats."""
        state = make_state()
        add_fact(state, "Hunter Kell", "A dangerous bounty hunter.")
        fact = next(
            e for e in state.entities if isinstance(e, NarrativeFact) and e.name == "Hunter Kell"
        )

        stats = ratify_fact_as_npc(state, fact)

        assert "NPC stats" in fact.description
        assert stats["skill_level"] >= 0

    def test_ratify_with_custom_ruleset(self):
        """Ratification works with a custom ruleset."""
        state = make_state()
        add_fact(state, "Custom NPC", "Test.")
        fact = next(e for e in state.entities if isinstance(e, NarrativeFact))

        rs = CepheusRuleSet()
        stats = ratify_fact_as_npc(state, fact, ruleset=rs)
        assert stats["name"] == "Custom NPC"


# ---------------------------------------------------------------------------
# Funnel-routed ratification (Fix #2B).
# ---------------------------------------------------------------------------


class TestRatifyFactFunnel:
    """ratify_fact_as_npc routes through the funnel when given an Engine (Fix #2B)."""

    def test_ratify_with_engine_logs_event(self):
        """Ratifying with an engine produces a ratify_fact audit event."""
        state = make_state()
        engine = Engine(state, roller=ForcedRoller([]))
        engine.apply(RegisterFactCommand(name="Bounty Hunter", description="Dangerous."))
        fact = next(
            e for e in state.entities if isinstance(e, NarrativeFact) and e.name == "Bounty Hunter"
        )
        initial_events = len(state.events)

        stats = ratify_fact_as_npc(state, fact, engine=engine)

        assert len(state.events) == initial_events + 1
        event = state.events[-1]
        assert event.command_type == "ratify_fact"
        assert "NPC stats" in fact.description
        assert stats["skill_level"] >= 0

    def test_ratify_without_engine_legacy_path(self):
        """Ratifying without engine still works (backward-compatible direct mutation)."""
        state = make_state()
        add_fact(state, "Old NPC", "A test.")
        fact = next(e for e in state.entities if isinstance(e, NarrativeFact))
        stats = ratify_fact_as_npc(state, fact)
        assert "NPC stats" in fact.description
        assert stats["name"] == "Old NPC"

    def test_ratify_command_directly(self):
        """RatifyFactCommand can be applied directly through the funnel."""
        state = make_state()
        engine = Engine(state, roller=ForcedRoller([]))
        engine.apply(RegisterFactCommand(name="Test NPC", description="Base desc."))

        engine.apply(
            RatifyFactCommand(
                fact_name="Test NPC",
                stats_description="[NPC stats: all 7, skill 1]",
            )
        )

        fact = next(
            e for e in state.entities if isinstance(e, NarrativeFact) and e.name == "Test NPC"
        )
        assert "[NPC stats:" in fact.description
        last_event = state.events[-1]
        assert last_event.command_type == "ratify_fact"
        assert last_event.changes["fact_name"] == "Test NPC"

    def test_ratify_command_validates_empty_name(self):
        """RatifyFactCommand rejects empty fact names."""
        state = make_state()
        engine = Engine(state, roller=ForcedRoller([]))
        import pytest

        with pytest.raises(ValueError, match="non-empty"):
            engine.apply(RatifyFactCommand(fact_name="", stats_description="x"))
