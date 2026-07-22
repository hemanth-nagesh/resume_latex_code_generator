"""N12 — Response Builder.

Final node in the pipeline. Packages the assembled LaTeX source
for delivery to the frontend. The client displays the LaTeX code
in a text area — users can copy/paste it into Overleaf or a local
TeX editor to compile to PDF themselves.

Also handles the cached-result shortcut from N1.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from server.graph.state import ResumeState

if TYPE_CHECKING:
    from server.services.blob import BlobClient

_logger = logging.getLogger(__name__)


async def run(state: ResumeState, *, blob: BlobClient | None = None) -> ResumeState:
    latex_source = state.get("latex_source", "")

    if not latex_source:
        _logger.error("N12: No LaTeX source available")
        return ResumeState(
            warnings=["No LaTeX source generated"],
        )

    filename = _build_filename(state)

    _logger.info("N12 response built: %s (%d chars)", filename, len(latex_source))
    return ResumeState(
        latex_source=latex_source,
        latex_filename=filename,
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
