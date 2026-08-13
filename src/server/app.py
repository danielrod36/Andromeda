"""FastAPI app factory for the Andromeda sidecar (M0.6).

The app owns: settings (with keyring-resolved key), the LLM trio (adapter /
advisor / translator — ``None`` when unconfigured, template mode), the
session registry, and the activity timestamp the idle watchdog reads.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI

from src.llm.settings import LLMSettings, create_llm_adapter, load_settings
from src.server.errors import register_error_handlers
from src.server.sessions import SessionRegistry


class ActivityMiddleware:
    """Stamp ``last_request_at`` on every HTTP request (idle watchdog feed).

    Pure ASGI — deliberately NOT ``@app.middleware("http")``:
    BaseHTTPMiddleware buffers response bodies on some Starlette versions,
    which would break the Task 8 NDJSON stream.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope["app"].state.last_request_at = time.monotonic()
        await self.app(scope, receive, send)


def create_app(
    *,
    saves_dir: Path = Path("saves"),
    settings_dir: Path = Path("settings"),
    settings: LLMSettings | None = None,
    adapter=None,
    advisor=None,
    translator=None,
) -> FastAPI:
    """Build the sidecar application.

    ``adapter``/``advisor``/``translator`` are injectable for tests (a
    ``TestModel``-backed adapter makes narration deterministic). When
    ``None`` and settings are complete, real ones are built.
    """
    app = FastAPI(title="andromeda-sidecar", docs_url=None, redoc_url=None)

    settings = settings if settings is not None else load_settings(settings_dir)
    if adapter is None:
        adapter = create_llm_adapter(settings)
    if advisor is None and settings.is_configured:
        from src.llm.advisor import Advisor, AdvisorConfig

        advisor = Advisor(AdvisorConfig(model=settings.model_string))
    if translator is None and settings.is_configured:
        from src.llm.adapter import AdapterConfig
        from src.llm.translator import Translator

        translator = Translator(AdapterConfig(model=settings.model_string))

    app.state.settings = settings
    app.state.settings_dir = Path(settings_dir)
    app.state.saves_dir = Path(saves_dir)
    app.state.adapter = adapter
    app.state.advisor = advisor
    app.state.translator = translator
    app.state.last_request_at = time.monotonic()
    app.state.registry = SessionRegistry(
        saves_dir=Path(saves_dir),
        settings=settings,
        adapter=adapter,
        advisor=advisor,
        translator=translator,
    )

    app.add_middleware(ActivityMiddleware)
    register_error_handlers(app)

    from src.server.routes_config import router as config_router
    from src.server.routes_meta import router as meta_router

    app.include_router(meta_router)
    app.include_router(config_router)

    # Gameplay/saves/settings/inspect routers land in Tasks 8-10 and are
    # included unconditionally — they exist by the time this ships.
    from src.server.routes_inspect import router as inspect_router
    from src.server.routes_saves import router as saves_router
    from src.server.routes_sessions import router as sessions_router
    from src.server.routes_settings import router as settings_router

    app.include_router(sessions_router)
    app.include_router(saves_router)
    app.include_router(settings_router)
    app.include_router(inspect_router)

    return app
