"""Save management endpoints (M0.6c, spec §5).

Files per chronicle: ``{name}.json`` (last manual save), ``{name}.autosave.json``
(live beat autosave), and ``*.checkpoint.json`` sidecars. Path safety goes
through :func:`resolve_save_path` (traversal-proof).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Request

from src.engine.persistence import migrate, save
from src.engine.state import GameState
from src.game.saves import discover_saves, resolve_save_path
from src.server.errors import ApiError
from src.server.models import DuplicateSaveRequest, ImportSaveRequest, SaveRequest
from src.server.routes_sessions import _record, _session_payload
from src.server.sessions import AUTOSAVE_SUFFIX

router = APIRouter(prefix="/v1")


def _files_for(saves_dir: Path, name: str) -> list[Path]:
    """All files belonging to a chronicle: main, autosave, and sidecars."""
    base = resolve_save_path(saves_dir, name)
    auto = base.with_name(base.stem + AUTOSAVE_SUFFIX + base.suffix)
    candidates = [base, auto]
    files = [p for p in candidates if p.exists()]
    files += [
        Path(str(p) + ".checkpoint.json")
        for p in candidates
        if Path(str(p) + ".checkpoint.json").exists()
    ]
    return files


@router.get("/saves")
async def list_saves(request: Request) -> dict:
    saves = []
    for info in discover_saves(request.app.state.saves_dir):
        autosave = info.name.endswith(AUTOSAVE_SUFFIX)
        base_name = info.name[: -len(AUTOSAVE_SUFFIX)] if autosave else info.name
        saves.append(
            {
                "name": info.name,
                "base_name": base_name,
                "autosave": autosave,
                "theme_pack": info.theme_pack,
                "character_name": info.character_name,
                "terms": info.terms,
                "career": info.career,
                "alive": info.alive,
                "mtime": info.mtime,
            }
        )
    return {"saves": saves}


@router.post("/sessions/{session_id}/save")
async def save_session(session_id: str, req: SaveRequest, request: Request) -> dict:
    """Manual save: write ``{name}.json`` + sidecar; retarget autosave base."""
    record = _record(request, session_id)
    request.app.state.registry.save_manual(record, req.name)
    return {"session": _session_payload(record)}


@router.delete("/saves/{name}")
async def delete_save(name: str, request: Request) -> dict:
    files = _files_for(request.app.state.saves_dir, name)
    if not files:
        raise ApiError(404, "save_not_found", f"No save named '{name}'")
    deleted = [p.name for p in files]
    for path in files:
        path.unlink()
    return {"deleted": deleted}


@router.post("/saves/{name}/duplicate", status_code=201)
async def duplicate_save(name: str, req: DuplicateSaveRequest, request: Request) -> dict:
    saves_dir = request.app.state.saves_dir
    files = _files_for(saves_dir, name)
    if not files:
        raise ApiError(404, "save_not_found", f"No save named '{name}'")
    target_base = resolve_save_path(saves_dir, req.new_name)
    if req.new_name.lower().endswith(AUTOSAVE_SUFFIX):
        raise ApiError(
            422, "invalid_name", f"Save names ending with '{AUTOSAVE_SUFFIX}' are reserved"
        )
    if _files_for(saves_dir, req.new_name):
        raise ApiError(409, "save_conflict", f"A save named '{req.new_name}' already exists")
    created: list[str] = []
    for path in files:
        # Rename the base portion, preserving .autosave/.checkpoint suffixes.
        suffix_tail = path.name[len(resolve_save_path(saves_dir, name).stem) :]
        target = target_base.with_name(target_base.stem + suffix_tail)
        shutil.copy2(path, target)
        created.append(target.name)
    return {"created": created}


@router.get("/saves/{name}/export")
async def export_save(name: str, request: Request) -> dict:
    files = _files_for(request.app.state.saves_dir, name)
    if not files:
        raise ApiError(404, "save_not_found", f"No save named '{name}'")
    # Prefer the main document; fall back to the autosave.
    main = resolve_save_path(request.app.state.saves_dir, name)
    source = main if main.exists() else files[0]
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ApiError(422, "invalid_save", f"Save file is corrupted: {exc}") from exc


@router.post("/saves/import", status_code=201)
async def import_save(req: ImportSaveRequest, request: Request) -> dict:
    try:
        data = migrate(dict(req.document), from_version=int(req.document.get("save_version", 1)))
        state = GameState.model_validate(data)
    except Exception as exc:
        raise ApiError(422, "invalid_save", f"Not a valid save document: {exc}") from exc
    target = resolve_save_path(request.app.state.saves_dir, req.name)
    if req.name.lower().endswith(AUTOSAVE_SUFFIX):
        raise ApiError(
            422, "invalid_name", f"Save names ending with '{AUTOSAVE_SUFFIX}' are reserved"
        )
    if target.exists() or _files_for(request.app.state.saves_dir, req.name):
        raise ApiError(409, "save_conflict", f"A save named '{req.name}' already exists")
    save(state, target)
    return {"name": target.stem}
