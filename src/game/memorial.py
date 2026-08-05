"""Death memorial and audit-derived obituary (U12, R14, AE4).

Derives a structured obituary from the event log — career history, age,
missions completed/abandoned, notable rolls (natural 2s and 12s from
``audit_rolls``) — with a template epitaph and mode-appropriate restart.

Terminal status rides the existing ``character.alive`` field (set through
the funnel by ``SetCharacterDeadCommand``): no new flag, no schema change.
The U6 phase predicate routes dead saves to the memorial route in the web
shell; the TUI's existing dead-character game-over handling is unchanged
(KTD-8).

Only Ironman death sets ``alive = False`` (Checkpoint rewinds with
``alive`` still True; Narrative applies an injury with ``alive`` still
True), so only Ironman saves reach the memorial as shipped.  The
Checkpoint and Narrative interstitial branches below are forward-looking
— they will be shown when a transient post-death interstitial screen is
added (planned post-U12), and are exercised today via the test harness:

- Checkpoint: names the rewind point (the scene the state was restored to).
- Narrative: lists the applied injury (the lasting consequence).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.engine.audit import EventKind, audit_rolls
from src.engine.state import GameState, Injury

# ---------------------------------------------------------------------------
# Structured memorial data.
# ---------------------------------------------------------------------------


@dataclass
class NotableRoll:
    """A notable dice roll from the audit log (U12).

    Natural 2s (snake eyes on 2D6) and natural 12s (boxcars) are called out
    as memorable moments — the crits and fumbles that define a character's
    story.
    """

    seq: int
    values: list[int]
    total: int
    roll_type: str  # "critical" (natural 12) or "fumble" (natural 2)
    description: str


@dataclass
class MissionRecord:
    """A completed mission's summary for the obituary (U12)."""

    objective: str
    ending: str  # success | failure | abandonment
    scenes: int


@dataclass
class MemorialData:
    """Structured data for the memorial interstitial (U12, R14).

    All fields are derived from canonical state — the event log, character
    sheet, and mission records. No LLM is needed for the template floor;
    the LLM polish path (same injection pattern as chapter summaries) is
    optional.
    """

    character_name: str = ""
    career: str = ""
    terms: int = 0
    age: int = 18
    death_mode: str = "ironman"
    death_reason: str = ""
    missions: list[MissionRecord] = field(default_factory=list)
    notable_rolls: list[NotableRoll] = field(default_factory=list)
    chapter_summaries: list[str] = field(default_factory=list)
    injuries: list[str] = field(default_factory=list)
    interstitial_text: str = ""
    interstitial_mode: str = ""  # "checkpoint" | "narrative" | ""


# ---------------------------------------------------------------------------
# Data extraction.
# ---------------------------------------------------------------------------


