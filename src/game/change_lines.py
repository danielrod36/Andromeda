"""Change-lines: inline mutation notices at the decision point (U14, R16).

Derives one-line change notices from Event change dicts so cause and effect
are visible alongside the receipt. Each mutation kind (skill gained, injury
applied, credits changed, thread opened/closed) produces a change-line with
an appropriate CSS class for positive/negative/neutral styling.

The change-lines render between the receipt and the narration in the spine,
making state changes visible at the moment they happen — not buried in the
audit log or character sheet.

Design: pure functions over the event log. No mutations, no state reads
beyond what the event carries in its ``changes`` dict.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.engine.audit import Event

#: CSS classes for positive/negative/neutral change styling.
CHANGE_POSITIVE = "change-positive"
CHANGE_NEGATIVE = "change-negative"
CHANGE_NEUTRAL = "change-neutral"


@dataclass
class ChangeLine:
    """A single change-line shown inline in the spine (U14).

    Attributes:
        text: Human-readable change notice.
        css_class: Styling class (positive/negative/neutral).
    """

    text: str
    css_class: str = CHANGE_NEUTRAL


# ---------------------------------------------------------------------------
# Per-command-type formatters.
# ---------------------------------------------------------------------------

# Each formatter takes the Event's ``changes`` dict and returns a ChangeLine
# (or None if the event shouldn't produce a change-line — e.g. noisy internal
# events).

_Formatter = object  # callable[[dict], ChangeLine | None]


def _fmt_skill_gained(changes: dict) -> ChangeLine | None:
    skill_id = changes.get("skill_id", "")
    level = changes.get("level", 0)
    if not skill_id:
        return None
    if level > 0:
        return ChangeLine(
            text=f"Skill improved: {skill_id} → level {level}",
            css_class=CHANGE_POSITIVE,
        )
    return ChangeLine(
        text=f"Skill gained: {skill_id}",
        css_class=CHANGE_POSITIVE,
    )


def _fmt_characteristic(changes: dict) -> ChangeLine | None:
    char = changes.get("characteristic", "")
    value = changes.get("value", 0)
    if not char:
        return None
    return ChangeLine(
        text=f"Characteristic set: {char} = {value}",
        css_class=CHANGE_NEUTRAL,
    )


def _fmt_characteristic_improved(changes: dict) -> ChangeLine | None:
    stat = changes.get("stat", "")
    outcome = changes.get("outcome", "")
    if not stat:
        return None
    return ChangeLine(
        text=f"Aging check ({stat}): {outcome}",
        css_class=CHANGE_NEGATIVE if "reduced" in str(outcome).lower() else CHANGE_NEUTRAL,
    )


def _fmt_register_fact(changes: dict) -> ChangeLine | None:
    name = changes.get("name", "")
    if not name:
        return None
    return ChangeLine(
        text=f"New fact established: {name}",
        css_class=CHANGE_POSITIVE,
    )


def _fmt_add_injury(changes: dict) -> ChangeLine | None:
    name = changes.get("name", "")
    severity = changes.get("severity", "")
    if not name:
        return None
    return ChangeLine(
        text=f"Injury sustained: {name} ({severity})",
        css_class=CHANGE_NEGATIVE,
    )


def _fmt_add_thread(changes: dict) -> ChangeLine | None:
    thread = changes.get("thread", "")
    if not thread:
        return None
    return ChangeLine(
        text=f"Thread opened: {thread}",
        css_class=CHANGE_NEUTRAL,
    )


def _fmt_remove_thread(changes: dict) -> ChangeLine | None:
    thread = changes.get("thread", "")
    if not thread:
        return None
    return ChangeLine(
        text=f"Thread resolved: {thread}",
        css_class=CHANGE_POSITIVE,
    )


def _fmt_character_dead(changes: dict) -> ChangeLine | None:
    reason = changes.get("reason", "")
    text = "Character died"
    if reason:
        text += f": {reason}"
    return ChangeLine(text=text, css_class=CHANGE_NEGATIVE)


def _fmt_mission_state(changes: dict) -> ChangeLine | None:
    ending = changes.get("ending", "")
    mission_id = changes.get("mission_id", "")
    if not ending:
        return None
    css = CHANGE_POSITIVE if ending == "success" else CHANGE_NEGATIVE
    label = mission_id or "mission"
    return ChangeLine(
        text=f"Mission resolved ({label}): {ending}",
        css_class=css,
    )


def _fmt_credits(changes: dict) -> ChangeLine | None:
    amount = changes.get("amount", 0)
    if amount == 0:
        return None
    sign = "+" if amount > 0 else ""
    css = CHANGE_POSITIVE if amount > 0 else CHANGE_NEGATIVE
    return ChangeLine(
        text=f"Credits: {sign}{amount}",
        css_class=css,
    )


def _fmt_promotion(changes: dict) -> ChangeLine | None:
    rank_title = changes.get("rank_title", "")
    rank = changes.get("rank", 0)
    if rank_title:
        return ChangeLine(
            text=f"Promoted: {rank_title}",
            css_class=CHANGE_POSITIVE,
        )
    if rank:
        return ChangeLine(
            text=f"Promoted to rank {rank}",
            css_class=CHANGE_POSITIVE,
        )
    return None


def _fmt_set_flag(changes: dict) -> ChangeLine | None:
    """Flags are internal — suppress from change-lines."""
    return None


def _fmt_default(changes: dict) -> ChangeLine | None:
    """Fallback: no change-line for unrecognized command types."""
    return None


# Command-type → formatter dispatch.
_FORMATTERS: dict[str, _Formatter] = {
    # Lifepath.
    "gain_skill": _fmt_skill_gained,
    "roll_characteristic": _fmt_characteristic,
    "set_characteristic": _fmt_characteristic,
    "aging_check": _fmt_characteristic_improved,
    "promote": _fmt_promotion,
    # Adventure / scene.
    "register_fact": _fmt_register_fact,
    "add_injury": _fmt_add_injury,
    "add_open_thread": _fmt_add_thread,
    "remove_open_thread": _fmt_remove_thread,
    "set_character_dead": _fmt_character_dead,
    "set_mission_state": _fmt_mission_state,
    "adjust_credits": _fmt_credits,
    # Suppressed (internal/noise).
    "set_flag": _fmt_set_flag,
    "set_rng_snapshot": _fmt_set_flag,
    "add_chapter_summary": _fmt_set_flag,
    "set_pending_freetext": _fmt_set_flag,
    "set_pending_hook": _fmt_set_flag,
    "flag_degradation": _fmt_set_flag,
    "oracle_roll": _fmt_set_flag,
    "complication_roll": _fmt_set_flag,
    "scene_check": _fmt_set_flag,
    "ratify_fact": _fmt_set_flag,
}


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def derive_change_line(event: Event) -> ChangeLine | None:
    """Derive a single change-line from one event (U14, R16).

    Returns ``None`` for events that shouldn't produce a change-line
    (internal flags, oracle rolls, unrecognized types).
    """
    formatter = _FORMATTERS.get(event.command_type, _fmt_default)
    return formatter(event.changes)


def derive_change_lines(events: list[Event]) -> list[ChangeLine]:
    """Derive change-lines from a list of events (U14, R16).

    Filters out ``None`` results and returns the change-lines in the same
    order as the input events (oldest first).
    """
    lines: list[ChangeLine] = []
    for event in events:
        line = derive_change_line(event)
        if line is not None:
            lines.append(line)
    return lines


def derive_recent_change_lines(
    events: list[Event],
    *,
    since_seq: int = 0,
) -> list[ChangeLine]:
    """Derive change-lines from events after a given sequence number (U14).

    Used by controllers to show only the change-lines from the most recent
    action (events appended since the last decision point).
    """
    recent = [e for e in events if e.seq > since_seq]
    return derive_change_lines(recent)
