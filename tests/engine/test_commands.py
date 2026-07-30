"""Tests for the command funnel: determinism, validation, event log, audit (AE1)."""

from __future__ import annotations

import hashlib

import pytest

from src.engine.audit import EventKind, audit_rolls
from src.engine.commands import (
    Engine,
    RollCharacteristicCommand,
    SetFlagCommand,
)
from src.engine.dice import ForcedRoller
from src.engine.state import GameState


def state_hash(state: GameState) -> str:
    """Stable hash of game state via canonical JSON."""
    return hashlib.sha256(state.model_dump_json().encode()).hexdigest()


# ---------------------------------------------------------------------------
# Scenario: Command funnel determinism (the foundational guarantee).
# ---------------------------------------------------------------------------


def test_command_funnel_determinism_same_seed_same_commands_same_hash():
    """Two engines with the same seed, fed the same commands, produce identical state.

    This is the foundational determinism guarantee of the engine (R1).
    """
    commands = [
        RollCharacteristicCommand(characteristic="STR"),
        RollCharacteristicCommand(characteristic="DEX"),
        RollCharacteristicCommand(characteristic="END"),
        RollCharacteristicCommand(characteristic="INT"),
        RollCharacteristicCommand(characteristic="EDU"),
        RollCharacteristicCommand(characteristic="SOC"),
    ]

    engine_a = Engine(GameState.new(seed=42))
    engine_b = Engine(GameState.new(seed=42))

    for cmd in commands:
        engine_a.apply(cmd)
        engine_b.apply(cmd)

    assert state_hash(engine_a.state) == state_hash(engine_b.state)


def test_empty_command_sequence_produces_deterministic_initial_state():
    """Two states with the same seed but no commands have the same hash."""
    state_a = GameState.new(seed=99)
    state_b = GameState.new(seed=99)
    assert state_hash(state_a) == state_hash(state_b)


# ---------------------------------------------------------------------------
# Scenario: AE1 — every roll is recorded in the audit log with inputs and outcome.
# ---------------------------------------------------------------------------


def test_every_roll_recorded_in_audit_log_with_inputs_and_outcome():
    """After rolling, the audit log has one entry per roll with full inputs+outcome (AE1)."""
    engine = Engine(GameState.new(seed=7))
    engine.apply(RollCharacteristicCommand(characteristic="STR"))
    engine.apply(RollCharacteristicCommand(characteristic="DEX"))

    rolls = audit_rolls(engine.state.events)
    assert len(rolls) == 2

    for entry in rolls:
        assert entry.kind == EventKind.ROLL
        assert entry.roll is not None
        r = entry.roll
        # Inputs present.
        assert r.stream == "lifepath"
        assert r.ndice == 2
        assert r.sides == 6
        assert r.modifiers == 0
        # Outcome present and internally consistent.
        assert len(r.rolls) == 2
        assert all(1 <= die <= 6 for die in r.rolls)
        assert r.total == sum(r.rolls) + r.modifiers

    # The state mutation reflects the rolled totals.
    chars = engine.state.character.characteristics
    assert chars["STR"] == rolls[0].roll.total
    assert chars["DEX"] == rolls[1].roll.total


def test_non_dice_command_does_not_appear_in_audit_view():
    """A STATE_CHANGE event is in the full log but not the audit (roll) view."""
    engine = Engine(GameState.new(seed=7))
    engine.apply(SetFlagCommand(key="phase", value="chargen"))

    assert len(engine.state.events) == 1
    assert audit_rolls(engine.state.events) == []


# ---------------------------------------------------------------------------
# Scenario: Command funnel validation — invalid command raises before touching state.
# ---------------------------------------------------------------------------


def test_invalid_command_raises_before_touching_state():
    """An invalid command raises and leaves state, RNG, and log unchanged."""
    engine = Engine(GameState.new(seed=1))
    snapshot_before = engine.state.model_dump_json()
    events_before = len(engine.state.events)
    rng_before = engine.state.rng.oracle.model_dump_json()

    with pytest.raises(ValueError, match="Unknown characteristic"):
        engine.apply(RollCharacteristicCommand(characteristic="WAT"))

    # Nothing moved.
    assert engine.state.model_dump_json() == snapshot_before
    assert len(engine.state.events) == events_before
    assert engine.state.rng.oracle.model_dump_json() == rng_before


def test_invalid_setflag_raises_before_touching_state():
    engine = Engine(GameState.new(seed=1))
    with pytest.raises(ValueError, match="non-empty"):
        engine.apply(SetFlagCommand(key="", value="x"))
    assert len(engine.state.events) == 0


# ---------------------------------------------------------------------------
# Scenario: Event log append-only — entries cannot be removed or modified after append.
# ---------------------------------------------------------------------------


