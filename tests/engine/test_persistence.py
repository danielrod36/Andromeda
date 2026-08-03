"""Tests for JSON save/load, atomic writes, and version migration (R17)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.engine.commands import Engine, RollCharacteristicCommand, SetFlagCommand
from src.engine.persistence import (
    CURRENT_SAVE_VERSION,
    current_save_version,
    load,
    migrate,
    save,
)
from src.engine.state import GameState


def state_hash(state: GameState) -> str:
    return hashlib.sha256(state.model_dump_json().encode()).hexdigest()


# ---------------------------------------------------------------------------
# Scenario: Save/load round-trip produces identical state.
# ---------------------------------------------------------------------------


def test_save_load_round_trip_identical_state(tmp_path: Path):
    """Save to disk, load back, and the state hash matches."""
    engine = Engine(GameState.new(seed=42))
    engine.apply(RollCharacteristicCommand(characteristic="STR"))
    engine.apply(RollCharacteristicCommand(characteristic="DEX"))

    path = tmp_path / "save.json"
    save(engine.state, path)

    loaded = load(path)
    assert state_hash(loaded) == state_hash(engine.state)


def test_save_file_is_valid_json_with_version(tmp_path: Path):
    state = GameState.new(seed=1)
    path = tmp_path / "save.json"
    save(state, path)

    raw = json.loads(path.read_text())
    assert raw["save_version"] == CURRENT_SAVE_VERSION
    assert raw["seed"] == 1


# ---------------------------------------------------------------------------
# Scenario: Save mid-sequence, load, continue — identical outcomes.
# ---------------------------------------------------------------------------


def test_save_load_continue_identical_outcomes(tmp_path: Path):
    """Save after some commands, load, continue with the same commands → same state."""
    commands_part_1 = [
        RollCharacteristicCommand(characteristic="STR"),
        RollCharacteristicCommand(characteristic="DEX"),
    ]
    commands_part_2 = [
        RollCharacteristicCommand(characteristic="END"),
        RollCharacteristicCommand(characteristic="INT"),
    ]

    # Path A: apply all four in one session.
    engine_full = Engine(GameState.new(seed=77))
    for cmd in commands_part_1 + commands_part_2:
        engine_full.apply(cmd)

    # Path B: apply part 1, save, load, apply part 2.
    engine_split = Engine(GameState.new(seed=77))
    for cmd in commands_part_1:
        engine_split.apply(cmd)
    path = tmp_path / "mid.json"
    save(engine_split.state, path)

    loaded_state = load(path)
    engine_resumed = Engine(loaded_state)
    for cmd in commands_part_2:
        engine_resumed.apply(cmd)

    assert state_hash(engine_resumed.state) == state_hash(engine_full.state)


# ---------------------------------------------------------------------------
# Scenario: RNG state persistence — next roll after load matches uninterrupted.
# ---------------------------------------------------------------------------


def test_rng_position_preserved_across_save_load(tmp_path: Path):
    """The RNG stream's position is saved; the next roll after load matches uninterrupted."""
    engine = Engine(GameState.new(seed=99))
    # Advance the lifepath stream a few times.
    engine.apply(RollCharacteristicCommand(characteristic="STR"))
    engine.apply(RollCharacteristicCommand(characteristic="DEX"))

    path = tmp_path / "rng.json"
    save(engine.state, path)
    loaded = load(path)

    # Roll on both — they should match because RNG state was preserved.
    engine_next = engine.state.rng.roll("lifepath", 2, 6)
    loaded_next = loaded.rng.roll("lifepath", 2, 6)
    assert engine_next.rolls == loaded_next.rolls
    assert engine_next.total == loaded_next.total


def test_rng_position_preserved_for_oracle_stream(tmp_path: Path):
    """Oracle stream position also survives save/load."""
    state = GameState.new(seed=50)
    # Advance oracle without going through commands (direct stream access).
    state.rng.roll("oracle", 2, 6)
    state.rng.roll("oracle", 2, 6)

    path = tmp_path / "oracle.json"
    save(state, path)
    loaded = load(path)

    direct_next = state.rng.roll("oracle", 2, 6).rolls
    loaded_next = loaded.rng.roll("oracle", 2, 6).rolls
    assert direct_next == loaded_next


# ---------------------------------------------------------------------------
# Scenario: Atomic write — interrupted save leaves previous save intact.
# ---------------------------------------------------------------------------


