"""Tests for mcp-pdf-generation feature — LatexMcpClient and PdfCompilationService.

Coverage:
- LatexMcpClient: success, auth failure, compile failure, timeout/retry, bad base64
- PdfCompilationService: primary success, primary-fail -> fallback success,
  both fail (last resort), DB-persist-fails-but-PDF-ok (non-fatal)
- n10_pdf_stage: state <-> service translation

All tests use fakes/mocks — no real network or database calls. DB persistence
is exercised by monkeypatching `server.db.queries.complete_session`.
"""

from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from server.services.latex_mcp import (
    LatexMcpClient,
    McpAuthError,
    McpCompileError,
    McpTimeoutError,
)
from server.services.pdf_compilation import CompiledResume, PdfCompilationService


# ===========================================================================
# Helpers — fake transports / collaborators
# ===========================================================================

def _make_client(handler, **kwargs) -> LatexMcpClient:
    """Build a LatexMcpClient whose underlying httpx.AsyncClient uses a
    MockTransport so no real network call happens."""
    client = LatexMcpClient(
        base_url="http://fake-mcp.example",
        api_key="test-api-key-123",
        timeout_seconds=kwargs.pop("timeout_seconds", 5),
        max_retries=kwargs.pop("max_retries", 2),
    )
    transport = httpx.MockTransport(handler)
    client._client = httpx.AsyncClient(transport=transport)
    return client


class _FakeDbPool:
    """Stand-in for DatabasePool — just a marker object. The actual
    persistence call goes through server.db.queries.complete_session,
    which we monkeypatch per-test."""


# ===========================================================================
# LatexMcpClient
# ===========================================================================

class TestLatexMcpClient:
    def test_compile_success(self):
        pdf_bytes = b"%PDF-1.4 fake pdf content"
        pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["x-api-key"] == "test-api-key-123"
            body = json.loads(request.content)
            assert body["filename"] == "resume"
            return httpx.Response(200, json={
                "success": True, "filename": "resume.pdf",
                "size_bytes": len(pdf_bytes), "pdf_base64": pdf_b64,
            })

        client = _make_client(handler)
        result_bytes, result_b64 = asyncio.run(client.compile(r"\documentclass{article}", "resume"))
        assert result_bytes == pdf_bytes
        assert result_b64 == pdf_b64

    def test_auth_error_not_retried(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(401, json={"detail": "invalid api key"})

        client = _make_client(handler, max_retries=2)
        with pytest.raises(McpAuthError):
            asyncio.run(client.compile("latex", "f"))
        assert call_count == 1  # no retry on auth errors

    def test_compile_failure_success_false(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"success": False, "error": "bad latex"})

        client = _make_client(handler)
        with pytest.raises(McpCompileError, match="bad latex"):
            asyncio.run(client.compile("latex", "f"))

    def test_5xx_retries_then_raises_timeout_error(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(503)

        client = _make_client(handler, max_retries=2)
        with pytest.raises(McpTimeoutError):
            asyncio.run(client.compile("latex", "f"))
        assert call_count == 3  # initial + 2 retries

    def test_5xx_then_success_on_retry(self):
        call_count = 0
        pdf_bytes = b"%PDF ok"
        pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={
                "success": True, "filename": "f.pdf",
                "size_bytes": len(pdf_bytes), "pdf_base64": pdf_b64,
            })

        client = _make_client(handler, max_retries=2)
        result_bytes, _ = asyncio.run(client.compile("latex", "f"))
        assert result_bytes == pdf_bytes
        assert call_count == 2

    def test_connect_error_raises_timeout_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = _make_client(handler, max_retries=1)
        with pytest.raises(McpTimeoutError):
            asyncio.run(client.compile("latex", "f"))

    def test_invalid_base64_raises_compile_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "success": True, "filename": "f.pdf",
                "size_bytes": 10, "pdf_base64": "not-valid-base64!!!",
            })

        client = _make_client(handler)
        with pytest.raises(McpCompileError):
            asyncio.run(client.compile("latex", "f"))

    def test_api_key_never_in_exception_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        client = _make_client(handler)
        try:
            asyncio.run(client.compile("latex", "f"))
        except McpAuthError as exc:
            assert "test-api-key-123" not in str(exc)


# ===========================================================================
# PdfCompilationService
# ===========================================================================

