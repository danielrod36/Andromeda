"""Adventure web routes — the full adventure loop playable via htmx (U9).

Drives the U8 AdventureController over HTTP. The spine renders typed-block
stream (scene headers, receipts, consequences); the choice dock renders
numbered cards with odds; free-text sits below.

While an action POST is in flight, the choice dock and free-text bar
render disabled (the web half of R5's input lock — KTD-9).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.engine.commands import Engine
from src.engine.persistence import load, save
from src.game.adventure import AdventureController
from src.game.saves import resolve_save_path
from src.themepacks.base import get_pack
from src.themepacks.cepheus_scifi import load_scifi_pack

router = APIRouter(prefix="/adventure")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

#: Default saves directory (shared with menu/lifepath routes).
DEFAULT_SAVES_DIR = Path("saves")


def _load_controller(save_name: str) -> tuple[AdventureController, Path]:
    """Load a save and construct an AdventureController."""
    saves_dir = DEFAULT_SAVES_DIR
    saves_dir.mkdir(parents=True, exist_ok=True)
    save_path = resolve_save_path(saves_dir, save_name)
    if not save_path.exists():
        raise FileNotFoundError(f"Save not found: {save_name}")
    state = load(save_path)
    engine = Engine(state)
    pack = (
        load_scifi_pack()
        if state.campaign.theme_pack == "scifi"
        else get_pack(state.campaign.theme_pack)
    )
    controller = AdventureController(engine, pack)
    return controller, save_path


def _render_adventure(
    request: Request, save_name: str, controller: AdventureController
) -> HTMLResponse:
    """Render the adventure screen from the controller's current view."""
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
            "odds_lines": view.odds_lines,
            "defeat": view.defeat,
            "mission_ending": view.mission_ending,
            "character_name": char.name,
            "character_career": char.career or "—",
            "character_terms": char.terms,
            "character_alive": char.alive,
        },
    )


@router.get("/{save_name}", response_class=HTMLResponse)
async def adventure_screen(save_name: str, request: Request) -> HTMLResponse:
    """Render the adventure screen with current phase + choices."""
    try:
        controller, _ = _load_controller(save_name)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

    return _render_adventure(request, save_name, controller)


@router.post("/{save_name}/action", response_class=HTMLResponse, response_model=None)
async def adventure_action(save_name: str, request: Request) -> HTMLResponse:
    """Apply a structured choice (option, mission action) and re-render."""
    try:
        controller, save_path = _load_controller(save_name)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

    form = await request.form()
    option_id = str(form.get("choice", ""))

    if option_id:
        controller.apply_choice(option_id)
        save(controller.state, save_path)

    return _render_adventure(request, save_name, controller)


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

    if text:
        controller.classify_freetext(text)
        save(controller.state, save_path)

    return _render_adventure(request, save_name, controller)
