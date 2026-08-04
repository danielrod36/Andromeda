"""FastAPI application factory for the Andromeda web shell (U4).

The web shell is a thin client over the engine — it renders HTML, accepts
htmx POSTs, and streams SSE narration blocks. The engine owns all mutations;
the web layer never touches ``GameState`` directly outside ``Engine.apply``.

Security contracts (U4):
- Same-origin guard: rejects non-GET requests whose Origin/Referer host
  doesn't match the server, so browser-mediated cross-origin POSTs from
  other open pages can't drive actions. The server's own host must also be
  in an allowlist, blocking DNS-rebinding attacks where an attacker's
  domain resolves to 127.0.0.1 and Origin/Host match each other.
- Output-encoding: Jinja autoescape is enabled globally; ``|safe`` is only
  used on markdown that has been rendered server-side with markdown-it-py's
  secure defaults (raw HTML disabled).
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

# Absolute paths so the app works regardless of CWD.
_BASE_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _BASE_DIR / "static"
_TEMPLATE_DIR = _BASE_DIR / "templates"


class SameOriginGuard(BaseHTTPMiddleware):
    """Reject non-GET requests whose Origin/Referer host doesn't match (U4).

    Browser Same-Origin Policy blocks *reading* cross-origin responses, but
    not *sending* cross-origin form POSTs. Without this guard, any website
    open in the player's browser could fire POSTs at the localhost server —
    resolving checks, creating campaigns, or burning LLM quota.

    Two checks:
    1. The server's own host must be in ``_ALLOWED_HOSTS`` — blocks
       DNS-rebinding attacks where an attacker's domain resolves to
       127.0.0.1 and Origin/Host would match each other but both be
       attacker-controlled.
    2. The Origin header (falling back to Referer) must match the server's
       host:port, so cross-origin pages can't POST.
    """

    #: Hosts the server will accept. The web shell is single-player
    #: localhost; any other host is suspicious (likely DNS rebinding).
    _ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})

    async def dispatch(self, request: Request, call_next):
        if request.method == "GET":
            return await call_next(request)

        # Determine the server's own host:port.
        server_host = request.url.hostname or "127.0.0.1"
        server_port = request.url.port or (443 if request.url.scheme == "https" else 80)

        # Block DNS-rebinding: if Host isn't localhost, reject even if
        # Origin matches (both could be attacker-controlled).
        if server_host not in self._ALLOWED_HOSTS:
            return HTMLResponse("<h1>403 — Unexpected host</h1>", status_code=403)

        # Check Origin header first, then Referer.
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")

        for header_val in (origin, referer):
            if not header_val:
                continue
            # Extract host:port from the header value.
            # Origin: "http://127.0.0.1:8000" → "127.0.0.1:8000"
            # Referer: "http://127.0.0.1:8000/saves" → "127.0.0.1:8000"
            try:
                parsed = urlparse(header_val)
            except ValueError:
                continue
            req_host = parsed.hostname or ""
            req_port = parsed.port

            if req_host != server_host:
                # Different host — reject.
                return HTMLResponse("<h1>403 — Cross-origin request blocked</h1>", status_code=403)
            if req_port is not None and req_port != server_port:
                # Same host, different port — reject (different origin).
                return HTMLResponse("<h1>403 — Cross-origin request blocked</h1>", status_code=403)
            # Origin matches — allow.
            return await call_next(request)

        # No Origin or Referer header at all on a non-GET request.
        # This is suspicious for browser-initiated requests (htmx always
        # sends Origin on same-origin POSTs). Reject defensively.
        return HTMLResponse("<h1>403 — Missing Origin header</h1>", status_code=403)


def create_app() -> FastAPI:
    """Create and configure the Andromeda web application (U4).

    Returns a FastAPI instance with:
    - Static file mount for CSS/JS/fonts/vendor assets
    - Jinja2 templates with autoescape enabled (security contract)
    - Same-origin guard middleware (security contract)
    - A root route ``GET /`` serving the base layout shell
    - Session registry on ``app.state`` (U1): keyed by
      ``(resolved_saves_dir, save_stem)`` → session bundle
    """
    from src.llm.settings import load_settings

    app = FastAPI(title="Andromeda")

    # U1: Session registry — holds GameSession + flow controllers per save.
    # Keyed by (resolved_saves_dir, save_stem) so per-test directories
    # never collide. The dev server runs a single uvicorn worker, so the
    # in-memory gate is per-process by design.
    app.state.session_registry: dict = {}

    # U1: Load LLM settings once at startup; passed to new sessions.
    app.state.llm_settings = load_settings()

    # Static files: CSS, JS, fonts, vendored htmx.
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Templates: autoescape is ON by default in Jinja2 — the security
    # contract is that |safe is never used on non-markdown strings.
    templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

    # Security: same-origin guard for mutation endpoints.
    app.add_middleware(SameOriginGuard)

    # U6: menu, config, saves, resume routes.
    from src.web.routes.menu import router as menu_router

    app.include_router(menu_router)

    # U7: lifepath screen routes.
    from src.web.routes.lifepath import router as lifepath_router

    app.include_router(lifepath_router)

    # U9: adventure screen routes.
    from src.web.routes.adventure import router as adventure_router

    app.include_router(adventure_router)

    # U10: SSE streaming narration.
    from src.web.routes.stream import router as stream_router

    app.include_router(stream_router)

    # U12: Memorial route for dead characters.
    from src.web.routes.memorial import router as memorial_router

    app.include_router(memorial_router)

    # U13: Audit viewer overlay.
    from src.web.routes.audit import router as audit_router

    app.include_router(audit_router)

    # U16: Curated-view inspector.
    from src.web.routes.inspector import router as inspector_router

    app.include_router(inspector_router)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """Serve the base layout shell — four regions, no gameplay yet (U4)."""
        return templates.TemplateResponse(request, "base.html", {"theme": "scifi"})

    return app
