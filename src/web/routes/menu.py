"""Menu, campaign config, saves, and resume routes for the web shell (U6).

These routes are the web shell's front door: main menu, new-campaign config
form, save list, and resume routing. Gameplay routes (lifepath U7, adventure
U9) are added in later units; this unit provides the routing infrastructure
and the config→save→resume flow.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.engine.state import CampaignConfig, GameState
from src.game.saves import determine_resume_route, discover_saves, resolve_save_path, safe_save_name

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

#: Default saves directory. The web shell uses a project-relative path.
DEFAULT_SAVES_DIR = Path("saves")


def get_saves_dir() -> Path:
    """Return the saves directory, creating it if needed."""
    DEFAULT_SAVES_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_SAVES_DIR


@router.get("/menu", response_class=HTMLResponse)
async def menu(request: Request) -> HTMLResponse:
    """Main menu: New Campaign or Load Save."""
    saves = discover_saves(get_saves_dir())
    return templates.TemplateResponse(
        request,
        "menu.html",
        {"has_saves": len(saves) > 0},
    )


@router.get("/config", response_class=HTMLResponse)
async def config_form(request: Request) -> HTMLResponse:
    """Campaign configuration form."""
    return templates.TemplateResponse(
        request,
        "config.html",
        {
            "errors": {},
            "name": "",
            "seed": "",
            "theme_pack": "scifi",
            "resolution_profile": "narrative",
            "death_mode": "narrative",
        },
    )


@router.post("/config", response_class=HTMLResponse, response_model=None)
async def config_submit(request: Request) -> HTMLResponse | RedirectResponse:
    """Process campaign config form submission.

    Creates a new campaign through the same engine commands the TUI uses,
    saves it, and redirects to the lifepath route (U7). Invalid input
    re-renders the form with errors; no state is created.
    """
    import secrets

    form = await request.form()
    name = str(form.get("name", "")).strip()
    theme_pack = str(form.get("theme_pack", "scifi"))
    resolution_profile = str(form.get("resolution_profile", "narrative"))
    death_mode = str(form.get("death_mode", "narrative"))
    seed_str = str(form.get("seed", "")).strip()

    errors: dict[str, str] = {}

    if not name:
        errors["name"] = "Character name is required."

    # Seed: optional (auto-generate) or must be a positive integer.
    if seed_str:
        try:
            seed = int(seed_str)
            if seed < 0:
                errors["seed"] = "Seed must be a positive integer."
        except ValueError:
            errors["seed"] = "Seed must be a number."
    else:
        seed = secrets.randbelow(2**31)

    # Validate theme pack.
    if theme_pack not in ("scifi", "fantasy"):
        errors["theme_pack"] = f"Unknown theme pack: {theme_pack}."

    if errors:
        return templates.TemplateResponse(
            request,
            "config.html",
            {
                "errors": errors,
                "name": name,
                "seed": seed_str,
                "theme_pack": theme_pack,
                "resolution_profile": resolution_profile,
                "death_mode": death_mode,
            },
        )

    # Create the campaign.
    config = CampaignConfig(
        ruleset="cepheus",
        theme_pack=theme_pack,
        resolution_profile=resolution_profile,
        death_mode=death_mode,
    )
    state = GameState.new(seed=seed)
    state.campaign = config
    state.character.name = name

    # Save immediately.
    from src.engine.persistence import save

    save_name = safe_save_name(name)
    save_path = resolve_save_path(get_saves_dir(), name)
    save(state, save_path)

    # Redirect to the lifepath start (U7 will own this route; for now redirect to menu).
    return RedirectResponse(url=f"/play/{save_name}", status_code=303)


@router.get("/saves", response_class=HTMLResponse)
async def saves_list(request: Request) -> HTMLResponse:
    """Save list page with character/campaign metadata."""
    saves = discover_saves(get_saves_dir())
    return templates.TemplateResponse(
        request,
        "saves.html",
        {"saves": saves},
    )


@router.post("/resume", response_class=HTMLResponse, response_model=None)
async def resume(request: Request) -> HTMLResponse | RedirectResponse:
    """Load a save and route to the correct phase.

    Uses the state-derived phase predicate (U6) to determine where the
    player should resume: memorial (dead), lifepath, freetext_prompt, or
    adventure.
    """
    from src.engine.persistence import load

    form = await request.form()
    save_name = str(form.get("save", ""))
    if not save_name:
        return RedirectResponse(url="/saves", status_code=303)

    save_path = resolve_save_path(get_saves_dir(), save_name)
    if not save_path.exists():
        return RedirectResponse(url="/saves", status_code=303)

    state = load(save_path)
    route = determine_resume_route(state)

    # Map route to URL (lifepath/adventure/memorial routes arrive in later units).
    route_urls = {
        "memorial": f"/memorial/{save_name}",
        "lifepath": f"/play/{save_name}",
        "freetext_prompt": f"/play/{save_name}",
        "adventure": f"/adventure/{save_name}",
    }
    return RedirectResponse(url=route_urls.get(route, f"/play/{save_name}"), status_code=303)
