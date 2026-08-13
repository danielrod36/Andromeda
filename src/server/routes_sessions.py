"""Session gameplay endpoints (M0.6b, spec §5).

Every mutation endpoint follows the same pipeline: gate (one in-flight
beat per session) → session contract → engine funnel → autosave → response
carrying the structured new events (the client's roll readouts render from
these, never from parsed text — spec D5).

``/narrate`` is the NDJSON stream. All mutations (steering record, shipped
prose record, autosave, watermarks) happen BEFORE streaming starts: the
trust boundary made temporal.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from src.engine.commands import (
    RecordNarrationCommand,
    RecordStoryDirectionCommand,
    SetCharacterNameCommand,
)
from src.engine.lifepath_choices import ChoiceOptionView, ChoicePointView
from src.game.adventure_session import CONTRACT_VERSION as ADVENTURE_CONTRACT
from src.game.advice import record_advice
from src.game.beats import build_beat_facts, narrator_memory
from src.game.change_lines import derive_recent_change_lines
from src.game.chargen.api import CONTRACT_VERSION as CHARGEN_CONTRACT
from src.llm.adapter import LLMAdapter, NarrationResult
from src.llm.status import STATUS_CONNECTION_LOST, STATUS_NARRATION_UNAVAILABLE
from src.server.errors import ActionInFlightError, ApiError
from src.server.models import (
    ChooseRequest,
    CreateSessionRequest,
    FreetextRequest,
    NameRequest,
    NarrateRequest,
)
from src.server.sessions import SessionRecord
from src.themepacks import get_pack

router = APIRouter(prefix="/v1/sessions")


# ---------------------------------------------------------------------------
# Envelope helpers.
# ---------------------------------------------------------------------------


def _session_payload(record: SessionRecord) -> dict:
    """The SessionEnvelope — everything the client needs to render."""
    if record.kind == "chargen":
        session = record.chargen
        contract = CHARGEN_CONTRACT
        if session.completed:
            phase, view = "complete", None
        else:
            phase = session.phase
            view = session.current_choice().model_dump(mode="json")
    else:
        contract = ADVENTURE_CONTRACT
        adv_view = record.adventure.current_view()
        phase = adv_view.phase
        view = dataclasses.asdict(adv_view)
    return {
        "id": record.id,
        "name": record.name,
        "kind": record.kind,
        "phase": phase,
        "view": view,
        "contract_version": contract,
    }


def _summary(record: SessionRecord) -> dict:
    return {"id": record.id, "name": record.name, "kind": record.kind}


def _record(request: Request, session_id: str) -> SessionRecord:
    return request.app.state.registry.get(session_id)


def _new_events_since(record: SessionRecord, start: int) -> list[dict]:
    return [e.model_dump(mode="json") for e in record.game.state.events[start:]]


# ---------------------------------------------------------------------------
# Session CRUD.
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
async def create_session(req: CreateSessionRequest, request: Request) -> dict:
    registry = request.app.state.registry
    if req.from_save is not None:
        # Opening a save: kind is inferred from where the story is.
        record = registry.resume(name=req.from_save)
    elif req.kind == "chargen":
        record = registry.create_chargen(
            name=req.name,
            seed=req.seed,
            pack_id=req.pack_id,
            profile=req.profile,
            death_mode=req.death_mode,
        )
    else:
        raise ApiError(
            422,
            "invalid_config",
            "Adventure sessions start from a completed chargen — "
            "promote a chargen session or open a save (from_save).",
        )
    return {"session": _session_payload(record)}


@router.get("")
async def list_sessions(request: Request) -> dict:
    return {"sessions": [_summary(r) for r in request.app.state.registry.list()]}


@router.get("/{session_id}")
async def get_session(session_id: str, request: Request) -> dict:
    return {"session": _session_payload(_record(request, session_id))}


@router.get("/{session_id}/sheet")
async def get_sheet(session_id: str, request: Request) -> dict:
    """Return the raw game-state document (M0.6b read view for the client)."""
    record = _record(request, session_id)
    return record.game.state.model_dump(mode="json")


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> None:
    request.app.state.registry.delete(session_id)


# ---------------------------------------------------------------------------
# Mutations.
# ---------------------------------------------------------------------------


@router.post("/{session_id}/choose")
async def choose(session_id: str, req: ChooseRequest, request: Request) -> dict:
    record = _record(request, session_id)
    if not record.game.begin_action():
        raise ActionInFlightError("A beat is already in flight for this session")
    try:
        before = len(record.game.state.events)
        if record.kind == "chargen":
            result = record.chargen.choose(req.option_id, origin=req.origin)
        else:
            result = record.adventure.choose(req.option_id)
        request.app.state.registry.autosave(record)
        return {
            "session": _session_payload(record),
            "result": result.model_dump(mode="json"),
            "events": _new_events_since(record, before),
        }
    finally:
        record.game.end_action()


@router.post("/{session_id}/freetext")
async def freetext(session_id: str, req: FreetextRequest, request: Request) -> dict:
    record = _record(request, session_id)
    if not record.game.begin_action():
        raise ActionInFlightError("A beat is already in flight for this session")
    try:
        before = len(record.game.state.events)
        if record.kind == "chargen":
            if request.app.state.translator is None:
                raise ApiError(
                    422,
                    "translator_unavailable",
                    "No translator configured — set the narrator model in Settings",
                )
            translation = await record.chargen.propose(req.text)
            request.app.state.registry.autosave(record)
            return {
                "session": _session_payload(record),
                "record": translation.model_dump(mode="json"),
                "events": _new_events_since(record, before),
            }
        # Adventure: classify is sync + blocking (KTD-9) — threadpool it.
        result = await run_in_threadpool(record.adventure.submit_freetext, req.text)
        request.app.state.registry.autosave(record)
        return {
            "session": _session_payload(record),
            "result": result.model_dump(mode="json"),
            "events": _new_events_since(record, before),
        }
    finally:
        record.game.end_action()


@router.post("/{session_id}/suggest")
async def suggest(session_id: str, request: Request) -> dict:
    record = _record(request, session_id)
    advisor = request.app.state.advisor
    if advisor is None:
        raise ApiError(
            422,
            "advisor_unavailable",
            "No advisor configured — set the narrator model in Settings",
        )
    if not record.game.begin_action():
        raise ActionInFlightError("A beat is already in flight for this session")
    try:
        if record.kind == "chargen":
            suggestion = await record.chargen.suggest()  # records internally
        else:
            view = record.adventure.current_view()
            choice = ChoicePointView(
                choice_id=f"adventure_{view.phase}",
                phase=view.phase,
                prompt=view.prompt or "Choose your action:",
                options=[
                    ChoiceOptionView(
                        option_id=c.option_id,
                        label=c.label,
                        description=c.description,
                        odds_line=c.description or None,
                        dimmed=c.dimmed,
                        requirement=c.requirement or None,
                    )
                    for c in view.choices
                ],
                allows_advisor=True,
                allows_freetext=True,
            )
            rules_summary = view.scaffold_text or "\n".join(view.odds_lines) or "Scene options."
            suggestion = await advisor.suggest(choice, rules_summary)
            if suggestion is not None:
                record_advice(record.game.engine, suggestion)
        if suggestion is not None:
            request.app.state.registry.autosave(record)
        return {"record": suggestion.model_dump(mode="json") if suggestion else None}
    finally:
        record.game.end_action()


@router.post("/{session_id}/name")
async def set_name(session_id: str, req: NameRequest, request: Request) -> dict:
    record = _record(request, session_id)
    if not record.game.begin_action():
        raise ActionInFlightError("A beat is already in flight for this session")
    try:
        record.game.engine.apply(SetCharacterNameCommand(name=req.name))
        request.app.state.registry.autosave(record)
        return {"session": _session_payload(record)}
    finally:
        record.game.end_action()


@router.post("/{session_id}/promote")
async def promote(session_id: str, request: Request) -> dict:
    record = request.app.state.registry.promote(session_id)
    return {"session": _session_payload(record)}


# ---------------------------------------------------------------------------
# Narration stream (NDJSON).
# ---------------------------------------------------------------------------


def _sentences(prose: str) -> list[str]:
    """Split prose into typewriter chunks on sentence-ending punctuation."""
    chunks: list[str] = []
    current = ""
    for char in prose.strip():
        current += char
        if char in ".!?":
            stripped = current.strip()
            if stripped:
                chunks.append(stripped)
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks or ([prose.strip()] if prose.strip() else [])


def _ndjson(block_type: str, content: str) -> str:
    return json.dumps({"type": block_type, "content": content}) + "\n"


@router.post("/{session_id}/narrate")
async def narrate(session_id: str, req: NarrateRequest, request: Request):
    """Stream one narration beat as NDJSON blocks (M0.4/M0.5, spec §3/§5).

    Beat kinds: ``world_intro`` (ceremony; replays its record without
    re-calling the LLM unless steered), ``scene`` / ``chargen_beat`` /
    ``chargen_close`` (facts from the events since the last beat; steering
    re-tells the SAME beat — the past is written, the present can be
    re-told, the future is steered).
    """
    record = _record(request, session_id)
    if not record.game.begin_action():
        raise ActionInFlightError("A beat is already in flight for this session")
    try:
        registry = request.app.state.registry
        engine = record.game.engine
        state = engine.state

        # 1. Beat span: new events, or the last beat's span for a re-tell.
        if record.last_narrated_seq < len(state.events):
            span = (record.last_narrated_seq, len(state.events))
        else:
            span = (record.last_beat_start, record.last_narrated_seq)

        # 2. Steering lands FIRST — it conditions this telling and the next.
        steering = req.steering.strip()
        if steering:
            engine.apply(RecordStoryDirectionCommand(text=steering, beat=req.beat))

        # 3. Facts + memory + curated view (engine-owned; the LLM sees only these).
        facts = build_beat_facts(state.events[span[0] : span[1]])
        memory = narrator_memory(state.events)
        adapter = request.app.state.adapter or LLMAdapter()  # template when unconfigured
        from src.llm.state_view import build_curated_view

        view = build_curated_view(state)

        # 4. Prose — world intro replays its record; everything else narrates.
        is_replay = False
        if req.beat == "world_intro":
            existing = [
                e
                for e in state.events
                if e.command_type == "record_narration" and e.changes.get("beat") == "world_intro"
            ]
            if existing and not steering:
                prose = existing[-1].changes["text"]
                result = NarrationResult(
                    prose=prose, source=existing[-1].changes.get("source", "template")
                )
                is_replay = True
            else:
                pack = get_pack(state.campaign.theme_pack)
                result = await adapter.narrate_world_intro(
                    view,
                    pack_name=pack.name,
                    pack_intro=pack.intro_text,
                    state=state,
                )
        else:
            result = await adapter.narrate_beat(
                view,
                facts,
                state=state,
                steering_text=steering,
                prior_prose=memory.prose,
                directions=memory.directions,
            )

        # 5. Shipped prose is canonical BEFORE the client sees a word.
        if not is_replay:
            engine.apply(
                RecordNarrationCommand(text=result.prose, beat=req.beat, source=result.source)
            )
        registry.autosave(record)
        record.last_beat_start = span[0]
        record.last_narrated_seq = len(state.events)

        # 6. Stream: narration sentences → change lines → degradation badge → done.
        change_lines = derive_recent_change_lines(state.events, since_seq=span[0] - 1)
        badge = None
        if result.llm_failed:
            badge = (
                STATUS_CONNECTION_LOST
                if result.failure_kind == "provider_error"
                else STATUS_NARRATION_UNAVAILABLE
            )

        async def _stream() -> AsyncIterator[str]:
            for sentence in _sentences(result.prose):
                yield _ndjson("narration", sentence)
            for line in change_lines:
                yield _ndjson("change", line.text)
            if badge is not None:
                yield _ndjson("badge", badge)
            yield _ndjson("done", "")

        return StreamingResponse(_stream(), media_type="application/x-ndjson")
    finally:
        record.game.end_action()
