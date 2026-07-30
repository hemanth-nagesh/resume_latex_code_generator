"""N9r — LaTeX Fixer (Gemini Call 6).

When N9 finds validation errors that the deterministic auto-fixer cannot
resolve, this node sends the broken LaTeX + the error list to Gemini for
targeted fixes. It does NOT regenerate content — it only fixes structural
and command-level errors.

Key design decisions:
- Temperature=0.1 for high consistency
- Fix ONLY the listed errors, never rewrite/normalize style
- Returns ONLY the fixed LaTeX content (not the whole preamble)
- Max 2 fix attempts before falling back to N10f
- Pre-applies deterministic fixes before calling Gemini (belt + suspenders)

If both retries fail, graph routes to N10f (fallback) instead of N10.
"""

from __future__ import annotations

import logging
import re

from server.graph.state import ResumeState
from server.services.gemini import GeminiClient
from server.services.latex_utils import sanitize_latex_source

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
4. If there are forbidden characters (raw &, unescaped %), escape them with a backslash:
   - Raw & → \\&
   - Raw % → \\%
   - Raw # → \\#
   - Raw $ → \\$
5. NEVER remove, add, or reorder \\resumeSubheading, \\resumeItem,
   \\resumeProjectHeading, or \\textbf calls — just fix their argument structure.
6. NEVER add \\begin{{}}, \\end{{}}, \\section{{}}, or any structural commands.
7. NEVER change the content of arguments — just ensure they have the right
   number of {{}} groups and all special chars are escaped.
8. Return the COMPLETE fixed LaTeX source. Every line must be present.
9. Return ONLY the fixed LaTeX, no markdown fences, no explanations.
10. For \\resumeProjectHeading: it takes EXACTLY 2 arguments:
    {{\\textbf{{Title}} $|$ \\emph{{Tech Stack}}}}{{Dates}}
11. For \\resumeSubheading: it takes EXACTLY 4 arguments:
    {{Company}}{{Dates}}{{Role}}{{Location}}
12. For \\resumeItem: it takes EXACTLY 1 argument: {{bullet text}}

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

    # --- Pre-apply deterministic fixes before wasting an LLM call ---
    # This catches simple issues like raw & that the LLM might miss
    pre_fixed = _apply_deterministic_fixes(latex_source, errors)
    if pre_fixed != latex_source:
        _logger.info("N9r: Deterministic pre-fix modified %d chars", abs(len(pre_fixed) - len(latex_source)))
        latex_source = pre_fixed

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
            _logger.warning("N9r: Gemini returned empty — using pre-fixed source")
            return ResumeState(
                latex_source=latex_source,
                latex_fix_attempts=fix_attempts + 1,
            )

        # Post-process: run sanitize_latex_source on Gemini's output to catch
        # any remaining forbidden chars it might have missed
        fixed = sanitize_latex_source(fixed)

        _logger.info(
            "N9r fix attempt %d: %d chars → %d chars",
            fix_attempts + 1,
            len(state.get("latex_source", "")),
            len(fixed),
        )

        return ResumeState(
            latex_source=fixed,
            latex_fix_attempts=fix_attempts + 1,
        )

    except Exception as exc:
        _logger.error("N9r Gemini call failed: %s", exc)
        # Even if Gemini fails, return the pre-fixed version
        return ResumeState(
            latex_source=latex_source,
            latex_fix_attempts=fix_attempts + 1,
        )


def _apply_deterministic_fixes(latex_source: str, errors: list[str]) -> str:
    """Apply rule-based fixes for known error patterns.

    This catches the most common issues before even calling the LLM:
    - "Forbidden chars: line N: raw '&' outside tabular" → escape the &
    - "Forbidden chars: line N: raw '%' ..." → escape the %
    - Unicode characters → LaTeX equivalents
    """
    lines = latex_source.split("\n")

    # Extract line numbers from "Forbidden chars" errors
    forbidden_lines: set[int] = set()
    for error in errors:
        if "Forbidden chars" in error:
            for m in re.finditer(r"line (\d+)", error):
                forbidden_lines.add(int(m.group(1)))

    if forbidden_lines:
        for line_no in forbidden_lines:
            if 1 <= line_no <= len(lines):
                idx = line_no - 1
                line = lines[idx]

                # Skip safe contexts
                if re.search(r"\\begin\{(tabular|tabularx|longtable)", line):
                    continue
                if "\\newcommand" in line or "\\renewcommand" in line:
                    continue

                # Escape raw & on this specific line
                fixed = _escape_raw_chars_on_line(line)
                lines[idx] = fixed

    return "\n".join(lines)


def _escape_raw_chars_on_line(line: str) -> str:
    """Escape raw &, #, and other forbidden chars on a single line.

    Preserves already-escaped sequences (\\&, \\#, etc.) and LaTeX comments.
    """
    result = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            # Already an escape sequence — keep both chars
            result.append(ch)
            result.append(line[i + 1])
            i += 2
        elif ch == "&":
            result.append("\\&")
            i += 1
        elif ch == "#":
            result.append("\\#")
            i += 1
        elif ch == "%":
            # Check if this starts a comment (rest of line after %)
            # by checking brace depth
            depth = 0
            for j in range(i):
                if line[j] == "{" and (j == 0 or line[j-1] != "\\"):
                    depth += 1
                elif line[j] == "}" and (j == 0 or line[j-1] != "\\"):
                    depth -= 1
            if depth == 0:
                # This is a comment — keep rest of line as-is
                result.append(line[i:])
                break
            else:
                # Inside a brace group — escape it
                result.append("\\%")
                i += 1
        else:
            result.append(ch)
            i += 1
    return "".join(result)


def _clean_output(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
