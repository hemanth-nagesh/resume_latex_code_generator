"""
Phase 1 tests — locked master template, custom command schema, substitution.

Coverage:
- Template exists and is structurally valid
- All 6 content slots present with correct names
- Preamble contains zero slot markers (Gemini can never touch this)
- CUSTOM_COMMAND_SCHEMA matches template definitions
- Substitution replaces all slots correctly
- No leftover %% placeholders after substitution
- N9 validator catches wrong argument counts
"""

import re
from pathlib import Path

import pytest

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "template" / "master_resume.tex"
REQUIRED_SLOTS = [
    "%%SUMMARY_TEXT%%",
    "%%EXPERIENCE_BLOCK%%",
    "%%PROJECTS_BLOCK%%",
    "%%SKILLS_BLOCK%%",
    "%%EDUCATION_BLOCK%%",
    "%%CERTIFICATIONS_BLOCK%%",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def template_text() -> str:
    assert TEMPLATE_PATH.exists(), f"Template not found: {TEMPLATE_PATH}"
    return TEMPLATE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def preamble(template_text: str) -> str:
    """Everything before \\begin{document} is the locked preamble."""
    doc_start = template_text.find(r"\begin{document}")
    return template_text[:doc_start]


@pytest.fixture(scope="module")
def body(template_text: str) -> str:
    """Everything from \\begin{document} to \\end{document}."""
    doc_start = template_text.find(r"\begin{document}")
    doc_end = template_text.find(r"\end{document}") + len(r"\end{document}")
    return template_text[doc_start:doc_end]


# ---------------------------------------------------------------------------
# Template structure tests
# ---------------------------------------------------------------------------

class TestTemplateExists:
    def test_template_file_found(self, template_text):
        assert len(template_text) > 500, "Template seems too short"

    def test_template_has_document_class(self, preamble):
        assert r"\documentclass" in preamble

    def test_template_has_begin_document(self, template_text):
        assert r"\begin{document}" in template_text

    def test_template_has_end_document(self, template_text):
        assert r"\end{document}" in template_text


class TestSlotsExist:
    """Every required content slot must appear exactly once in the body."""

    def test_all_slots_present(self, body):
        for slot in REQUIRED_SLOTS:
            assert slot in body, f"Missing slot: {slot}"

    def test_slots_only_in_body(self, preamble):
        """Preamble must contain ZERO slot markers — Gemini never sees them there."""
        for slot in REQUIRED_SLOTS:
            assert slot not in preamble, (
                f"Slot {slot} found in preamble! Slots must only appear in the body "
                "(after \\begin{document}). Gemini must never touch the preamble."
            )

    def test_each_slot_appears_once(self, body):
        for slot in REQUIRED_SLOTS:
            count = body.count(slot)
            assert count == 1, (
                f"Slot {slot} appears {count} times — must appear exactly once"
            )


class TestCustomCommandsDefined:
    """Verify the preamble defines all commands in CUSTOM_COMMAND_SCHEMA."""

    REQUIRED_COMMANDS = [
        r"\resumeItem",
        r"\resumeSubheading",
        r"\resumeProjectHeading",
    ]

    def test_all_commands_defined(self, preamble):
        for cmd in self.REQUIRED_COMMANDS:
            assert f"\\newcommand{{{cmd}}}" in preamble or f"\\newcommand{{{cmd}}}[" in preamble, (
                f"Custom command {cmd} not defined in preamble"
            )

    def test_environment_wrappers_in_template(self, template_text):
        """List wrappers stay in template — Gemini never generates them."""
        wrappers = [
            r"\resumeSubHeadingListStart",
            r"\resumeSubHeadingListEnd",
            r"\resumeItemListStart",
            r"\resumeItemListEnd",
        ]
        for wrapper in wrappers:
            # Must be in template body, not in a content slot
            assert wrapper in template_text, f"Missing environment wrapper: {wrapper}"


class TestSectionOrder:
    """Sections in the template must follow the standard resume order."""

    def test_sections_in_correct_order(self, body):
        section_phrases = [
            "PROFESSIONAL SUMMARY",
            "EXPERIENCE",
            "PROJECTS",
            "TECHNICAL SKILLS",
            "EDUCATION",
            "CERTIFICATIONS",
        ]
        last_pos = 0
        for phrase in section_phrases:
            pos = body.find(phrase)
            assert pos > last_pos, (
                f"Section '{phrase}' is out of order or missing (pos={pos})"
            )
            last_pos = pos


# ---------------------------------------------------------------------------
# Substitution tests
# ---------------------------------------------------------------------------

class TestSubstitution:
    """Verify str.replace() substitution produces valid output."""

    DUMMY = {
        "%%SUMMARY_TEXT%%": "Experienced engineer with 3+ years in AI and backend systems.",
        "%%EXPERIENCE_BLOCK%%": (
            r"\resumeSubheading{Eng}{2023--Present}{TCS}{Bangalore}"
            r"\resumeItemListStart"
            r"\resumeItem{Built scalable APIs.}"
            r"\resumeItemListEnd"
        ),
        "%%PROJECTS_BLOCK%%": (
            r"\resumeProjectHeading{\textbf{AI Platform}}{2025--present}"
            r"\resumeItemListStart"
            r"\resumeItem{Designed multi-agent system.}"
            r"\resumeItemListEnd"
        ),
        "%%SKILLS_BLOCK%%": (
            r"\textbf{Backend} {: Python, FastAPI}\vspace{2pt} \\"
            r"\textbf{AI} {: PyTorch, LangGraph}\vspace{2pt}"
        ),
        "%%EDUCATION_BLOCK%%": (
            r"\resumeSubheading{PES College}{2021--2023}{MCA}{}"
        ),
        "%%CERTIFICATIONS_BLOCK%%": (
            r"\item[] \textbf{Azure AI Engineer} (2026) \vspace{-2pt}"
        ),
    }

    def test_substitution_replaces_all(self, template_text):
        result = template_text
        for slot, value in self.DUMMY.items():
            result = result.replace(slot, value)

        for slot in REQUIRED_SLOTS:
            assert slot not in result, f"Slot {slot} not substituted"

    def test_substitution_preserves_preamble(self, template_text, preamble):
        """The preamble must be byte-identical after substitution."""
        result = template_text
        for slot, value in self.DUMMY.items():
            result = result.replace(slot, value)

        result_preamble = result[: result.find(r"\begin{document}")]
        assert result_preamble == preamble, (
            "Preamble changed after substitution! Slots must not exist in preamble."
        )

    def test_substitution_preserves_section_headers(self, template_text):
        """Section headers and formatting must stay untouched."""
        result = template_text
        for slot, value in self.DUMMY.items():
            result = result.replace(slot, value)

        expected_headers = [
            r"\section{PROFESSIONAL SUMMARY}",
            r"\section{EXPERIENCE}",
            r"\section{PROJECTS}",
            r"\section{TECHNICAL SKILLS}",
            r"\section{EDUCATION}",
            r"\section{CERTIFICATIONS \& PUBLICATIONS}",
        ]
        for header in expected_headers:
            assert header in result, f"Missing section header: {header}"


# ---------------------------------------------------------------------------
# CUSTOM_COMMAND_SCHEMA validation tests
# ---------------------------------------------------------------------------

class TestCommandSchemaValidation:
    """Verify the N9 validator correctly catches schema violations."""

    @pytest.mark.asyncio
    async def test_valid_content_passes(self):
        from server.graph.n9_validator import run as n9_run

        state = {
            "latex_source": (
                r"\resumeSubheading{Eng}{2022--2024}{TCS}{Bangalore}"
                r"\resumeItem{Built APIs}"
                r"\resumeItem{Reduced latency by 40\%}"
                r"\resumeProjectHeading{\textbf{Project}}{2024}"
                r"\resumeSubItem{Sub-item text}"
            ),
        }
        result = await n9_run(state)
        assert result["latex_valid"] is True
        assert result["validation_errors"] == []

    @pytest.mark.asyncio
    async def test_wrong_arg_count_fails(self):
        """\resumeSubheading with 3 args instead of 4 must be caught."""
        from server.graph.n9_validator import run as n9_run

        state = {
            "latex_source": (
                r"\resumeSubheading{Eng}{2022--2024}{TCS}"  # 3 args, needs 4
            ),
        }
        result = await n9_run(state)
        assert result["latex_valid"] is False
        assert len(result["validation_errors"]) > 0
        assert any("expected 4 args" in e for e in result["validation_errors"])

    @pytest.mark.asyncio
    async def test_too_many_args_fails(self):
        """\resumeItem with 2 args instead of 1 must be caught."""
        from server.graph.n9_validator import run as n9_run

        state = {
            "latex_source": r"\resumeItem{Bullet one}{Extra arg}",
        }
        result = await n9_run(state)
        assert result["latex_valid"] is False
        assert any("expected 1 args" in e for e in result["validation_errors"])

    @pytest.mark.asyncio
    async def test_unbalanced_braces_fails(self):
        from server.graph.n9_validator import run as n9_run

        state = {
            "latex_source": r"\resumeItem{Unclosed brace",
        }
        result = await n9_run(state)
        assert result["latex_valid"] is False
        assert any("Brace balance" in e for e in result["validation_errors"])

    @pytest.mark.asyncio
    async def test_empty_source_fails(self):
        from server.graph.n9_validator import run as n9_run

        state = {"latex_source": ""}
        result = await n9_run(state)
        assert result["latex_valid"] is False
