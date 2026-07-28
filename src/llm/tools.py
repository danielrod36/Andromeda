"""Tool definitions for LLM-initiated state mutation (R3).

Every tool is a thin wrapper that constructs a :class:`Command` and applies
it through :meth:`Engine.apply`. The LLM never mutates state directly —
tools are the bridge, and the command funnel is the trust boundary.

Tools are defined as standalone functions (not ``@agent.tool`` decorators)
so they can be registered with any agent and unit-tested independently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext

from src.engine.commands import Command, Engine, SetFlagCommand
from src.engine.state import GameState

#: Strict whitelist for LLM-provided flag keys: lowercase snake_case,
#: starting with a letter, max 64 chars. Prevents log injection and key
#: confusion from untrusted LLM output.
_FLAG_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


# ---------------------------------------------------------------------------
# Deps type — passed to every tool via RunContext.
# ---------------------------------------------------------------------------


@dataclass
class ToolDeps:
    """Runtime dependencies injected into every tool call.

    The adapter builds this from the current :class:`Engine` and
    :class:`GameState` before each turn. Tools access the engine through
    ``ctx.deps.engine`` to apply commands through the funnel.
    """

    engine: Engine
    state: GameState


# ---------------------------------------------------------------------------
# Tools — each constructs a Command and applies it through Engine.apply().
# ---------------------------------------------------------------------------


async def set_narrative_flag(
    ctx: RunContext[ToolDeps], key: str, value: str
) -> str:
    """Set a narrative flag on the story log.

    This is the primary mechanism for the LLM to record narrative facts
    (R24) that the engine ratifies later. The key must be non-empty.

    Args:
        key: Non-empty flag name (e.g. ``"met_npc"``, ``"visited_station"``).
        value: The flag value as a string.

    Returns:
        A confirmation message describing what was set.
    """
    key = key.strip() if key else ""
    if not _FLAG_KEY_RE.match(key):
        raise ValueError(
            "Flag key must be lowercase snake_case starting with a letter "
            f"(e.g. 'met_npc'): got {key!r}"
        )

    cmd = SetFlagCommand(key=key, value=value)
    event = ctx.deps.engine.apply(cmd)
    return f"Narrative flag set: {key}={value}"


async def add_narrative_log_entry(
    ctx: RunContext[ToolDeps], entry: str
) -> str:
    """Append a prose entry to the narrative log.

    This lets the LLM record its narration output into the canonical
    narrative log (so it appears in the curated view's ``recent_log`` for
    future turns).

    Args:
        entry: The prose entry to append. Must be non-empty.

    Returns:
        A confirmation message.
    """
    if not entry or not entry.strip():
        raise ValueError("Log entry must be non-empty")

    # Use SetFlagCommand's mechanism (append to narrative_log) with a
    # special key prefix so these are identifiable.
    cmd = SetFlagCommand(key="narration", value=entry.strip())
    ctx.deps.engine.apply(cmd)
    return "Narrative log entry added."


# ---------------------------------------------------------------------------
# Tool registry — the adapter registers these with the agent.
# ---------------------------------------------------------------------------

#: All tool functions, keyed by name. The adapter iterates this to register
#: tools with the Pydantic AI agent.
TOOL_REGISTRY: dict[str, Any] = {
    "set_narrative_flag": set_narrative_flag,
    "add_narrative_log_entry": add_narrative_log_entry,
}
