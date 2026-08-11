"""JSON save/load with ``save_version`` and atomic writes (R17).

Save files are single JSON documents. Writes are atomic: the document is
written to a sibling temp file then moved into place with ``os.replace`` so an
interrupted save leaves the previous file intact. Load runs any registered
stepwise migration so older saves upgrade to the current version on the way in.

No pickle, no SQLite — single-player, single-session, small documents.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from src.engine.state import GameState

#: Current save-file version. Bump when the schema changes; add a migrator.
CURRENT_SAVE_VERSION = 7


def _migrate_v1_to_v2(data: dict[str, object]) -> dict[str, object]:
    """Add v2 fields (Tasks 1–12 state) with defaults to v1 saves."""
    char = data.setdefault("character", {})
    assert isinstance(char, dict)
    char.setdefault("credits", 0)
    char.setdefault("inventory", [])
    char.setdefault("unassigned_rolls", [])
    char.setdefault("pool_rerolled", False)
    char.setdefault("career_history", [])
    char.setdefault("drafted", False)
    char.setdefault("background_picks_remaining", -1)
    char.setdefault("basic_training_done", False)
    char.setdefault("pending_aging", [])
    data.setdefault("open_threads", [])
    data.setdefault("mission_counter", 0)
    data["save_version"] = 2
    return data


def _migrate_v2_to_v3(data: dict[str, object]) -> dict[str, object]:
    """Add v3 field (pending_freetext) with default None to v2 saves (U3/TUI-6)."""
    data.setdefault("pending_freetext", None)
    data["save_version"] = 3
    return data


def _migrate_v3_to_v4(data: dict[str, object]) -> dict[str, object]:
    """Add v4 field (pending_hook) with default None to v3 saves (U8)."""
    data.setdefault("pending_hook", None)
    data["save_version"] = 4
    return data


def _migrate_v4_to_v5(data: dict[str, object]) -> dict[str, object]:
    """v4→v5: add Character.benefits_lost, debt_cr, mustered_careers (P3.T4)."""
    char = data.get("character", {})
    char.setdefault("benefits_lost", False)
    char.setdefault("debt_cr", 0)
    char.setdefault("mustered_careers", [])
    data["character"] = char
    data["save_version"] = 5
    return data


def _migrate_v5_to_v6(data: dict[str, object]) -> dict[str, object]:
    """v5→v6: add Character.pending_cascades (C3)."""
    char = data.get("character", {})
    char.setdefault("pending_cascades", [])
    data["character"] = char
    data["save_version"] = 6
    return data


def _migrate_v6_to_v7(data: dict[str, object]) -> dict[str, object]:
    """v6→v7: add CareerTermRecord.terms_in_career, delta-backfilled (C6, G4).

    ``terms_in_career`` is the number of terms served in THIS career stint.
    Older saves stored only ``terms`` (cumulative across all careers at the
    time of exit); we recover per-career terms by differencing successive
    records' cumulative values. The first record's per-career terms equals
    its cumulative terms.
    """
    char = data.get("character", {})
    history = char.get("career_history", [])
    previous_cumulative = 0
    for record in history:
        cumulative = record.get("terms", 0)
        record.setdefault("terms_in_career", cumulative - previous_cumulative)
        previous_cumulative = cumulative
    data["character"] = char
    data["save_version"] = 7
    return data


#: Migration functions keyed by source version. Each takes raw dict data at
#: version N and returns dict data at version N+1. ``migrate`` walks the chain.
_MIGRATIONS: dict[int, Callable[[dict[str, object]], dict[str, object]]] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
    3: _migrate_v3_to_v4,
    4: _migrate_v4_to_v5,
    5: _migrate_v5_to_v6,
    6: _migrate_v6_to_v7,
}


def current_save_version() -> int:
    """Return the current save-file schema version."""
    return CURRENT_SAVE_VERSION


def migrate(data: dict[str, object], from_version: int) -> dict[str, object]:
    """Stepwise-migrate ``data`` from ``from_version`` to ``CURRENT_SAVE_VERSION``.

    Walks the ``_MIGRATIONS`` chain one step at a time. Raises if a required
    migrator is missing. Returns data unchanged if already current.
    """
    if from_version > CURRENT_SAVE_VERSION:
        raise ValueError(
            f"Save version {from_version} is newer than supported "
            f"({CURRENT_SAVE_VERSION}); upgrade the game."
        )
    version = from_version
    while version < CURRENT_SAVE_VERSION:
        migrator = _MIGRATIONS.get(version)
        if migrator is None:
            raise ValueError(
                f"No migration registered from save version {version}; "
                f"current is {CURRENT_SAVE_VERSION}"
            )
        data = migrator(data)
        version += 1
    return data


def save(state: GameState, path: str | Path) -> Path:
    """Serialize ``state`` to JSON at ``path`` atomically.

    Writes to ``{path}.tmp`` then ``os.replace`` into place, so a crash mid-write
    leaves any prior file at ``path`` untouched (R17). Returns the final path.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(state.model_dump_json())
    # Ensure the version stamp is current on save.
    payload["save_version"] = CURRENT_SAVE_VERSION
    # Re-serialize without sort_keys so Pydantic's insertion-order representation
    # is preserved bit-for-bit (dict fields like `characteristics` must round-trip
    # in the same key order, or state hashes diverge after a save/load cycle).
    json_str = json.dumps(payload, indent=2)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json_str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)
    return target


def load(path: str | Path) -> GameState:
    """Load a :class:`GameState` from JSON at ``path``, running migrations.

    Reads the JSON, checks ``save_version``, migrates if needed, then validates
    into a :class:`GameState`. The reconstructed state is byte-identical (in
    the sense of ``model_dump_json`` equality) to the saved state.
    """
    source = Path(path)
    with source.open("r", encoding="utf-8") as f:
        data = json.load(f)
    version = int(data.get("save_version", 1))
    data = migrate(data, version)
    return GameState.model_validate(data)
