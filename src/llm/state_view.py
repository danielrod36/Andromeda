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

from src.engine.retrieval import FactRetriever
from src.engine.state import GameState, NarrativeFact, NpcRecord

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


class FactSummary(BaseModel):
    """A narrative fact safe for the LLM to see (R25)."""

    name: str
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
    # U7: Chapter summaries replace raw event history (R19, AE16).
    chapter_summaries: list[str] = Field(default_factory=list)
    # U7: Relevant narrative facts re-surfaced for context (R25).
    relevant_facts: list[FactSummary] = Field(default_factory=list)


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
    chapter_summaries: list[str] | None = None,
    relevant_facts: list[FactSummary] | None = None,
) -> CuratedView:
    """Build a :class:`CuratedView` from the canonical :class:`GameState`.

    Parameters:
        state: The engine's canonical state.
        scene_npcs: NPCs currently in the scene (empty if not provided).
        active_mission: Description of the active mission, or ``None``.
        open_threads: Open narrative threads (empty if not provided).
        recent_log_count: How many recent narrative-log entries to include.
        chapter_summaries: Validated chapter summaries replacing raw events (R19).
        relevant_facts: Re-surfaced narrative facts for context (R25).

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

    # Use chapter summaries from state if not explicitly provided.
    summaries = (
        chapter_summaries if chapter_summaries is not None else list(state.chapter_summaries)
    )

    return CuratedView(
        character_sheet=sheet,
        active_mission=active_mission,
        scene_npcs=list(scene_npcs or []),
        recent_log=log_slice,
        open_threads=list(open_threads if open_threads is not None else state.open_threads),
        chapter_summaries=summaries,
        relevant_facts=list(relevant_facts or []),
    )


# ---------------------------------------------------------------------------
# Prohibited-field check (used by AE13 test).
# ---------------------------------------------------------------------------

#: Field names from GameState / Event / RollResult that must never appear
#: in the curated view's serialized form. Used by tests (AE13) and as a
#: runtime guard.
PROHIBITED_KEYS: frozenset[str] = frozenset(
    {
        "roll",  # RollResult objects
        "rolls",  # individual die pips
        "modifiers",  # dice modifiers
        "rng",  # RNG state
        "events",  # raw audit log
        "seed",  # internal seed
        "save_version",  # internal version
        "stream",  # RNG stream name
        "ndice",  # dice count
        "sides",  # die sides
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


# ---------------------------------------------------------------------------
# Scene-aware curated view (R25, R15) — retrieval + NPC dispositions.
# ---------------------------------------------------------------------------


def _disposition_label(value: int) -> str:
    """Map a numeric disposition (-2..2) to a label for the LLM."""
    if value <= -2:
        return "hostile"
    if value == -1:
        return "unfriendly"
    if value >= 2:
        return "allied"
    if value == 1:
        return "friendly"
    return "neutral"


def build_curated_view_for_scene(
    state: GameState,
    scaffold_texts: list[str],
    player_input: str | None = None,
    *,
    retriever: FactRetriever | None = None,
    recent_log_count: int = 3,
) -> CuratedView:
    """Assemble a :class:`CuratedView` for a scene, with fact retrieval (R25)
    and ratified-NPC dispositions (R15) populated.

    Re-surfaces narrative facts whose entity names appear in the scaffold,
    player input, or open threads (entity-matched + a recency slice), and
    includes any ratified :class:`NpcRecord` referenced by the scene in
    ``scene_npcs`` with its disposition label. This is the view Task 24's
    adventure narration consumes.
    """
    retriever = retriever or FactRetriever()
    open_threads = list(state.open_threads)

    # R25: entity-matched + recency-ranked facts.
    facts: list[NarrativeFact] = retriever.retrieve_for_scene(
        state,
        scaffold_texts=scaffold_texts,
        player_input=player_input,
        open_threads=open_threads,
    )
    relevant = [FactSummary(name=f.name, description=f.description) for f in facts]

    # R15: ratified NPCs referenced by the scene → NpcSummary with disposition.
    combined = " ".join(scaffold_texts + ([player_input] if player_input else [])).lower()
    npc_summaries: list[NpcSummary] = []
    for entity in state.entities:
        if isinstance(entity, NpcRecord) and entity.name.lower() in combined:
            npc_summaries.append(
                NpcSummary(
                    name=entity.name,
                    disposition=_disposition_label(entity.disposition),
                    description=entity.description,
                )
            )

    active = state.active_mission.get("hook") if state.active_mission else None
    return build_curated_view(
        state,
        scene_npcs=npc_summaries,
        active_mission=active,
        open_threads=open_threads,
        recent_log_count=recent_log_count,
        relevant_facts=relevant,
    )
