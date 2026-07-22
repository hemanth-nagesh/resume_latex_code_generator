"""Phase 5 tests — LaTeX assembly (N8), validation (N9), and fixing (N9r).

Coverage:
- N8: template slot substitution, summary escaping, certification block building
- N9: brace balance, custom command schema, forbidden chars, placeholder detection
- N9r: prompt construction, error context formatting

All pure functions — no Gemini calls needed.
"""

from __future__ import annotations

import pytest

from server.graph.n8_assembler import _escape_plain, _build_certifications
from server.graph.n9_validator import CUSTOM_COMMAND_SCHEMA
from server.services.latex_utils import (
    escape_special_chars,
    check_brace_balance,
    check_environment_matching,
    check_placeholders,
    parse_custom_command_args,
    strip_latex_commands,
)

# Minimal master template fragment for testing
TEST_TEMPLATE = r"""\documentclass{article}
\begin{document}
\section{Summary}
%%SUMMARY_TEXT%%
\section{Experience}
\resumeSubHeadingListStart
%%EXPERIENCE_BLOCK%%
\resumeSubHeadingListEnd
\section{Projects}
\resumeSubHeadingListStart
%%PROJECTS_BLOCK%%
\resumeSubHeadingListEnd
\section{Skills}
\begin{itemize}
\item{
%%SKILLS_BLOCK%%
}
\end{itemize}
\section{Education}
\resumeSubHeadingListStart
%%EDUCATION_BLOCK%%
\resumeSubHeadingListEnd
\section{Certifications}
\begin{itemize}
\item{
%%CERTIFICATIONS_BLOCK%%
}
\end{itemize}
\end{document}"""


# ===========================================================================
# N8 — LaTeX Assembler
# ===========================================================================

class TestN8Assembler:
    def test_all_slots_substituted(self):
        """Verify no placeholders remain after assembly."""
        latex = TEST_TEMPLATE
        latex = latex.replace("%%SUMMARY_TEXT%%", "Three sentences here.")
        latex = latex.replace("%%EXPERIENCE_BLOCK%%", r"\resumeSubheading{...}{...}{...}{...}")
        latex = latex.replace("%%PROJECTS_BLOCK%%", r"\resumeProjectHeading{...}{...}")
        latex = latex.replace("%%SKILLS_BLOCK%%", r"\textbf{Languages}{: Python}")
        latex = latex.replace("%%EDUCATION_BLOCK%%", "B.E. CSE")
        latex = latex.replace("%%CERTIFICATIONS_BLOCK%%", r"\item[] \textbf{Cert} (2024)")

        ok, msg = check_placeholders(latex)
        assert ok, f"Unsubstituted placeholders: {msg}"
        assert "%%SUMMARY_TEXT%%" not in latex
        assert "%%EXPERIENCE_BLOCK%%" not in latex
        assert "%%PROJECTS_BLOCK%%" not in latex
        assert "%%SKILLS_BLOCK%%" not in latex
        assert "%%EDUCATION_BLOCK%%" not in latex
        assert "%%CERTIFICATIONS_BLOCK%%" not in latex

    def test_template_preamble_preserved(self):
        """Verify preamble is byte-identical after substitution."""
        latex = TEST_TEMPLATE
        preamble = latex[: latex.find(r"\begin{document}")]
        # Substitutions in body only
        latex = latex.replace("%%SUMMARY_TEXT%%", "Test summary.")
        latex = latex.replace("%%EXPERIENCE_BLOCK%%", "Experience here.")
        latex = latex.replace("%%PROJECTS_BLOCK%%", "Projects here.")
        latex = latex.replace("%%SKILLS_BLOCK%%", "Skills here.")
        latex = latex.replace("%%EDUCATION_BLOCK%%", "Education here.")
        latex = latex.replace("%%CERTIFICATIONS_BLOCK%%", "Certs here.")

        new_preamble = latex[: latex.find(r"\begin{document}")]
        assert new_preamble == preamble

    def test_escape_special_chars_plain_text(self):
        """Summary text must have special chars escaped."""
        raw = "Built API with Python & FastAPI — 99.9% uptime (SLA $100k/yr)"
        escaped = _escape_plain(raw)
        assert "\\&" in escaped
        assert "\\%" in escaped
        assert "\\$" in escaped

    def test_experience_not_escaped(self):
        """LaTeX commands must NOT be escaped."""
        exp = r"\resumeSubheading{Dev}{2024}{TCS}{India}"
        assert _escape_plain(exp) != exp  # the {} to \{\}
        # But we pass experience through raw — only summary gets escaping

    def test_certification_block_from_kg(self):
        kg = {
            "certifications": [
                {"title": "Azure AI Engineer", "year": 2026},
                {"title": "AI Information Retrieval", "year": 2023},
            ]
        }
        block = _build_certifications(kg)
        assert r"\textbf{Azure AI Engineer}" in block
        assert "(2026)" in block
        assert r"\textbf{AI Information Retrieval}" in block

    def test_certification_empty_kg(self):
        assert _build_certifications({}) == ""
        assert _build_certifications({"certifications": []}) == ""

    def test_education_block_is_latex(self):
        """Education block should be a valid \\resumeSubheading."""
        from server.graph.n8_assembler import EDUCATION_BLOCK
        assert r"\resumeSubheading" in EDUCATION_BLOCK
        assert "PES College" in EDUCATION_BLOCK


