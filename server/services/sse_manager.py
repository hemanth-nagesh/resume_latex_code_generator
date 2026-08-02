"""SSE Event Manager — per-session asyncio.Queue for streaming pipeline progress.

LangGraph nodes emit events via callbacks. Those events land in per-session
asyncio.Queues. The SSE streaming endpoint reads from its session's queue
and yields Server-Sent Events to the client.

Lifecycle:
- Created when POST /generate starts a pipeline run
- Queued events accumulate until GET /stream/{session_id} connects
- Auto-cleanup after 10 minutes of inactivity (heartbeat keeps alive)
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from server.services.types import (
    SSEEvent,
    SessionReadyEvent,
    NodeStartEvent,
    NodeCompleteEvent,
    NodeErrorEvent,
    PipelineErrorEvent,
    CompleteEvent,
    ReviewPendingEvent,
    HeartbeatEvent,
    NodeId,
    SSEEventType,
)

_logger = logging.getLogger(__name__)


class SSEEventManager:
    """Manages per-session SSE event queues with lifecycle tracking.

    Shared instance created once at FastAPI startup. Thread-safe: all
    operations are async and dictionary access is single-threaded in asyncio.
    """

    HEARTBEAT_INTERVAL = 15.0  # seconds
    SESSION_TTL = 600.0  # 10 minutes before stale queue cleanup

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[SSEEvent]] = {}
        self._last_activity: dict[str, float] = {}
        self._pipeline_running: dict[str, bool] = {}
        self._heartbeat_tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Queue lifecycle
    # ------------------------------------------------------------------

    async def create_session(self, session_key: str, session_id: str) -> None:
        """Initialize a session queue and start heartbeat."""
        if session_key in self._queues:
            _logger.debug("SSE queue already exists for %s", session_key)
            return

        self._queues[session_key] = asyncio.Queue(maxsize=200)
        self._last_activity[session_key] = time.monotonic()
        self._pipeline_running[session_key] = True
        self._heartbeat_tasks[session_key] = asyncio.create_task(
            self._heartbeat_loop(session_key)
        )

        await self._emit(
            session_key,
            SessionReadyEvent(
                event=SSEEventType.SESSION_READY,
                session_key=session_key,
                timestamp=_now_iso(),
                session_id=session_id,
            ),
        )

        _logger.info("SSE session created: %s", session_key)

    async def get_queue(
        self, session_key: str
    ) -> asyncio.Queue[SSEEvent] | None:
        """Get the event queue for a session, or None if not found."""
        return self._queues.get(session_key)

    async def remove_session(self, session_key: str) -> None:
        """Clean up a session queue and its heartbeat task."""
        self._pipeline_running.pop(session_key, None)
        self._queues.pop(session_key, None)
        self._last_activity.pop(session_key, None)

        task = self._heartbeat_tasks.pop(session_key, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        _logger.info("SSE session removed: %s", session_key)

    # ------------------------------------------------------------------
    # Event emission (called by LangGraph callbacks)
    # ------------------------------------------------------------------

    async def emit_node_start(self, session_key: str, node: NodeId) -> None:
        await self._emit(
            session_key,
            NodeStartEvent(
                event=SSEEventType.NODE_START,
                session_key=session_key,
                timestamp=_now_iso(),
                node=node,
            ),
        )

    async def emit_node_complete(
        self, session_key: str, node: NodeId, duration_ms: int
    ) -> None:
        await self._emit(
            session_key,
            NodeCompleteEvent(
                event=SSEEventType.NODE_COMPLETE,
                session_key=session_key,
                timestamp=_now_iso(),
                node=node,
                duration_ms=duration_ms,
            ),
        )

    async def emit_node_error(
        self,
        session_key: str,
        node: NodeId,
        error: str,
        will_retry: bool = False,
    ) -> None:
        await self._emit(
            session_key,
            NodeErrorEvent(
                event=SSEEventType.NODE_ERROR,
                session_key=session_key,
                timestamp=_now_iso(),
                node=node,
                error=error,
                will_retry=will_retry,
            ),
        )

    async def emit_complete(
        self,
        session_key: str,
        latex_source: str,
        filename: str,
        warnings: list[str] | None = None,
        pdf_base64: str = "",
    ) -> None:
        await self._emit(
            session_key,
            CompleteEvent(
                event=SSEEventType.COMPLETE,
                session_key=session_key,
                timestamp=_now_iso(),
                latex_source=latex_source,
                filename=filename,
                pdf_base64=pdf_base64,
                warnings=warnings or [],
            ),
        )
        self._pipeline_running[session_key] = False

    async def emit_review_pending(
        self,
        session_key: str,
        latex_source: str,
        warnings: list[str] | None = None,
    ) -> None:
        """Emit after LaTeX is assembled and validated — pipeline pauses here
        for human review before PDF compilation.

        Does NOT set _pipeline_running to False — the session stays alive
        waiting for the approve endpoint to trigger Run 2. Heartbeats
        continue until the user approves or the SESSION_TTL expires."""
        await self._emit(
            session_key,
            ReviewPendingEvent(
                event=SSEEventType.REVIEW_PENDING,
                session_key=session_key,
                timestamp=_now_iso(),
                latex_source=latex_source,
                warnings=warnings or [],
            ),
        )

    async def emit_pipeline_error(
        self,
        session_key: str,
        error: str,
        failed_node: NodeId,
    ) -> None:
        """Emit a fatal pipeline error — NO PDF available."""
        await self._emit(
            session_key,
            PipelineErrorEvent(
                event=SSEEventType.PIPELINE_ERROR,
                session_key=session_key,
                timestamp=_now_iso(),
                error=error,
                failed_node=failed_node,
            ),
        )
        self._pipeline_running[session_key] = False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _emit(self, session_key: str, event: SSEEvent) -> None:
        queue = self._queues.get(session_key)
        if queue is None:
            _logger.warning("No SSE queue for session %s — event dropped", session_key)
            return

        try:
            queue.put_nowait(event)
            self._last_activity[session_key] = time.monotonic()
        except asyncio.QueueFull:
            _logger.warning("SSE queue full for session %s — event dropped", session_key)

    async def _heartbeat_loop(self, session_key: str) -> None:
        """Send periodic heartbeats to keep the SSE connection alive."""
        try:
            while session_key in self._queues:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)

                # Check if session is stale
                last = self._last_activity.get(session_key, 0)
                if time.monotonic() - last > self.SESSION_TTL:
                    _logger.info("SSE session %s stale — cleaning up", session_key)
                    await self.remove_session(session_key)
                    return

                # Don't heartbeat if pipeline finished
                if not self._pipeline_running.get(session_key, False):
                    continue

                await self._emit(
                    session_key,
                    HeartbeatEvent(
                        event=SSEEventType.HEARTBEAT,
                        session_key=session_key,
                        timestamp=_now_iso(),
                    ),
                )
        except asyncio.CancelledError:
            pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_sse_manager: SSEEventManager | None = None


def get_sse_manager() -> SSEEventManager:
    global _sse_manager
    if _sse_manager is None:
        _sse_manager = SSEEventManager()
    return _sse_manager
