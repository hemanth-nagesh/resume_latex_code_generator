"""N12 — Response Builder.

Final node in the pipeline. Packages the assembled LaTeX source and the
compiled PDF (base64) for delivery to the frontend.

Also handles the cached-result shortcut from N1.
"""

from __future__ import annotations

import logging

from server.graph.state import ResumeState

_logger = logging.getLogger(__name__)


async def run(state: ResumeState) -> ResumeState:
    latex_source = state.get("latex_source", "")

    if not latex_source:
        _logger.error("N12: No LaTeX source available")
        return ResumeState(
            warnings=["No LaTeX source generated"],
        )

    filename = _build_filename(state)
    pdf_base64 = state.get("pdf_base64", "")
    pdf_filename = state.get("pdf_filename", "") or filename.removesuffix(".tex")

    _logger.info(
        "N12 response built: %s (%d chars LaTeX, %s)",
        filename, len(latex_source),
        f"{len(pdf_base64)} b64 chars PDF" if pdf_base64 else "no PDF",
    )
    return ResumeState(
        latex_source=latex_source,
        latex_filename=filename,
        pdf_base64=pdf_base64,
        pdf_filename=pdf_filename,
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
        return f"{company_short}_{role_short}_{session_key}.tex"

    return f"resume_{session_key}.tex"
