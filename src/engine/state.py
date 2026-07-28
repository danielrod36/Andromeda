"""GameState and entity models — the engine's canonical serializable state (R2).

All mutation flows through the command funnel (:func:`Engine.apply`). The
``events`` list is the append-only event log (audit views filter it); the
``rng`` field holds named RNG streams whose state persists across save/load.

Entity types use a discriminated union keyed on ``type`` so polymorphic world
entities serialize and deserialize correctly without engine code changes when
new entity kinds are added.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from src.engine.audit import Event
from src.engine.dice import RngStreams


class Character(BaseModel):
    """Player character sheet.

    Characteristics use the six Cepheus stats (STR, DEX, END, INT, EDU, SOC).
    Skills, career, and rank are populated by the lifepath engine (U3); the
    model is intentionally permissive here so U1 can exercise state mutation.
    """

    name: str = ""
    characteristics: dict[str, int] = Field(default_factory=dict)
    skills: dict[str, int] = Field(default_factory=dict)
    age: int = 18
    terms: int = 0
    career: str = ""
    rank: int = 0
    alive: bool = True


class CampaignConfig(BaseModel):
    """Campaign configuration selected at creation (F1).

    Values default to the Narrative resolution profile and Narrative death mode
    per the plan's defaults; U2/U3/U6/U8 populate and enforce these.
    """

    ruleset: str = "cepheus"
    theme_pack: str = "scifi"
    resolution_profile: str = "narrative"  # "narrative" | "classic"
    death_mode: str = "narrative"  # "narrative" | "ironman" | "checkpoint"


# ---------------------------------------------------------------------------
# Discriminated-union entities.
#
# New entity kinds are added by: defining a BaseModel with a unique
# ``type`` Literal, then appending it to ``EntityUnion``. No engine-core
# changes required — the union deserializes by the discriminator field.
# ---------------------------------------------------------------------------


class NarrativeFact(BaseModel):
    """An LLM-introduced narrative fact (R24).

    Mechanically inert until the engine ratifies it from a rule-set template
    when a check targets it. Lives in ``entities`` alongside other world state.
    """

    type: Literal["narrative_fact"] = "narrative_fact"
    name: str
    description: str = ""


class Injury(BaseModel):
    """A lasting injury/consequence on the character (R15).

    Populated by the Narrative death mode (U8) or scene consequences (U7); the
    model exists in U1 to exercise the discriminated union with a second kind.
    """

    type: Literal["injury"] = "injury"
    name: str
    severity: str = "minor"  # minor | moderate | severe
    description: str = ""


EntityUnion = Annotated[
    Union[NarrativeFact, Injury],
    Field(discriminator="type"),
]


class GameState(BaseModel):
    """Root model for all canonical game state (R2).

    Every field here is engine-owned and serializable. The LLM never sees the
    full state — it receives a curated view assembled by the LLM adapter (U5).
    The ``events`` list is append-only via the command funnel; ``rng`` carries
    named RNG streams whose positions persist across save/load so resumed play
    continues the exact same roll sequence.
    """

    save_version: int = 1
    seed: int
    campaign: CampaignConfig = Field(default_factory=CampaignConfig)
    character: Character = Field(default_factory=Character)
    rng: RngStreams
    entities: list[EntityUnion] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    narrative_log: list[str] = Field(default_factory=list)
    # U7: Mission tracking and chapter summaries.
    active_mission: dict | None = None
    completed_missions: list[dict] = Field(default_factory=list)
    chapter_summaries: list[str] = Field(default_factory=list)

    @classmethod
    def new(cls, seed: int, **kwargs: object) -> GameState:
        """Create a new game state with seeded RNG streams.

        Convenience factory: callers pass a seed and get per-stream RNG
        instances derived from it, so two ``GameState.new(seed=N)`` calls
        produce identical initial state.
        """
        return cls(seed=seed, rng=RngStreams.seeded(seed), **kwargs)
