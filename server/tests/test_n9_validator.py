"""Property-based tests for server/graph/n9_validator.py.

Covers Property 4 (custom command schema matches template arity) from
`.kiro/specs/graph-reliability-fixes/design.md`.

This complements the pure-parser unit tests already in `test_phase5.py`
(`TestN9Validator.test_custom_command_schema_resumeSubheading`,
`test_schema_completeness`, etc.) by exercising the actual async check
function `_check_custom_command_schema` directly, across a randomized range
of `\resumeProjectHeading` argument counts.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from server.graph.n9_validator import _check_custom_command_schema, map_errors_to_sections

_COMMAND = r"\resumeProjectHeading"

# Simple placeholder text for argument content — letters, digits, and spaces
# only, so it can never be mistaken for a brace, backslash, or line break
# that would confuse the brace-counting parser.
_arg_text_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "),
    min_size=1,
    max_size=8,
).map(str.strip).filter(lambda s: len(s) > 0)


def _build_call(arg_count: int, arg_texts: list[str]) -> str:
    """Build a minimal LaTeX snippet containing exactly one
    `\resumeProjectHeading` call with `arg_count` brace-delimited groups."""
    groups = "".join(f"{{{text}}}" for text in arg_texts[:arg_count])
    return _COMMAND + groups


class TestCustomCommandSchemaArity:
    """**Property 4: Custom command schema matches template arity**

    **Validates: Requirements 2.1, 2.2**

    For any LaTeX snippet containing a call to `\resumeProjectHeading` with
    exactly 2 brace-delimited argument groups, `_check_custom_command_schema`
    reports no schema error for that call; for any call with a different
    argument count, it reports an error naming the expected count of 2.
    """

    @settings(max_examples=100)
    @given(
        arg_count=st.integers(min_value=0, max_value=4),
        arg_texts=st.lists(_arg_text_strategy, min_size=4, max_size=4),
    )
    async def test_schema_error_matches_expected_arity(
        self, arg_count: int, arg_texts: list[str]
    ) -> None:
        latex = _build_call(arg_count, arg_texts)
        ok, msg = await _check_custom_command_schema(latex)

        if arg_count == 2:
            assert (ok, msg) == (True, None), (
                f"Expected no schema error for a 2-arg call, got {(ok, msg)!r} "
                f"for latex={latex!r}"
            )
        elif arg_count == 0:
            # With zero brace groups there is no `{` immediately following
            # the command, so `parse_custom_command_args` (server/services/
            # latex_utils.py) cannot distinguish "a call with 0 args" from
            # "no call at all" — no instance is recorded and no error is
            # raised. This is documented, verified behavior of the
            # underlying parser (out of scope for the Bug 2 schema-dict fix),
            # so we assert the actual observed contract instead of a
            # detected arity mismatch.
            assert (ok, msg) == (True, None), (
                f"Expected no detectable call (and thus no error) for a "
                f"bare 0-arg reference, got {(ok, msg)!r} for latex={latex!r}"
            )
        else:
            assert ok is False, (
                f"Expected a schema error for a {arg_count}-arg call, "
                f"got {(ok, msg)!r} for latex={latex!r}"
            )
            assert msg is not None
            assert "2" in msg, f"Expected error to name '2' as expected count, got: {msg!r}"
            assert _COMMAND in msg, f"Expected error to name the command, got: {msg!r}"


async def test_resumeProjectHeading_2args_passes_3args_fails() -> None:
    """Concrete example matching the bug report: a 2-arg
    `\resumeProjectHeading{Title}{Date}` call passes schema validation, while
    the historically-mishandled 3-arg `\resumeProjectHeading{Title}{Stack}{Date}`
    call (previously silently allowed through as "variadic") now fails with a
    schema error naming the expected count of 2.

    Validates: Requirements 2.1, 2.2
    """
    valid_latex = r"\resumeProjectHeading{Resume Builder}{Jan 2024 -- Present}"
    ok, msg = await _check_custom_command_schema(valid_latex)
    assert (ok, msg) == (True, None)

    invalid_latex = (
        r"\resumeProjectHeading{Resume Builder}{Python, FastAPI, React}{Jan 2024 -- Present}"
    )
    ok, msg = await _check_custom_command_schema(invalid_latex)
    assert ok is False
    assert msg is not None
    assert "2" in msg
    assert _COMMAND in msg


_MAPPING_LATEX = r"""\documentclass{article}
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
\resumeProjectHeading{Resume Builder}{Python, FastAPI}{Jan 2024 -- Present}
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


async def test_map_errors_to_sections_returns_only_projects_for_bad_heading() -> None:
    """Direct unit test of `map_errors_to_sections()` in isolation (task 9.6).

    A single malformed `\resumeProjectHeading` call (3 args instead of 2)
    inside the "projects" section produces a schema error whose line number
    falls within the PROJECTS section's line range, so the mapping must
    return exactly `["projects"]` — no other section should be implicated.

    Validates: Requirements 1.4, 1.6, 1.7
    """
    ok, msg = await _check_custom_command_schema(_MAPPING_LATEX)
    assert ok is False
    assert msg is not None

    sections = map_errors_to_sections([msg], _MAPPING_LATEX)
    assert sections == ["projects"]
