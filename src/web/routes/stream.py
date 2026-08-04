"""SSE streaming narration endpoint (U10).

Streams typed narration blocks via Server-Sent Events. The action POST
already locked the outcome (mechanics resolved first); this endpoint
fetches the narration idempotently — a browser refresh mid-stream
re-renders the receipt from state and resumes or cleanly skips narration
(KTD-9 pending-beat ownership).

When no LLM is configured, template blocks are emitted through the same
endpoint so the client protocol is identical (AE3 parity).

Per the plan's U10 execution note: pydantic-ai's ``run_stream`` delivers
partial structured output only when the provider streams tool-call deltas.
Several configured providers buffer them. This endpoint uses block-append
delivery (blocks emitted as they finalize) which works universally —
progressive token streaming is a future enhancement gated on per-provider
spike results.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.game.narration import (
    MAX_RETRIES_PER_BEAT,
    build_badge_block,
    build_done_block,
    build_error_block,
    build_template_blocks,
)
from src.web.routes._saves import DEFAULT_SAVES_DIR, load_state_for_save

router = APIRouter(prefix="/stream")


@router.get("/{save_name}/narration")
async def stream_narration(save_name: str) -> StreamingResponse:
    """Stream narration blocks for the current beat via SSE (U10).

    Emits typed blocks (narration, receipt, change) then a ``done`` event.
    Without an LLM configured, template blocks are emitted through the
    same protocol. On error, emits an ``error`` event with a message.
    """

    async def event_stream():
        try:
            # Load the save (LLM streaming is a future enhancement —
            # block-append delivery works universally).
            state, _save_path = load_state_for_save(save_name, DEFAULT_SAVES_DIR)
        except FileNotFoundError:
            yield build_error_block("Save not found.").to_sse()
            return
        except (ValueError, OSError):
            yield build_error_block("Failed to load save.").to_sse()
            return

        try:
            char = state.character

            # Build minimal template blocks from the current state.
            scaffold = f"Character: {char.name}, Career: {char.career or '—'}"
            # outcome_facts intentionally empty — populated when LLM narration is wired in.
            outcome_facts: list[str] = []
            receipts: list[str] = []

            # Extract recent events as receipts (last 3).
            recent_events = state.events[-3:] if state.events else []
            for event in recent_events:
                if event.description:
                    receipts.append(event.description)

            blocks = build_template_blocks(scaffold, outcome_facts, receipts)

            for block in blocks:
                yield block.to_sse()

            # Terminal done event.
            yield build_done_block().to_sse()
        except Exception:
            # Deliver an error event so the SSE client gets a terminal
            # signal instead of a silent stream death, then re-raise so
            # the exception still surfaces in server logs (not swallowed).
            yield build_error_block("Narration generation failed.").to_sse()
            raise

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable proxy buffering
        },
    )


@router.post("/{save_name}/retry")
async def retry_narration(save_name: str, request: Request) -> StreamingResponse:
    """Stream re-narrated blocks with steering text (U15, R17, AE5).

    Accepts ``steering_text`` and ``attempt`` (1-based) from the form body.
    The outcome is locked — only narration prose changes. Emits an
    ``outcome unchanged`` badge before the narration blocks, then ``done``.

    Enforces the retry cap (``MAX_RETRIES_PER_BEAT``): attempts beyond the
    cap receive an error event. Currently emits template blocks in all
    modes; LLM steered narration will be wired in when the narration
    endpoint gains LLM support (matching the ``/narration`` endpoint's
    staging pattern). The ``attempt`` counter is client-provided — a
    best-effort guardrail for single-player localhost.
    """
    form = await request.form()
    steering_text = (form.get("steering_text") or "").strip()[:500]
    attempt_str = form.get("attempt") or "1"
    try:
        attempt = max(1, int(attempt_str))
    except (ValueError, TypeError):
        attempt = 1

    async def retry_stream():
        # Cap enforcement (U15).
        if attempt > MAX_RETRIES_PER_BEAT:
            yield build_error_block(
                f"Retry limit reached ({MAX_RETRIES_PER_BEAT} per beat)."
            ).to_sse()
            return

        try:
            state, _save_path = load_state_for_save(save_name, DEFAULT_SAVES_DIR)
        except FileNotFoundError:
            yield build_error_block("Save not found.").to_sse()
            return
        except (ValueError, OSError):
            yield build_error_block("Failed to load save.").to_sse()
            return

        try:
            # AE5: state is never touched — we only read it to build
            # template blocks. The badge signals this to the player.
            yield build_badge_block("Outcome unchanged — mechanics locked").to_sse()

            char = state.character
            scaffold = f"Character: {char.name}, Career: {char.career or '—'}"
            outcome_facts: list[str] = []
            receipts: list[str] = []

            recent_events = state.events[-3:] if state.events else []
            for event in recent_events:
                if event.description:
                    receipts.append(event.description)

            # Include steering text in the scaffold so template mode at
            # least acknowledges the player's direction.
            if steering_text:
                scaffold += f"\nDirection: {steering_text}"

            blocks = build_template_blocks(scaffold, outcome_facts, receipts)
            for block in blocks:
                yield block.to_sse()

            yield build_done_block().to_sse()
        except Exception:
            yield build_error_block("Re-narration failed.").to_sse()
            raise

    return StreamingResponse(
        retry_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