def build_memorial(state: GameState) -> MemorialData:
    """Extract memorial data from canonical state (U12, R14).

    Reads the event log, character sheet, mission records, and entity list
    to assemble everything the memorial template needs. Pure data extraction
    — no mutations, no LLM calls.
    """
    char = state.character
    data = MemorialData(
        character_name=char.name or "the traveler",
        career=char.career or "—",
        terms=char.terms,
        age=char.age,
        death_mode=state.campaign.death_mode,
    )

    # --- Death reason from the set_character_dead event ---
    for event in reversed(state.events):
        if event.command_type == "set_character_dead":
            data.death_reason = event.changes.get("reason", "") or event.description
            break

    # --- Missions ---
    for mission_dict in state.completed_missions:
        hook = mission_dict.get("hook", {})
        if isinstance(hook, dict):
            objective = hook.get("objective") or hook.get("description") or "an unknown job"
        else:
            objective = str(hook) if hook else "an unknown job"
        ending = mission_dict.get("ending", "unknown")
        scenes = mission_dict.get("scenes_completed", 0)
        data.missions.append(MissionRecord(objective=objective, ending=ending, scenes=scenes))

    # --- Notable rolls (natural 2s and 12s) ---
    for event in audit_rolls(state.events):
        if event.roll is None:
            continue
        roll = event.roll
        # Only flag 2D6 rolls (the Cepheus Engine standard).
        if roll.ndice != 2 or roll.sides != 6:
            continue
        dice_sum = sum(roll.rolls)
        if dice_sum == 2:
            data.notable_rolls.append(
                NotableRoll(
                    seq=event.seq,
                    values=list(roll.rolls),
                    total=roll.total,
                    roll_type="fumble",
                    description=event.description,
                )
            )
        elif dice_sum == 12:
            data.notable_rolls.append(
                NotableRoll(
                    seq=event.seq,
                    values=list(roll.rolls),
                    total=roll.total,
                    roll_type="critical",
                    description=event.description,
                )
            )

    # --- Chapter summaries ---
    data.chapter_summaries = list(state.chapter_summaries)

    # --- Injuries (for narrative mode interstitial) ---
    for entity in state.entities:
        if isinstance(entity, Injury):
            data.injuries.append(f"{entity.name} ({entity.severity})")

    # --- Mode-appropriate interstitial ---
    data.interstitial_mode = state.campaign.death_mode
    if state.campaign.death_mode == "checkpoint":
        # Find the last REWIND_APPLIED boundary.
        rewind_events = [e for e in state.events if e.kind == EventKind.REWIND_APPLIED]
        if rewind_events:
            last_rewind = rewind_events[-1]
            abandoned = last_rewind.changes.get("abandoned_branch_events", 0)
            data.interstitial_text = (
                f"State rewound to scene start. "
                f"{abandoned} event(s) in the abandoned branch remain in the audit log."
            )
        else:
            data.interstitial_text = "State rewound to scene start."
    elif state.campaign.death_mode == "narrative":
        if data.injuries:
            data.interstitial_text = (
                f"Lasting consequence applied: {', '.join(data.injuries)}. "
                f"The character survived and play continues."
            )
        else:
            data.interstitial_text = "A lasting consequence was applied. Play continues."

    return data


# ---------------------------------------------------------------------------
# Template obituary.
# ---------------------------------------------------------------------------


def build_obituary(data: MemorialData) -> list[str]:
    """Build a template obituary from memorial data (U12, R14).

    Returns a list of lines forming the obituary text. The template is the
    deterministic floor — always available, no LLM needed. Each line is a
    self-contained sentence or data point for flexible rendering.
    """
    lines: list[str] = []

    # --- Epitaph line ---
    name = data.character_name
    if data.death_mode == "ironman":
        lines.append(
            f"In memoriam: {name}, {data.career}, "
            f"who fell after {data.terms} term{'s' if data.terms != 1 else ''} of service "
            f"at age {data.age}."
        )
    else:
        lines.append(
            f"In memoriam: {name}, {data.career}, "
            f"{data.terms} term{'s' if data.terms != 1 else ''} of service, "
            f"age {data.age}."
        )

    # --- Death cause ---
    if data.death_reason:
        lines.append(f"Cause of death: {data.death_reason}")

    # --- Mission summary ---
    if data.missions:
        successes = sum(1 for m in data.missions if m.ending == "success")
        failures = sum(1 for m in data.missions if m.ending == "failure")
        abandoned = sum(1 for m in data.missions if m.ending == "abandonment")
        parts: list[str] = []
        if successes:
            parts.append(f"{successes} completed")
        if failures:
            parts.append(f"{failures} failed")
        if abandoned:
            parts.append(f"{abandoned} abandoned")
        if parts:
            lines.append(f"Missions: {', '.join(parts)}.")

        # Detail notable missions (up to 3).
        for mission in data.missions[:3]:
            lines.append(f"  • {mission.objective} — {mission.ending}")
    else:
        lines.append("No missions completed.")

    # --- Notable rolls ---
    if data.notable_rolls:
        crit_count = sum(1 for r in data.notable_rolls if r.roll_type == "critical")
        fumble_count = sum(1 for r in data.notable_rolls if r.roll_type == "fumble")
        roll_parts: list[str] = []
        if crit_count:
            roll_parts.append(f"{crit_count} critical{'s' if crit_count != 1 else ''} (natural 12)")
        if fumble_count:
            roll_parts.append(
                f"{fumble_count} fumble{'s' if fumble_count != 1 else ''} (natural 2)"
            )
        lines.append(f"Notable rolls: {', '.join(roll_parts)}.")

    return lines


def build_memorial_lines(state: GameState) -> list[str]:
    """Convenience: build the full obituary lines from state (U12).

    Combines :func:`build_memorial` and :func:`build_obituary` in one call
    for template rendering.
    """
    data = build_memorial(state)
    return build_obituary(data)
