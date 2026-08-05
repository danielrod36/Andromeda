"""Adventure web routes — the full adventure loop playable via htmx (U9, U1).

Drives the U8 AdventureController over HTTP. The spine renders typed-block
stream (scene headers, receipts, consequences); the choice dock renders
numbered cards with odds; free-text sits below.

U1: routes now drive a cached :class:`GameSession` held on the app instance.
The action gate (``begin_action``/``end_action``) rejects concurrent beats;
autosave goes through ``session.save()`` (stale-write guard + sidecar cadence).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.game.adventure import AdventureController, AdventureView
from src.game.session import StaleWriteError
from src.web.routes._saves import (
    DEFAULT_SAVES_DIR,
    busy_notice,
    conflict_notice,
    evict_session,
    get_or_create_session,
)

router = APIRouter(prefix="/adventure")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _adventure_context(
    save_name: str,
    controller: AdventureController,
    view: AdventureView | None = None,
    recap=None,
) -> dict:
    """Build the Jinja context for the adventure screen.

    When *view* is provided (e.g. the return value of ``apply_choice``), it is
    rendered directly — this preserves receipts, defeat interstitials, and
    mission endings that would be lost if ``get_view()`` were called again
    after a mutation (U9 receipt-preservation fix).
    """
    if view is None:
        view = controller.get_view()
    char = controller.state.character

    # U16: Extract tool-call pills from recent events.
    from src.game.pills import extract_recent_pills

    pills = extract_recent_pills(
        controller.state.events,
        since_seq=controller.action_start_seq - 1,
    )

    return {
        "save_name": save_name,
        "phase": view.phase,
        "prompt": view.prompt,
        "choices": view.choices,
        "receipts": view.receipts,
        "scaffold_text": view.scaffold_text,
        "defeat": view.defeat,
        "mission_ending": view.mission_ending,
        "change_lines": view.change_lines,
        "pills": pills,
        "character_name": char.name,
        "character_career": char.career or "—",
        "character_terms": char.terms,
        "recap": recap,
    }


def _render_adventure(
    request: Request,
    save_name: str,
    controller: AdventureController,
    view: AdventureView | None = None,
    recap=None,
) -> HTMLResponse:
    """Render the full adventure page (GET).

    The page wraps the shared spine partial inside ``<section id="spine">`` and
    includes the client-managed drawer.  The drawer's default Sheet content is
    server-rendered inline so the drawer never opens empty (U6, R12).
    """
    from src.game.theming import resolve_theme_attr

    context = _adventure_context(save_name, controller, view, recap)
    context["theme"] = resolve_theme_attr(controller.state.campaign.theme_pack)

    # U6: Sheet context for the inline drawer default content.
    from src.web.routes.sheet import _build_sheet_context

    context.update(_build_sheet_context(save_name, controller.state))

    return templates.TemplateResponse(request, "adventure.html", context)


def _render_adventure_fragment(
    request: Request,
    save_name: str,
    controller: AdventureController,
    view: AdventureView | None = None,
) -> HTMLResponse:
    """Render the adventure POST fragment (U5, R10/R11, AE5).

    Returns ONLY the spine inner content plus one OOB block: the status
    strip.  No ``<html>``/``<body>``/duplicate ``#spine`` — the fragment is
    swapped into the existing ``#spine`` via ``hx-swap="innerHTML"``.  The
    drawer is never included, so its open state and loaded tab content
    survive every action.
    """
    context = _adventure_context(save_name, controller, view)
    return templates.TemplateResponse(request, "adventure_action.html", context)


@router.get("/{save_name}", response_class=HTMLResponse)
async def adventure_screen(save_name: str, request: Request) -> HTMLResponse:
    """Render the adventure screen with current phase + choices."""
    try:
        bundle = get_or_create_session(save_name, DEFAULT_SAVES_DIR, request)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

    controller = bundle.adventure_controller
    assert controller is not None

    # Build story-so-far recap on resume (U11).
    recap = None
    if request.query_params.get("recap"):
        from src.game.recap import build_recap

        recap = build_recap(controller.state)

    return _render_adventure(request, save_name, controller, recap=recap)


@router.post("/{save_name}/action", response_class=HTMLResponse, response_model=None)
async def adventure_action(save_name: str, request: Request) -> HTMLResponse:
    """Apply a structured choice (option, mission action) and re-render."""
    try:
        bundle = get_or_create_session(save_name, DEFAULT_SAVES_DIR, request)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

    session = bundle.session
    controller = bundle.adventure_controller
    assert controller is not None

    # U1: action gate — reject concurrent beats with a graceful notice.
    if not session.begin_action():
        return busy_notice()

    try:
        form = await request.form()
        option_id = str(form.get("choice", ""))

        view: AdventureView | None = None
        if option_id:
            view = controller.apply_choice(option_id)
            try:
                session.save()
            except StaleWriteError:
                evict_session(save_name, DEFAULT_SAVES_DIR, request)
                return conflict_notice()

        return _render_adventure_fragment(request, save_name, controller, view=view)
    finally:
        session.end_action()


@router.post("/{save_name}/freetext", response_class=HTMLResponse, response_model=None)
async def adventure_freetext(save_name: str, request: Request) -> HTMLResponse:
    """Classify free-text input and render the interpretation or error (U9).

    This endpoint calls the blocking classify_freetext on the controller.
    At the web layer with an LLM configured, this runs in a threadpool
    (KTD-9). Without an LLM, the keyword classifier is instant.
    """
    try:
        bundle = get_or_create_session(save_name, DEFAULT_SAVES_DIR, request)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

    session = bundle.session
    controller = bundle.adventure_controller
    assert controller is not None

    # U1: action gate.
    if not session.begin_action():
        return busy_notice()

    try:
        form = await request.form()
        text = str(form.get("freetext", "")).strip()

        view: AdventureView | None = None
        if text:
            view = controller.classify_freetext(text)
            try:
                session.save()
            except StaleWriteError:
                evict_session(save_name, DEFAULT_SAVES_DIR, request)
                return conflict_notice()

        return _render_adventure_fragment(request, save_name, controller, view=view)
    finally:
        session.end_action()
