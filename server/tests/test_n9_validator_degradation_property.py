"""Property-based tests for `server/graph/n9_validator.py`'s degrade-and-
revalidate path in `run()` (task 9.5).

Covers Property 7 (hard failure only occurs when plain text also fails)
from `.kiro/specs/graph-reliability-fixes/design.md`, generalizing beyond
the four hardcoded examples in `test_n9_validator_run.py` (task 9.3) using
Hypothesis.

Reuses the document-construction conventions from `test_n9_validator_run.py`
(the `\\section{...}` anchors N9's `_SECTION_ANCHOR_PATTERNS` expects, and
the "introduce one malformed custom-command call" pattern from
`_with_bad_project_heading` / `_with_unbalanced_brace`) but generalizes them
across all four AI-generated sections and all three schema commands.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from server.graph.n9_validator import LatexDegradationError, MAX_FIX_ATTEMPTS, run

# ---------------------------------------------------------------------------
# Shared document scaffolding
# ---------------------------------------------------------------------------

# Plain alphanumeric text only — never a backslash, brace, or LaTeX special
# character — so it can never accidentally form a new command, environment,
# or forbidden-character violation once run through `strip_latex_commands`.
_SAFE_TEXT = (
    st.text(
        alphabet=st.sampled_from(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "
        ),
        min_size=1,
        max_size=10,
    )
    .map(str.strip)
    .filter(lambda s: len(s) > 0)
)

_SECTION_ORDER: tuple[str, ...] = ("summary", "experience", "projects", "skills")

_ANCHORS: dict[str, str] = {
    "summary": r"\section{PROFESSIONAL SUMMARY}",
    "experience": r"\section{EXPERIENCE}",
    "projects": r"\section{PROJECTS}",
    "skills": r"\section{TECHNICAL SKILLS}",
}

_FILLER: dict[str, str] = {
    "summary": "Safe filler content for the summary section.",
    "experience": "Safe filler content for the experience section.",
    "projects": "Safe filler content for the projects section.",
    "skills": "Safe filler content for the skills section.",
}

# Expected argument counts per CUSTOM_COMMAND_SCHEMA (server/graph/n9_validator.py)
_COMMAND_EXPECTED_ARGS: dict[str, int] = {
    r"\resumeItem": 1,
    r"\resumeSubheading": 4,
    r"\resumeProjectHeading": 2,
}

# Valid (command, section) placements — mirrors how N8 actually assembles
# these commands into sections: \resumeItem is a generic bullet usable in
# any of the four AI-generated sections; \resumeSubheading only appears in
# experience/education-style blocks; \resumeProjectHeading only appears in
# projects.
_COMMAND_SECTION_PAIRS: tuple[tuple[str, str], ...] = (
    (r"\resumeItem", "summary"),
    (r"\resumeItem", "experience"),
    (r"\resumeItem", "projects"),
    (r"\resumeItem", "skills"),
    (r"\resumeSubheading", "experience"),
    (r"\resumeProjectHeading", "projects"),
)


def _build_document(section_contents: dict[str, str]) -> str:
    """Assemble a minimal document using the same \\section{...} anchors
    N9's `_SECTION_ANCHOR_PATTERNS` expects, with one content line per
    AI-generated section plus a trailing EDUCATION section acting as the
    `__end__` anchor."""
    return (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        f"{_ANCHORS['summary']}\n"
        f"{section_contents['summary']}\n"
        f"{_ANCHORS['experience']}\n"
        f"{section_contents['experience']}\n"
        f"{_ANCHORS['projects']}\n"
        f"{section_contents['projects']}\n"
        f"{_ANCHORS['skills']}\n"
        f"{section_contents['skills']}\n"
        "\\section{EDUCATION}\n"
        "Placeholder education content.\n"
        "\\end{document}\n"
    )


# ---------------------------------------------------------------------------
# Strategy 1: degradation SUCCEEDS — a mappable schema violation whose
# stripped plain text introduces no new errors.
# ---------------------------------------------------------------------------


@st.composite
def degradable_document_strategy(draw: st.DrawFn) -> tuple[str, str, str]:
    command, target_section = draw(st.sampled_from(_COMMAND_SECTION_PAIRS))
    expected = _COMMAND_EXPECTED_ARGS[command]
    bad_arg_count = draw(
        st.integers(min_value=1, max_value=5).filter(lambda n: n != expected)
    )
    arg_texts = draw(st.lists(_SAFE_TEXT, min_size=bad_arg_count, max_size=bad_arg_count))
    bad_call = command + "".join(f"{{{t}}}" for t in arg_texts)

    section_contents = dict(_FILLER)
    section_contents[target_section] = bad_call

    document = _build_document(section_contents)
    return document, target_section, command


# ---------------------------------------------------------------------------
# Strategy 2a: degradation FAILS — document-level error with no mappable
# line number (unbalanced brace, same mechanism as
# `test_n9_validator_run.py`'s `_with_unbalanced_brace`).
# ---------------------------------------------------------------------------


@st.composite
def undegradable_document_level_strategy(draw: st.DrawFn) -> str:
    section_contents = {name: draw(_SAFE_TEXT) for name in _SECTION_ORDER}
    document = _build_document(section_contents)
    # Drop the closing brace from \documentclass{article} — a document-wide
    # structural defect. check_brace_balance's error message carries no
    # "line {n}:" reference at all, so map_errors_to_sections cannot
    # attribute it to any section.
    return document.replace(r"\documentclass{article}", r"\documentclass{article", 1)


# ---------------------------------------------------------------------------
# Strategy 2b: degradation FAILS — a mappable error whose stripped
# plain-text still fails, because `strip_latex_commands` only removes
# \command{...} wrappers, not special characters inside the argument text.
# A raw unescaped '&' inside a malformed \resumeItem call survives
# stripping and still trips the forbidden-character check.
# ---------------------------------------------------------------------------


@st.composite
def undegradable_mappable_document_strategy(draw: st.DrawFn) -> tuple[str, str]:
    target_section = draw(st.sampled_from(_SECTION_ORDER))
    # \resumeItem expects exactly 1 arg; 2-5 args is a schema violation.
    bad_arg_count = draw(st.integers(min_value=2, max_value=5))
    extra_arg_texts = draw(
        st.lists(_SAFE_TEXT, min_size=bad_arg_count - 1, max_size=bad_arg_count - 1)
    )
    first_arg = f"{draw(_SAFE_TEXT)} & {draw(_SAFE_TEXT)}"
    args = [first_arg, *extra_arg_texts]
    bad_call = r"\resumeItem" + "".join(f"{{{a}}}" for a in args)

    section_contents = dict(_FILLER)
    section_contents[target_section] = bad_call
    document = _build_document(section_contents)
    return document, target_section


# ---------------------------------------------------------------------------
# Property 7: Hard failure only occurs when plain text also fails
# ---------------------------------------------------------------------------


class TestDegradationSucceedsWhenPlainTextPasses:
    """**Property 7: Hard failure only occurs when plain text also fails**
    (succeeds branch)

    **Validates: Requirements 1.6, 1.7**

    For any document that fails validation at `latex_fix_attempts ==
    MAX_FIX_ATTEMPTS` due to a mappable schema violation whose degraded
    (plain-text) form introduces no new errors, `run()` SHALL NOT raise and
    SHALL set `latex_valid=True` with `degraded_sections` populated with the
    implicated section.
    """

    @settings(max_examples=100)
    @given(case=degradable_document_strategy())
    async def test_degradable_schema_violation_resolves_without_raising(
        self, case: tuple[str, str, str]
    ) -> None:
        document, target_section, command = case
        state = {"latex_source": document, "latex_fix_attempts": MAX_FIX_ATTEMPTS}

        result = await run(state)

        assert result["latex_valid"] is True
        assert result["validation_errors"] == []
        assert result["degraded_sections"] == [target_section]

        degraded_source = result["latex_source"]
        assert command not in degraded_source


class TestDegradationFailsWhenPlainTextAlsoFails:
    """**Property 7: Hard failure only occurs when plain text also fails**
    (fails branch)

    **Validates: Requirements 1.6, 1.7**

    For any document whose validation failure cannot be resolved by
    plain-text degradation — either because no section can be mapped to the
    error at all, or because the degraded text still violates a check —
    `run()` SHALL raise `LatexDegradationError` and never set
    `latex_valid=True`.
    """

    @settings(max_examples=100)
    @given(document=undegradable_document_level_strategy())
    async def test_document_level_error_with_no_mappable_line_raises(
        self, document: str
    ) -> None:
        state = {"latex_source": document, "latex_fix_attempts": MAX_FIX_ATTEMPTS}

        with pytest.raises(LatexDegradationError) as exc_info:
            await run(state)

        assert "no sections could be mapped" in str(exc_info.value)

    @settings(max_examples=100)
    @given(case=undegradable_mappable_document_strategy())
    async def test_residual_special_char_after_degradation_still_raises(
        self, case: tuple[str, str]
    ) -> None:
        document, target_section = case
        state = {"latex_source": document, "latex_fix_attempts": MAX_FIX_ATTEMPTS}

        with pytest.raises(LatexDegradationError) as exc_info:
            await run(state)

        message = str(exc_info.value)
        assert "plain-text degradation of sections" in message
        assert target_section in message
