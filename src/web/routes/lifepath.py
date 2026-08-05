"""Lifepath web routes — the complete lifepath mini-game playable via htmx (U7, U1).

Drives the step → choice → receipt cycle against the U5 LifepathController.
GET renders the full page; POST returns a clean spine fragment plus one OOB
block (the status strip), so the live DOM never nests duplicate regions and
the client-managed drawer's content survives every action (U5, R10/R11).

U1: routes now drive a cached :class:`GameSession` held on the app instance.
The action gate rejects concurrent beats; autosave goes through
``session.save()`` (stale-write guard + sidecar cadence).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.game.lifepath import LifepathController
from src.game.session import StaleWriteError
from src.game.theming import resolve_theme_attr
from src.game.views import PhaseView
from src.web.routes._saves import (
    DEFAULT_SAVES_DIR,
    busy_notice,
    conflict_notice,
    evict_session,
    get_or_create_session,
)

router = APIRouter(prefix="/play")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _lifepath_context(
    save_name: str,
    controller: LifepathController,
    view: PhaseView,
    recap=None,
) -> dict:
    """Build the Jinja context for the lifepath screen."""
    char = controller.engine.state.character
    return {
        "save_name": save_name,
        "phase": view.phase,
        "prompt": view.prompt,
        "choices": view.choices,
        "receipts": view.receipts,
        "drawer_pinned": view.drawer_pinned,
        "character_name": char.name,
        "character_career": char.career or "—",
        "character_terms": char.terms,
        "recap": recap,
    }


@router.get("/{save_name}", response_class=HTMLResponse)
async def lifepath_screen(save_name: str, request: Request) -> HTMLResponse:
    """Render the lifepath screen with current phase + choices."""
    try:
        bundle = get_or_create_session(save_name, DEFAULT_SAVES_DIR, request)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

    controller = bundle.lifepath_controller
    assert controller is not None

    view = controller.get_phase_view()

    # Build story-so-far recap on resume (U11).
    recap = None
    if request.query_params.get("recap"):
        from src.game.recap import build_recap

        recap = build_recap(controller.engine.state)

    context = _lifepath_context(save_name, controller, view, recap=recap)
    context["theme"] = resolve_theme_attr(controller.engine.state.campaign.theme_pack)

    # U6: Sheet context for the inline drawer default content.
    from src.web.routes.sheet import _build_sheet_context

    context.update(_build_sheet_context(save_name, controller.engine.state))

    return templates.TemplateResponse(request, "lifepath.html", context)


@router.post("/{save_name}/action", response_class=HTMLResponse, response_model=None)
async def lifepath_action(save_name: str, request: Request) -> HTMLResponse:
    """Apply a choice and return the updated lifepath fragment (U5).

    Returns ONLY the spine inner content plus one OOB block: the status
    strip (carrying the drawer pin as a data attribute).  No drawer markup
    is included — the client-managed drawer's open state and loaded tab
    content survive every action.
    """
    try:
        bundle = get_or_create_session(save_name, DEFAULT_SAVES_DIR, request)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

    session = bundle.session
    controller = bundle.lifepath_controller
    assert controller is not None

    # U1: action gate.
    if not session.begin_action():
        return busy_notice()

    try:
        form = await request.form()
        option_id = str(form.get("choice", ""))

        if option_id:
            view = controller.apply_choice(option_id)
            try:
                session.save()
            except StaleWriteError:
                evict_session(save_name, DEFAULT_SAVES_DIR, request)
                return conflict_notice()
        else:
            view = controller.get_phase_view()

        context = _lifepath_context(save_name, controller, view)
        return templates.TemplateResponse(request, "lifepath_action.html", context)
    finally:
        session.end_action()
