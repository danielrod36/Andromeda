"""Tool-call pill extraction from the event log (U16, R18).

Derives pill data from events representing LLM tool calls — register_fact,
ratify_fact, set_flag. Each pill carries the tool name, a human-readable
summary, and the audit sequence number for linking into the audit viewer
overlay.

The ``add_narrative_log_entry`` LLM tool (src/llm/tools.py) delegates to
``SetFlagCommand(key="narration")``, so its events carry
``command_type="set_flag"`` with ``key="narration"`` — the pill extractor
detects this pattern and labels those events as "Added log entry" rather
than "Set narrative flag".

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
        "set_flag",
    }
)

#: Sentinel key used by the add_narrative_log_entry LLM tool, which
#: delegates to SetFlagCommand(key="narration") — see src/llm/tools.py.
_NARRATION_KEY: str = "narration"


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
        summary = self.summary if self.summary else "(no detail)"
        return f"{self.tool_name}: {summary}"


def _extract_label_and_summary(event: Event) -> tuple[str, str]:
    """Return ``(label, summary)`` for a tool-call event.

    Handles the special case where the ``add_narrative_log_entry`` LLM tool
    delegates to ``SetFlagCommand(key="narration")`` — its events carry
    ``command_type="set_flag"`` but should be labeled as log entries.
    """
    ct = event.command_type
    changes = event.changes

    if ct == "register_fact":
        return "Registered fact", changes.get("name", "unknown")
    if ct == "ratify_fact":
        return "Ratified fact", changes.get("fact_name", "unknown")
    if ct == "set_flag":
        key = changes.get("key", "")
        value = changes.get("value", "")
        if key == _NARRATION_KEY:
            return "Added log entry", value[:50]
        return "Set narrative flag", f"{key}={value}" if key else "(unnamed flag)"
    # Fallback for any future tool types added to _TOOL_COMMAND_TYPES.
    return ct, event.description[:50]


def extract_pills(events: list[Event]) -> list[ToolPill]:
    """Extract tool-call pills from the event log (U16, R18).

    Returns pills for events matching LLM tool command types, in
    sequence order. Events that aren't tool calls are skipped.
    """
    pills: list[ToolPill] = []
    for event in events:
        if event.command_type not in _TOOL_COMMAND_TYPES:
            continue
        label, summary = _extract_label_and_summary(event)
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
