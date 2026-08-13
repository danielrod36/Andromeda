"""Meta endpoints: /health and /v1/llm/status (M0.6)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from src.game.adventure_session import CONTRACT_VERSION as ADVENTURE_CONTRACT
from src.game.chargen.api import CONTRACT_VERSION as CHARGEN_CONTRACT
from src.llm.status import STATUS_NARRATION_UNAVAILABLE

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "contract_versions": {"chargen": CHARGEN_CONTRACT, "adventure": ADVENTURE_CONTRACT},
    }


@router.get("/v1/llm/status")
async def llm_status(request: Request) -> dict:
    """Narrator status for the status strip (spec §9: canonical strings only)."""
    settings = request.app.state.settings
    adapter = request.app.state.adapter
    configured = bool(adapter is not None and adapter.llm_configured)
    return {
        "configured": configured,
        "model": settings.model_string if configured else None,
        "key_backend": settings.key_backend,
        # Shown when narration degrades; canonical string, never invented copy.
        "degraded_line": None if configured else STATUS_NARRATION_UNAVAILABLE,
    }
