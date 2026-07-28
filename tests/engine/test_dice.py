"""Tests for named seeded RNG streams and the Roller protocol."""
from __future__ import annotations

import random

import pytest

from src.engine.dice import (
    ForcedRoller,
    LiveRoller,
    Roller,
    RngSnapshot,
    RngStreams,
    RollResult,
)


# ---------------------------------------------------------------------------
# Scenario: Dice determinism — random.Random(42) produces identical sequences.
# ---------------------------------------------------------------------------


def test_random_random_42_produces_identical_sequences():
    """Bare random.Random determinism — the guarantee our streams are built on."""
    a = random.Random(42)
    b = random.Random(42)
    assert [a.randint(1, 6) for _ in range(20)] == [b.randint(1, 6) for _ in range(20)]


def test_seeded_rng_streams_produce_identical_sequences_for_same_seed():
    """Two RngStreams.seeded with the same seed produce identical rolls per stream."""
    a = RngStreams.seeded(seed=42)
    b = RngStreams.seeded(seed=42)
    for stream in ("oracle", "lifepath", "combat"):
        rolls_a = [a.roll(stream, 2, 6).total for _ in range(10)]
        rolls_b = [b.roll(stream, 2, 6).total for _ in range(10)]
        assert rolls_a == rolls_b


def test_different_seeds_produce_different_sequences():
    a = RngStreams.seeded(seed=42)
    b = RngStreams.seeded(seed=43)
    rolls_a = [a.roll("lifepath", 2, 6).total for _ in range(10)]
    rolls_b = [b.roll("lifepath", 2, 6).total for _ in range(10)]
    assert rolls_a != rolls_b


# ---------------------------------------------------------------------------
# Scenario: Multiple RNG streams do not interfere with each other.
# ---------------------------------------------------------------------------


def test_streams_are_independent_rolling_one_does_not_shift_another():
    """Rolling oracle does not change the next lifepath roll (key independence guarantee)."""
    # Baseline: roll lifepath first, oracle never touched.
    baseline = RngStreams.seeded(seed=42)
    baseline_lifepath = [baseline.roll("lifepath", 2, 6).total for _ in range(5)]

    # Interleaved: roll oracle between each lifepath roll.
    interleaved = RngStreams.seeded(seed=42)
    interleaved_results = []
    for _ in range(5):
        # Roll oracle — must not affect lifepath's sequence.
        interleaved.roll("oracle", 2, 6)
        interleaved_results.append(interleaved.roll("lifepath", 2, 6).total)

    assert interleaved_results == baseline_lifepath


def test_streams_are_independent_combat_does_not_shift_lifepath():
    baseline = RngStreams.seeded(seed=100)
    baseline_lp = [baseline.roll("lifepath", 1, 6).total for _ in range(8)]

    interleaved = RngStreams.seeded(seed=100)
    interleaved_lp = []
    for _ in range(8):
        interleaved.roll("combat", 3, 6)
        interleaved.roll("oracle", 1, 100)
        interleaved_lp.append(interleaved.roll("lifepath", 1, 6).total)

    assert interleaved_lp == baseline_lp


def test_unknown_stream_raises():
    streams = RngStreams.seeded(seed=1)
    with pytest.raises(ValueError, match="Unknown RNG stream"):
        streams.roll("nonexistent", 2, 6)


# ---------------------------------------------------------------------------
# Scenario: RNG state round-trip via snapshot.
# ---------------------------------------------------------------------------


def test_rng_snapshot_round_trip_preserves_sequence():
    """Capturing a snapshot mid-sequence and restoring continues identically."""
    original = RngStreams.seeded(seed=42)
    # Roll a few times to advance state.
    for _ in range(3):
        original.roll("lifepath", 2, 6)

    # Snapshot and restore into a new instance.
    snap = original.snapshot()["lifepath"]
    restored = snap.to_random()

    # Both should produce the same subsequent rolls.
    original_next = [original.roll("lifepath", 2, 6).total for _ in range(5)]
    restored_next = [restored.randint(1, 6) + restored.randint(1, 6) for _ in range(5)]
    assert original_next == restored_next


def test_rng_snapshot_survives_json_round_trip():
    """Snapshot serializes to JSON and back without losing state (tuple→list→tuple)."""
    original = RngStreams.seeded(seed=42)
    for _ in range(3):
        original.roll("oracle", 2, 6)

    snap = original.snapshot()["oracle"]
    json_str = snap.model_dump_json()
    restored = RngSnapshot.model_validate_json(json_str)

    # The restored snapshot should produce the same next rolls as the original.
    original_next = [original.roll("oracle", 1, 6) for _ in range(5)]
    restored_r = restored.to_random()
    restored_next = [restored_r.randint(1, 6) for _ in range(5)]
    assert [r.total for r in original_next] == restored_next


# ---------------------------------------------------------------------------
# Scenario: RollResult records all inputs and the outcome.
# ---------------------------------------------------------------------------


def test_roll_result_carries_inputs_and_outcome():
    streams = RngStreams.seeded(seed=42)
    result = streams.roll("lifepath", ndice=3, sides=6, modifiers=2)
    assert result.stream == "lifepath"
    assert result.ndice == 3
    assert result.sides == 6
    assert result.modifiers == 2
    assert len(result.rolls) == 3
    assert all(1 <= d <= 6 for d in result.rolls)
    assert result.total == sum(result.rolls) + 2


def test_modifiers_apply_to_total():
    streams = RngStreams.seeded(seed=42)
    no_mod = streams.roll("lifepath", 2, 6, modifiers=0)
    # Reset by re-seeding to get same dice values with a modifier.
    streams2 = RngStreams.seeded(seed=42)
    with_mod = streams2.roll("lifepath", 2, 6, modifiers=-3)
    assert with_mod.rolls == no_mod.rolls
    assert with_mod.total == no_mod.total - 3


# ---------------------------------------------------------------------------
# Scenario: Roller protocol and LiveRoller / ForcedRoller.
# ---------------------------------------------------------------------------


def test_live_roller_is_runtime_checkable_roller():
    streams = RngStreams.seeded(seed=10)
    roller = LiveRoller(streams)
    assert isinstance(roller, Roller)
    result = roller.roll("lifepath", 2, 6)
    assert isinstance(result, RollResult)


def test_forced_roller_returns_queued_results_in_order():
    forced = ForcedRoller([[1, 2], [3, 4], [5, 6]])
    r1 = forced.roll("lifepath", 2, 6)
    assert r1.rolls == [1, 2]
    assert r1.total == 3
    r2 = forced.roll("oracle", 2, 6, modifiers=1)
    assert r2.rolls == [3, 4]
    assert r2.total == 8  # 7 + 1
    assert forced.remaining == 1


def test_forced_roller_extend():
    forced = ForcedRoller([[1, 1]])
    forced.extend([[2, 2], [3, 3]])
    assert forced.remaining == 3
    forced.roll("lifepath", 2, 6)
    forced.roll("lifepath", 2, 6)
    forced.roll("lifepath", 2, 6)
    assert forced.remaining == 0