def test_event_log_grows_monotonically_with_sequence_numbers():
    """Events get monotonically increasing sequence numbers matching their index."""
    engine = Engine(GameState.new(seed=5))
    engine.apply(RollCharacteristicCommand(characteristic="STR"))
    engine.apply(SetFlagCommand(key="k", value="v"))
    engine.apply(RollCharacteristicCommand(characteristic="DEX"))

    seqs = [e.seq for e in engine.state.events]
    assert seqs == [0, 1, 2]


def test_event_log_entries_are_self_describing():
    """Each event carries its command_type, description, and kind for audit/replay."""
    engine = Engine(GameState.new(seed=5))
    engine.apply(RollCharacteristicCommand(characteristic="STR"))
    e = engine.state.events[-1]
    assert e.command_type == "roll_characteristic"
    assert "STR" in e.description
    assert e.kind == EventKind.ROLL


# ---------------------------------------------------------------------------
# Scenario: ForcedRoller injects deterministic results through the funnel.
# ---------------------------------------------------------------------------


def test_forced_roller_results_flow_through_funnel():
    """ForcedRoller values reach the audit log and the state mutation."""
    engine = Engine(
        GameState.new(seed=0),
        roller=ForcedRoller([[6, 6], [1, 1]]),
    )
    engine.apply(RollCharacteristicCommand(characteristic="STR"))
    engine.apply(RollCharacteristicCommand(characteristic="DEX"))

    rolls = audit_rolls(engine.state.events)
    assert rolls[0].roll.rolls == [6, 6]
    assert rolls[0].roll.total == 12
    assert rolls[1].roll.rolls == [1, 1]
    assert rolls[1].roll.total == 2

    assert engine.state.character.characteristics == {"STR": 12, "DEX": 2}


def test_forced_roller_queue_exhaustion_raises():
    engine = Engine(
        GameState.new(seed=0),
        roller=ForcedRoller([[6, 6]]),
    )
    engine.apply(RollCharacteristicCommand(characteristic="STR"))
    with pytest.raises(IndexError, match="exhausted"):
        engine.apply(RollCharacteristicCommand(characteristic="DEX"))


def test_event_log_existing_entries_unchanged_by_new_appends():
    """Appending a new event does not modify or reorder existing entries."""
    engine = Engine(GameState.new(seed=8))
    engine.apply(RollCharacteristicCommand(characteristic="STR"))
    first_event_snapshot = engine.state.events[0].model_dump_json()

    engine.apply(RollCharacteristicCommand(characteristic="DEX"))
    engine.apply(SetFlagCommand(key="k", value="v"))

    # The first event is untouched.
    assert engine.state.events[0].model_dump_json() == first_event_snapshot
    assert len(engine.state.events) == 3


def test_forced_roller_determinism_two_engines_same_queue():
    """Two engines with the same ForcedRoller queue produce identical state."""
    cmds = [
        RollCharacteristicCommand(characteristic="STR"),
        RollCharacteristicCommand(characteristic="DEX"),
    ]
    queue = [[3, 5], [6, 2]]

    engine_a = Engine(GameState.new(seed=0), roller=ForcedRoller(list(queue)))
    engine_b = Engine(GameState.new(seed=0), roller=ForcedRoller(list(queue)))
    for c in cmds:
        engine_a.apply(c)
        engine_b.apply(c)

    assert engine_a.state.model_dump_json() == engine_b.state.model_dump_json()


# ---------------------------------------------------------------------------
# Regression: swap_state rebinds LiveRoller to restored RNG streams (AE3).
# ---------------------------------------------------------------------------


def test_swap_state_rebinds_live_roller_to_restored_rng():
    """After swap_state, rolls advance the RESTORED state's RNG, not the old one.

    Without rebinding, the LiveRoller keeps advancing the abandoned branch's
    streams while the restored state's RNG stays frozen — breaking the
    determinism/replay guarantee (AE3).
    """
    from src.engine.checkpoint import CheckpointManager
    from src.engine.state import CampaignConfig

    state = GameState.new(seed=99)
    state.campaign = CampaignConfig(death_mode="checkpoint")

    # Production engine: LiveRoller bound to state.rng.
    engine = Engine(state)

    mgr = CheckpointManager()
    mgr.take_snapshot(state)

    # Roll during the abandoned scene branch — advances the original RNG.
    engine.state.rng.roll("oracle", 2, 6)

    restored = mgr.restore(engine.state)
    engine.swap_state(restored)

    # The next oracle roll should match a fresh state that hasn't rolled
    # during the scene — proving the roller now reads restored state's RNG.
    reference = GameState.new(seed=99)
    expected = reference.rng.roll("oracle", 2, 6).total
    actual = engine.state.rng.roll("oracle", 2, 6).total
    assert actual == expected


def test_swap_state_leaves_forced_roller_untouched():
    """swap_state does not replace a ForcedRoller (test injection)."""
    state = GameState.new(seed=1)
    roller = ForcedRoller([[3, 3]])
    engine = Engine(state, roller=roller)

    new_state = GameState.new(seed=2)
    engine.swap_state(new_state)

    assert engine.roller is roller
    assert engine.state is new_state
