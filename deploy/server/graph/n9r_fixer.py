"""N9r — LaTeX Fixer (Gemini Call 6).

When N9 finds validation errors, this node sends the broken LaTeX + the
error list to Gemini for targeted fixes. It does NOT regenerate content —
it only fixes structural and command-level errors.

Key design decisions:
- Temperature=0.1 for high consistency
- Fix ONLY the listed errors, never rewrite/normalize style
- Returns ONLY the fixed LaTeX content (not the whole preamble)
- Max 2 fix attempts before falling back to N10f

If both retries fail, graph routes to N10f (fallback) instead of N10.
"""

from __future__ import annotations

import logging

from server.graph.state import ResumeState
from server.services.gemini import GeminiClient

_logger = logging.getLogger(__name__)

FIXER_PROMPT = """You are a LaTeX error fixer. Below is a resume .tex file that failed
validation with specific errors. Fix ONLY the listed errors. Do NOT rewrite,
rephrase, or restructure anything else.

---

LATEX SOURCE:
{latex_source}

VALIDATION ERRORS (fix ONLY these — nothing else):
{errors}

---

RULES (critical):

1. Fix ONLY the errors listed above. Do NOT improve wording, change formatting,
   add new content, or restructure the document.
2. If a command has the wrong number of arguments, fix ONLY that command.
3. If braces are unbalanced, add/remove the missing braces at the exact location.
4. If there are forbidden characters (raw &, unescaped %), fix ONLY those.
5. NEVER remove, add, or reorder \\resumeSubheading, \\resumeItem,
   \\resumeProjectHeading, or \\textbf calls — just fix their argument structure.
6. NEVER add \\begin{{}}, \\end{{}}, \\section{{}}, or any structural commands.
7. NEVER change the content of arguments — just ensure they have the right
   number of {{}} groups.
8. Return the COMPLETE fixed LaTeX source. Every line must be present.
9. Return ONLY the fixed LaTeX, no markdown fences, no explanations.

If you cannot fix an error without rewriting content, leave it as-is.
It's better to have a minor formatting error than to lose content."""


async def run(state: ResumeState, *, gemini: GeminiClient) -> ResumeState:
    latex_source = state.get("latex_source", "")
    errors = state.get("validation_errors", [])
    fix_attempts = state.get("latex_fix_attempts", 0)

    if not latex_source:
        _logger.warning("N9r: No LaTeX source to fix")
        return ResumeState()

    if not errors:
        _logger.info("N9r: No errors to fix — skipping")
        return ResumeState(latex_valid=True, validation_errors=[])

    _logger.info(
        "N9r: Attempt %d to fix %d validation errors",
        fix_attempts + 1,
        len(errors),
    )

    errors_text = "\n".join(f"  - {e}" for e in errors)

    prompt = FIXER_PROMPT.format(
        latex_source=latex_source,
        errors=errors_text,
    )

    try:
        raw = await gemini.generate(
            prompt,
            temperature=0.1,
            expect_json=False,
            max_retries=1,
        )

        fixed = _clean_output(raw)

        if not fixed:
            _logger.warning("N9r: Gemini returned empty — keeping original")
            return ResumeState(latex_fix_attempts=fix_attempts + 1)

        return ResumeState(
            latex_source=fixed,
            latex_fix_attempts=fix_attempts + 1,
        )

        _logger.info(
            "N9r fix attempt %d: %d chars → %d chars",
            fix_attempts + 1,
            len(latex_source),
            len(fixed),
        )

    except Exception as exc:
        _logger.error("N9r Gemini call failed: %s", exc)
        return ResumeState(latex_fix_attempts=fix_attempts + 1)


def _clean_output(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
