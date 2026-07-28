"""Curated state view — the safe subset of GameState the LLM is allowed to see.

Per R2 and AE13, the LLM never receives the full :class:`GameState`. Instead,
:meth:`build_curated_view` assembles a :class:`CuratedView` containing only:

**Always included:**
- Character sheet (name, characteristics, skills, career, rank).
- Active mission description (``None`` in v0.2 — no missions yet).
- NPCs in the current scene with dispositions (empty in v0.2).
- Last 3 narrative log entries.
- Open narrative threads (empty in v0.2).

**Never included:**
- Raw dice / audit log details (``Event.roll`` values, individual die pips).
- Stats of off-scene NPCs.
- Unoffered mission hooks.
- RNG state or internal engine fields.

The view is a Pydantic model so it serializes cleanly to JSON for the prompt.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from src.engine.state import GameState


# ---------------------------------------------------------------------------
# View sub-models — intentionally minimal to control what the LLM can see.
# ---------------------------------------------------------------------------


class CharacterSheet(BaseModel):
    """Character data safe for the LLM to see.

    Excludes ``alive`` (internal flag) — the narrative log conveys death.
    """

    name: str = ""
    characteristics: dict[str, int] = Field(default_factory=dict)
    skills: dict[str, int] = Field(default_factory=dict)
    age: int = 18
    terms: int = 0
    career: str = ""
    rank: int = 0


class NpcSummary(BaseModel):
    """NPC in the current scene — name and disposition only, no full stats.

    Off-scene NPC stats are excluded per AE13.
    """

    name: str
    disposition: str = "neutral"
    description: str = ""


class CuratedView(BaseModel):
    """The complete curated view passed to the LLM (R2, AE13).

    Fields are deliberately constrained: no raw dice logs, no off-scene NPC
    stats, no unoffered hooks, no RNG state.
    """

    character_sheet: CharacterSheet
    active_mission: str | None = None
    scene_npcs: list[NpcSummary] = Field(default_factory=list)
    recent_log: list[str] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Assembly.
# ---------------------------------------------------------------------------


def build_curated_view(
    state: GameState,
    *,
    scene_npcs: list[NpcSummary] | None = None,
    active_mission: str | None = None,
    open_threads: list[str] | None = None,
    recent_log_count: int = 3,
) -> CuratedView:
    """Build a :class:`CuratedView` from the canonical :class:`GameState`.

    Parameters:
        state: The engine's canonical state.
        scene_npcs: NPCs currently in the scene (empty if not provided).
        active_mission: Description of the active mission, or ``None``.
        open_threads: Open narrative threads (empty if not provided).
        recent_log_count: How many recent narrative-log entries to include.

    The narrative log is capped at ``recent_log_count`` entries (default 3)
    per the spec. Raw dice events from the audit log are never included —
    only human-facing prose from ``narrative_log``.
    """
    char = state.character
    sheet = CharacterSheet(
        name=char.name,
        characteristics=dict(char.characteristics),
        skills=dict(char.skills),
        age=char.age,
        terms=char.terms,
        career=char.career,
        rank=char.rank,
    )

    # Only the last N prose entries — no raw dice/audit data.
    log_slice = list(state.narrative_log[-recent_log_count:])

    return CuratedView(
        character_sheet=sheet,
        active_mission=active_mission,
        scene_npcs=list(scene_npcs or []),
        recent_log=log_slice,
        open_threads=list(open_threads or []),
    )


# ---------------------------------------------------------------------------
# Prohibited-field check (used by AE13 test).
# ---------------------------------------------------------------------------

#: Field names from GameState / Event / RollResult that must never appear
#: in the curated view's serialized form. Used by tests (AE13) and as a
#: runtime guard.
PROHIBITED_KEYS: frozenset[str] = frozenset(
    {
        "roll",          # RollResult objects
        "rolls",         # individual die pips
        "modifiers",     # dice modifiers
        "rng",           # RNG state
        "events",        # raw audit log
        "seed",          # internal seed
        "save_version",  # internal version
        "stream",        # RNG stream name
        "ndice",         # dice count
        "sides",         # die sides
    }
)


def assert_no_prohibited_fields(view: CuratedView) -> None:
    """Assert that the curated view's JSON contains no prohibited keys.

    This is the runtime enforcement of AE13. It serializes the view to a
    dict and checks that none of the keys in :data:`PROHIBITED_KEYS` appear
    at any level.
    """
    import json

    raw = json.dumps(view.model_dump())
    for key in PROHIBITED_KEYS:
        if f'"{key}"' in raw:
            raise ValueError(
                f"Curated view contains prohibited key '{key}' "
                f"— violates AE13 (curated view safety)"
            )
