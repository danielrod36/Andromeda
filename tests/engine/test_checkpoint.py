"""Tests for scene-start checkpoint snapshot/restore infrastructure (AE3).

Covers:
- AE3: Checkpoint rewind restores canonical state to scene start, byte-identical,
  including removal of LLM-registered facts introduced during the scene.
- AE3: Audit log is preserved across rewind (append-only, excluded from restore).
- Scene boundary definition: snapshot taken at each F4 cycle start.
- Snapshot includes all canonical state: character, campaign, world, narrative log.
- Snapshot persistence: save game mid-scene, relaunch, rewind still works.
- RNG hydration works correctly after model_copy.
"""

from __future__ import annotations

import pytest

from src.engine.checkpoint import CheckpointManager
from src.engine.persistence import load, save
from src.engine.state import CampaignConfig, GameState, NarrativeFact

# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def make_state(seed: int = 42, death_mode: str = "checkpoint") -> GameState:
    """Create a GameState with some character data and entities."""
    state = GameState.new(seed=seed)
    state.campaign = CampaignConfig(death_mode=death_mode)
    state.character.name = "Captain Vega"
    state.character.age = 34
    state.character.characteristics = {
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    state.character.skills = {"Gun Combat": 1, "Pilot": 2}
    state.narrative_log.append("Campaign started.")
    state.narrative_log.append("Arrived at station.")
    return state


# ---------------------------------------------------------------------------
# AE3: Byte-identical canonical state restoration.
# ---------------------------------------------------------------------------


class TestByteIdenticalRestore:
    """Checkpoint rewind restores canonical state to scene start, byte-identical."""

    def test_character_restored_byte_identical(self):
        """Character state matches scene-start snapshot after rewind."""
        state = make_state()
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        # Record the character JSON at snapshot time.
        char_json = state.character.model_dump_json()

        # Mutate character during the scene.
        state.character.age = 50
        state.character.skills["Gun Combat"] = 5
        state.character.alive = False

        restored = mgr.restore(state)
        assert restored.character.model_dump_json() == char_json

    def test_campaign_restored_byte_identical(self):
        """Campaign config matches scene-start snapshot after rewind."""
        state = make_state()
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        campaign_json = state.campaign.model_dump_json()

        # Change campaign during scene.
        state.campaign.resolution_profile = "classic"

        restored = mgr.restore(state)
        assert restored.campaign.model_dump_json() == campaign_json

    def test_narrative_log_restored_byte_identical(self):
        """Narrative log reverts to scene-start state."""
        state = make_state()
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        log_snapshot = list(state.narrative_log)

        # Add narration entries during the scene.
        state.narrative_log.append("Scene narration: pirates attack!")
        state.narrative_log.append("The character fights bravely.")

        restored = mgr.restore(state)
        assert restored.narrative_log == log_snapshot

    def test_llm_registered_facts_removed_on_rewind(self):
        """Narrative facts introduced during the scene are removed by rewind."""
        state = make_state()
        # Pre-existing entity at scene start.
        state.entities.append(NarrativeFact(name="Station Alpha"))
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        entity_jsons = [e.model_dump_json() for e in state.entities]

        # Simulate LLM registering new facts during the scene.
        state.entities.append(NarrativeFact(name="Pirate Captain"))
        state.entities.append(NarrativeFact(name="Hidden Cargo"))

        assert len(state.entities) == 3

        restored = mgr.restore(state)

        # The two scene-introduced facts must be gone; only Station Alpha remains.
        restored_jsons = [e.model_dump_json() for e in restored.entities]
        assert restored_jsons == entity_jsons
        assert len(restored.entities) == 1
        assert restored.entities[0].name == "Station Alpha"

    def test_rng_streams_restored_byte_identical(self):
        """RNG stream snapshots match scene-start state after rewind."""
        state = make_state()
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        rng_json = state.rng.model_dump_json()

        # Advance RNG during the scene.
        state.rng.roll("oracle", 2, 6)
        state.rng.roll("combat", 2, 6)

        restored = mgr.restore(state)
        assert restored.rng.model_dump_json() == rng_json

    def test_rng_continues_same_sequence_after_restore(self):
        """After rewind, the next RNG roll matches the scene-start sequence."""
        state = make_state()
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        # Roll during the scene (abandoned branch).
        state.rng.roll("oracle", 2, 6)

        restored = mgr.restore(state)

        # The restored state's next oracle roll should match a fresh state
        # that hasn't rolled during the scene.
        reference = make_state()
        expected = reference.rng.roll("oracle", 2, 6)
        actual = restored.rng.roll("oracle", 2, 6)
        assert actual.rolls == expected.rolls
        assert actual.total == expected.total


# ---------------------------------------------------------------------------
# AE3: Audit log preserved across rewind (append-only).
# ---------------------------------------------------------------------------


class TestAuditLogPreserved:
    """The event log is append-only and excluded from rewind."""

    def test_events_from_abandoned_branch_retained(self):
        """Events from the abandoned scene branch stay in the log after rewind."""
        from src.engine.commands import Engine, SetFlagCommand
        from src.engine.dice import ForcedRoller

        engine = Engine(make_state(), roller=ForcedRoller([]))
        # Apply some commands before snapshot (pre-scene events).
        engine.apply(SetFlagCommand(key="pre_scene", value="yes"))
        pre_scene_count = len(engine.state.events)

        mgr = CheckpointManager()
        mgr.take_snapshot(engine.state)

        # Apply commands during the scene (abandoned branch events).
        engine.apply(SetFlagCommand(key="during_scene", value="attack"))
        engine.apply(SetFlagCommand(key="during_scene_2", value="retreat"))

        assert len(engine.state.events) == pre_scene_count + 2

        restored = mgr.restore(engine.state)

        # All events from the abandoned branch are retained.
        assert len(restored.events) == pre_scene_count + 2 + 1  # + RewindApplied
        # The pre-scene and during-scene events are all still there.
        assert restored.events[0].changes["key"] == "pre_scene"
        assert restored.events[1].changes["key"] == "during_scene"
        assert restored.events[2].changes["key"] == "during_scene_2"

    def test_rewind_applied_event_appended(self):
        """A REWIND_APPLIED event is appended after rewind."""
        from src.engine.audit import EventKind

        state = make_state()
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        # Simulate events during the scene by appending directly.
        from src.engine.audit import Event

        state.events.append(
            Event(
                seq=0,
                kind=EventKind.STATE_CHANGE,
                command_type="test_event",
                description="Something happened during the scene.",
            )
        )

        restored = mgr.restore(state)

        last_event = restored.events[-1]
        assert last_event.kind == EventKind.REWIND_APPLIED
        assert last_event.command_type == "rewind_applied"
        assert last_event.changes["abandoned_branch_events"] == 1

    def test_rewind_applied_seq_is_correct(self):
        """The RewindApplied event gets the correct sequence number."""
        from src.engine.audit import Event, EventKind

        state = make_state()
        # Add 3 events before snapshot.
        for i in range(3):
            state.events.append(
                Event(
                    seq=i,
                    kind=EventKind.STATE_CHANGE,
                    command_type="pre",
                    description=f"Pre-scene event {i}",
                )
            )

        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        # Add 2 events during the scene.
        for i in range(2):
            state.events.append(
                Event(
                    seq=3 + i,
                    kind=EventKind.STATE_CHANGE,
                    command_type="during",
                    description=f"During-scene event {i}",
                )
            )

        restored = mgr.restore(state)

        # RewindApplied should be seq=5 (0-indexed, 5th event).
        assert restored.events[-1].seq == 5
        assert len(restored.events) == 6

    def test_empty_events_at_snapshot_still_works(self):
        """Restore works when no events existed at snapshot time."""
        from src.engine.audit import EventKind

        state = make_state()
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        restored = mgr.restore(state)

        assert len(restored.events) == 1
        assert restored.events[0].kind == EventKind.REWIND_APPLIED


# ---------------------------------------------------------------------------
# Scene boundary definition.
# ---------------------------------------------------------------------------


class TestSceneBoundary:
    """Snapshot is taken at each F4 cycle (scene) start."""

    def test_take_snapshot_makes_snapshot_available(self):
        """has_snapshot is True after take_snapshot."""
        state = make_state()
        mgr = CheckpointManager()
        assert not mgr.has_snapshot

        mgr.take_snapshot(state)
        assert mgr.has_snapshot

    def test_take_snapshot_replaces_previous(self):
        """A second take_snapshot replaces the first (depth-1 slot)."""
        state = make_state()
        mgr = CheckpointManager()

        state.narrative_log.append("Scene 1 start")
        mgr.take_snapshot(state)

        state.narrative_log.append("Scene 1 narration")
        state.narrative_log.append("Scene 2 start")
        mgr.take_snapshot(state)

        state.narrative_log.append("Scene 2 narration")

        restored = mgr.restore(state)
        # The snapshot should be from scene 2 start, not scene 1.
        assert "Scene 2 start" in restored.narrative_log
        assert "Scene 2 narration" not in restored.narrative_log

    def test_restore_without_snapshot_raises(self):
        """Restore raises RuntimeError if no snapshot was taken."""
        state = make_state()
        mgr = CheckpointManager()
        with pytest.raises(RuntimeError, match="No checkpoint snapshot"):
            mgr.restore(state)

    def test_clear_removes_snapshot(self):
        """clear() discards the snapshot."""
        state = make_state()
        mgr = CheckpointManager()
        mgr.take_snapshot(state)
        assert mgr.has_snapshot

        mgr.clear()
        assert not mgr.has_snapshot

        with pytest.raises(RuntimeError):
            mgr.restore(state)

    def test_restore_does_not_mutate_current_state(self):
        """Restore returns a new state; the input state is not modified."""
        state = make_state()
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        state.character.age = 99
        original_events_count = len(state.events)

        restored = mgr.restore(state)

        # The input state is unchanged.
        assert state.character.age == 99
        assert len(state.events) == original_events_count
        # The restored state has the snapshot's age + RewindApplied event.
        assert restored.character.age == 34

    def test_stored_snapshot_not_mutated_by_repeated_restore(self):
        """The stored snapshot is not mutated by restore; repeated restores work."""
        state = make_state()
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        state.character.age = 50
        restored1 = mgr.restore(state)
        assert restored1.character.age == 34

        # The snapshot should still be intact for a second restore.
        state2 = make_state()
        state2.character.age = 60
        restored2 = mgr.restore(state2)
        assert restored2.character.age == 34


# ---------------------------------------------------------------------------
# Snapshot includes all canonical state.
# ---------------------------------------------------------------------------


class TestSnapshotCompleteness:
    """The snapshot captures all canonical state: character, campaign, world,
    narrative log, RNG streams."""

    def test_snapshot_captures_full_state(self):
        """All canonical fields are captured by the snapshot."""
        state = make_state()
        state.entities.append(NarrativeFact(name="World Entity"))
        state.completed_missions.append({"id": "mission_1", "ending": "success"})

        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        # Mutate everything.
        state.character.name = "Changed"
        state.character.alive = False
        state.campaign.death_mode = "ironman"
        state.entities.append(NarrativeFact(name="New Entity"))
        state.narrative_log.append("New entry")
        state.completed_missions.append({"id": "mission_2"})
        state.rng.roll("oracle", 2, 6)

        restored = mgr.restore(state)

        assert restored.character.name == "Captain Vega"
        assert restored.character.alive is True
        assert restored.campaign.death_mode == "checkpoint"
        assert len(restored.entities) == 1
        assert restored.entities[0].name == "World Entity"
        assert "New entry" not in restored.narrative_log
        assert len(restored.completed_missions) == 1
        assert restored.completed_missions[0]["id"] == "mission_1"


# ---------------------------------------------------------------------------
# RNG hydration after model_copy.
# ---------------------------------------------------------------------------


class TestRngHydration:
    """RngStreams._hydrate() must be called after model_copy(deep=True)."""

    def test_restored_rng_produces_live_rolls(self):
        """The restored state's RNG can actually roll (live instances exist)."""
        state = make_state()
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        state.rng.roll("oracle", 2, 6)
        state.rng.roll("lifepath", 2, 6)
        state.rng.roll("combat", 2, 6)

        restored = mgr.restore(state)

        # These should not raise — live Random instances exist.
        result = restored.rng.roll("oracle", 2, 6)
        assert len(result.rolls) == 2
        result = restored.rng.roll("lifepath", 2, 6)
        assert len(result.rolls) == 2
        result = restored.rng.roll("combat", 2, 6)
        assert len(result.rolls) == 2


# ---------------------------------------------------------------------------
# Snapshot persistence.
# ---------------------------------------------------------------------------


class TestSnapshotPersistence:
    """Snapshot persistence: save game mid-scene, relaunch, rewind still works."""

    def test_save_and_load_snapshot_round_trip(self, tmp_path):
        """A snapshot saved to disk loads back and can restore."""
        state = make_state()
        mgr = CheckpointManager()
        mgr.take_snapshot(state)

        # Mutate after snapshot.
        state.character.age = 50
        state.entities.append(NarrativeFact(name="Scene Entity"))

        # Persist the snapshot.
        save_path = tmp_path / "campaign.json"
        mgr.save_snapshot(save_path)
        assert (tmp_path / "campaign.json.checkpoint.json").exists()

        # Relaunch: new manager, load snapshot from disk.
        mgr2 = CheckpointManager()
        assert not mgr2.has_snapshot
        loaded = mgr2.load_snapshot(save_path)
        assert loaded
        assert mgr2.has_snapshot

        restored = mgr2.restore(state)
        assert restored.character.age == 34
        assert len(restored.entities) == 0  # Scene Entity removed.

    def test_load_snapshot_missing_file_returns_false(self, tmp_path):
        """load_snapshot returns False when no checkpoint file exists."""
        mgr = CheckpointManager()
        result = mgr.load_snapshot(tmp_path / "nonexistent.json")
        assert result is False
        assert not mgr.has_snapshot

    def test_save_snapshot_without_snapshot_returns_none(self, tmp_path):
        """save_snapshot returns None when no snapshot exists."""
        mgr = CheckpointManager()
        result = mgr.save_snapshot(tmp_path / "campaign.json")
        assert result is None

    def test_full_save_load_rewind_cycle(self, tmp_path):
        """Full cycle: save mid-scene, load game + snapshot, rewind works."""
        from src.engine.commands import Engine, SetFlagCommand
        from src.engine.dice import ForcedRoller

        engine = Engine(make_state(), roller=ForcedRoller([]))
        engine.apply(SetFlagCommand(key="pre_scene", value="setup"))

        mgr = CheckpointManager()
        mgr.take_snapshot(engine.state)

        # Mid-scene: apply more commands.
        engine.apply(SetFlagCommand(key="mid_scene", value="combat"))

        # Save both game state and snapshot.
        save_path = tmp_path / "save.json"
        save(engine.state, save_path)
        mgr.save_snapshot(save_path)

        # Simulate relaunch.
        loaded_state = load(save_path)
        mgr2 = CheckpointManager()
        mgr2.load_snapshot(save_path)

        # Rewind should work with the loaded state.
        restored = mgr2.restore(loaded_state)

        # Canonical state reverts to pre-scene.
        assert restored.character.age == 34
        # Events are append-only: pre-scene + mid-scene + RewindApplied.
        assert len(restored.events) == 3
        assert restored.events[-1].kind.value == "rewind_applied"
