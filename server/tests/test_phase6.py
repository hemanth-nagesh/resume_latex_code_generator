"""Phase 6 tests — PDF compilation, fallback, persistence, response builder.

Coverage:
- N10: temp directory creation, pdflatex exit code handling, PDF file reading
- N10f: LaTeX command stripping, fallback document assembly
- N11: slug generation, metadata construction, blob path building
- N12: filename generation, base64 encoding

pdflatex tests are skipped if pdflatex is not installed locally (Docker-only).
"""

from __future__ import annotations

import base64
import os
import shutil

import pytest

from server.graph.n10f_fallback import _build_fallback_document
from server.graph.n11_persister import _slugify, _hash_dict
from server.graph.n12_response import _build_filename
from server.services.latex_utils import strip_latex_commands


# ===========================================================================
# N10 — PDF Compiler
# ===========================================================================

HAS_PDFLATEX = shutil.which("pdflatex") is not None

@pytest.mark.skipif(not HAS_PDFLATEX, reason="pdflatex not installed locally")
class TestN10Compiler:
    def test_basic_compilation(self):
        """Compile a minimal LaTeX document."""
        from server.graph.n10_compiler import _compile
        latex = r"""
\documentclass{article}
\begin{document}
Hello, World!
\end{document}
"""
        import asyncio
        pdf = asyncio.run(_compile(latex, timeout=10))
        assert len(pdf) > 100
        assert pdf[:4] == b"%PDF"

    def test_compilation_error(self):
        """Invalid LaTeX should raise RuntimeError."""
        from server.graph.n10_compiler import _compile
        latex = r"\documentclass{article}\begin{document}\brokenxyz\end{document}"
        import asyncio
        with pytest.raises(RuntimeError, match="exit code"):
            asyncio.run(_compile(latex, timeout=10))

    def test_empty_source(self):
        from server.graph.n10_compiler import run
        from server.graph.state import ResumeState
        import asyncio
        state = ResumeState(latex_source="")
        result = asyncio.run(run(state, pdflatex_timeout=10))
        # Should not crash, just skip with no pdf_bytes
        assert result.get("pdf_bytes") is None

    def test_name_is_ascii(self):
        """N10 module itself should be importable."""
        from server.graph import n10_compiler
        assert hasattr(n10_compiler, "run")


# ===========================================================================
# N10f — Fallback Template
# ===========================================================================

class TestN10fFallback:
    def test_build_fallback_has_all_sections(self):
        sections = {
            "summary": "Experienced engineer.",
            "experience": "Built APIs at TCS.",
            "projects": "API Gateway project.",
            "skills": "Python, FastAPI, Docker.",
        }
        doc = _build_fallback_document(sections)
        assert r"\documentclass" in doc
        assert r"Professional Summary" in doc
        assert "Experienced engineer" in doc
        assert "Experience" in doc
        assert "Projects" in doc
        assert "Technical Skills" in doc

    def test_build_fallback_empty_sections(self):
        sections = {"summary": "", "experience": "", "projects": "", "skills": ""}
        doc = _build_fallback_document(sections)
        assert r"\documentclass" in doc
        assert r"\end{document}" in doc

    def test_strip_latex_commands_removes_custom(self):
        """strip_latex_commands should remove \resumeItem, \textbf, etc."""
        latex = r"\resumeItem{Built API with \textbf{Python} and \emph{FastAPI}}"
        result = strip_latex_commands(latex)
        assert r"\resumeItem" not in result
        assert r"\textbf" not in result
        assert "Built API with Python and FastAPI" in result

    def test_strip_preserves_joint_text(self):
        latex = r"\resumeSubheading{Dev}{2024}{TCS}{India}"
        result = strip_latex_commands(latex)
        assert "Dev" in result
        assert "2024" in result
        assert "TCS" in result

    def test_fallback_importable(self):
        from server.graph import n10f_fallback
        assert hasattr(n10f_fallback, "run")


# ===========================================================================
# N11 — State Persister
# ===========================================================================

