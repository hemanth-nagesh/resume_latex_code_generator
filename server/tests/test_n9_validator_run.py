"""Unit tests for `server/graph/n9_validator.py`'s `run()` degrade-and-
revalidate path (task 9.3).

Covers the bounded-retry + plain-text-degradation behavior described in
`design.md`'s "Fix 1b" section and `requirements.md` Requirements 1.4-1.7:

(a) valid LaTeX still validates cleanly (no regression to the happy path)
(b) fix_attempts < MAX_FIX_ATTEMPTS with invalid LaTeX just returns
    latex_valid=False (no degradation attempted yet)
(c) fix_attempts >= MAX_FIX_ATTEMPTS with a mappable error degrades the
    affected section and revalidates successfully
(d) fix_attempts >= MAX_FIX_ATTEMPTS with a non-mappable (document-level)
    error raises LatexDegradationError
"""

from __future__ import annotations

import pytest

from server.graph.n9_validator import LatexDegradationError, MAX_FIX_ATTEMPTS, run

# Minimal but realistic assembled document using the same \section{...}
# anchors n9_validator.py's _SECTION_ANCHOR_PATTERNS expects.
_VALID_LATEX = r"""\documentclass{article}
\begin{document}
\section{PROFESSIONAL SUMMARY}
Experienced engineer with a track record of shipping reliable systems.
\section{EXPERIENCE}
\resumeSubHeadingListStart
\resumeSubheading{Acme Corp}{2022 -- Present}{Senior Engineer}{Remote}
\resumeItem{Built things.}
\resumeSubHeadingListEnd
\section{PROJECTS}
\resumeSubHeadingListStart
\resumeProjectHeading{Resume Builder}{Jan 2024 -- Present}
\resumeItem{Automated resume generation.}
\resumeSubHeadingListEnd
\section{TECHNICAL SKILLS}
\textbf{Languages}{: Python, TypeScript}
\section{EDUCATION}
\resumeSubHeadingListStart
\resumeSubheading{PES College}{2018 -- 2022}{B.E. CSE}{Bangalore}
\resumeSubHeadingListEnd
\end{document}
"""


def _with_bad_project_heading(latex: str) -> str:
    """Introduce a 3-arg \\resumeProjectHeading call (schema violation)
    inside the PROJECTS section — a mappable, degradable error."""
    return latex.replace(
        r"\resumeProjectHeading{Resume Builder}{Jan 2024 -- Present}",
        r"\resumeProjectHeading{Resume Builder}{Python, FastAPI}{Jan 2024 -- Present}",
    )


def _with_unbalanced_brace(latex: str) -> str:
    """Introduce a document-level brace-balance error with no line-number-
    mappable custom-command context — used for the non-degradable case.
    Removing a closing brace from \\documentclass shifts brace balance for
    the WHOLE document without being attributable to any one section via
    the "line {n}:" convention (brace balance errors carry no line number
    at all — see check_brace_balance's message format)."""
    return latex.replace(r"\documentclass{article}", r"\documentclass{article")


class TestRunHappyPath:
    async def test_valid_latex_passes_unchanged(self):
        """(a) validation still passes unchanged for valid LaTeX."""
        state = {"latex_source": _VALID_LATEX, "latex_fix_attempts": 0}
        result = await run(state)
        assert result["latex_valid"] is True
        assert result["validation_errors"] == []
        assert "degraded_sections" not in result
        assert "latex_source" not in result  # unchanged, not re-emitted


class TestRunBeforeAttemptsExhausted:
    async def test_invalid_latex_below_max_attempts_returns_errors(self):
        """(b) fix_attempts < MAX_FIX_ATTEMPTS with invalid LaTeX just
        returns latex_valid=False with errors — no degradation attempted."""
        broken = _with_bad_project_heading(_VALID_LATEX)
        state = {"latex_source": broken, "latex_fix_attempts": MAX_FIX_ATTEMPTS - 1}
        result = await run(state)
        assert result["latex_valid"] is False
        assert result["validation_errors"]
        assert "degraded_sections" not in result
        assert "latex_source" not in result  # source itself is not degraded yet


class TestRunDegradeAndRevalidate:
    async def test_mappable_error_degrades_and_passes(self):
        """(c) fix_attempts >= MAX_FIX_ATTEMPTS with a mappable error
        degrades the affected section and revalidates successfully."""
        broken = _with_bad_project_heading(_VALID_LATEX)
        state = {"latex_source": broken, "latex_fix_attempts": MAX_FIX_ATTEMPTS}
        result = await run(state)

        assert result["latex_valid"] is True
        assert result["validation_errors"] == []
        assert result["degraded_sections"] == ["projects"]

        degraded_source = result["latex_source"]
        assert r"\resumeProjectHeading" not in degraded_source
        # Other sections must remain byte-identical.
        assert r"\resumeSubheading{Acme Corp}{2022 -- Present}{Senior Engineer}{Remote}" in degraded_source
        assert r"\resumeSubheading{PES College}{2018 -- 2022}{B.E. CSE}{Bangalore}" in degraded_source
        assert "Experienced engineer with a track record" in degraded_source

    async def test_non_mappable_error_raises(self):
        """(d) fix_attempts >= MAX_FIX_ATTEMPTS with an error that's NOT
        mappable to any section (document-level brace imbalance) raises."""
        broken = _with_unbalanced_brace(_VALID_LATEX)
        state = {"latex_source": broken, "latex_fix_attempts": MAX_FIX_ATTEMPTS}
        with pytest.raises(LatexDegradationError):
            await run(state)
