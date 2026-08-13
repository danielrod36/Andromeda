"""LLM settings endpoints (M0.6c + M0.7, spec §5/D7).

The API key moves through the key store only: PUT accepts it, stores it,
and never echoes it back; GET reports the masked tail and the backend.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from src.llm.providers import fetch_available_models
from src.llm.settings import (
    LLMSettings,
    delete_api_key,
    load_settings,
    masked_key_tail,
    resolve_api_key,
    save_settings,
)
from src.server.models import LlmSettingsRequest

router = APIRouter(prefix="/v1/settings")


def _payload(request: Request) -> dict:
    settings: LLMSettings = request.app.state.settings
    settings_dir = request.app.state.settings_dir
    return {
        "provider": settings.provider,
        "model": settings.model,
        "base_url": settings.base_url,
        "max_retries": settings.max_retries,
        "is_configured": settings.is_configured,
        "key_backend": settings.key_backend,
        "key_tail": masked_key_tail(settings, settings_dir),
    }


def _rebuild_llm_trio(request: Request) -> None:
    """Rebuild adapter/advisor/translator after a settings change.

    Live sessions keep the trio they were constructed with (their session
    contracts captured the references); sessions created or resumed after
    the change get the new one.
    """
    from src.llm.adapter import AdapterConfig
    from src.llm.advisor import Advisor, AdvisorConfig
    from src.llm.settings import create_llm_adapter
    from src.llm.translator import Translator

    settings: LLMSettings = request.app.state.settings
    request.app.state.adapter = create_llm_adapter(settings)
    if settings.is_configured:
        request.app.state.advisor = Advisor(AdvisorConfig(model=settings.model_string))
        request.app.state.translator = Translator(AdapterConfig(model=settings.model_string))
    else:
        request.app.state.advisor = None
        request.app.state.translator = None
    registry = request.app.state.registry
    registry.adapter = request.app.state.adapter
    registry.advisor = request.app.state.advisor
    registry.translator = request.app.state.translator


@router.get("/llm")
async def get_llm_settings(request: Request) -> dict:
    return _payload(request)


@router.put("/llm")
async def put_llm_settings(req: LlmSettingsRequest, request: Request) -> dict:
    settings_dir = request.app.state.settings_dir
    current: LLMSettings = request.app.state.settings
    updated = LLMSettings(
        provider=req.provider,
        model=req.model,
        base_url=req.base_url,  # pydantic validator rejects non-http(s)
        max_retries=req.max_retries,
        key_backend=current.key_backend,
    )
    if req.api_key is None:
        # Keep the stored key; carry it at runtime so save can re-affirm it.
        updated.api_key = resolve_api_key(current, settings_dir)
    elif req.api_key == "":
        current.api_key = resolve_api_key(current, settings_dir)
        delete_api_key(current, settings_dir)
        updated.key_backend = ""
    else:
        updated.api_key = req.api_key
    save_settings(updated, settings_dir)
    # Reload from disk so key_backend and the resolved api_key reflect the
    # keystore's actual state (save_settings writes a scrubbed copy).
    request.app.state.settings = load_settings(settings_dir)
    _rebuild_llm_trio(request)
    return _payload(request)


@router.post("/llm/test")
async def test_llm_settings(request: Request) -> dict:
    """Live connectivity test — never raises; the client renders the error."""
    settings: LLMSettings = request.app.state.settings
    api_key = resolve_api_key(settings, request.app.state.settings_dir)
    if not api_key:
        return {"ok": False, "error": "No API key stored"}
    try:
        models = await fetch_available_models(settings.provider, api_key, settings.base_url or None)
        return {"ok": True, "models": models}
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
