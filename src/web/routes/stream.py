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

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.game.narration import build_done_block, build_error_block, build_template_blocks
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
