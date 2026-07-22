"""GET /api/stream/{session_id} — SSE event stream for pipeline progress.

The client opens this endpoint immediately after POST /generate returns.
Events arrive as Server-Sent Events with named event types:
  event: session_ready
  event: node_start
  event: node_complete
  event: node_error
  event: complete
  event: heartbeat  (every 15s while pipeline runs)

The connection stays open until the pipeline completes or the client
disconnects. On disconnect, the queue continues buffering (up to 200 events)
so a reconnecting client can catch up.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from server.services.sse_manager import get_sse_manager, SSEEventManager
from server.services.types import SSEEventType

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])


@router.get("/stream/{session_id}")
async def stream(session_id: str, request: Request) -> StreamingResponse:
    sse_manager = get_sse_manager()

    # Walk all sessions to find the matching queue
    # (session_id is a short form of session_key — we need the real key)
    queue = await _find_queue(sse_manager, session_id)
    if queue is None:
        # Queue not found yet or already cleaned up — return 404
        return StreamingResponse(
            _empty_stream(session_id),
            media_type="text/event-stream",
        )

    return StreamingResponse(
        _event_stream(sse_manager, queue, session_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


async def _event_stream(
    sse_manager: SSEEventManager,
    queue: asyncio.Queue,
    session_id: str,
    request: Request,
):
    """Yield SSE events until pipeline completes or client disconnects."""
    try:
        while True:
            if await request.is_disconnected():
                _logger.info("SSE client disconnected: %s", session_id)
                break

            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield event.to_sse()
                queue.task_done()

                # Stop after complete or pipeline_error events
                if event.event.value in ("complete", "pipeline_error"):
                    break
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        _logger.error("SSE stream error for %s: %s", session_id, exc)


async def _empty_stream(session_id: str):
    """Return a single error event when the session queue is not found."""
    yield f"event: error\ndata: {{\"error\": \"Session {session_id} not found\"}}\n\n"


async def _find_queue(
    sse_manager: SSEEventManager, session_id: str
) -> asyncio.Queue | None:
    """Find the queue matching this session_id.

    The session_id is a short prefix of the full session_key. We check
    all active queues and return the first match.
    """
    prefix = session_id.replace("ses_", "")
    for key, queue in sse_manager._queues.items():
        if key.startswith(prefix) or prefix in key:
            return queue
    return None
