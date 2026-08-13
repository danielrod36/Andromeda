"""Beat facts — the engine-owned "what just happened" for narration (M0.4).

After each action, the events it produced are translated into human-readable
mechanical facts. Facts name OUTCOMES (check tiers, injuries, mission
endings) and never expose pips, RNG, or audit internals — the narrator
weaves them into prose but cannot contradict them (the trust boundary made
textual).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.engine.audit import Event

#: Command types that never produce narration facts: flags, pending-state
#: markers, narration/advice records (they are prose/meta, not mechanics).
_SKIP_COMMANDS: frozenset[str] = frozenset(
    {
        "set_flag",
        "set_pending_freetext",
        "set_pending_hook",
        "log_narration",
        "log_mission",
        "record_advice",
        "record_proposal",
        "record_narration",
        "record_story_direction",
        "flag_degradation",
        "next_mission_id",
        "oracle_roll",
        "mission_table_roll",
    }
)

_TIER_PHRASES: dict[str, str] = {
    "strong_hit": "succeeded brilliantly",
    "weak_hit": "succeeded, but with a complication",
    "miss": "failed",
}


def build_beat_facts(events: list[Event]) -> list[str]:
    """Translate an event slice into LLM-safe mechanical facts (M0.4).

    One fact per meaningful event, in order. Empty slice → empty list.
    """
    facts: list[str] = []
    for event in events:
        ct = event.command_type
        c = event.changes
        if ct in _SKIP_COMMANDS:
            continue
        if ct == "scene_check":
            tier = _TIER_PHRASES.get(c.get("quality", ""), c.get("quality", "resolved"))
            facts.append(
                f"The {c.get('skill', 'unknown')} check {tier} (margin {c.get('effect', 0):+d})."
            )
        elif ct == "complication_roll":
            facts.append(f"The situation shifted: {c.get('result_text', '')}")
        elif ct == "npc_reaction_roll":
            continue  # the disposition lands on the NPC record; no prose fact
        elif ct == "create_npc_record":
            if not c.get("already_existed"):
                facts.append(
                    f"{c.get('name', 'Someone')} stepped out of the background — the story can now test them."
                )
        elif ct == "add_injury":
            facts.append(
                f"You suffered {c.get('name', 'an injury')} ({c.get('severity', 'moderate')})."
            )
        elif ct == "register_fact":
            facts.append(f"New element in the story: {c.get('name', '')}.")
        elif ct == "ratify_fact":
            continue  # paired with create_npc_record; one fact is enough
        elif ct == "resolve_mission":
            facts.append(f"The mission ended in {c.get('ending', 'unknown')}.")
        elif ct == "set_mission_state":
            mission = c.get("mission_data") or {}
            hook = mission.get("hook") or {}
            if hook.get("objective"):
                facts.append(
                    f"You took the job: {hook.get('objective')} "
                    f"(patron: {hook.get('patron', 'unknown')}; reward: {hook.get('reward', 'unknown')})."
                )
        elif ct == "set_character_dead":
            reason = c.get("reason") or "your injuries"
            facts.append(f"You died — {reason}.")
        elif ct == "add_open_thread":
            facts.append(f"A new thread opened: {c.get('thread', '')}.")
        elif ct == "remove_open_thread":
            facts.append(f"A thread closed: {c.get('thread', '')}.")
        # Unknown command types produce no fact — beats stay honest about
        # what the engine actually did rather than guessing.
    return facts


# ---------------------------------------------------------------------------
# Narrator memory (M0.5).
# ---------------------------------------------------------------------------


@dataclass
class NarratorMemory:
    """Recent shipped prose + standing player directions (M0.5).

    Derived from the event log (never from a side channel), so a restored
    session remembers exactly what a never-saved session would.
    """

    prose: list[str] = field(default_factory=list)
    directions: list[str] = field(default_factory=list)


def narrator_memory(
    events: list[Event],
    *,
    prose_limit: int = 6,
    direction_limit: int = 3,
) -> NarratorMemory:
    """Scan the event log for narration records and story directions (M0.5).

    Returns the most recent ``prose_limit`` shipped-prose texts and
    ``direction_limit`` player directions, oldest-first within each list.
    """
    prose = [e.changes["text"] for e in events if e.command_type == "record_narration"]
    directions = [e.changes["text"] for e in events if e.command_type == "record_story_direction"]
    return NarratorMemory(
        prose=prose[-prose_limit:],
        directions=directions[-direction_limit:],
    )
