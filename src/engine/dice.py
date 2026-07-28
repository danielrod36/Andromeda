"""Named seeded RNG streams and the Roller protocol.

One ``random.Random`` per subsystem (oracle, lifepath, combat) so rolls in one
stream never shift another's sequence. RNG state is captured via
``getstate()``/``setstate()`` and stored inside :class:`GameState` as
serializable snapshots. Pydantic field serializers convert the internal-state
tuple to/from a list so JSON round-trips losslessly (``setstate`` requires
tuples; JSON has no tuples).

Tests inject forced-result queues via :class:`ForcedRoller`.

Never use module-level ``random``.
"""
from __future__ import annotations

import random
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, PrivateAttr


# The canonical named streams. New streams are added here when their subsystem
# lands (combat is included from the start per the U1 spec; loot/post-v1).
STREAM_NAMES: tuple[str, ...] = ("oracle", "lifepath", "combat")


class RollSpec(BaseModel):
    """Specification of a dice roll: stream, dice count, sides, modifiers."""

    stream: str
    ndice: int
    sides: int
    modifiers: int = 0


class RollResult(BaseModel):
    """Outcome of a dice roll — recorded in the audit log (R4, AE1).

    Carries every input (stream, dice, sides, modifiers) and the outcome
    (individual die values and total) so fairness is inspectable after the fact.
    """

    stream: str
    ndice: int
    sides: int
    modifiers: int
    rolls: list[int]
    total: int


@runtime_checkable
class Roller(Protocol):
    """Protocol for dice rolling.

    Production uses :class:`LiveRoller` (backed by :class:`RngStreams` inside
    ``GameState``); tests use :class:`ForcedRoller` to inject deterministic
    results.
    """

    def roll(
        self, stream: str, ndice: int, sides: int, modifiers: int = 0
    ) -> RollResult: ...


class RngSnapshot(BaseModel):
    """JSON-serializable snapshot of one ``random.Random``'s internal state.

    ``random.Random.getstate()`` returns ``(version, internalstate, gauss_next)``
    where ``internalstate`` is a tuple of ints. Tuples become lists on JSON
    round-trip, and ``setstate()`` requires tuples, so we store as a list and
    convert back on hydration.
    """

    version: int
    internalstate: list[int]
    gauss_next: float | None

    @classmethod
    def from_random(cls, r: random.Random) -> RngSnapshot:
        version, internalstate, gauss_next = r.getstate()
        return cls(
            version=version,
            internalstate=list(internalstate),
            gauss_next=gauss_next,
        )

    def to_random(self) -> random.Random:
        r = random.Random()
        # setstate requires tuples; JSON round-trips tuples to lists.
        r.setstate(
            (self.version, tuple(self.internalstate), self.gauss_next)
        )
        return r


class RngStreams(BaseModel):
    """Named RNG stream snapshots stored inside :class:`GameState`.

    Each named stream has its own ``random.Random`` so rolls don't interfere
    (rolling oracle never shifts lifepath's next result). Snapshots are kept in
    sync after every roll so the model is always serializable. On load,
    ``model_post_init`` rehydrates live instances from the snapshots.
    """

    oracle: RngSnapshot
    lifepath: RngSnapshot
    combat: RngSnapshot

    # Live instances — not serialized; rebuilt from snapshots on load.
    _live: dict[str, random.Random] = PrivateAttr(default_factory=dict)

    def model_post_init(self, __context: object) -> None:
        self._hydrate()

    def _hydrate(self) -> None:
        """Rebuild live ``Random`` instances from serializable snapshots.

        Called after validation (including ``model_validate_json``) and should
        be called after any ``model_copy(deep=True)`` to refresh the live
        instances.
        """
        self._live = {}
        for name in STREAM_NAMES:
            snap: RngSnapshot = getattr(self, name)
            self._live[name] = snap.to_random()

    def roll(
        self, stream: str, ndice: int, sides: int, modifiers: int = 0
    ) -> RollResult:
        """Roll ``ndice`` dice of ``sides`` on the named stream."""
        if stream not in self._live:
            known = sorted(self._live)
            raise ValueError(f"Unknown RNG stream: {stream!r}. Known: {known}")
        r = self._live[stream]
        rolls = [r.randint(1, sides) for _ in range(ndice)]
        total = sum(rolls) + modifiers
        # Keep the serializable snapshot current.
        setattr(self, stream, RngSnapshot.from_random(r))
        return RollResult(
            stream=stream,
            ndice=ndice,
            sides=sides,
            modifiers=modifiers,
            rolls=rolls,
            total=total,
        )

    def snapshot(self) -> dict[str, RngSnapshot]:
        """Return current snapshots of all streams (useful for debugging/tests)."""
        return {name: RngSnapshot.from_random(self._live[name]) for name in STREAM_NAMES}

    @classmethod
    def seeded(cls, seed: int) -> RngStreams:
        """Create streams with deterministic per-stream seeds.

        Each stream derives its own seed from ``f"{seed}:{name}"`` so two
        ``GameState.new(seed=42)`` instances produce identical stream states,
        while streams within one state are independent (the seed strings
        differ, so the sequences diverge).
        """
        kwargs: dict[str, RngSnapshot] = {}
        for name in STREAM_NAMES:
            # String seeds are a supported random.Random seed type; the name
            # suffix makes per-stream sequences independent while keeping the
            # base seed as the determinism key.
            r = random.Random(f"{seed}:{name}")
            kwargs[name] = RngSnapshot.from_random(r)
        return cls(**kwargs)


class LiveRoller:
    """Production :class:`Roller` backed by :class:`RngStreams` in ``GameState``.

    Mutating the streams through ``roll`` updates the live ``random.Random``
    instances and their serializable snapshots in place, so state stays
    consistent for save/load at any moment.
    """

    def __init__(self, streams: RngStreams) -> None:
        self._streams = streams

    @property
    def streams(self) -> RngStreams:
        return self._streams

    def roll(
        self, stream: str, ndice: int, sides: int, modifiers: int = 0
    ) -> RollResult:
        return self._streams.roll(stream, ndice, sides, modifiers)


class ForcedRoller:
    """Test :class:`Roller` that returns queued dice values in FIFO order.

    Each queued entry is a list of individual die pip values (e.g. ``[3, 5]``
    for a 2D6 roll). The roller pops entries in order and assembles a full
    :class:`RollResult` from the call's parameters, so the audit log still
    records the correct stream/dice/modifiers.
    """

    def __init__(self, queued_rolls: list[list[int]] | None = None) -> None:
        self._queue: list[list[int]] = list(queued_rolls or [])

    def roll(
        self, stream: str, ndice: int, sides: int, modifiers: int = 0
    ) -> RollResult:
        if not self._queue:
            raise IndexError("ForcedRoller queue exhausted")
        rolls = self._queue.pop(0)
        return RollResult(
            stream=stream,
            ndice=ndice,
            sides=sides,
            modifiers=modifiers,
            rolls=list(rolls),
            total=sum(rolls) + modifiers,
        )

    def extend(self, more: list[list[int]]) -> None:
        """Append more queued rolls."""
        self._queue.extend(more)

    @property
    def remaining(self) -> int:
        return len(self._queue)