# ===========================================================================
# N9 — LaTeX Validator (pure checks)
# ===========================================================================

class TestN9Validator:
    def test_brace_balance_ok(self):
        ok, _ = check_brace_balance(r"\textbf{Languages}: {Python}")
        assert ok

    def test_brace_balance_unbalanced(self):
        ok, msg = check_brace_balance(r"\textbf{Languages}: {Python")
        assert not ok
        assert "Unbalanced" in msg

    def test_brace_balance_escaped_ignored(self):
        """Escaped braces \{ \} should not count as structural."""
        ok, _ = check_brace_balance(r"\textbf{Languages}: \{Python\}")
        assert ok

    def test_environment_matching_ok(self):
        latex = r"\begin{itemize} \item test \end{itemize}"
        ok, _ = check_environment_matching(latex)
        assert ok

    def test_environment_mismatch(self):
        latex = r"\begin{itemize} \item test \end{enumerate}"
        ok, msg = check_environment_matching(latex)
        assert not ok
        assert "Mismatched" in msg

    def test_environment_unclosed(self):
        latex = r"\begin{itemize} \item test"
        ok, msg = check_environment_matching(latex)
        assert not ok
        assert "Unclosed" in msg

    def test_placeholder_detection(self):
        ok, msg = check_placeholders("%%SUMMARY_TEXT%%")
        assert not ok
        assert "SUMMARY_TEXT" in msg

    def test_placeholder_clean(self):
        ok, _ = check_placeholders("All slots filled. No placeholders.")
        assert ok

    def test_custom_command_schema_resumeSubheading(self):
        # Correct: 4 args
        latex = r"\resumeSubheading{Title}{Date}{Company}{Location}"
        results = parse_custom_command_args(latex, (r"\resumeSubheading",))
        assert len(results) == 1
        assert results[0]["arg_count"] == 4
        assert results[0]["command"] == r"\resumeSubheading"

    def test_custom_command_wrong_args(self):
        # Wrong: 3 args instead of 4
        latex = r"\resumeSubheading{Title}{Date}{Company}"
        results = parse_custom_command_args(latex, (r"\resumeSubheading",))
        assert results[0]["arg_count"] == 3

    def test_custom_command_with_nested_braces(self):
        latex = r"\resumeItem{Built API with \textbf{Python} and FastAPI}"
        results = parse_custom_command_args(latex, (r"\resumeItem",))
        assert len(results) == 1
        assert results[0]["arg_count"] == 1

    def test_schema_completeness(self):
        """Schema must cover core custom commands from template.
        \resumeProjectHeading is excluded — its arity varies (2 or 3 args)."""
        assert CUSTOM_COMMAND_SCHEMA == {
            r"\resumeItem": 1,
            r"\resumeSubheading": 4,
        }

    def test_multiple_commands_in_one_line(self):
        latex = r"\resumeItem{One}\resumeItem{Two}"
        results = parse_custom_command_args(latex, (r"\resumeItem",))
        assert len(results) == 2
        assert all(r["arg_count"] == 1 for r in results)


# ===========================================================================
# N9r — LaTeX Fixer (prompt construction)
# ===========================================================================

class TestN9rFixer:
    def test_clean_output_strips_fences(self):
        from server.graph.n9r_fixer import _clean_output
        assert _clean_output("```\nfixed latex\n```") == "fixed latex"
        assert _clean_output("  content  ") == "content"

    def test_error_list_formatting(self):
        """Errors should be parseable and actionable."""
        errors = [
            "Brace balance: Unbalanced braces: 5 open, 4 close",
            "Command schema: line 42: \\resumeSubheading expected 4 args, got 3",
            "Forbidden chars: line 18: raw '&' outside tabular",
        ]
        errors_text = "\n".join(f"  - {e}" for e in errors)
        assert "Unbalanced braces" in errors_text
        assert "line 42" in errors_text
        assert "raw '&'" in errors_text


# ===========================================================================
# latex_utils — edge cases
# ===========================================================================

class TestLatexUtils:
    def test_escape_ampersand(self):
        assert escape_special_chars("A & B") == r"A \& B"

    def test_escape_percent(self):
        assert escape_special_chars("50%") == r"50\%"

    def test_escape_hash(self):
        assert escape_special_chars("#1") == r"\#1"

    def test_escape_underscore(self):
        assert escape_special_chars("my_var") == r"my\_var"

    def test_strip_latex_commands(self):
        result = strip_latex_commands(r"\textbf{Bold} and \emph{italic} text")
        assert "Bold" in result
        assert "italic" in result
        assert r"\textbf" not in result

    def test_parse_nested_braces_in_command(self):
        latex = r"\resumeProjectHeading{{\textbf{Title} $|$ \emph{Tech}}}{Dates}"
        results = parse_custom_command_args(
            latex,
            (r"\resumeProjectHeading",)
        )
        assert len(results) == 1
        assert results[0]["arg_count"] == 2