class TestN11Persister:
    def test_slugify_simple(self):
        assert _slugify("Tata Consultancy Services") == "tata-consultancy-services"

    def test_slugify_special_chars(self):
        assert _slugify("AI/ML & Prompt Engineer") == "aiml-prompt-engineer"

    def test_slugify_truncation(self):
        long_name = "A" * 100
        assert len(_slugify(long_name)) <= 50

    def test_hash_dict_stable(self):
        jd = {"required_skills": [
            {"skill": "Python", "is_technical": True, "ats_exact_phrase": "Python"},
            {"skill": "Docker", "is_technical": True, "ats_exact_phrase": "Docker"},
        ]}
        h1 = _hash_dict(jd)
        h2 = _hash_dict(jd)
        assert h1 == h2
        assert len(h1) == 12

    def test_hash_dict_order_independent(self):
        a = {"required_skills": [
            {"skill": "Python", "is_technical": True, "ats_exact_phrase": "Python"},
            {"skill": "Docker", "is_technical": True, "ats_exact_phrase": "Docker"},
        ]}
        b = {"required_skills": [
            {"skill": "Docker", "is_technical": True, "ats_exact_phrase": "Docker"},
            {"skill": "Python", "is_technical": True, "ats_exact_phrase": "Python"},
        ]}
        assert _hash_dict(a) == _hash_dict(b)

    def test_importable(self):
        from server.graph import n11_persister
        assert hasattr(n11_persister, "run")


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
# N10 run() — dummy tests (no pdflatex required)
# ===========================================================================

class TestN10RunWithoutPdflatex:
    """Test N10.run() edge cases that don't need pdflatex installed."""

    def test_empty_latex_source_skips_compilation(self):
        from server.graph.n10_compiler import run
        from server.graph.state import ResumeState
        import asyncio
        state = ResumeState(latex_source="")
        result = asyncio.run(run(state))
        assert result.get("pdf_bytes") is None

    def test_missing_latex_source_skips_compilation(self):
        from server.graph.n10_compiler import run
        from server.graph.state import ResumeState
        import asyncio
        state = ResumeState()
        result = asyncio.run(run(state))
        assert result.get("pdf_bytes") is None

    def test_compilation_failure_captures_error(self, monkeypatch):
        """When pdflatex fails, N10 returns warnings, not pdf_bytes."""
        from server.graph.n10_compiler import run, _compile
        import asyncio

        async def fake_compile(*args, **kwargs):
            raise RuntimeError("pdflatex not found")

        monkeypatch.setattr(
            "server.graph.n10_compiler._compile", fake_compile
        )

        from server.graph.state import ResumeState
        state = ResumeState(latex_source=r"\documentclass{article}\begin{document}Hi\end{document}")
        result = asyncio.run(run(state))
        warnings = result.get("warnings", [])
        assert result.get("pdf_bytes") is None
        assert any("pdflatex" in w for w in warnings)


# ===========================================================================
# N10f run() — dummy tests (no pdflatex required)
# ===========================================================================

class TestN10fRunWithoutPdflatex:
    """Test N10f.run() delivers raw LaTeX when pdflatex is missing."""

    def test_pdflatex_missing_delivers_latex_as_bytes(self):
        from server.graph.n10f_fallback import run
        from server.graph.state import ResumeState
        import asyncio

        state = ResumeState(
            sections_output=[
                {"section": "summary", "content": r"Experienced engineer."},
                {"section": "skills", "content": r"\textbf{Languages}{Python}"},
            ],
        )
        result = asyncio.run(run(state))
        # Should get raw LaTeX bytes (pdflatex not installed)
        pdf = result.get("pdf_bytes")
        assert pdf is not None
        assert isinstance(pdf, bytes)
        assert rb"\documentclass" in pdf
        assert b"Professional Summary" in pdf
        warnings = result.get("warnings", [])
        assert any("pdflatex not installed" in w for w in warnings)

    def test_empty_sections_output_doesnt_crash(self):
        from server.graph.n10f_fallback import run
        from server.graph.state import ResumeState
        import asyncio

        state = ResumeState(sections_output=[])
        result = asyncio.run(run(state))
        pdf = result.get("pdf_bytes")
        assert pdf is not None
        assert rb"\documentclass" in pdf

    def test_no_sections_output_doesnt_crash(self):
        from server.graph.n10f_fallback import run
        from server.graph.state import ResumeState
        import asyncio

        state = ResumeState()
        result = asyncio.run(run(state))
        pdf = result.get("pdf_bytes")
        assert pdf is not None

    def test_strips_custom_commands_from_sections(self):
        from server.graph.n10f_fallback import run
        from server.graph.state import ResumeState
        import asyncio

        state = ResumeState(
            sections_output=[{
                "section": "experience",
                "content": (
                    r"\resumeSubheading{ML Engineer}{2022--2024}{TCS}{India}"
                    r"\resumeItem{Built \textbf{scalable} APIs with 99.9\% uptime}"
                ),
            }],
        )
        result = asyncio.run(run(state))
        pdf = result.get("pdf_bytes")
        decoded = pdf.decode("utf-8")
        assert r"\resumeSubheading" not in decoded
        assert "ML Engineer" in decoded
        assert "TCS" in decoded
        assert "99.9" in decoded

    def test_latex_source_set_on_output(self):
        from server.graph.n10f_fallback import run
        from server.graph.state import ResumeState
        import asyncio

        state = ResumeState(
            sections_output=[
                {"section": "summary", "content": "A short bio."},
            ],
        )
        result = asyncio.run(run(state))
        assert result.get("latex_source") is not None
        assert r"\begin{document}" in result["latex_source"]


