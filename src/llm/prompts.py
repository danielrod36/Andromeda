"""System prompt and prompt templates for the LLM narration agent (U5).

These templates assemble the system prompt and user-turn prompts from the
curated state view and mechanical events (R11, R19). They never expose raw
dice, RNG state, or audit internals.
"""

from __future__ import annotations

import json

from src.llm.state_view import CuratedView

# ---------------------------------------------------------------------------
# System prompt.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the narration engine for Andromeda, a deterministic-rules \
CYOA RPG. Your role is to weave engaging backstory and narrative prose that \
faithfully reflects the mechanical events provided to you.

## Core rules

1. **Faithfulness above all.** Every mechanical fact (skill gained, \
characteristic changed, term survived or failed, promotion, aging) must be \
referenced accurately in your prose. Never invent outcomes that contradict \
the events you are given.

2. **You cannot alter mechanics.** The mechanical results (dice rolls, \
success/failure, skill gains) are determined by the engine. Your job is \
purely to narrate them in an engaging way. Never attempt to change a result.

3. **Consistent voice.** Maintain a consistent second-person narrative voice \
("You enlisted...", "Your skills grew..."). Keep the tone adventurous and \
grounded in the Cepheus Engine setting (space opera / sci-fi).

4. **No meta-references.** Do not mention dice, rolls, target numbers, or \
game mechanics in the prose. Translate mechanical outcomes into in-world \
narrative.

