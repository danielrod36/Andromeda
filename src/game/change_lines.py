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

from collections.abc import Callable
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

_Formatter = Callable[[dict], ChangeLine | None]


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


def _fmt_aging_apply(changes: dict) -> ChangeLine | None:
    """Format ``lifepath_aging_apply`` — stat reduction from aging."""
    stat = changes.get("characteristic", "")
    points = changes.get("points", 0)
    new_value = changes.get("new_value", 0)
    if not stat:
        return None
    return ChangeLine(
        text=f"Aging: {stat} reduced by {points} (now {new_value})",
        css_class=CHANGE_NEGATIVE,
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


def _fmt_mission_resolved(changes: dict) -> ChangeLine | None:
    """Format ``resolve_mission`` — the user-visible resolution event."""
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


def _fmt_benefit(changes: dict) -> ChangeLine | None:
    """Format ``lifepath_benefit`` — cash mustering-out benefits only."""
    if changes.get("benefit_type") != "cash":
        return None
    result_text = changes.get("result_text", "")
    if not result_text:
        return None
    return ChangeLine(
        text=f"Mustering-out benefit: {result_text}",
        css_class=CHANGE_POSITIVE,
    )


def _fmt_commission(changes: dict) -> ChangeLine | None:
    """Format ``lifepath_commission`` — officer commission (success only)."""
    if not changes.get("success"):
        return None
    return ChangeLine(
        text="Commissioned as officer",
        css_class=CHANGE_POSITIVE,
    )


def _fmt_advancement(changes: dict) -> ChangeLine | None:
    """Format ``lifepath_advancement`` — rank promotion (success only)."""
    if not changes.get("success"):
        return None
    new_rank = changes.get("new_rank", 0)
    if new_rank > 0:
        return ChangeLine(
            text=f"Promoted to rank {new_rank}",
            css_class=CHANGE_POSITIVE,
        )
    return ChangeLine(
        text="Advancement check succeeded",
        css_class=CHANGE_POSITIVE,
    )


def _fmt_suppress(changes: dict) -> ChangeLine | None:
    """Suppress this event type from change-lines."""
    return None


def _fmt_default(changes: dict) -> ChangeLine | None:
    """Fallback: no change-line for unrecognized command types."""
    return None


# Command-type → formatter dispatch.
#
# Keys MUST match the ``command_type`` ClassVar on the engine's Command
# subclasses (e.g. ``"lifepath_gain_skill"``, not ``"gain_skill"``).
# Each formatter reads field names from the Event's ``changes`` dict that
# match what the command's ``mutate()`` method actually produces.
_FORMATTERS: dict[str, _Formatter] = {
    # Lifepath.
    "lifepath_gain_skill": _fmt_skill_gained,
    "roll_characteristic": _fmt_characteristic,
    "lifepath_assign_characteristic": _fmt_characteristic,
    "lifepath_aging_apply": _fmt_aging_apply,
    "lifepath_commission": _fmt_commission,
    "lifepath_advancement": _fmt_advancement,
    "lifepath_benefit": _fmt_benefit,
    # Adventure / scene.
    "register_fact": _fmt_register_fact,
    "add_injury": _fmt_add_injury,
    "add_open_thread": _fmt_add_thread,
    "remove_open_thread": _fmt_remove_thread,
    "set_character_dead": _fmt_character_dead,
    "resolve_mission": _fmt_mission_resolved,
    # Suppressed (internal/noise).
    "set_flag": _fmt_suppress,
    "set_mission_state": _fmt_suppress,
    "next_mission_id": _fmt_suppress,
    "set_pending_hook": _fmt_suppress,
    "log_mission": _fmt_suppress,
    "add_chapter_summary": _fmt_suppress,
    "set_pending_freetext": _fmt_suppress,
    "flag_degradation": _fmt_suppress,
    "oracle_roll": _fmt_suppress,
    "complication_roll": _fmt_suppress,
    "scene_check": _fmt_suppress,
    "ratify_fact": _fmt_suppress,
    "set_rng_snapshot": _fmt_suppress,
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