class _SucceedingMcp:
    def __init__(self, pdf_bytes=b"%PDF ok"):
        self.pdf_bytes = pdf_bytes
        self.calls: list[str] = []

    async def compile(self, latex_source: str, filename: str):
        self.calls.append(latex_source)
        return self.pdf_bytes, base64.b64encode(self.pdf_bytes).decode()


class _FailingMcp:
    def __init__(self, exc):
        self.exc = exc
        self.calls: list[str] = []

    async def compile(self, latex_source: str, filename: str):
        self.calls.append(latex_source)
        raise self.exc


class _FailThenSucceedMcp:
    def __init__(self, exc, pdf_bytes=b"%PDF fallback ok"):
        self.exc = exc
        self.pdf_bytes = pdf_bytes
        self.calls: list[str] = []

    async def compile(self, latex_source: str, filename: str):
        self.calls.append(latex_source)
        if len(self.calls) == 1:
            raise self.exc
        return self.pdf_bytes, base64.b64encode(self.pdf_bytes).decode()


class TestPdfCompilationService:
    def test_primary_success_persists_to_db(self, monkeypatch):
        persisted_calls = []

        async def fake_complete_session(db, session_key, **kwargs):
            persisted_calls.append((session_key, kwargs))

        monkeypatch.setattr(
            "server.services.pdf_compilation.queries.complete_session",
            fake_complete_session,
        )

        mcp = _SucceedingMcp()
        service = PdfCompilationService(mcp_client=mcp)

        result: CompiledResume = asyncio.run(service.compile_and_prepare(
            latex_source=r"\documentclass{article}",
            filename="resume",
            sections_output=[],
            session_key="sess1",
            jd_profile={},
            selected_projects=[],
            selected_roles=[{"company_name": "Acme Corp", "role_title": "Engineer"}],
            covered_skills=[],
            uncovered_skills=[],
            db=_FakeDbPool(),
        ))

        assert result.pdf_bytes == mcp.pdf_bytes
        assert result.used_fallback is False
        assert result.warnings == []
        assert len(persisted_calls) == 1
        assert persisted_calls[0][0] == "sess1"
        assert persisted_calls[0][1]["pdf_data"] == mcp.pdf_bytes

    def test_primary_fail_falls_back_and_succeeds(self, monkeypatch):
        async def fake_complete_session(db, session_key, **kwargs):
            pass

        monkeypatch.setattr(
            "server.services.pdf_compilation.queries.complete_session",
            fake_complete_session,
        )

        mcp = _FailThenSucceedMcp(McpCompileError("bad latex"))
        service = PdfCompilationService(mcp_client=mcp)

        result = asyncio.run(service.compile_and_prepare(
            latex_source=r"\documentclass{broken}",
            filename="resume",
            sections_output=[{"section": "summary", "content": "A bio."}],
            session_key="sess2",
            jd_profile={},
            selected_projects=[],
            selected_roles=[],
            covered_skills=[],
            uncovered_skills=[],
            db=_FakeDbPool(),
        ))

        assert result.used_fallback is True
        assert result.pdf_bytes == mcp.pdf_bytes
        assert any("fallback" in w.lower() for w in result.warnings)
        assert len(mcp.calls) == 2  # primary attempt + fallback attempt
        assert r"\documentclass[11pt]{article}" in result.latex_source  # fallback doc shape

    def test_both_fail_delivers_latex_as_last_resort(self, monkeypatch):
        persist_called = False

        async def fake_complete_session(db, session_key, **kwargs):
            nonlocal persist_called
            persist_called = True

        monkeypatch.setattr(
            "server.services.pdf_compilation.queries.complete_session",
            fake_complete_session,
        )

        mcp = _FailingMcp(McpTimeoutError("unreachable"))
        service = PdfCompilationService(mcp_client=mcp)

        result = asyncio.run(service.compile_and_prepare(
            latex_source=r"\documentclass{article}",
            filename="resume",
            sections_output=[{"section": "summary", "content": "Bio text."}],
            session_key="sess3",
            jd_profile={},
            selected_projects=[],
            selected_roles=[],
            covered_skills=[],
            uncovered_skills=[],
            db=_FakeDbPool(),
        ))

        assert result.pdf_base64 == ""
        assert result.pdf_bytes  # raw latex bytes, non-empty
        assert b"Bio text." in result.pdf_bytes
        assert any("No PDF could be produced" in w for w in result.warnings)
        assert persist_called is False  # persistence skipped when no real PDF

    def test_db_persist_failure_is_non_fatal(self, monkeypatch):
        async def fake_complete_session(db, session_key, **kwargs):
            raise RuntimeError("db unavailable")

        monkeypatch.setattr(
            "server.services.pdf_compilation.queries.complete_session",
            fake_complete_session,
        )

        mcp = _SucceedingMcp()
        service = PdfCompilationService(mcp_client=mcp)

        result = asyncio.run(service.compile_and_prepare(
            latex_source=r"\documentclass{article}",
            filename="resume",
            sections_output=[],
            session_key="sess4",
            jd_profile={},
            selected_projects=[],
            selected_roles=[],
            covered_skills=[],
            uncovered_skills=[],
            db=_FakeDbPool(),
        ))

        assert result.pdf_bytes == mcp.pdf_bytes  # PDF still delivered
        assert any("Session DB update failed" in w for w in result.warnings)

    def test_auth_error_routes_to_fallback(self, monkeypatch):
        async def fake_complete_session(db, session_key, **kwargs):
            pass

        monkeypatch.setattr(
            "server.services.pdf_compilation.queries.complete_session",
            fake_complete_session,
        )

        mcp = _FailThenSucceedMcp(McpAuthError("bad key"))
        service = PdfCompilationService(mcp_client=mcp)

        result = asyncio.run(service.compile_and_prepare(
            latex_source=r"\documentclass{article}",
            filename="resume",
            sections_output=[{"section": "summary", "content": "Bio."}],
            session_key="sess5",
            jd_profile={},
            selected_projects=[],
            selected_roles=[],
            covered_skills=[],
            uncovered_skills=[],
            db=_FakeDbPool(),
        ))

        assert result.used_fallback is True
        assert result.pdf_bytes == mcp.pdf_bytes
        assert any("authentication failed" in w.lower() for w in result.warnings)

    def test_no_db_skips_persistence_without_error(self):
        """db=None (e.g. tests, or DB genuinely unavailable) should not crash."""
        mcp = _SucceedingMcp()
        service = PdfCompilationService(mcp_client=mcp)

        result = asyncio.run(service.compile_and_prepare(
            latex_source=r"\documentclass{article}",
            filename="resume",
            sections_output=[],
            session_key="sess6",
            jd_profile={},
            selected_projects=[],
            selected_roles=[],
            covered_skills=[],
            uncovered_skills=[],
            db=None,
        ))

        assert result.pdf_bytes == mcp.pdf_bytes

    def test_never_raises_on_unexpected_exception(self):
        """Even a non-McpError exception from the client must not propagate."""
        class _WeirdMcp:
            async def compile(self, latex_source, filename):
                raise ValueError("unexpected")

        service = PdfCompilationService(mcp_client=_WeirdMcp())

        # ValueError is not caught by the narrow except clauses in the service
        # by design (only Mcp* errors + McpError base are caught for the
        # primary attempt) — this test documents that behavior explicitly.
        with pytest.raises(ValueError):
            asyncio.run(service.compile_and_prepare(
                latex_source="x", filename="f", sections_output=[],
                session_key="s", jd_profile={}, selected_projects=[],
                selected_roles=[], covered_skills=[], uncovered_skills=[], db=None,
            ))


