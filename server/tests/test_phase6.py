"""Phase 6 tests — LaTeX/PDF response building.

N10 (local pdflatex compiler), N10f (local fallback), and N11 (Blob
persister) have been retired in favor of the MCP-based
PdfCompilationService (see tests/test_pdf_mcp.py for that coverage —
fallback-document construction, retry behavior, and Postgres persistence
are all tested there). This file now only covers N12 — the response
builder — plus the base64 encoding it relies on.
"""

from __future__ import annotations

import base64

from server.graph.n12_response import _build_filename


# ===========================================================================
# N12 — Response Builder
# ===========================================================================

class TestN12Response:
    def test_filename_with_role(self):
        from server.graph.state import ResumeState
        state = ResumeState(
            session_key="abc123def456",
            selected_roles=[{
                "company_name": "Tata Consultancy Services",
                "role_title": "AI/ML Engineer",
            }],
        )
        filename = _build_filename(state)
        assert filename.startswith("Tata_")
        assert filename.endswith(".tex")
        assert "ai-ml" not in filename  # uses simplified first-word only

    def test_filename_no_role(self):
        from server.graph.state import ResumeState
        state = ResumeState(session_key="abc123def456")
        filename = _build_filename(state)
        assert "resume" in filename
        assert filename.endswith(".tex")

    def test_filename_includes_session_key(self):
        from server.graph.state import ResumeState
        state = ResumeState(session_key="hello12abc")
        filename = _build_filename(state)
        assert "hello12" in filename

    def test_base64_encoding(self):
        """Verify standard Base64 encoding produces valid output."""
        data = b"Hello, PDF world!"
        encoded = base64.b64encode(data).decode("ascii")
        decoded = base64.b64decode(encoded)
        assert decoded == data
        assert encoded == "SGVsbG8sIFBERiB3b3JsZCE="

    def test_importable(self):
        from server.graph import n12_response
        assert hasattr(n12_response, "run")


# ===========================================================================
# N12 run() — state integration tests
# ===========================================================================

class TestN12Run:
    """Test N12.run() with various input states."""

    def test_builds_response_from_latex(self):
        from server.graph.n12_response import run
        from server.graph.state import ResumeState
        import asyncio

        state = ResumeState(
            session_key="test12345",
            latex_source=r"\documentclass{article}\begin{document}Test\end{document}",
            selected_roles=[{"company_name": "TCS", "role_title": "Dev"}],
        )
        result = asyncio.run(run(state))
        assert result.get("latex_source") is not None
        assert result.get("latex_filename") is not None
        assert ".tex" in result["latex_filename"]
        assert r"\documentclass" in result["latex_source"]

    def test_no_latex_produces_warning(self):
        from server.graph.n12_response import run
        from server.graph.state import ResumeState
        import asyncio

        state = ResumeState(session_key="empty")
        result = asyncio.run(run(state))
        assert result.get("latex_source") is None
        assert any("No LaTeX" in w for w in result.get("warnings", []))
