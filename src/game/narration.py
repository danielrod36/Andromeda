"""Typed narration block assembly for the reading spine (U10).

Assembles typed blocks (narration, receipt, change, divider, pill) that
the SSE endpoint streams to the browser. Each block type renders
differently in the spine. The outcome is locked before streaming starts
—the trust boundary made temporal (mechanics resolve first, then narrate).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

BlockType = Literal["narration", "receipt", "change", "divider", "pill", "badge", "done", "error"]

#: Maximum guided retries per beat (U15, R17).
MAX_RETRIES_PER_BEAT: int = 3


@dataclass
class NarrationBlock:
    """A single typed block in the narration stream (U10).

    Attributes:
        type: The block type — controls how the client renders it.
        content: The block's text content (prose, receipt text, etc.).
    """

    type: BlockType
    content: str

    def to_sse(self) -> str:
        """Serialize to an SSE ``data:`` line."""
        return f"data: {json.dumps({'type': self.type, 'content': self.content})}\n\n"


def build_template_blocks(
    scaffold_text: str,
    outcome_facts: list[str],
    receipts: list[str],
) -> list[NarrationBlock]:
    """Build narration blocks for template (no-LLM) mode (U10).

    Template mode emits the scaffold, receipts, and outcome facts as
    discrete blocks — no streaming, but the same typed-block protocol
    so the client renders them identically to LLM-narrated blocks.
    """
    blocks: list[NarrationBlock] = []

    if scaffold_text:
        blocks.append(NarrationBlock(type="narration", content=scaffold_text))

    for receipt in receipts:
        blocks.append(NarrationBlock(type="receipt", content=receipt))

    for fact in outcome_facts:
        blocks.append(NarrationBlock(type="change", content=fact))

    return blocks


def build_done_block() -> NarrationBlock:
    """Build the terminal 'done' block that signals stream end (U10)."""
    return NarrationBlock(type="done", content="")


def build_error_block(message: str) -> NarrationBlock:
    """Build an error block for stream failures (U10)."""
    return NarrationBlock(type="error", content=message)


def build_badge_block(text: str) -> NarrationBlock:
    """Build a badge block for inline UI badges (U15).

    Badges are non-content signals — they communicate metadata like
    "outcome unchanged" without adding to the narration prose.
    """
    return NarrationBlock(type="badge", content=text)
