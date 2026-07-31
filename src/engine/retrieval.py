"""Narrative fact retrieval: entity-based matching + recency-ranked slice (U7).

When assembling the curated view, the retrieval layer re-surfaces narrative
facts whose entity names appear in the current scene's oracle scaffold,
player input, or active threads (R25). A capped recency-ranked slice of the
fact registry is always included so the LLM can reference existing entities
by name.

LLM-introduced NPCs/places/items registered as narrative facts in canonical
state; mechanically inert until any engine check targets them, at which
point the engine generates stats from rule-set templates (R24, AE9).
"""

from __future__ import annotations

import re

from src.engine.commands import Engine
from src.engine.scene import RatifyFactCommand
from src.engine.state import GameState, NarrativeFact

# ---------------------------------------------------------------------------
# Configuration.
# ---------------------------------------------------------------------------

#: Maximum number of facts in the recency slice.
DEFAULT_RECENCY_CAP: int = 10

#: Maximum number of entity-matched facts to include.
DEFAULT_MATCH_CAP: int = 5


# ---------------------------------------------------------------------------
# Fact retriever.
# ---------------------------------------------------------------------------


class FactRetriever:
    """Retrieves relevant narrative facts for curated view assembly (R25).

    Two mechanisms:

    1. **Entity-based matching**: facts whose entity names appear in the
       current scene's scaffold text, player input, or open threads are
       re-injected into the curated view.
    2. **Recency-ranked slice**: a capped slice of the most recent facts
       is always included so the LLM can reference existing entities.
    """

    def __init__(
        self,
        recency_cap: int = DEFAULT_RECENCY_CAP,
        match_cap: int = DEFAULT_MATCH_CAP,
    ) -> None:
        self.recency_cap = recency_cap
        self.match_cap = match_cap

    # ------------------------------------------------------------------
    # Public API.
    # ------------------------------------------------------------------

    def retrieve_facts(
        self,
        state: GameState,
        context_texts: list[str],
    ) -> list[NarrativeFact]:
        """Retrieve relevant narrative facts for the given context.

        Parameters:
            state: The canonical game state.
            context_texts: Text strings to match against (scaffold text,
                player input, open threads, etc.).

        Returns:
            A deduplicated list of relevant narrative facts, with entity-
            matched facts first (up to ``match_cap``), then recency-slice
            facts (up to ``recency_cap`` total).
        """
        all_facts = self._get_all_facts(state)
        if not all_facts:
            return []

        # 1. Entity-based matching.
        matched = self._entity_match(all_facts, context_texts)

        # 2. Recency-ranked slice (most recent facts).
        recent = self._recency_slice(all_facts)

        # 3. Merge: matched first, then fill with recent, deduplicated.
        result: list[NarrativeFact] = []
        seen_names: set[str] = set()

        for fact in matched[: self.match_cap]:
            if fact.name not in seen_names:
                result.append(fact)
                seen_names.add(fact.name)

        for fact in recent:
            if len(result) >= self.recency_cap:
                break
            if fact.name not in seen_names:
                result.append(fact)
                seen_names.add(fact.name)

        return result

    def retrieve_for_scene(
        self,
        state: GameState,
        scaffold_texts: list[str],
        player_input: str | None = None,
        open_threads: list[str] | None = None,
    ) -> list[NarrativeFact]:
        """Convenience method: retrieve facts for a scene context.

        Combines scaffold text, player input, and open threads into the
        context for entity matching.
        """
        texts = list(scaffold_texts)
        if player_input:
            texts.append(player_input)
        if open_threads:
            texts.extend(open_threads)
        return self.retrieve_facts(state, texts)

    # ------------------------------------------------------------------
    # Internal helpers.
    # ------------------------------------------------------------------

    @staticmethod
    def _get_all_facts(state: GameState) -> list[NarrativeFact]:
        """Extract all NarrativeFact entities from state, preserving order."""
        return [e for e in state.entities if isinstance(e, NarrativeFact)]

    def _entity_match(
        self,
        facts: list[NarrativeFact],
        context_texts: list[str],
    ) -> list[NarrativeFact]:
        """Match facts whose names appear in any context text.

        Matching is case-insensitive and word-boundary aware so "Dock
        Officer" matches "dock officer" but not "dockofficer".
        """
        if not context_texts:
            return []

        # Combine all context into one lowercase string for searching.
        combined = " ".join(context_texts).lower()

        matched: list[NarrativeFact] = []
        for fact in facts:
            # Match the fact name as a substring (case-insensitive).
            # Use word-boundary-ish matching: the name should appear as
            # a distinct phrase, not as a substring of a larger word.
            name_lower = fact.name.lower()
            if len(name_lower) <= 3:
                # Short names: require exact word match to avoid false hits.
                pattern = r"\b" + re.escape(name_lower) + r"\b"
                if re.search(pattern, combined):
                    matched.append(fact)
            else:
                # Longer names: substring match is sufficient.
                if name_lower in combined:
                    matched.append(fact)

        return matched

    def _recency_slice(self, facts: list[NarrativeFact]) -> list[NarrativeFact]:
        """Return the most recent facts (last N in the entity list).

        Entities are appended in order, so the last N facts are the most
        recently registered.
        """
        return list(reversed(facts[-self.recency_cap :]))


# ---------------------------------------------------------------------------
# NPC stat generation (R24, AE9).
# ---------------------------------------------------------------------------


def generate_npc_stats(
    name: str,
    ruleset=None,
) -> dict:
    """Generate mechanical stats for an NPC from rule-set templates (R24, AE9).

    Called when a check targets an LLM-introduced NPC that was previously
    registered as a narrative fact. The NPC is mechanically inert until this
    function generates stats.

    Returns a dict with characteristics and skill level suitable for
    computing DMs in opposed checks.
    """
    from src.rulesets.cepheus import CepheusRuleSet

    rs = ruleset or CepheusRuleSet()

    # Standard NPC stats: average characteristics (7 across the board).
    characteristics = dict.fromkeys(rs.characteristics, 7)
    # Skill level 1 for a competent NPC.
    skill_level = 1

    return {
        "name": name,
        "characteristics": characteristics,
        "skill_level": skill_level,
    }


def ratify_fact_as_npc(
    fact: NarrativeFact,
    engine: Engine,
    ruleset=None,
) -> dict:
    """Ratify a narrative fact as an NPC with mechanical stats (AE9).

    The fact remains in the entity list; this function returns the generated
    stats and marks the fact as mechanically active by updating its
    description via the command funnel. The engine uses the returned stats
    when checks target this NPC.

    The description update is always routed through the command funnel via
    :class:`RatifyFactCommand`, producing an audit event and **logging the
    ratification** (R24/AE9). The ``engine`` parameter is required — there
    is no direct-mutation path.

    Note: stat generation is math-neutral for now. Stats are recorded and
    logged per AE9; opposed-check math using these stats is post-v1.
    """
    stats = generate_npc_stats(fact.name, ruleset)
    stats_description = (
        f"[NPC stats: all characteristics {stats['characteristics'].get('STR', 7)}, "
        f"skill level {stats['skill_level']}]"
    )
    engine.apply(
        RatifyFactCommand(
            fact_name=fact.name,
            stats_description=stats_description,
        )
    )
    return stats
