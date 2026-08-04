"""Adventure web routes — the full adventure loop playable via htmx (U9).

Drives the U8 AdventureController over HTTP. The spine renders typed-block
stream (scene headers, receipts, consequences); the choice dock renders
numbered cards with odds; free-text sits below.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.engine.persistence import save
from src.game.adventure import AdventureController, AdventureView
from src.web.routes._saves import DEFAULT_SAVES_DIR, load_engine_for_save

router = APIRouter(prefix="/adventure")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _load_controller(save_name: str) -> tuple[AdventureController, Path]:
    """Load a save and construct an AdventureController."""
    engine, pack, save_path = load_engine_for_save(save_name, DEFAULT_SAVES_DIR)
    controller = AdventureController(engine, pack)
    return controller, save_path


def _render_adventure(
    request: Request,
    save_name: str,
    controller: AdventureController,
    view: AdventureView | None = None,
    recap=None,
) -> HTMLResponse:
    """Render the adventure screen from a view (or the controller's current view).

    When *view* is provided (e.g. the return value of ``apply_choice``), it is
    rendered directly — this preserves receipts, defeat interstitials, and
    mission endings that would be lost if ``get_view()`` were called again
    after a mutation (U9 receipt-preservation fix).
    """
    if view is None:
        view = controller.get_view()
    char = controller.state.character
    return templates.TemplateResponse(
        request,
        "adventure.html",
        {
            "save_name": save_name,
            "phase": view.phase,
            "prompt": view.prompt,
            "choices": view.choices,
            "receipts": view.receipts,
            "scaffold_text": view.scaffold_text,
            "defeat": view.defeat,
            "mission_ending": view.mission_ending,
            "change_lines": view.change_lines,
            "character_name": char.name,
            "character_career": char.career or "—",
            "character_terms": char.terms,
            "recap": recap,
        },
    )


@router.get("/{save_name}", response_class=HTMLResponse)
async def adventure_screen(save_name: str, request: Request) -> HTMLResponse:
    """Render the adventure screen with current phase + choices."""
    try:
        controller, _ = _load_controller(save_name)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

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
        controller, save_path = _load_controller(save_name)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

    form = await request.form()
    option_id = str(form.get("choice", ""))

    view: AdventureView | None = None
    if option_id:
        view = controller.apply_choice(option_id)
        save(controller.state, save_path)

    return _render_adventure(request, save_name, controller, view=view)


@router.post("/{save_name}/freetext", response_class=HTMLResponse, response_model=None)
async def adventure_freetext(save_name: str, request: Request) -> HTMLResponse:
    """Classify free-text input and render the interpretation or error (U9).

    This endpoint calls the blocking classify_freetext on the controller.
    At the web layer with an LLM configured, this runs in a threadpool
    (KTD-9). Without an LLM, the keyword classifier is instant.
    """
    try:
        controller, save_path = _load_controller(save_name)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

    form = await request.form()
    text = str(form.get("freetext", "")).strip()

    view: AdventureView | None = None
    if text:
        view = controller.classify_freetext(text)
        save(controller.state, save_path)

    return _render_adventure(request, save_name, controller, view=view)
