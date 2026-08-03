"""Memorial route for dead characters (U12, R14, AE4).

Renders the audit-derived obituary when a dead character's save is loaded.
The U6 phase predicate routes dead saves here (``determine_resume_route``
returns ``"memorial"``); this route is the web shell's terminal equivalent
of the TUI's game-over screen.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.game.memorial import build_memorial, build_obituary
from src.web.routes._saves import DEFAULT_SAVES_DIR, load_state_for_save

router = APIRouter(prefix="/memorial")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/{save_name}", response_class=HTMLResponse)
async def memorial_screen(save_name: str, request: Request) -> HTMLResponse:
    """Render the memorial interstitial for a dead character (U12, R14).

    Displays the audit-derived obituary (career, missions, notable rolls)
    and mode-appropriate restart options. A dead-character save always lands
    here, never into play.
    """
    try:
        state, _ = load_state_for_save(save_name, DEFAULT_SAVES_DIR)
    except FileNotFoundError:
        return RedirectResponse(url="/saves", status_code=303)

    # Safety: if the character is somehow alive, redirect to the resume flow.
    if state.character.alive:
        return RedirectResponse(url=f"/play/{save_name}", status_code=303)

    data = build_memorial(state)
    obituary_lines = build_obituary(data)

    return templates.TemplateResponse(
        request,
        "memorial.html",
        {
            "save_name": save_name,
            "character_name": data.character_name,
            "obituary_lines": obituary_lines,
            "interstitial_text": data.interstitial_text,
            "interstitial_mode": data.interstitial_mode,
            "death_mode": data.death_mode,
            "missions": [
                {"objective": m.objective, "ending": m.ending, "scenes": m.scenes}
                for m in data.missions
            ],
            "notable_rolls": [
                {
                    "type": r.roll_type,
                    "values": r.values,
                    "total": r.total,
                    "description": r.description,
                }
                for r in data.notable_rolls
            ],
            "chapter_summaries": data.chapter_summaries,
        },
    )
