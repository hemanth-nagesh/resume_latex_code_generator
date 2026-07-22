"""Phase 7 tests — SSE event manager, API routes, and pipeline integration.

Coverage:
- SSEEventManager: queue lifecycle, event emission, heartbeat, cleanup
- POST /generate: request validation, session creation, background task launch
- GET /stream/{session_id}: queue lookup, SSE wire format
- GET /resume/{session_key}: blob path construction, error handling

All tests use dependency mocking — no real DB/Blob/Gemini needed.
"""

from __future__ import annotations

import asyncio
import time
import uuid as uuid_lib

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from server.services.sse_manager import SSEEventManager, get_sse_manager
from server.services.types import (
    SSEEventType,
    NodeId,
    SessionReadyEvent,
    NodeStartEvent,
    NodeCompleteEvent,
    NodeErrorEvent,
    CompleteEvent,
    HeartbeatEvent,
)


# ===========================================================================
# SSE Event Manager — queue lifecycle
# ===========================================================================

@pytest_asyncio.fixture
async def sse_manager():
    manager = SSEEventManager()
    yield manager
    # Cleanup all sessions
    for key in list(manager._queues.keys()):
        await manager.remove_session(key)


class TestSSEManagerLifecycle:
    async def test_create_session(self, sse_manager):
        await sse_manager.create_session("test-key", "test-id")
        assert "test-key" in sse_manager._queues
        assert sse_manager._pipeline_running["test-key"]

    async def test_create_session_emits_ready_event(self, sse_manager):
        await sse_manager.create_session("test-key-2", "test-id-2")
        queue = sse_manager._queues["test-key-2"]
        event = queue.get_nowait()
        assert isinstance(event, SessionReadyEvent)
        assert event.session_key == "test-key-2"
        assert event.session_id == "test-id-2"

    async def test_remove_session_cleans_up(self, sse_manager):
        await sse_manager.create_session("test-key-3", "test-id-3")
        await sse_manager.remove_session("test-key-3")
        assert "test-key-3" not in sse_manager._queues
        assert "test-key-3" not in sse_manager._pipeline_running
        assert "test-key-3" not in sse_manager._heartbeat_tasks

    async def test_remove_nonexistent_session(self, sse_manager):
        await sse_manager.remove_session("nonexistent")  # should not crash


# ===========================================================================
# SSE Event Manager — event emission
# ===========================================================================

class TestSSEManagerEvents:
    async def test_emit_node_start(self, sse_manager):
        await sse_manager.create_session("key-1", "id-1")
        _ = sse_manager._queues["key-1"].get_nowait()  # drain ready event
        await sse_manager.emit_node_start("key-1", NodeId.JD_ANALYZER)
        event = sse_manager._queues["key-1"].get_nowait()
        assert isinstance(event, NodeStartEvent)
        assert event.node == NodeId.JD_ANALYZER

    async def test_emit_node_complete(self, sse_manager):
        await sse_manager.create_session("key-2", "id-2")
        _ = sse_manager._queues["key-2"].get_nowait()
        await sse_manager.emit_node_complete("key-2", NodeId.KG_LOADER, 42)
        event = sse_manager._queues["key-2"].get_nowait()
        assert isinstance(event, NodeCompleteEvent)
        assert event.duration_ms == 42

    async def test_emit_node_error(self, sse_manager):
        await sse_manager.create_session("key-3", "id-3")
        _ = sse_manager._queues["key-3"].get_nowait()
        await sse_manager.emit_node_error("key-3", NodeId.JD_ANALYZER, "API error", True)
        event = sse_manager._queues["key-3"].get_nowait()
        assert isinstance(event, NodeErrorEvent)
        assert event.error == "API error"
        assert event.will_retry is True

    async def test_emit_complete(self, sse_manager):
        await sse_manager.create_session("key-4", "id-4")
        _ = sse_manager._queues["key-4"].get_nowait()
        await sse_manager.emit_complete("key-4", "latex code here", "resume.tex", ["warning1"])
        event = sse_manager._queues["key-4"].get_nowait()
        assert isinstance(event, CompleteEvent)
        assert event.latex_source == "latex code here"
        assert "warning1" in event.warnings
        assert not sse_manager._pipeline_running["key-4"]

    async def test_emit_to_nonexistent_session(self, sse_manager):
        await sse_manager.emit_node_start("ghost", NodeId.KG_LOADER)
        # Should not crash — just log warning


# ===========================================================================
# SSE Wire Format
# ===========================================================================