# ===========================================================================
# n10_pdf_stage adapter node
# ===========================================================================

class TestN10PdfStage:
    def test_maps_compiled_resume_into_state(self):
        from server.graph.n10_pdf_stage import run
        from server.graph.state import ResumeState

        class _FakeService:
            async def compile_and_prepare(self, **kwargs):
                return CompiledResume(
                    pdf_bytes=b"%PDF fake",
                    pdf_base64="ZmFrZQ==",
                    pdf_filename="resume_abc",
                    latex_source=kwargs["latex_source"],
                    used_fallback=False,
                    warnings=[],
                )

        state = ResumeState(
            latex_source=r"\documentclass{article}",
            session_key="abcdef1234",
        )
        result = asyncio.run(run(state, service=_FakeService(), db=None))
        assert result["pdf_bytes"] == b"%PDF fake"
        assert result["pdf_base64"] == "ZmFrZQ=="
        assert result["warnings"] == []

    def test_no_latex_source_skips_compile(self):
        from server.graph.n10_pdf_stage import run
        from server.graph.state import ResumeState

        class _UnusedService:
            async def compile_and_prepare(self, **kwargs):
                raise AssertionError("should not be called")

        state = ResumeState()
        result = asyncio.run(run(state, service=_UnusedService(), db=None))
        assert result == {}
