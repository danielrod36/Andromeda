"""Tool-call pill extraction from the event log (U16, R18).

Derives pill data from events representing LLM tool calls — register_fact,
ratify_npc, add_narrative_log_entry, set_narrative_flag. Each pill carries
the tool name, a human-readable summary, and the audit sequence number for
linking into the audit viewer overlay.

Pills render inline in the narration stream, making the engine/LLM boundary
visible in real time. They are read-only derived data — pure functions over
the event log.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.engine.audit import Event

#: Command types that represent LLM tool calls (U16).
_TOOL_COMMAND_TYPES: frozenset[str] = frozenset(
    {
        "register_fact",
        "ratify_fact",
        "add_narrative_log_entry",
        "set_flag",  # set_narrative_flag
    }
)

#: Human-readable labels for each tool type.
_TOOL_LABELS: dict[str, str] = {
    "register_fact": "Registered fact",
    "ratify_fact": "Ratified NPC",
    "add_narrative_log_entry": "Added log entry",
    "set_flag": "Set narrative flag",
}


@dataclass
class ToolPill:
    """A single tool-call pill for inline rendering (U16, R18).

    Attributes:
        tool_name: Display label for the tool (e.g. "Registered fact").
        summary: Human-readable summary of what the tool did.
        seq: Audit sequence number — links into the audit viewer.
    """

    tool_name: str
    summary: str
    seq: int

    @property
    def label(self) -> str:
        """Short label for the pill chip."""
        return f"{self.tool_name}: {self.summary}"


def _extract_summary(event: Event) -> str:
    """Extract a human-readable summary from a tool-call event."""
    ct = event.command_type
    changes = event.changes

    if ct == "register_fact":
        return changes.get("name", "unknown")
    if ct == "ratify_fact":
        return changes.get("name", "unknown")
    if ct == "add_narrative_log_entry":
        return changes.get("text", "")[:50]
    if ct == "set_flag":
        key = changes.get("key", "")
        value = changes.get("value", "")
        return f"{key}={value}" if key else ""
    return event.description[:50]


def extract_pills(events: list[Event]) -> list[ToolPill]:
    """Extract tool-call pills from the event log (U16, R18).

    Returns pills for events matching LLM tool command types, in
    sequence order. Events that aren't tool calls are skipped.
    """
    pills: list[ToolPill] = []
    for event in events:
        if event.command_type not in _TOOL_COMMAND_TYPES:
            continue
        label = _TOOL_LABELS.get(event.command_type, event.command_type)
        summary = _extract_summary(event)
        pills.append(ToolPill(tool_name=label, summary=summary, seq=event.seq))
    return pills


def extract_recent_pills(
    events: list[Event],
    *,
    since_seq: int = 0,
) -> list[ToolPill]:
    """Extract pills from events after a given sequence number (U16).

    Used by controllers to show only the pills from the most recent action.
    """
    recent = [e for e in events if e.seq > since_seq]
    return extract_pills(recent)
