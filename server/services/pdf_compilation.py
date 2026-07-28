"""PdfCompilationService — the "validated LaTeX → persisted PDF" use case.

Owns the full flow selected in the mcp-pdf-generation design
(.kiro/specs/mcp-pdf-generation/design.md, Candidate B — Compilation
Boundary Service), adapted to store results in Postgres instead of an
external blob store (there is no Azure Blob Storage in this deployment —
generated PDFs and LaTeX source live directly on the `sessions` row):

    1. Try compiling the primary LaTeX source via the external LaTeX MCP
       server (LatexMcpClient).
    2. On failure, build a minimal fallback article-class document (same
       strategy the old n10f_fallback.py used) and retry the MCP compile
       once against that document.
    3. If that also fails, degrade to delivering the fallback LaTeX text
       as the "pdf_bytes" payload (last resort — no PDF, but the user still
       gets something).
    4. On any successful compile (primary or fallback), persist the PDF +
       LaTeX source + session metadata to Postgres via queries.complete_session.

This service never raises — every failure is caught, logged, and turned
into a warning on the returned CompiledResume (INV-B2 in design.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, TYPE_CHECKING

from server.db import queries
from server.services.latex_mcp import McpAuthError, McpCompileError, McpError, McpTimeoutError
from server.services.latex_utils import strip_latex_commands

if TYPE_CHECKING:
    from server.services.database import DatabasePool
    from server.services.latex_mcp import LatexMcpClient

_logger = logging.getLogger(__name__)


@dataclass
class CompiledResume:
    """Result of PdfCompilationService.compile_and_prepare()."""

    pdf_bytes: bytes = b""
    pdf_base64: str = ""
    pdf_filename: str = ""
    latex_source: str = ""
    used_fallback: bool = False
    warnings: list[str] = field(default_factory=list)


class PdfCompilationService:
    """Use-case service: compile validated LaTeX to a persisted PDF."""

    def __init__(self, mcp_client: LatexMcpClient) -> None:
        self._mcp = mcp_client

    async def compile_and_prepare(
        self,
        *,
        latex_source: str,
        filename: str,
        sections_output: list[dict[str, Any]],
        session_key: str,
        jd_profile: dict[str, Any],
        selected_projects: list[dict[str, Any]],
        selected_roles: list[dict[str, Any]],
        covered_skills: list[str],
        uncovered_skills: list[str],
        db: DatabasePool | None = None,
    ) -> CompiledResume:
        """Compile `latex_source` to PDF, falling back if needed, then persist.

        Never raises. All MCP/network/DB failures become warnings.
        """
        warnings: list[str] = []
        used_fallback = False
        pdf_bytes = b""
        pdf_base64 = ""
        final_latex = latex_source

        # --- 1. Primary compile attempt ---
        try:
            pdf_bytes, pdf_base64 = await self._mcp.compile(latex_source, filename)
        except McpAuthError as exc:
            _logger.error("MCP auth failed — check LATEX_MCP_API_KEY: %s", exc)
            warnings.append("PDF compiler authentication failed — using fallback formatting")
        except (McpCompileError, McpTimeoutError, McpError) as exc:
            _logger.warning("Primary MCP compile failed: %s", exc)
            warnings.append(f"PDF compilation error: {exc}")

        # --- 2. Fallback document + retry ---
        if not pdf_bytes:
            used_fallback = True
            fallback_doc = self._build_fallback_document(sections_output)
            final_latex = fallback_doc

            try:
                pdf_bytes, pdf_base64 = await self._mcp.compile(fallback_doc, filename)
                warnings.append(
                    "Used fallback template — formatting may differ from standard layout"
                )
            except McpAuthError as exc:
                _logger.error("MCP auth failed on fallback attempt: %s", exc)
                warnings.append("PDF compiler authentication failed on fallback attempt too")
            except (McpCompileError, McpTimeoutError, McpError) as exc:
                _logger.error("Fallback MCP compile also failed: %s", exc)
                warnings.append(f"Fallback compilation failed: {exc} — raw LaTeX attached")

        # --- 3. Last resort: no PDF at all ---
        if not pdf_bytes:
            pdf_bytes = final_latex.encode("utf-8")
            pdf_base64 = ""
            warnings.append("No PDF could be produced — raw LaTeX delivered instead")

        # --- 4. Persist to Postgres (only meaningful once we have a real PDF) ---
        if pdf_base64 and db is not None:
            await self._persist(
                db=db,
                session_key=session_key,
                pdf_bytes=pdf_bytes,
                pdf_filename=filename,
                latex_source=final_latex,
                jd_profile=jd_profile,
                selected_projects=selected_projects,
                selected_roles=selected_roles,
                covered_skills=covered_skills,
                uncovered_skills=uncovered_skills,
                warnings=warnings,
            )

        return CompiledResume(
            pdf_bytes=pdf_bytes,
            pdf_base64=pdf_base64,
            pdf_filename=filename,
            latex_source=final_latex,
            used_fallback=used_fallback,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Persistence (calls the DB collaborator; never raises)
    # ------------------------------------------------------------------

    async def _persist(
        self,
        *,
        db: DatabasePool,
        session_key: str,
        pdf_bytes: bytes,
        pdf_filename: str,
        latex_source: str,
        jd_profile: dict[str, Any],
        selected_projects: list[dict[str, Any]],
        selected_roles: list[dict[str, Any]],
        covered_skills: list[str],
        uncovered_skills: list[str],
        warnings: list[str],
    ) -> None:
        try:
            await queries.complete_session(
                db,
                session_key,
                jd_profile=jd_profile,
                selected_project_ids=[
                    sp.get("project_id", "") for sp in selected_projects
                ],
                selected_role_ids=[r.get("id", "") for r in selected_roles],
                covered_skills=covered_skills,
                uncovered_skills=uncovered_skills,
                pdf_data=pdf_bytes,
                pdf_filename=pdf_filename,
                latex_source=latex_source,
            )
            _logger.info("Session %s persisted (%d bytes PDF)", session_key, len(pdf_bytes))
        except Exception as exc:
            _logger.error("Session DB update failed (non-fatal): %s", exc)
            warnings.append(f"Session DB update failed: {exc}")

    # ------------------------------------------------------------------
    # Fallback document construction (mirrors legacy n10f_fallback.py)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_fallback_document(sections_output: list[dict[str, Any]]) -> str:
        sections: dict[str, str] = {}
        for entry in sections_output:
            name = entry.get("section", "")
            content = entry.get("content", "")
            if name and content:
                sections[name] = strip_latex_commands(content)

        summary = sections.get("summary", "")
        experience = sections.get("experience", "")
        projects = sections.get("projects", "")
        skills = sections.get("skills", "")

        return dedent(fr"""
\documentclass[11pt]{{article}}
\usepackage[utf8]{{inputenc}}
\usepackage[margin=1in]{{geometry}}

\begin{{document}}

\begin{{center}}
    {{\Large \textbf{{Resume}}}}
\end{{center}}

\section*{{Professional Summary}}
{summary}

\section*{{Experience}}
{experience}

\section*{{Projects}}
{projects}

\section*{{Technical Skills}}
{skills}

\end{{document}}
""").strip()