def test_atomic_write_interrupted_save_leaves_previous_intact(tmp_path: Path):
    """If a write is interrupted (simulated by a corrupted .tmp), the prior save is intact.

    os.replace is atomic on POSIX: the target file is either the old version or
    the new version, never a partial write. We simulate a crash by writing junk
    to the .tmp file and NOT calling os.replace — the prior save at the target
    path must be unchanged.
    """
    path = tmp_path / "campaign.json"
    # First, establish a valid save.
    state_v1 = GameState.new(seed=1)
    state_v1.character.name = "Version One"
    save(state_v1, path)
    original_bytes = path.read_bytes()

    # Simulate a crash: write junk to the .tmp file but don't replace.
    tmp_file = path.with_suffix(path.suffix + ".tmp")
    tmp_file.write_text("CORRUPTED PARTIAL WRITE")

    # The target file is still the valid v1 save.
    assert path.read_bytes() == original_bytes
    # And it loads fine.
    loaded = load(path)
    assert loaded.character.name == "Version One"


def test_save_creates_parent_directories(tmp_path: Path):
    """save() creates parent directories if they don't exist."""
    path = tmp_path / "saves" / "nested" / "game.json"
    state = GameState.new(seed=1)
    save(state, path)
    assert path.exists()
    assert load(path).seed == 1


def test_no_temp_file_left_after_successful_save(tmp_path: Path):
    """A clean save leaves no .tmp file behind."""
    path = tmp_path / "clean.json"
    save(GameState.new(seed=1), path)
    tmp_file = path.with_suffix(path.suffix + ".tmp")
    assert not tmp_file.exists()
    assert path.exists()


# ---------------------------------------------------------------------------
# Scenario: Version migration.
# ---------------------------------------------------------------------------


def test_migrate_current_version_is_noop():
    """Migrating data at the current version is a no-op."""
    data = {"save_version": CURRENT_SAVE_VERSION, "seed": 1}
    result = migrate(data, CURRENT_SAVE_VERSION)
    assert result is data


def test_migrate_missing_migrator_raises():
    """A missing migrator for an intermediate version raises clearly."""
    data = {"save_version": 0, "seed": 1}
    with pytest.raises(ValueError, match="No migration registered"):
        migrate(data, 0)


def test_current_save_version_is_positive():
    assert current_save_version() >= 1


# ---------------------------------------------------------------------------
# Scenario: v1 → v2 migration (Task 1).
# ---------------------------------------------------------------------------


def test_migrate_v1_to_v2(tmp_path: Path):
    import json

    from src.engine.persistence import load
    from src.engine.state import GameState

    v1 = json.loads(GameState.new(seed=7).model_dump_json())
    v1["save_version"] = 1
    for k in (
        "credits",
        "inventory",
        "unassigned_rolls",
        "pool_rerolled",
        "career_history",
        "drafted",
        "background_picks_remaining",
        "basic_training_done",
        "pending_aging",
    ):
        v1["character"].pop(k, None)
    v1.pop("open_threads", None)
    v1.pop("mission_counter", None)
    p = tmp_path / "old.json"
    p.write_text(json.dumps(v1))
    loaded = load(p)
    assert loaded.save_version == CURRENT_SAVE_VERSION
    assert loaded.character.credits == 0
    assert loaded.character.background_picks_remaining == -1
    assert loaded.open_threads == []
    assert loaded.pending_freetext is None  # v3 field defaulted by migration.


def test_migrate_rejects_newer_version():
    import pytest

    from src.engine.persistence import migrate

    with pytest.raises(ValueError, match="newer"):
        migrate({}, from_version=99)


# ---------------------------------------------------------------------------
# Scenario: Empty events and narrative log round-trip.
# ---------------------------------------------------------------------------


def test_empty_state_round_trips(tmp_path: Path):
    """A fresh GameState with no commands round-trips through save/load."""
    state = GameState.new(seed=123)
    path = tmp_path / "empty.json"
    save(state, path)
    loaded = load(path)
    assert state_hash(loaded) == state_hash(state)
    assert loaded.events == []
    assert loaded.narrative_log == []


# ---------------------------------------------------------------------------
# Scenario: Entities and full state survive save/load.
# ---------------------------------------------------------------------------


def test_full_state_with_entities_and_events_round_trips(tmp_path: Path):
    """A populated state with entities, events, and character data round-trips."""
    engine = Engine(GameState.new(seed=55))
    engine.apply(RollCharacteristicCommand(characteristic="STR"))
    engine.apply(SetFlagCommand(key="phase", value="chargen"))
    engine.state.character.name = "Captain Test"
    from src.engine.state import NarrativeFact

    engine.state.entities.append(NarrativeFact(name="Old Friend"))

    path = tmp_path / "full.json"
    save(engine.state, path)
    loaded = load(path)

    assert state_hash(loaded) == state_hash(engine.state)
    assert loaded.character.name == "Captain Test"
    assert len(loaded.entities) == 1
    assert loaded.entities[0].name == "Old Friend"
    assert len(loaded.events) == 2