5. **Concise but vivid.** Each term's narration should be 2-4 sentences — \
enough to paint a picture without belaboring the point.
"""


# ---------------------------------------------------------------------------
# Prompt builders.
# ---------------------------------------------------------------------------


def build_lifepath_prompt(
    view: CuratedView,
    term_facts: list[str],
) -> str:
    """Build the user-turn prompt for lifepath narration (R11).

    Parameters:
        view: The curated state view (R2) — safe subset only.
        term_facts: Mechanical facts for this term as human-readable strings.
            These are the engine's authoritative outcomes; the LLM must
            reference them faithfully but never contradict them.

    The prompt includes the curated view (character sheet, recent log) and
    the term facts. It never includes raw dice values, RNG state, or audit
    internals.
    """
    view_json = json.dumps(view.model_dump(), indent=2)
    facts_block = "\n".join(f"  - {f}" for f in term_facts)

    return (
        f"## Character State\n"
        f"{view_json}\n\n"
        f"## Mechanical Events for This Term\n"
        f"{facts_block}\n\n"
        f"Write engaging backstory prose (2-4 sentences, second person) "
        f"that faithfully narrates the events above. "
        f"Do not contradict any mechanical outcome."
    )


def build_term_facts(term_result) -> list[str]:
    """Extract human-readable mechanical facts from a :class:`TermResult`.

    These facts are the authoritative events the LLM must reference (R11).
    They convey *outcomes* (survived, promoted, gained skill X) without
    exposing raw dice values or target numbers.

    Parameters:
        term_result: A :class:`src.engine.lifepath.TermResult` instance.
    """
    facts: list[str] = []

    # Career and term.
    facts.append(
        f"Term {term_result.term_number}: served as a "
        f"{term_result.career_name} (age {term_result.age_before}"
        f" to {term_result.age_after})."
    )

    # Survival.
    if term_result.died:
        facts.append("You did not survive the term — killed in the line of duty.")
        return facts  # No further events after death.
    if term_result.mishap:
        facts.append("A serious mishap ended your career this term.")
    else:
        facts.append("You survived the term without major incident.")

    # Advancement.
    if term_result.advancement_success:
        rank_info = ""
        if term_result.rank_title:
            rank_info = f" (rank: {term_result.rank_title})"
        facts.append(f"You were promoted{rank_info}.")
    else:
        facts.append("You were not promoted this term.")

    # Skill gains.
    for gain in term_result.skill_gains:
        if gain.gain_type == "skill":
            facts.append(f"You developed the skill: {gain.gain_name}.")
        else:
            facts.append(f"Your {gain.gain_name} characteristic improved (+1).")

    # Aging.
    if term_result.aging_reductions:
        parts = [f"{stat} reduced by {amt}" for stat, amt in term_result.aging_reductions.items()]
        facts.append(f"Aging took its toll: {', '.join(parts)}.")

    return facts


def build_full_lifepath_prompt(
    view: CuratedView,
    all_term_facts: list[list[str]],
) -> str:
    """Build a prompt for narrating the entire lifepath at once.

    Used for the full-lifepath narration mode (AE12). Each inner list is
    the facts for one term.
    """
    view_json = json.dumps(view.model_dump(), indent=2)

    sections: list[str] = []
    for i, term_facts in enumerate(all_term_facts, 1):
        facts_block = "\n".join(f"    - {f}" for f in term_facts)
        sections.append(f"  Term {i}:\n{facts_block}")

    all_facts = "\n".join(sections)

    return (
        f"## Character State\n"
        f"{view_json}\n\n"
        f"## Full Lifepath Events\n"
        f"{all_facts}\n\n"
        f"Write a cohesive backstory (one paragraph per term, "
        f"second person) that faithfully narrates the entire lifepath. "
        f"Maintain a consistent voice throughout. "
        f"Do not contradict any mechanical outcome."
    )


# ---------------------------------------------------------------------------
# Scene narration + free-text classification prompts (R14, AE5 — Task 24).
# ---------------------------------------------------------------------------


def build_scene_prompt(
    view: CuratedView,
    scaffold,
    outcome_facts: list[str],
) -> str:
    """Build the user-turn prompt for scene narration (R14).

    Parameters:
        view: The curated state view for this scene (R2, R25).
        scaffold: :class:`SceneScaffold` with focus, situation, NPC hints.
        outcome_facts: Mechanical outcome facts as human-readable strings.
    """
    view_json = json.dumps(view.model_dump(), indent=2)
    facts_block = "\n".join(f"  - {f}" for f in outcome_facts)

    npc_hint = getattr(scaffold, "npc_hint", None)
    npc_line = f"\nNPC: {npc_hint}" if npc_hint else ""

    return (
        f"## Character State\n"
        f"{view_json}\n\n"
        f"## Scene Context\n"
        f"Focus: {scaffold.focus} — {scaffold.focus_description}\n"
        f"Situation: {scaffold.situation}{npc_line}\n\n"
        f"## Scene Outcome Facts\n"
        f"{facts_block}\n\n"
        f"Write engaging second-person narration (2-4 sentences) for this "
        f"scene. Faithfully reflect the mechanical outcomes above. "
        f"Do not mention dice or game mechanics."
    )


def build_classification_prompt(
    text: str,
    scaffold,
    view: CuratedView,
    valid_skill_ids: set[str],
) -> str:
    """Build the user-turn prompt for free-text classification (R14, AE5).

    The LLM must choose a ``skill_id`` from the enumerated valid set and a
    ``difficulty`` from the Cepheus Engine difficulty ladder. Validators on
    :class:`FreeTextCheck` enforce both; the adapter validates ``skill_id``
    membership post-call.
    """
    view_json = json.dumps(view.model_dump(), indent=2)
    skills_block = "\n".join(f"  - {s}" for s in sorted(valid_skill_ids))

    return (
        f"## Character State\n"
        f"{view_json}\n\n"
        f"## Scene Context\n"
        f"Focus: {scaffold.focus} — {scaffold.focus_description}\n"
        f"Situation: {scaffold.situation}\n\n"
        f"## Player Free-Text Input\n"
        f'"{text}"\n\n'
        f"## Valid Skill IDs\n"
        f"{skills_block}\n\n"
        f"Interpret the player's input as an engine-known check. Choose:\n"
        f"- skill_id: exactly one from the Valid Skill IDs list above.\n"
        f"- difficulty: one of easy, routine, average, difficult, "
        f"very_difficult, formidable.\n"
        f"- label: a short player-facing description of the action.\n"
        f"- characteristic: the most fitting characteristic (STR, DEX, END, "
        f"INT, EDU, SOC).\n"
        f"- life_threatening: true if the action involves mortal combat."
    )


def build_chapter_summary_prompt(
    mission_record: dict,
    log_entries: list[str],
    view: CuratedView,
) -> str:
    """Build the user-turn prompt for an LLM chapter summary (R19, AE16).

    The summary must be faithful prose — no dice notation, modifiers, raw stat
    names, or target numbers (the engine's :class:`SummaryValidator` enforces
    this and falls back to the template on violation).
    """
    view_json = json.dumps(view.model_dump(), indent=2)
    beats = "\n".join(f"  - {line}" for line in log_entries[-6:])
    hook = mission_record.get("hook", {})
    if isinstance(hook, dict):
        hook_text = hook.get("objective") or hook.get("description") or "an unknown job"
    else:
        hook_text = str(hook) if hook else "an unknown job"
    ending = mission_record.get("ending", "unknown")
    scenes = mission_record.get("scenes_completed", 0)

    return (
        f"## Character & Campaign State\n"
        f"{view_json}\n\n"
        f"## Completed Mission\n"
        f"Objective: {hook_text}\n"
        f"Scenes played: {scenes}\n"
        f"Ending: {ending}\n\n"
        f"## Recent Narrative Log\n"
        f"{beats}\n\n"
        f"Write a concise chapter summary (2-4 sentences, past tense, "
        f"third person) of how this mission went for the character. "
        f"Reference named people, places, and outcomes consistently with the "
        f"state above. Do NOT mention dice, rolls, modifiers, stats, target "
        f"numbers, or any game mechanics — write as if recounting a story."
    )
