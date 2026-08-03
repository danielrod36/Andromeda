"""Story-so-far recap assembly for returning players (U11, R13).

Builds a ≤5-line cause-and-effect recap from chapter summaries plus recent
events. The recap has a deterministic template floor — it always produces
something useful from canonical state, even without an LLM. When the LLM
is configured, the recap is polished through the same injection pattern as
chapter summaries (validated by :class:`SummaryValidator`); on any failure
the template ships.

The 5-line cap is enforced in **assembly**, not by the LLM. The LLM is asked
for a short recap; whatever comes back is split into lines and truncated to 5.
This keeps the cap deterministic regardless of what the model returns.

Design precedent: ``build_template_summary`` / ``ChapterSummarizer``
(:mod:`src.engine.summary`) — the recap follows the same validated-floor
pattern, just assembled across the whole story rather than one mission.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.engine.state import GameState

logger = logging.getLogger(__name__)

#: Hard cap on recap lines (R13).
MAX_RECAP_LINES: int = 5


# ---------------------------------------------------------------------------
# Result types.
# ---------------------------------------------------------------------------


@dataclass
class RecapResult:
    """The recap shown to a returning player (U11).

    Attributes:
        lines: The recap text, one entry per line (≤ ``MAX_RECAP_LINES``).
        source: ``"llm"`` if the LLM produced this prose, ``"template"``
            if the deterministic floor was used.
        llm_failed: True if the LLM was attempted but fell back to template.
    """

    lines: list[str] = field(default_factory=list)
    source: str = "template"
    llm_failed: bool = False


# ---------------------------------------------------------------------------
# Template assembly — the deterministic floor.
# ---------------------------------------------------------------------------


def build_template_recap(state: GameState) -> list[str]:
    """Build a deterministic ≤5-line recap from canonical state (U11, R13).

    Assembles the most salient story beats from:

    1. **Chapter summaries** — condensed mission outcomes, most recent first.
    2. **Recent events** — the last few state-changing events that paint the
       current situation.
    3. **Open threads** — unresolved narrative threads.

    The character's identity anchors line 1 (or the most recent chapter summary
    if the character has no career yet — a mid-lifepath save).

    Returns an empty list when there is no story to recap (new campaign with
    no events and no summaries), so callers can suppress the recap entirely.
    """
    lines: list[str] = []
    char = state.character

    # --- Anchor: who is this character and where are they? ---
    if char.career:
        anchor = f"{char.name or 'You'} — {char.career}"
        if char.terms:
            anchor += f", {char.terms} term{'s' if char.terms != 1 else ''} served"
        lines.append(anchor)
    elif char.name:
        # Mid-lifepath: character exists but career not chosen.
        lines.append(f"{char.name}, a new recruit whose story is just beginning.")

    # --- Chapter summaries (most recent 2) ---
    # Each summary is a self-contained mission recap — use the most recent
    # ones to fill lines 2-3.
    for summary in state.chapter_summaries[-2:]:
        text = summary.strip()
        if text and text not in lines:
            lines.append(text)
            if len(lines) >= MAX_RECAP_LINES:
                break

    if len(lines) >= MAX_RECAP_LINES:
        return lines[:MAX_RECAP_LINES]

    # --- Recent significant events ---
    # Pick state_change events with human-readable descriptions, excluding
    # noisy internal events (flag sets, RNG snapshots, etc.).
    recent = [
        e
        for e in state.events[-10:]
        if e.description
        and e.command_type
        not in (
            "set_flag",
            "set_rng_snapshot",
            "add_chapter_summary",
            "set_pending_freetext",
            "set_pending_hook",
        )
    ]
    # Take the last few, but only as many as fit.
    for event in reversed(recent):
        if len(lines) >= MAX_RECAP_LINES:
            break
        desc = event.description.strip()
        if desc and desc not in lines:
            lines.append(desc)

    if len(lines) >= MAX_RECAP_LINES:
        return lines[:MAX_RECAP_LINES]

    # --- Open threads ---
    for thread in state.open_threads:
        if len(lines) >= MAX_RECAP_LINES:
            break
        lines.append(f"Unresolved: {thread}")

    return lines[:MAX_RECAP_LINES]


# ---------------------------------------------------------------------------
# LLM polish path.
# ---------------------------------------------------------------------------


def _cap_lines(text: str, cap: int = MAX_RECAP_LINES) -> list[str]:
    """Split text into lines and enforce the cap.

    Non-empty lines only; whitespace-only lines are dropped so the LLM's
    paragraph breaks don't eat the budget.
    """
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    # If the LLM wrote one big paragraph (no newlines), split on sentences
    # to respect the line budget.
    if len(raw_lines) <= 1:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        raw_lines = [s.strip() for s in sentences if s.strip()]
    return raw_lines[:cap]


def build_recap(
    state: GameState,
    *,
    adapter=None,
    view=None,
) -> RecapResult:
    """Build a recap with optional LLM polish and template floor (U11, R13).

    The template floor is always computed first. If an LLM adapter is provided
    and configured, the recap is polished; on any failure (provider error,
    validation, retries exhausted), the template ships unchanged.

    Args:
        state: The canonical game state.
        adapter: Optional :class:`~src.llm.adapter.LLMAdapter`. When ``None``
            or unconfigured, the template recap is returned.
        view: Optional curated view (avoids rebuilding it if the caller
            already has one).

    Returns:
        :class:`RecapResult` with ≤5 lines.
    """
    template_lines = build_template_recap(state)

    # No story to recap.
    if not template_lines:
        return RecapResult(lines=[], source="template")

    # No LLM — template floor is the recap.
    if adapter is None or not adapter.llm_configured:
        return RecapResult(lines=template_lines, source="template")

    # Try LLM polish.
    try:
        from src.engine.summary import SummaryValidator

        polished = adapter.polish_recap(state, template_lines, view)
        if polished:
            # Validate: no mechanical claims (same guard as chapter summaries).
            validator = SummaryValidator()
            result = validator.validate(polished, state)
            if result.valid:
                lines = _cap_lines(polished)
                if lines:
                    return RecapResult(lines=lines, source="llm")
            else:
                logger.info(
                    "Recap LLM output failed validation, using template: %s",
                    result.error_summary,
                )
    except Exception as exc:
        logger.warning("Recap LLM polish failed, falling back to template: %s", exc)

    return RecapResult(lines=template_lines, source="template", llm_failed=True)
