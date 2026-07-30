"""Tests for GameState models and serialization round-trip (R2)."""

from __future__ import annotations

import hashlib

import pytest

from src.engine.commands import Engine, RollCharacteristicCommand
from src.engine.state import (
    CampaignConfig,
    Character,
    GameState,
    Injury,
    NarrativeFact,
)


def state_hash(state: GameState) -> str:
    return hashlib.sha256(state.model_dump_json().encode()).hexdigest()


# ---------------------------------------------------------------------------
# Scenario: State serialization round-trip — JSON → GameState → identical hash.
# ---------------------------------------------------------------------------


def test_state_serialization_round_trip_identical_hash():
    """GameState → JSON → GameState produces an identical state hash."""
    original = GameState.new(seed=42)
    original.character.name = "Test Hero"
    original.character.characteristics = {"STR": 7, "DEX": 10}

    json_str = original.model_dump_json()
    restored = GameState.model_validate_json(json_str)

    assert state_hash(restored) == state_hash(original)


def test_state_serialization_round_trip_after_commands():
    """Round-trip preserves state after applying several commands."""
    engine = Engine(GameState.new(seed=7))
    for c in ("STR", "DEX", "END"):
        engine.apply(RollCharacteristicCommand(characteristic=c))

    json_str = engine.state.model_dump_json()
    restored = GameState.model_validate_json(json_str)
    assert state_hash(restored) == state_hash(engine.state)
    # RNG state preserved: next roll matches.
    assert restored.rng.snapshot() == engine.state.rng.snapshot()


def test_state_round_trip_preserves_full_event_log():
    """The event log round-trips with all entries intact."""
    engine = Engine(GameState.new(seed=3))
    engine.apply(RollCharacteristicCommand(characteristic="STR"))
    engine.apply(RollCharacteristicCommand(characteristic="DEX"))

    restored = GameState.model_validate_json(engine.state.model_dump_json())
    assert len(restored.events) == len(engine.state.events)
    for a, b in zip(restored.events, engine.state.events, strict=False):
        assert a.seq == b.seq
        assert a.kind == b.kind
        assert a.command_type == b.command_type


# ---------------------------------------------------------------------------
# Scenario: Discriminated union entities serialize correctly.
# ---------------------------------------------------------------------------


def test_discriminated_union_narrative_fact_round_trip():
    state = GameState.new(seed=1)
    state.entities.append(
        NarrativeFact(name="Bartender", description="A tall woman with a cybernetic arm.")
    )
    json_str = state.model_dump_json()
    restored = GameState.model_validate_json(json_str)
    assert len(restored.entities) == 1
    entity = restored.entities[0]
    assert isinstance(entity, NarrativeFact)
    assert entity.name == "Bartender"
    assert entity.description == "A tall woman with a cybernetic arm."


def test_discriminated_union_injury_round_trip():
    state = GameState.new(seed=1)
    state.entities.append(
        Injury(name="Broken Rib", severity="moderate", description="From a bad fall.")
    )
    restored = GameState.model_validate_json(state.model_dump_json())
    entity = restored.entities[0]
    assert isinstance(entity, Injury)
    assert entity.name == "Broken Rib"
    assert entity.severity == "moderate"


def test_discriminated_union_mixed_entities_round_trip():
    state = GameState.new(seed=1)
    state.entities.append(NarrativeFact(name="Dock Officer"))
    state.entities.append(Injury(name="Sprained Ankle", severity="minor"))
    restored = GameState.model_validate_json(state.model_dump_json())
    assert len(restored.entities) == 2
    assert isinstance(restored.entities[0], NarrativeFact)
    assert isinstance(restored.entities[1], Injury)


def test_discriminated_union_rejects_unknown_type():
    """An entity with an unknown discriminator value fails validation."""
    import json

    from pydantic import ValidationError

    state = GameState.new(seed=1)
    raw = json.loads(state.model_dump_json())
    raw["entities"] = [{"type": "unknown_kind", "name": "X"}]
    with pytest.raises(ValidationError):
        GameState.model_validate(raw)


# ---------------------------------------------------------------------------
# Scenario: Model defaults and construction.
# ---------------------------------------------------------------------------


def test_new_game_state_has_seeded_rng():
    state = GameState.new(seed=42)
    assert state.seed == 42
    # All three named streams present.
    snaps = state.rng.snapshot()
    assert set(snaps.keys()) == {"oracle", "lifepath", "combat"}


def test_character_defaults():
    c = Character()
    assert c.name == ""
    assert c.characteristics == {}
    assert c.alive is True
    assert c.age == 18


def test_campaign_config_defaults():
    cc = CampaignConfig()
    assert cc.ruleset == "cepheus"
    assert cc.resolution_profile == "narrative"
    assert cc.death_mode == "narrative"


def test_save_version_defaults_to_current():
    state = GameState.new(seed=1)
    assert state.save_version == 1


# ---------------------------------------------------------------------------
# Scenario: RNG state preserved across deep copy (for future Checkpoint use).
# ---------------------------------------------------------------------------


def test_rng_streams_after_model_copy_need_hydrate():
    """model_copy(deep=True) copies fields but live Random instances must be rehydrated.

    This documents the contract U8's Checkpoint will rely on: after a deep copy,
    call _hydrate() on the RngStreams before rolling. Snapshots are the source
    of truth, live instances are derived.
    """
    original = GameState.new(seed=42)
    # Advance RNG.
    original.rng.roll("lifepath", 2, 6)
    original.rng.roll("oracle", 1, 6)

    # Deep copy.
    copied = original.model_copy(deep=True)
    # Rehydrate live instances from snapshots.
    copied.rng._hydrate()

    # Both should produce the same next roll (snapshots were in sync at copy time).
    orig_next = original.rng.roll("lifepath", 2, 6).total
    copy_next = copied.rng.roll("lifepath", 2, 6).total
    assert orig_next == copy_next
