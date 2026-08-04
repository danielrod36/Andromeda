"""Audit viewer overlay route (U13, R15).

Serves a filterable, paginated view of the append-only event log. The
overlay loads into the adventure screen's drawer via htmx. Read-only —
no mutations, no annotations.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.game.audit_view import build_audit_view, filter_from_params
from src.web.routes._saves import DEFAULT_SAVES_DIR, load_state_for_save

router = APIRouter(prefix="/audit")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/{save_name}", response_class=HTMLResponse)
async def audit_overlay(
    save_name: str,
    request: Request,
    kind: str | None = None,
    stream: str | None = None,
    seq_min: str | None = None,
    seq_max: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    """Render the audit overlay fragment (U13, R15).

    Returns an HTML fragment (not a full page) suitable for swapping into
    the drawer's audit tab via htmx. Supports filtering by kind, stream,
    and sequence range, plus pagination for long logs.
    """
    try:
        state, _ = load_state_for_save(save_name, DEFAULT_SAVES_DIR)
    except (FileNotFoundError, ValueError):
        return RedirectResponse(url="/saves", status_code=303)

    flt = filter_from_params(kind=kind, stream=stream, seq_min=seq_min, seq_max=seq_max)
    view = build_audit_view(state, audit_filter=flt, page=page)

    return templates.TemplateResponse(
        request,
        "partials/audit.html",
        {
            "save_name": save_name,
            "rows": view.rows,
            "page": view.page,
            "total_pages": view.total_pages,
            "filtered_count": view.filtered_count,
            "total_events": view.total_events,
            "has_rewinds": view.has_rewinds,
            "filter_kind": kind or "",
            "filter_stream": stream or "",
            "filter_seq_min": seq_min or "",
            "filter_seq_max": seq_max or "",
        },
    )
