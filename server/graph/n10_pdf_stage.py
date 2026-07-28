"""N10 — PDF Stage (adapter node).

Thin translation layer between ResumeState and PdfCompilationService.
Replaces the previously-separate N10 (pdflatex subprocess), N10f (local
fallback), and N11 (state persister) nodes with a single call into the
use-case service selected in the mcp-pdf-generation design (Candidate B —
Compilation Boundary Service). See
.kiro/specs/mcp-pdf-generation/design.md for the full rationale.

This node never inspects HTTP/MCP-specific details — it only sees the
CompiledResume contract returned by the service (INV-B1).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from server.graph.state import ResumeState

if TYPE_CHECKING:
    from server.services.database import DatabasePool
    from server.services.pdf_compilation import PdfCompilationService

_logger = logging.getLogger(__name__)


async def run(
    state: ResumeState,
    *,
    service: PdfCompilationService,
    db: DatabasePool | None = None,
) -> ResumeState:
    latex_source = state.get("latex_source", "")

    if not latex_source:
        _logger.warning("N10: No LaTeX source to compile")
        return ResumeState()

    filename = _build_filename(state)

    _logger.info("N10: Compiling %d chars of LaTeX via LaTeX MCP", len(latex_source))

    result = await service.compile_and_prepare(
        latex_source=latex_source,
        filename=filename,
        sections_output=state.get("sections_output", []),
        session_key=state.get("session_key", ""),
        jd_profile=state.get("jd_profile", {}),
        selected_projects=state.get("selected_projects", []),
        selected_roles=state.get("selected_roles", []),
        covered_skills=state.get("covered_skills", []),
        uncovered_skills=state.get("uncovered_skills", []),
        db=db,
    )

    if result.used_fallback:
        _logger.warning("N10: Used fallback document for session %s", state.get("session_key"))

    return ResumeState(
        pdf_bytes=result.pdf_bytes,
        pdf_base64=result.pdf_base64,
        pdf_filename=result.pdf_filename,
        latex_source=result.latex_source,
        warnings=result.warnings,
    )


def _build_filename(state: ResumeState) -> str:
    roles = state.get("selected_roles", [])
    session_key = state.get("session_key", "resume")[:8]

    if roles:
        r = roles[0]
        company = r.get("company_name", "Company")
        role = r.get("role_title", "Role")
        company_short = company.split()[0] if company else "Company"
        role_short = role.split()[0] if role else "Role"
        return f"{company_short}_{role_short}_{session_key}"

    return f"resume_{session_key}"
