"""World drawer tab route (U6, R12).

Serves a read-only world-state fragment loaded into the drawer's World tab
via htmx.  Shows the active mission, open threads, and established facts —
all derived from canonical ``GameState`` read-only.  Mirrors the audit
route's pattern.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.engine.state import NarrativeFact
from src.web.routes._saves import DEFAULT_SAVES_DIR, load_state_for_save

router = APIRouter(prefix="/world")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _build_world_context(save_name: str, state: object) -> dict:
    """Build the Jinja context for the World fragment from *state*.

    Derives display data read-only from the canonical ``GameState``: active
    mission summary, open threads, and established narrative facts.  Empty
    states render empty-state text — not errors.
    """
    # Active mission — a serialized dict or None.
    mission = None
    if state.active_mission is not None:
        md = state.active_mission
        hook = md.get("hook", {}) if isinstance(md, dict) else {}
        mission = {
            "id": md.get("id", ""),
            "patron": hook.get("patron", ""),
            "objective": hook.get("objective", ""),
            "complication": hook.get("complication", ""),
            "reward": hook.get("reward", ""),
            "scenes_completed": md.get("scenes_completed", 0),
            "min_scenes": md.get("min_scenes", 3),
        }

    # Open threads — plain strings.
    open_threads = list(state.open_threads) if state.open_threads else []

    # Established facts from the entity list.
    facts = [e for e in state.entities if isinstance(e, NarrativeFact)]

    return {
        "save_name": save_name,
        "mission": mission,
        "open_threads": open_threads,
        "facts": facts,
    }


@router.get("/{save_name}", response_class=HTMLResponse)
async def world_fragment(save_name: str, request: Request) -> HTMLResponse:
    """Render the World tab fragment (U6, R12).

    Returns an HTML fragment (not a full page) suitable for swapping into
    the drawer's World tab via htmx.  Read-only — no state mutation.
    """
    try:
        state, _ = load_state_for_save(save_name, DEFAULT_SAVES_DIR)
    except (FileNotFoundError, ValueError):
        return RedirectResponse(url="/saves", status_code=303)

    context = _build_world_context(save_name, state)
    return templates.TemplateResponse(request, "partials/world.html", context)
