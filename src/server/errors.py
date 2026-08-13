"""API error envelope (spec §5): {"error": {"code", "message"}}."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.game.session import StaleWriteError
from src.themepacks.base import PackLoadError


class ApiError(Exception):
    """An error with a stable machine code and a client-renderable message."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class SessionNotFoundError(Exception):
    """Unknown session id."""


class ActionInFlightError(Exception):
    """A beat is already in flight for this session (KTD-9 gate)."""


def envelope(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register_error_handlers(app: FastAPI) -> None:
    """Map exceptions onto the error envelope (spec §5: engine messages verbatim)."""

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=envelope(exc.code, exc.message))

    @app.exception_handler(SessionNotFoundError)
    async def _not_found(_request: Request, exc: SessionNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content=envelope("session_not_found", str(exc)))

    @app.exception_handler(ActionInFlightError)
    async def _in_flight(_request: Request, exc: ActionInFlightError) -> JSONResponse:
        return JSONResponse(status_code=409, content=envelope("action_in_flight", str(exc)))

    @app.exception_handler(StaleWriteError)
    async def _stale(_request: Request, exc: StaleWriteError) -> JSONResponse:
        return JSONResponse(status_code=409, content=envelope("save_conflict", str(exc)))

    @app.exception_handler(PackLoadError)
    async def _pack(_request: Request, exc: PackLoadError) -> JSONResponse:
        return JSONResponse(status_code=422, content=envelope("invalid_config", str(exc)))

    @app.exception_handler(ValueError)
    async def _value(_request: Request, exc: ValueError) -> JSONResponse:
        # Engine/controller validation messages ship verbatim — the client
        # renders them in toasts (spec §5).
        return JSONResponse(status_code=422, content=envelope("invalid_choice", str(exc)))

    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return JSONResponse(status_code=404, content=envelope("not_found", "Unknown endpoint"))
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope("http_error", str(exc.detail)),
        )

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content=envelope("invalid_request", str(exc)))

    @app.exception_handler(KeyError)
    async def _key_error(_request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=422, content=envelope("invalid_choice", str(exc)))
