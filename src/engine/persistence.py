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
CURRENT_SAVE_VERSION = 1

#: Migration functions keyed by source version. Each takes raw dict data at
#: version N and returns dict data at version N+1. ``migrate`` walks the chain.
_MIGRATIONS: dict[int, Callable[[dict[str, object]], dict[str, object]]] = {
    # Example for when v2 lands:
    # 1: _migrate_v1_to_v2,
}


def current_save_version() -> int:
    """Return the current save-file schema version."""
    return CURRENT_SAVE_VERSION


def migrate(data: dict[str, object], from_version: int) -> dict[str, object]:
    """Stepwise-migrate ``data`` from ``from_version`` to ``CURRENT_SAVE_VERSION``.

    Walks the ``_MIGRATIONS`` chain one step at a time. Raises if a required
    migrator is missing. Returns data unchanged if already current.
    """
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
