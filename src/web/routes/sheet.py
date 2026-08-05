"""Sheet drawer tab route (U6, R12).

Serves a read-only character-sheet fragment loaded into the drawer's Sheet
tab via htmx.  All data is derived from canonical ``GameState`` read-only;
no mutations.  Mirrors the audit route's pattern.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.engine.skills import skill_display_name
from src.engine.state import GameState, Injury
from src.rulesets.cepheus import CepheusRuleSet
from src.web.routes._saves import DEFAULT_SAVES_DIR, _resolve_pack, load_state_for_save

router = APIRouter(prefix="/sheet")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

#: The six Cepheus characteristics in display order.
_CHAR_ORDER = ("STR", "DEX", "END", "INT", "EDU", "SOC")

#: Shared rule-set instance for characteristic DM computation.
_RULESET = CepheusRuleSet()


def _build_sheet_context(save_name: str, state: GameState) -> dict:
    """Build the Jinja context for the Sheet fragment from *state*.

    Derives all display data read-only from the canonical ``GameState``:
    characteristics with DMs, skill display names, career/rank info,
    injuries, and lifepath-midstate indicators (unassigned pool, picks).
    """
    char = state.character
    pack = _resolve_pack(state)

    # Characteristics with DMs — only those already assigned appear.
    char_rows = []
    for stat in _CHAR_ORDER:
        value = char.characteristics.get(stat)
        if value is not None:
            char_rows.append(
                {
                    "stat": stat,
                    "value": value,
                    "dm": _RULESET.characteristic_dm(value),
                }
            )

    # Skills — sorted alphabetically by display name for stable output.
    skill_rows = sorted(
        (
            {
                "name": skill_display_name(pack, skill_id),
                "level": level,
            }
            for skill_id, level in char.skills.items()
        ),
        key=lambda s: s["name"],
    )

    # Rank title lookup from the active career's rank table.
    rank_title = ""
    career_name = char.career or ""
    if char.career and char.rank > 0:
        career_data = pack.careers.get(char.career)
        if career_data is not None:
            career_name = career_data.name
            for rank_entry in career_data.ranks:
                if rank_entry.rank == char.rank:
                    rank_title = rank_entry.title
                    break

    # Injuries from the entity list.
    injuries = [e for e in state.entities if isinstance(e, Injury)]

    # Lifepath midstate indicators.
    unassigned_rolls = list(char.unassigned_rolls) if char.unassigned_rolls else []
    background_picks = (
        char.background_picks_remaining if char.background_picks_remaining >= 0 else None
    )
    pending_aging = list(char.pending_aging) if char.pending_aging else []

    return {
        "save_name": save_name,
        "character_name": char.name,
        "alive": char.alive,
        "char_rows": char_rows,
        "skill_rows": skill_rows,
        "career_name": career_name,
        "rank": char.rank,
        "rank_title": rank_title,
        "terms": char.terms,
        "age": char.age,
        "credits": char.credits,
        "injuries": injuries,
        "unassigned_rolls": unassigned_rolls,
        "background_picks_remaining": background_picks,
        "pending_aging": pending_aging,
    }


@router.get("/{save_name}", response_class=HTMLResponse)
async def sheet_fragment(save_name: str, request: Request) -> HTMLResponse:
    """Render the Sheet tab fragment (U6, R12).

    Returns an HTML fragment (not a full page) suitable for swapping into
    the drawer's Sheet tab via htmx.  Read-only — no state mutation.
    """
    try:
        state, _ = load_state_for_save(save_name, DEFAULT_SAVES_DIR)
    except (FileNotFoundError, ValueError):
        return RedirectResponse(url="/saves", status_code=303)

    context = _build_sheet_context(save_name, state)
    return templates.TemplateResponse(request, "partials/sheet.html", context)
