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

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.engine.persistence import load
from src.game.narration import build_done_block, build_error_block, build_template_blocks
from src.game.saves import resolve_save_path

router = APIRouter(prefix="/stream")

DEFAULT_SAVES_DIR = Path("saves")


@router.get("/{save_name}/narration")
async def stream_narration(save_name: str, request: Request) -> StreamingResponse:
    """Stream narration blocks for the current beat via SSE (U10).

    Emits typed blocks (narration, receipt, change) then a ``done`` event.
    Without an LLM configured, template blocks are emitted through the
    same protocol. On error, emits an ``error`` event with a message.
    """

    async def event_stream():
        try:
            # Load the save and build template blocks (LLM streaming is
            # a future enhancement — block-append delivery works universally).
            saves_dir = DEFAULT_SAVES_DIR
            save_path = resolve_save_path(saves_dir, save_name)
            if not save_path.exists():
                yield build_error_block("Save not found.").to_sse()
                return

            state = load(save_path)
            char = state.character

            # Build minimal template blocks from the current state.
            scaffold = f"Character: {char.name}, Career: {char.career or '—'}"
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

        except Exception as exc:
            yield build_error_block(f"Stream error: {exc!s}").to_sse()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable proxy buffering
        },
    )
