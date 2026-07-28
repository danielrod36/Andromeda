"""Cepheus Adventure engine core (U1).

Deterministic command funnel, append-only event log, seeded RNG streams,
Pydantic state models, and JSON save/load with versioning.

The engine is a plain sync Python package with zero TUI imports; the Textual
shell and the LLM adapter are clients that call ``Engine.apply(cmd)`` and read
curated views of :class:`GameState`.
"""
from src.engine.audit import Event, EventKind, audit_rolls
from src.engine.commands import (
    Command,
    Engine,
    RollCharacteristicCommand,
    SetFlagCommand,
)
from src.engine.dice import (
    ForcedRoller,
    LiveRoller,
    Roller,
    RngSnapshot,
    RngStreams,
    RollResult,
    RollSpec,
)
from src.engine.persistence import (
    CURRENT_SAVE_VERSION,
    current_save_version,
    load,
    migrate,
    save,
)
from src.engine.state import (
    CampaignConfig,
    Character,
    GameState,
    Injury,
    NarrativeFact,
)

__all__ = [
    "CURRENT_SAVE_VERSION",
    "CampaignConfig",
    "Character",
    "Command",
    "Engine",
    "Event",
    "EventKind",
    "ForcedRoller",
    "GameState",
    "Injury",
    "LiveRoller",
    "NarrativeFact",
    "RollCharacteristicCommand",
    "RollResult",
    "RollSpec",
    "Roller",
    "RngSnapshot",
    "RngStreams",
    "SetFlagCommand",
    "audit_rolls",
    "current_save_version",
    "load",
    "migrate",
    "save",
]
