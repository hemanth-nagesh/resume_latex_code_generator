"""Property-based test for `map_errors_to_sections` / `_degrade_sections`
isolation guarantees (task 9.4).

Covers Property 6 (section degradation only touches implicated sections)
from `.kiro/specs/graph-reliability-fixes/design.md`.

This is distinct from `test_n9_validator_run.py` (which covers the full
`run()` orchestration with 4 concrete scenarios) — here we drive the two
pure helpers, `map_errors_to_sections` and `_degrade_sections`, directly and
in isolation across a large, randomized space of multi-section documents and
error placements.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from server.graph.n9_validator import (
    _degrade_sections,
    _locate_section_line_ranges,
    map_errors_to_sections,
)

_SECTION_NAMES: tuple[str, ...] = ("summary", "experience", "projects", "skills")

_ANCHOR_LINES: dict[str, str] = {
    "summary": r"\section{PROFESSIONAL SUMMARY}",
    "experience": r"\section{EXPERIENCE}",
    "projects": r"\section{PROJECTS}",
    "skills": r"\section{TECHNICAL SKILLS}",
}

_EDUCATION_ANCHOR = r"\section{EDUCATION}"

# Marker suffixes are restricted to letters/digits so they can never be
# mistaken for LaTeX control characters (braces, backslashes, %, &) by the
# brace-balance / forbidden-char / placeholder checks, and so they remain a
# reliable, exact substring to search for pre- and post-degradation.
_marker_suffix = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    min_size=4,
    max_size=10,
)


def _marker(section: str, idx: int, suffix: str) -> str:
    return f"{section.upper()}_MARKER_{idx}_{suffix}"


@st.composite
def _document_strategy(draw):
    """Build a realistic multi-section assembled LaTeX document using the
    exact `_SECTION_ANCHOR_PATTERNS` anchor text, with 1-3 distinguishable
    marker lines per AI-generated section, plus a random subset of those
    sections designated as "affected" (simulating validation errors)."""
    section_lines: dict[str, list[str]] = {}
    section_markers: dict[str, list[str]] = {}

    for section in _SECTION_NAMES:
        n_lines = draw(st.integers(min_value=1, max_value=3))
        suffixes = draw(
            st.lists(_marker_suffix, min_size=n_lines, max_size=n_lines, unique=True)
        )
        markers = [_marker(section, i, suffix) for i, suffix in enumerate(suffixes)]
        section_lines[section] = [f"\\resumeItem{{{m}}}" for m in markers]
        section_markers[section] = markers

    doc_lines: list[str] = [
        r"\documentclass{article}",
        r"\begin{document}",
    ]
    for section in _SECTION_NAMES:
        doc_lines.append(_ANCHOR_LINES[section])
        doc_lines.extend(section_lines[section])
    doc_lines.append(_EDUCATION_ANCHOR)
    doc_lines.append(r"\resumeSubheading{PES College}{2018 -- 2022}{B.E. CSE}{Bangalore}")
    doc_lines.append(r"\end{document}")

    latex_source = "\n".join(doc_lines)

    # Compute actual ranges against the *assembled* document (not assumed).
    ranges = _locate_section_line_ranges(latex_source)
    assert set(ranges.keys()) == set(_SECTION_NAMES)

    affected = draw(
        st.lists(st.sampled_from(_SECTION_NAMES), min_size=0, max_size=4, unique=True)
    )

    errors: list[str] = []
    for section in affected:
        start, end = ranges[section]
        line_no = draw(st.integers(min_value=start, max_value=end))
        errors.append(f"line {line_no}: synthetic error in {section}")

    return latex_source, errors, affected, section_markers, ranges


class TestSectionDegradationIsolation:
    """**Property 6: Section degradation only touches implicated sections**

    **Validates: Requirements 1.4, 1.5**
    """

    @settings(max_examples=100)
    @given(data=_document_strategy())
    def test_map_and_degrade_only_touch_affected_sections(self, data) -> None:
        latex_source, errors, affected, section_markers, orig_ranges = data
        affected_set = set(affected)

        # 1. map_errors_to_sections identifies exactly the affected set.
        mapped = map_errors_to_sections(errors, latex_source)
        assert set(mapped) == affected_set, (
            f"expected mapped sections {affected_set}, got {set(mapped)} "
            f"for errors={errors!r}"
        )
        assert len(mapped) == len(set(mapped)), "mapped sections must be deduplicated"

        # 2. Degrading only the mapped sections leaves every other section
        # byte-for-byte unchanged, and strips LaTeX markup from the
        # affected ones.
        degraded = _degrade_sections(latex_source, mapped)

        # Note: re-locating ranges via `_locate_section_line_ranges` on the
        # degraded output is NOT used as the unchanged-content oracle here.
        # Degrading a section strips its own \section{...} anchor line too
        # (the anchor is part of that section's content range), which can
        # shift the anchor-scan's inferred boundary of an EARLIER,
        # non-affected section forward into where a LATER degraded
        # section's anchor used to be. That's an artifact of anchor-based
        # re-scanning after mutation, not a defect in `_degrade_sections`
        # itself (production code never re-locates ranges post-degradation
        # — see `run()`, which just re-validates the degraded source).
        # Exact substring containment is therefore the reliable oracle for
        # "byte-for-byte unchanged".
        for section in _SECTION_NAMES:
            orig_start, orig_end = orig_ranges[section]
            orig_content = "\n".join(
                latex_source.split("\n")[orig_start - 1:orig_end]
            )

            if section in affected_set:
                # Affected sections must have their \resumeItem markup for
                # this section's markers stripped (no LaTeX commands
                # survive strip_latex_commands), but the plain marker text
                # itself must still be present somewhere in the degraded
                # document since strip_latex_commands only removes
                # commands/braces, not their text content.
                for marker in section_markers[section]:
                    assert marker in degraded, (
                        f"expected marker {marker!r} to survive degradation "
                        f"(plain text) somewhere in the degraded document"
                    )
                    assert f"\\resumeItem{{{marker}}}" not in degraded, (
                        f"expected \\resumeItem wrapper around {marker!r} to "
                        f"be stripped by degradation, but it is still present"
                    )
            else:
                # Non-affected sections must be byte-for-byte unchanged:
                # the exact original content block (anchor line + all
                # marker lines) must appear verbatim, contiguously, in the
                # degraded output.
                assert orig_content in degraded, (
                    f"non-affected section {section!r} content missing "
                    f"verbatim from degraded output: {orig_content!r}"
                )


def test_map_errors_to_sections_first_occurrence_order() -> None:
    """Manually-crafted example verifying the documented first-occurrence-
    order contract: sections are ordered by first appearance across the
    `errors` list (and, within a single error string, by first occurrence
    of its embedded line references) — NOT by canonical section order.

    Validates: Requirements 1.4, 1.5
    """
    latex_source = "\n".join(
        [
            r"\documentclass{article}",
            r"\begin{document}",
            r"\section{PROFESSIONAL SUMMARY}",       # line 3
            r"\resumeItem{SUMMARY_MARKER}",           # line 4
            r"\section{EXPERIENCE}",                  # line 5
            r"\resumeItem{EXPERIENCE_MARKER}",        # line 6
            r"\section{PROJECTS}",                    # line 7
            r"\resumeItem{PROJECTS_MARKER}",          # line 8
            r"\section{TECHNICAL SKILLS}",            # line 9
            r"\resumeItem{SKILLS_MARKER}",            # line 10
            r"\section{EDUCATION}",
            r"\resumeSubheading{PES}{2018}{BE}{Blr}",
            r"\end{document}",
        ]
    )

    # Errors list references skills first, then summary — canonical section
    # order is summary/experience/projects/skills, so a bug that ordered by
    # canonical order instead of first-occurrence would produce
    # ["summary", "skills"] instead of the correct ["skills", "summary"].
    errors_across_list = ["line 10: skills issue", "line 4: summary issue"]
    assert map_errors_to_sections(errors_across_list, latex_source) == [
        "skills",
        "summary",
    ]

    # A single error string with multiple embedded line refs: projects (8)
    # referenced before experience (6) in the *string*, even though
    # experience's line number is numerically smaller and appears earlier
    # in the document.
    single_error_multi_ref = ["line 8: x; line 6: y"]
    assert map_errors_to_sections(single_error_multi_ref, latex_source) == [
        "projects",
        "experience",
    ]