# ===========================================================================
# N10f run() — mocked pdflatex success
# ===========================================================================

class TestN10fMockedPdflatex:
    """Test N10f when pdflatex IS available (mocked subprocess)."""

    def test_pdflatex_success_produces_real_pdf_bytes(self, monkeypatch):
        from server.graph.n10f_fallback import run
        from server.graph.state import ResumeState
        import asyncio

        fake_pdf = b"%PDF-1.4\n%fake pdf content\n%%EOF"
        async def fake_compile(*args, **kwargs):
            return fake_pdf

        monkeypatch.setattr(
            "server.graph.n10_compiler._compile", fake_compile
        )

        state = ResumeState(
            sections_output=[
                {"section": "summary", "content": "Test summary."},
            ],
        )
        result = asyncio.run(run(state))
        assert result.get("pdf_bytes") == fake_pdf
        warnings = result.get("warnings", [])
        assert any("fallback template" in w.lower() for w in warnings)

    def test_pdflatex_error_delivers_latex_text(self, monkeypatch):
        from server.graph.n10f_fallback import run
        from server.graph.state import ResumeState
        import asyncio

        async def fake_compile(*args, **kwargs):
            raise RuntimeError("Something broke in pdflatex!")

        monkeypatch.setattr(
            "server.graph.n10_compiler._compile", fake_compile
        )

        state = ResumeState(
            sections_output=[
                {"section": "summary", "content": "Test."},
            ],
        )
        result = asyncio.run(run(state))
        pdf = result.get("pdf_bytes")
        assert pdf is not None
        assert rb"\documentclass" in pdf  # raw LaTeX delivered as bytes
        warnings = result.get("warnings", [])
        assert any("Something broke" in w for w in warnings)


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
        result = asyncio.run(run(state, blob=None))
        assert result.get("latex_source") is not None
        assert result.get("latex_filename") is not None
        assert ".tex" in result["latex_filename"]
        assert r"\documentclass" in result["latex_source"]

    def test_no_latex_produces_warning(self):
        from server.graph.n12_response import run
        from server.graph.state import ResumeState
        import asyncio

        state = ResumeState(session_key="empty")
        result = asyncio.run(run(state, blob=None))
        assert result.get("latex_source") is None
        assert any("No LaTeX" in w for w in result.get("warnings", []))


# ===========================================================================
# Integration: N10f → N10 compilation chain
# ===========================================================================

@pytest.mark.skipif(not HAS_PDFLATEX, reason="pdflatex not installed locally")
class TestFallbackToPdfChain:
    def test_fallback_document_compiles(self):
        """The fallback document should be valid LaTeX that compiles."""
        from server.graph.n10_compiler import _compile
        sections = {
            "summary": "Experienced backend engineer with 4 years in AI/ML.",
            "experience": "Built scalable APIs and ML pipelines at TCS.",
            "projects": "API Gateway: High-availability microservices platform.",
            "skills": "Python, FastAPI, PostgreSQL, Docker, Azure.",
        }
        doc = _build_fallback_document(sections)
        import asyncio
        pdf = asyncio.run(_compile(doc, timeout=10))
        assert len(pdf) > 100
        assert pdf[:4] == b"%PDF"