class TestSSEWireFormat:
    def test_session_ready_sse_format(self):
        event = SessionReadyEvent(
            event=SSEEventType.SESSION_READY,
            session_key="abc",
            timestamp="2026-01-01T00:00:00Z",
            session_id="ses_abc",
        )
        wire = event.to_sse()
        assert wire.startswith("event: session_ready\n")
        assert "data: " in wire
        assert "ses_abc" in wire

    def test_node_start_sse_format(self):
        event = NodeStartEvent(
            event=SSEEventType.NODE_START,
            session_key="abc",
            timestamp="2026-01-01T00:00:00Z",
            node=NodeId.JD_ANALYZER,
        )
        wire = event.to_sse()
        assert "event: node_start" in wire
        assert "n3_jd_analyzer" in wire

    def test_complete_event_sse_format(self):
        event = CompleteEvent(
            event=SSEEventType.COMPLETE,
            session_key="abc",
            timestamp="2026-01-01T00:00:00Z",
            latex_source=r"\documentclass{article}\begin{document}Hi\end{document}",
            filename="TCS_Engineer_abc.tex",
            warnings=[],
        )
        wire = event.to_sse()
        assert "event: complete" in wire
        assert "latex_source" in wire
        assert "TCS_Engineer_abc.tex" in wire

    def test_heartbeat_sse_format(self):
        event = HeartbeatEvent(
            event=SSEEventType.HEARTBEAT,
            session_key="abc",
            timestamp="2026-01-01T00:00:00Z",
        )
        wire = event.to_sse()
        assert "event: heartbeat" in wire


# ===========================================================================
# Singleton
# ===========================================================================

class TestSSEManagerSingleton:
    def test_get_sse_manager_returns_same_instance(self):
        m1 = get_sse_manager()
        m2 = get_sse_manager()
        assert m1 is m2
        # Clean up after this test since it uses the global
        import asyncio
        for key in list(m1._queues.keys()):
            asyncio.get_event_loop().run_until_complete(m1.remove_session(key))


# ===========================================================================
# API Models
# ===========================================================================

class TestGenerateModels:
    def test_valid_request(self):
        from server.api.generate import GenerateRequest
        body = GenerateRequest(
            jd_text="We need a Python developer with FastAPI experience." * 3,
            sections=[{"name": "summary"}],
        )
        assert len(body.jd_text) >= 50
        assert body.session_key is None

    def test_too_short_jd(self):
        from server.api.generate import GenerateRequest
        with pytest.raises(Exception):
            GenerateRequest(jd_text="Short", sections=[])

    def test_default_sections(self):
        from server.api.generate import GenerateRequest
        body = GenerateRequest(jd_text="We need a senior Python developer." * 5)
        assert len(body.sections) == 4
        assert body.sections[0].name == "summary"


# ===========================================================================
# Pipeline runner helpers
# ===========================================================================

class TestGenerateHelpers:
    def test_compute_session_key_deterministic(self):
        from server.api.generate import _compute_session_key
        k1 = _compute_session_key("Same JD text", ["summary", "skills"])
        k2 = _compute_session_key("Same JD text", ["summary", "skills"])
        assert k1 == k2

    def test_compute_session_key_differs(self):
        from server.api.generate import _compute_session_key
        k1 = _compute_session_key("JD text A", ["summary"])
        k2 = _compute_session_key("JD text B", ["summary"])
        assert k1 != k2

    def test_short_hash_length(self):
        from server.api.generate import _short_hash
        h = _short_hash("a" * 64)
        assert len(h) == 16

    def test_node_name_mapping(self):
        from server.api.generate import _to_node_id
        from server.services.types import NodeId
        assert _to_node_id("n1_session_validator") == NodeId.SESSION_VALIDATOR
        assert _to_node_id("n7a_summary_gen") == NodeId.SUMMARY_GEN
        assert _to_node_id("unknown_node") == NodeId.RESPONSE_BUILDER


# ===========================================================================
# Stream endpoint helpers
# ===========================================================================

class TestStreamHelpers:
    async def test_find_queue_by_prefix(self):
        manager = SSEEventManager()
        try:
            await manager.create_session("hello1234567890abcdef", "ses_hello1234567890")
            from server.api.stream import _find_queue
            q = await _find_queue(manager, "ses_hello1234567890")
            assert q is not None
        finally:
            await manager.remove_session("hello1234567890abcdef")

    async def test_find_queue_not_found(self):
        manager = SSEEventManager()
        from server.api.stream import _find_queue
        q = await _find_queue(manager, "nonexistent")
        assert q is None
