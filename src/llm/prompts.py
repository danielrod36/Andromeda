"""System prompt and prompt templates for the LLM narration agent (U5).

These templates assemble the system prompt and user-turn prompts from the
curated state view and mechanical events (R11, R19). They never expose raw
dice, RNG state, or audit internals.
"""

from __future__ import annotations

import json

from src.engine.lifepath_choices import ChoicePointView
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


ADVISOR_SYSTEM_PROMPT = """\
You are the Advisor for Andromeda character creation, a deterministic-rules \
CYOA RPG. You recommend ONE option from an engine-enumerated candidate list.

## Core rules

1. **Candidates only.** Select an option_id from the list in the prompt. \
Never invent options or mechanics.

2. **Ground every claim.** Your rationale must cite the listed previews and \
odds lines — they are the engine's authoritative mechanics.

3. **Unavailable means unavailable.** Options marked UNAVAILABLE cannot be \
selected.

4. **Honest trade-offs.** Name up to 2 alternatives with a concrete reason \
each was not chosen.
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


def build_steered_scene_prompt(
    view: CuratedView,
    scaffold,
    outcome_facts: list[str],
    steering_text: str,
) -> str:
    """Build a steered re-narration prompt for guided retry (U15, R17, AE5).

    Identical to :func:`build_scene_prompt` but appends the player's steering
    text — natural-language direction for the narration tone, focus, or
    style. The mechanical outcomes are locked (they're the same facts from
    the already-resolved check); only the prose changes. The adapter
    validates output like any narration.
    """
    base_prompt = build_scene_prompt(view, scaffold, outcome_facts)
    return (
        f"{base_prompt}\n\n"
        f"## Player Steering Direction\n"
        f'"{steering_text}"\n\n'
        f"Re-narrate the scene above, incorporating the player's direction "
        f"for tone, focus, or style. The mechanical outcomes must not change "
        f"— only the prose. Do not contradict any outcome fact."
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
        f"second person) of how this mission went for the character. "
        f"Reference named people, places, and outcomes consistently with the "
        f"state above. Do NOT mention dice, rolls, modifiers, stats, target "
        f"numbers, or any game mechanics — write as if recounting a story."
    )


def build_recap_prompt(
    view: CuratedView,
    template_lines: list[str],
    open_threads: list[str],
) -> str:
    """Build the user-turn prompt for an LLM-polished story recap (U11, R13).

    The recap is ≤5 lines of cause-and-effect prose that helps a returning
    player remember where they are. The template lines are injected as the
    deterministic floor — the LLM is told to polish, not replace, the facts.
    The engine's :class:`SummaryValidator` guards against mechanical claims;
    the caller enforces the 5-line cap in assembly.

    Parameters:
        view: The curated state view (R2) — safe subset only.
        template_lines: The deterministic template recap (the validated floor).
        open_threads: Unresolved narrative threads from state.
    """
    view_json = json.dumps(view.model_dump(), indent=2)
    template_block = "\n".join(f"  - {line}" for line in template_lines)
    threads_block = "\n".join(f"  - {t}" for t in open_threads) if open_threads else "  (none)"

    return (
        f"## Character & Campaign State\n"
        f"{view_json}\n\n"
        f"## Story Beats (deterministic floor)\n"
        f"{template_block}\n\n"
        f"## Open Threads\n"
        f"{threads_block}\n\n"
        f"Write a story-so-far recap for a returning player (≤5 lines, "
        f"second person, cause-and-effect). The beats above are the "
        f"deterministic facts — polish them into flowing prose, but do NOT "
        f"contradict or omit any of them. Do NOT mention dice, rolls, "
        f"modifiers, stats, target numbers, or any game mechanics."
    )


# ---------------------------------------------------------------------------
# Advisor prompt (P4.T2, ADR A3).
# ---------------------------------------------------------------------------


def build_advisor_prompt(choice: ChoicePointView, rules_summary: str) -> str:
    """Build the user-turn prompt for an Advisor suggestion (P4.T2, ADR A3).

    Every option is presented verbatim (option_id, label, description,
    preview lines, odds_line) so the rationale is grounded in engine-computed
    facts. Dimmed options are shown but marked UNAVAILABLE. The Advisor
    validates ``selected_option_id`` against the non-dimmed ids post-call.
    """
    blocks: list[str] = []
    for o in choice.options:
        lines = [f"  - option_id: {o.option_id}", f"    label: {o.label}"]
        if o.description:
            lines.append(f"    description: {o.description}")
        for p in o.preview:
            lines.append(f"    preview: {p}")
        if o.odds_line:
            lines.append(f"    odds: {o.odds_line}")
        if o.dimmed:
            lines.append(
                f"    UNAVAILABLE ({o.requirement or 'requirement not met'}) — do not select"
            )
        blocks.append("\n".join(lines))
    options_block = "\n".join(blocks)

    return (
        f"## Decision\n{choice.prompt}\n\n"
        f"## Options (engine-enumerated; ids verbatim)\n{options_block}\n\n"
        f"## Rules Summary (engine-derived)\n{rules_summary}\n\n"
        f"Select exactly ONE available option_id and respond with:\n"
        f'- choice_id: "{choice.choice_id}"\n'
        f"- selected_option_id: one of the available option_ids above.\n"
        f"- rationale: 2-4 sentences grounded in the listed previews and odds — quote them.\n"
        f"- alternatives: up to 2 other available option_ids, each with a one-sentence why_not.\n"
        f"Never select an UNAVAILABLE option. Do not invent mechanics not listed above."
    )
