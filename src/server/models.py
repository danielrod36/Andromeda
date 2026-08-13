"""Wire DTOs for the v1 API (M0.6). Request/response pydantic models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    """POST /v1/sessions body."""

    kind: Literal["chargen", "adventure"] = "chargen"
    name: str = Field(min_length=1, max_length=80)
    seed: int | None = None  # None → server picks one (client's REROLL sends an int)
    pack_id: str = "scifi"
    profile: Literal["narrative", "classic"] = "narrative"
    death_mode: Literal["narrative", "ironman", "checkpoint"] = "narrative"
    from_save: str | None = None  # adventure kind: save name to load/resume


class ChooseRequest(BaseModel):
    option_id: str
    origin: Literal["player", "advisor", "freetext"] = "player"


class FreetextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class NarrateRequest(BaseModel):
    beat: str = "scene"  # "world_intro" | "scene" | "chargen_beat" | "chargen_close"
    steering: str = ""


class NameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class DuplicateSaveRequest(BaseModel):
    new_name: str = Field(min_length=1, max_length=80)


class ImportSaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    document: dict  # the full GameState JSON document


class LlmSettingsRequest(BaseModel):
    """PUT /v1/settings/llm body. ``api_key=None`` leaves the stored key untouched."""

    provider: str = "anthropic"
    model: str = ""
    api_key: str | None = None
    base_url: str = ""
    max_retries: int = 3


class OddsRequest(BaseModel):
    skill: str
    characteristic: str
    difficulty: str