# ---------------------------------------------------------------------------
# Scenario: Rapid sequential saves to the same path.
# ---------------------------------------------------------------------------


def test_rapid_sequential_saves_each_loadable(tmp_path: Path):
    """Saving to the same path multiple times in succession always yields a loadable file."""
    path = tmp_path / "rapid.json"
    for seed in (1, 2, 3):
        save(GameState.new(seed=seed), path)
        loaded = load(path)
        assert loaded.seed == seed


def test_overwrite_existing_save_replaces_cleanly(tmp_path: Path):
    """A second save to the same path fully replaces the first."""
    path = tmp_path / "replace.json"
    state_a = GameState.new(seed=10)
    state_a.character.name = "Alpha"
    save(state_a, path)

    state_b = GameState.new(seed=20)
    state_b.character.name = "Beta"
    save(state_b, path)

    loaded = load(path)
    assert loaded.character.name == "Beta"
    assert loaded.seed == 20


# ---------------------------------------------------------------------------
# U3 / TUI-6: v2→v3 migration adds pending_freetext.
# ---------------------------------------------------------------------------


class TestV2ToV3Migration:
    """v2 saves migrate to v3 with pending_freetext=None."""

    def test_v2_save_loads_with_pending_freetext_none(self, tmp_path: Path):
        """A v2 save loads at current version with pending_freetext defaulted to None."""
        from src.engine.state import GameState

        v2 = json.loads(GameState.new(seed=7).model_dump_json())
        v2["save_version"] = 2
        v2.pop("pending_freetext", None)
        p = tmp_path / "v2.json"
        p.write_text(json.dumps(v2))
        loaded = load(p)
        assert loaded.save_version == current_save_version()
        assert loaded.pending_freetext is None

    def test_v3_save_round_trips_pending_freetext(self, tmp_path: Path):
        """A v3 save with pending_freetext set round-trips correctly."""
        from src.engine.state import GameState

        state = GameState.new(seed=42)
        state.pending_freetext = {
            "text": "I bribe the guard",
            "check": {
                "label": "Bribe",
                "skill": "broker",
                "characteristic": "SOC",
                "difficulty": "average",
            },
            "scaffold": {
                "focus": "Dock",
                "focus_description": "Busy",
                "situation": "Tense",
                "npc_hint": "",
            },
            "options": [],
        }
        p = tmp_path / "v3.json"
        save(state, p)
        loaded = load(p)
        assert loaded.save_version == current_save_version()
        assert loaded.pending_freetext is not None
        assert loaded.pending_freetext["text"] == "I bribe the guard"
        assert loaded.pending_freetext["check"]["skill"] == "broker"

    def test_current_save_version_is_4(self):
        """CURRENT_SAVE_VERSION is 4 after U8."""
        assert current_save_version() == 4


# ---------------------------------------------------------------------------
# U8: v3→v4 migration adds pending_hook.
# ---------------------------------------------------------------------------


class TestV3ToV4Migration:
    """v3 saves migrate to v4 with pending_hook=None."""

    def test_v3_save_loads_with_pending_hook_none(self, tmp_path: Path):
        """A v3 save loads at v4 with pending_hook defaulted to None."""
        from src.engine.state import GameState

        v3 = json.loads(GameState.new(seed=7).model_dump_json())
        v3["save_version"] = 3
        v3.pop("pending_hook", None)
        p = tmp_path / "v3.json"
        p.write_text(json.dumps(v3))
        loaded = load(p)
        assert loaded.save_version == 4
        assert loaded.pending_hook is None

    def test_v4_save_round_trips_pending_hook(self, tmp_path: Path):
        """A v4 save with pending_hook set round-trips correctly."""
        from src.engine.state import GameState

        state = GameState.new(seed=42)
        state.pending_hook = {
            "patron": "Navy",
            "objective": "Recover cargo",
            "complication": "Pirates",
            "reward": "100k Cr",
            "description": "A Navy mission.",
        }
        p = tmp_path / "v4.json"
        save(state, p)
        loaded = load(p)
        assert loaded.save_version == 4
        assert loaded.pending_hook is not None
        assert loaded.pending_hook["patron"] == "Navy"
        assert loaded.pending_hook["objective"] == "Recover cargo"
