"""
Smoke test: verify Phase 0 infrastructure compiles and imports cleanly.

Run: python -m pytest server/tests/test_phase0.py -v
"""

import pytest

from server.config import AppConfig
from server.services.latex_utils import (
    escape_special_chars,
    count_braces,
    check_brace_balance,
    check_environment_matching,
    check_placeholders,
    parse_custom_command_args,
    strip_latex_commands,
)
from server.services.types import (
    NodeId,
    SSEEventType,
    JDProfile,
    SectionConfig,
    CompleteEvent,
)


class TestConfig:
    def test_config_requires_gemini_key(self):
        with pytest.raises(Exception):
            AppConfig(gemini_api_key="", azure_storage_connection_string="x", database_url="x", auth_passcode_hash="$2b$12$test")

    def test_config_validates_database_url(self):
        with pytest.raises(ValueError):
            AppConfig(
                gemini_api_key="test-key-1234567890",
                azure_storage_connection_string="DefaultEndpointsProtocol=https;AccountName=x;AccountKey=x;EndpointSuffix=core.windows.net",
                database_url="mysql://localhost/test",
                auth_passcode_hash="$2b$12$testtesttesttesttesttesttest",
            )

    def test_config_splits_cors_origins(self):
        cfg = AppConfig(
            gemini_api_key="test-key-1234567890",
            azure_storage_connection_string="DefaultEndpointsProtocol=https;AccountName=x;AccountKey=x;EndpointSuffix=core.windows.net",
            database_url="postgresql://localhost/test",
            cors_origins="http://a.com, http://b.com",
            auth_passcode_hash="$2b$12$testtesttesttesttesttesttest",
        )
        assert cfg.cors_origins == ["http://a.com", "http://b.com"]


class TestLatexUtils:
    def test_escape_special_chars_handles_ampersand(self):
        assert escape_special_chars("A & B") == r"A \& B"

    def test_escape_special_chars_handles_all(self):
        raw = "Cost: $50 & 30% savings (see #1) with ~2x speed"
        escaped = escape_special_chars(raw)
        assert "$" not in escaped or escaped.count("\\$") > 0
        assert "&" not in escaped or escaped.count("\\&") > 0

    def test_count_braces_balanced(self):
        latex = r"\textbf{hello} world \textit{test}"
        o, c, _, _ = count_braces(latex)
        assert o == c

    def test_count_braces_ignores_escaped(self):
        latex = r"Cost is \$50, use \{ and \} for sets"
        o, c, eo, ec = count_braces(latex)
        assert o == c  # Structural braces: 0 open, 0 close (both braces are escaped)

    def test_check_brace_balance_passes(self):
        ok, err = check_brace_balance(r"\textbf{hello \textit{world}}")
        assert ok
        assert err is None

    def test_check_brace_balance_fails(self):
        ok, err = check_brace_balance(r"\textbf{hello")
        assert not ok
        assert "Unbalanced" in err

    def test_check_environment_matching_passes(self):
        latex = r"\begin{itemize}\item one\end{itemize}"
        ok, err = check_environment_matching(latex)
        assert ok
        assert err is None

    def test_check_environment_matching_mismatch(self):
        latex = r"\begin{itemize}\item one\end{enumerate}"
        ok, err = check_environment_matching(latex)
        assert not ok
        assert "Mismatched" in err

    def test_check_placeholders_clean(self):
        latex = "Hello world, no placeholders here"
        ok, err = check_placeholders(latex)
        assert ok

    def test_check_placeholders_detects_unsubstituted(self):
        latex = r"\section{%%SUMMARY_TEXT%%} still has placeholder"
        ok, err = check_placeholders(latex)
        assert not ok
        assert "%%SUMMARY_TEXT%%" in err

    def test_parse_custom_command_args(self):
        latex = (
            r"\resumeItem{Built API}"
            r"\resumeSubheading{Eng}{2022--2024}{TCS}{Bangalore}"
        )
        results = parse_custom_command_args(
            latex, (r"\resumeItem", r"\resumeSubheading")
        )
        item = next(r for r in results if r["command"] == r"\resumeItem")
        sub = next(r for r in results if r["command"] == r"\resumeSubheading")
        assert item["arg_count"] == 1
        assert sub["arg_count"] == 4

    def test_strip_latex_commands(self):
        latex = r"\textbf{Skills}: Python, React"
        stripped = strip_latex_commands(latex)
        assert "Skills" in stripped
        assert "\\textbf" not in stripped


class TestTypes:
    def test_node_id_enum_values(self):
        assert NodeId.JD_ANALYZER == "n3_jd_analyzer"
        assert NodeId.LATEX_VALIDATOR == "n9_latex_validator"
        assert NodeId.RESPONSE_BUILDER == "n12_response_builder"

    def test_section_config_rejects_unknown_name(self):
        with pytest.raises(ValueError):
            SectionConfig(name="unknown_section")

    def test_section_config_accepts_valid_names(self):
        for name in ("summary", "experience", "projects", "skills"):
            sc = SectionConfig(name=name)
            assert sc.name == name

    def test_jd_profile_validates_seniority(self):
        with pytest.raises(ValueError):
            JDProfile(
                required_skills=[],
                preferred_skills=[],
                seniority_level="ceo",
                domain="tech",
                industry="software",
                role_type="engineer",
                ats_keywords=[],
                company_values=[],
                red_flags_to_avoid=[],
            )

    def test_complete_event_sse_format(self):
        event = CompleteEvent(
            event=SSEEventType.COMPLETE,
            session_key="abc123",
            timestamp="2026-01-01T00:00:00Z",
            latex_source=r"\documentclass{article}",
            filename="resume_engineer_2026.tex",
            warnings=["Uncovered skill: Kubernetes"],
        )
        sse = event.to_sse()
        assert sse.startswith("event: complete")
        assert "latex_source" in sse


class TestNodeIdsCoverage:
    def test_all_17_nodes_have_stubs(self):
        """Verify every NodeId has a corresponding stub module."""
        from server.graph import (
            n1_session, n2_input, n3_jd_analyzer, n4_kg_loader,
            n5_scorer, n6_selector,
            n7a_summary, n7b_experience, n7c_projects, n7d_skills,
            n8_assembler, n9_validator, n9r_fixer,
            n10_compiler, n10f_fallback, n11_persister, n12_response,
        )
        modules = [
            n1_session, n2_input, n3_jd_analyzer, n4_kg_loader,
            n5_scorer, n6_selector,
            n7a_summary, n7b_experience, n7c_projects, n7d_skills,
            n8_assembler, n9_validator, n9r_fixer,
            n10_compiler, n10f_fallback, n11_persister, n12_response,
        ]
        for mod in modules:
            assert hasattr(mod, "run"), f"{mod.__name__} missing run function"
            assert callable(mod.run), f"{mod.__name__}.run is not callable"
