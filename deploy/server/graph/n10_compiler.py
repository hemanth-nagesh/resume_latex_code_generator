"""N10 — PDF Compiler (pdflatex ×2).

Compiles the validated LaTeX source to PDF by running pdflatex twice
in a temporary directory. The first pass generates .aux files; the
second resolves cross-references and produces the final PDF.

Requirements:
- pdflatex in PATH (provided by texlive/texlive Docker image)
- 30s timeout per compilation pass (configurable)
- No network access during compilation (--no-shell-escape equivalent)

On success: state["pdf_bytes"] populated with binary PDF content.
On failure: state["pdf_bytes"] stays empty; graph routes to N10f fallback.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

from server.graph.state import ResumeState

_logger = logging.getLogger(__name__)

# pdflatex must be compiled twice for cross-references, TOC, etc.
PDFLATEX_PASSES = 2
DEFAULT_TIMEOUT = 30


async def run(
    state: ResumeState,
    *,
    pdflatex_timeout: int = DEFAULT_TIMEOUT,
) -> ResumeState:
    latex_source = state.get("latex_source", "")

    if not latex_source:
        _logger.warning("N10: No LaTeX source to compile")
        return ResumeState()

    _logger.info("N10: Compiling %d chars of LaTeX", len(latex_source))

    try:
        pdf_bytes = await _compile(latex_source, timeout=pdflatex_timeout)
        _logger.info("N10 compilation successful: %d bytes", len(pdf_bytes))
        return ResumeState(pdf_bytes=pdf_bytes)
    except Exception as exc:
        _logger.error("N10 compilation failed: %s", exc)
        return ResumeState(
            warnings=["PDF compilation error: " + str(exc)],
        )


async def _compile(latex_source: str, timeout: int) -> bytes:
    """Run pdflatex in a temp directory, return PDF bytes."""

    tmpdir = tempfile.mkdtemp(prefix="resume_pdf_")
    tex_path = os.path.join(tmpdir, "resume.tex")
    pdf_path = os.path.join(tmpdir, "resume.pdf")

    try:
        # Write .tex file
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(latex_source)

        # Run pdflatex twice
        for pass_num in range(1, PDFLATEX_PASSES + 1):
            _logger.debug("pdflatex pass %d/%d", pass_num, PDFLATEX_PASSES)
            proc = await asyncio.create_subprocess_exec(
                "pdflatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-output-directory", tmpdir,
                tex_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError(
                    f"pdflatex timed out after {timeout}s on pass {pass_num}"
                )

            if proc.returncode != 0:
                # Extract error context from log
                log_path = os.path.join(tmpdir, "resume.log")
                error_context = ""
                if os.path.exists(log_path):
                    with open(log_path, "r") as lf:
                        lines = lf.readlines()
                        # Grab last 20 lines for context
                        error_context = "".join(lines[-20:])

                raise RuntimeError(
                    f"pdflatex exit code {proc.returncode} on pass {pass_num}\n"
                    f"Last 20 lines of log:\n{error_context}"
                )

        # Read the generated PDF
        if not os.path.exists(pdf_path):
            raise RuntimeError("pdflatex completed but no PDF was generated")

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        if len(pdf_bytes) == 0:
            raise RuntimeError("Generated PDF is empty")

        return pdf_bytes

    finally:
        # Clean up temp directory
        shutil.rmtree(tmpdir, ignore_errors=True)
