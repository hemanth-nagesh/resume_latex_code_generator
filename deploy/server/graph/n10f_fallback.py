"""N10f — Fallback Template Handler.

Triggered when the main template fails validation twice (N9r → N9 → N9r → N9
failure). Builds a minimal article-class LaTeX document from the raw text
content, bypassing custom commands entirely.

Strategy:
- Strip all custom LaTeX commands from generated sections
- Extract plain text from each section output
- Reassemble into a bare article-class document
- Compile that to PDF (no fancy formatting, but readable)

This ensures the user always gets a PDF even when Gemini misbehaves.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from textwrap import dedent

from server.graph.state import ResumeState
from server.services.latex_utils import strip_latex_commands

_logger = logging.getLogger(__name__)


async def run(state: ResumeState) -> ResumeState:
    _logger.warning(
        "N10f: Falling back to minimal template after %d fix attempts failed",
        state.get("latex_fix_attempts", 0),
    )

    sections: dict[str, str] = {}
    for entry in state.get("sections_output", []):
        name = entry.get("section", "")
        content = entry.get("content", "")
        if name and content:
            sections[name] = strip_latex_commands(content)

    fallback = _build_fallback_document(sections)

    try:
        from server.graph.n10_compiler import _compile
        pdf_bytes = await _compile(fallback, timeout=30)
        _logger.info("N10f fallback PDF generated: %d bytes", len(pdf_bytes))
        return ResumeState(
            pdf_bytes=pdf_bytes,
            latex_source=fallback,
            warnings=["Used fallback template — formatting may differ from standard layout"],
        )
    except FileNotFoundError:
        _logger.error("N10f: pdflatex not installed — delivering LaTeX as text")
        return ResumeState(
            pdf_bytes=fallback.encode("utf-8"),
            latex_source=fallback,
            warnings=[
                "pdflatex not installed — raw LaTeX attached instead of PDF",
                "Install texlive to generate PDFs: brew install texlive or use Docker",
            ],
        )
    except Exception as exc:
        _logger.error("N10f fallback compilation also failed: %s", exc)
        return ResumeState(
            pdf_bytes=fallback.encode("utf-8"),
            latex_source=fallback,
            warnings=[f"Fallback compilation failed: {exc} — raw LaTeX attached"],
        )


def _build_fallback_document(sections: dict[str, str]) -> str:
    """Build a minimal article-class LaTeX document with plain-text sections."""

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
