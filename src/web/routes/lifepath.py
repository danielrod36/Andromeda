"""Lifepath web routes — the complete lifepath mini-game playable via htmx (U7).

Drives the step → choice → receipt cycle against the U5 LifepathController.
Each POST returns an htmx fragment that swaps into the spine.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.game.lifepath import LifepathController
from src.web.routes._saves import DEFAULT_SAVES_DIR, load_engine_for_save

router = APIRouter(prefix="/play")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _load_controller(save_name: str) -> tuple[LifepathController, Path]:
    """Load a save and construct a LifepathController."""
    engine, pack, save_path = load_engine_for_save(save_name, DEFAULT_SAVES_DIR)
    controller = LifepathController(engine, pack)
    return controller, save_path


@router.get("/{save_name}", response_class=HTMLResponse)
async def lifepath_screen(save_name: str, request: Request) -> HTMLResponse:
    """Render the lifepath screen with current phase + choices."""
    try:
        controller, _ = _load_controller(save_name)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

    view = controller.get_phase_view()
    char = controller.engine.state.character

    return templates.TemplateResponse(
        request,
        "lifepath.html",
        {
            "save_name": save_name,
            "phase": view.phase,
            "prompt": view.prompt,
            "choices": view.choices,
            "receipts": view.receipts,
            "drawer_pinned": view.drawer_pinned,
            "character_name": char.name,
            "character_career": char.career or "—",
            "character_terms": char.terms,
        },
    )


@router.post("/{save_name}/action", response_class=HTMLResponse, response_model=None)
async def lifepath_action(save_name: str, request: Request) -> HTMLResponse:
    """Apply a choice and return the updated lifepath fragment."""
    from src.engine.persistence import save

    try:
        controller, save_path = _load_controller(save_name)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

    form = await request.form()
    option_id = str(form.get("choice", ""))

    if option_id:
        view = controller.apply_choice(option_id)
        save(controller.engine.state, save_path)
    else:
        view = controller.get_phase_view()
    char = controller.engine.state.character

    return templates.TemplateResponse(
        request,
        "lifepath.html",
        {
            "save_name": save_name,
            "phase": view.phase,
            "prompt": view.prompt,
            "choices": view.choices,
            "receipts": view.receipts,
            "drawer_pinned": view.drawer_pinned,
            "character_name": char.name,
            "character_career": char.career or "—",
            "character_terms": char.terms,
        },
    )
