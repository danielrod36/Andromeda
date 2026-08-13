"""Introspection endpoints (M0.6c, spec §5): sheet, recap, memorial, audit,
llm-context, odds, hash, verify.

All read-only views over canonical state. ``verify`` ships disabled — it
needs the engine replay walker (spec §12).
"""

from __future__ import annotations

import dataclasses
import hashlib

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from src.engine.odds import compute_check_odds, format_odds_line
from src.game.audit_view import build_audit_view, filter_from_params
from src.game.memorial import build_memorial, build_obituary
from src.game.recap import build_recap
from src.llm.state_view import (
    PROHIBITED_KEYS,
    build_curated_view,
    build_curated_view_for_scene,
)
from src.rulesets.cepheus import CepheusRuleSet
from src.server.errors import ApiError
from src.server.models import OddsRequest
from src.server.routes_sessions import _record
from src.themepacks import get_pack

router = APIRouter(prefix="/v1/sessions")


@router.get("/{session_id}/sheet")
async def sheet(session_id: str, request: Request) -> dict:
    """The full character sheet + server-computed DMs (no client-side math)."""
    record = _record(request, session_id)
    state = record.game.state
    ruleset = CepheusRuleSet()
    pack = get_pack(state.campaign.theme_pack)
    from src.engine.skills import skill_display_name

    return {
        "character": state.character.model_dump(mode="json"),
        "characteristic_dms": {
            char: ruleset.characteristic_dm(value)
            for char, value in state.character.characteristics.items()
        },
        "skill_names": {
            skill_id: skill_display_name(pack, skill_id) for skill_id in state.character.skills
        },
    }


@router.get("/{session_id}/recap")
async def recap(session_id: str, request: Request) -> dict:
    record = _record(request, session_id)
    result = await run_in_threadpool(
        build_recap, record.game.state, adapter=request.app.state.adapter
    )
    return {"lines": result.lines, "source": result.source}


@router.get("/{session_id}/memorial")
async def memorial(session_id: str, request: Request) -> dict:
    record = _record(request, session_id)
    data = build_memorial(record.game.state)
    return {
        "data": dataclasses.asdict(data),
        "obituary": build_obituary(data),
    }


@router.get("/{session_id}/audit")
async def audit(
    session_id: str,
    request: Request,
    kind: str | None = Query(default=None),
    stream: str | None = Query(default=None),
    since: int | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=50),
) -> dict:
    """The proof log: paginated, filterable event rows (spec §5)."""
    record = _record(request, session_id)
    audit_filter = filter_from_params(
        kind=kind,
        stream=stream,
        seq_min=str(since) if since is not None else None,
    )
    view = build_audit_view(
        record.game.state, audit_filter=audit_filter, page=page, per_page=per_page
    )
    return dataclasses.asdict(view)


@router.get("/{session_id}/llm-context")
async def llm_context(session_id: str, request: Request) -> dict:
    """What the narrator sees — and the never-includes strip (spec §7.12)."""
    record = _record(request, session_id)
    state = record.game.state
    if record.kind == "adventure":
        view = build_curated_view_for_scene(state, [])
    else:
        view = build_curated_view(state)
    return {
        "view": view.model_dump(mode="json"),
        "never_includes": sorted(PROHIBITED_KEYS),
        "note": "Raw rolls, RNG state, off-scene NPC stats, unoffered hooks, and full event history never leave the server.",
    }


@router.post("/{session_id}/odds")
async def odds(session_id: str, req: OddsRequest, request: Request) -> dict:
    """Pre-commit odds for a prospective check — no roll (spec §5)."""
    record = _record(request, session_id)
    state = record.game.state
    result = compute_check_odds(
        state.character,
        skill=req.skill,
        characteristic=req.characteristic,
        difficulty=req.difficulty,
        profile=state.campaign.resolution_profile,
    )
    return {**dataclasses.asdict(result), "odds_line": format_odds_line(result)}


@router.get("/{session_id}/hash")
async def state_hash(session_id: str, request: Request) -> dict:
    """Determinism fingerprint: sha256 of the canonical state document."""
    record = _record(request, session_id)
    digest = hashlib.sha256(record.game.state.model_dump_json().encode()).hexdigest()
    return {"sha256": digest}


@router.post("/{session_id}/verify")
async def verify(session_id: str, request: Request) -> None:
    """Replay verification — ships disabled (spec §5/§12)."""
    _record(request, session_id)  # 404s on unknown sessions, consistently
    raise ApiError(
        501,
        "not_implemented",
        "Replay verification needs the engine replay walker — it ships in a later milestone.",
    )
