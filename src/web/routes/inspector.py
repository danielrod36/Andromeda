"""Curated-view inspector route (U16, R18, AE13).

Renders ``build_curated_view`` verbatim — exactly what the LLM receives.
This is the honest reading of the trust boundary: the inspector shows the
safe subset, nothing more. The ``assert_no_prohibited_fields`` guard runs
on every render as a runtime AE13 check.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.llm.state_view import assert_no_prohibited_fields, build_curated_view
from src.web.routes._saves import DEFAULT_SAVES_DIR, load_state_for_save

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inspector")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/{save_name}", response_class=HTMLResponse)
async def inspector(save_name: str, request: Request) -> HTMLResponse:
    """Render the curated view exactly as the LLM sees it (U16, R18).

    The view is built from the canonical state and rendered as structured
    JSON. The ``assert_no_prohibited_fields`` guard runs on every render
    as a runtime AE13 check — if it fails, the inspector shows the error
    rather than leaking prohibited fields.
    """
    try:
        state, _ = load_state_for_save(save_name, DEFAULT_SAVES_DIR)
    except (FileNotFoundError, ValueError):
        return RedirectResponse(url="/saves", status_code=303)

    view = build_curated_view(state)

    # AE13 runtime guard: verify no prohibited keys leaked.
    guard_error: str | None = None
    try:
        assert_no_prohibited_fields(view)
    except ValueError as exc:
        guard_error = str(exc)
        logger.error("Curated view AE13 violation: %s", exc)

    view_json = json.dumps(view.model_dump(), indent=2)

    return templates.TemplateResponse(
        request,
        "inspector.html",
        {
            "save_name": save_name,
            "view_json": view_json,
            "guard_error": guard_error,
        },
    )
