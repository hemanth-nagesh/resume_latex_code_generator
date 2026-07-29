"""Tests for N3 — JD Analyzer retry-then-raise behavior on JDProfile validation.

Covers the fix in `server/graph/n3_jd_analyzer.py`: a Gemini response whose
parsed JSON fails `JDProfile` field validation triggers exactly one retry
(same prompt); a second failure raises a descriptive `JDAnalysisError`
instead of a bare `pydantic.ValidationError`.
"""

from __future__ import annotations

import asyncio
import copy
import json

import pytest
from hypothesis import given, settings, strategies as st

from server.graph.n3_jd_analyzer import JDAnalysisError, run
from server.graph.state import ResumeState

# ===========================================================================
# Fixtures / fakes
# ===========================================================================

VALID_JD_RAW: dict = {
    "required_skills": [
        {"skill": "Python", "is_technical": True, "ats_exact_phrase": "Python"},
        {"skill": "FastAPI", "is_technical": True, "ats_exact_phrase": "FastAPI"},
    ],
    "preferred_skills": [
        {"skill": "Docker", "is_technical": True},
    ],
    "seniority_level": "senior",
    "domain": "Backend Engineering",
    "industry": "Enterprise SaaS",
    "role_type": "IC",
    "ats_keywords": ["agile", "CI/CD"],
    "company_values": ["innovation", "collaboration"],
    "red_flags_to_avoid": [],
}


def _invalid_raw(seniority_level: str = "expert") -> dict:
    """A JD raw payload that fails JDProfile.validate_seniority."""
    raw = copy.deepcopy(VALID_JD_RAW)
    raw["seniority_level"] = seniority_level
    return raw


class FakeGeminiClient:
    """Minimal stand-in for GeminiClient — returns queued responses in
    order and records how many times `generate()` was called."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.call_count = 0

    async def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.3,
        model: str | None = None,
        expect_json: bool = False,
        max_retries: int = 2,
    ) -> str:
        self.call_count += 1
        if self.call_count > len(self._responses):
            raise AssertionError(
                f"generate() called more times ({self.call_count}) than "
                f"responses queued ({len(self._responses)})"
            )
        return self._responses[self.call_count - 1]


def _make_state() -> ResumeState:
    return ResumeState(jd_cleaned="We need a senior backend engineer.", estimated_tokens=42)


# ===========================================================================
# Scenario 1: valid JSON on first attempt
# ===========================================================================

async def test_valid_on_first_attempt_no_retry():
    gemini = FakeGeminiClient([json.dumps(VALID_JD_RAW)])
    state = _make_state()

    result = await run(state, gemini=gemini)

    assert gemini.call_count == 1
    assert result.get("jd_profile") is not None
    assert result["jd_profile"]["seniority_level"] == "senior"


# ===========================================================================
# Scenario 2: invalid then valid → recovers on retry
# ===========================================================================

async def test_invalid_then_valid_recovers():
    gemini = FakeGeminiClient(
        [json.dumps(_invalid_raw("expert")), json.dumps(VALID_JD_RAW)]
    )
    state = _make_state()

    result = await run(state, gemini=gemini)

    assert gemini.call_count == 2
    assert result.get("jd_profile") is not None
    assert result["jd_profile"]["seniority_level"] == "senior"


# ===========================================================================
# Scenario 3: invalid then invalid → raises JDAnalysisError after exactly 2 calls
# ===========================================================================

INVALID_SENIORITY_VALUES = [
    "expert",
    "principal",
    "intern",
    "director",
    "",
    "SENIOR-ISH",
    "junior mid",
]


@given(seniority_value=st.sampled_from(INVALID_SENIORITY_VALUES))
@settings(max_examples=20, deadline=None)
def test_invalid_then_invalid_raises_jd_analysis_error(seniority_value):
    async def _run() -> None:
        gemini = FakeGeminiClient(
            [
                json.dumps(_invalid_raw(seniority_value)),
                json.dumps(_invalid_raw(seniority_value)),
            ]
        )
        state = _make_state()

        with pytest.raises(JDAnalysisError) as exc_info:
            await run(state, gemini=gemini)

        assert gemini.call_count == 2
        assert "seniority_level" in str(exc_info.value)
        # Must not be a bare pydantic ValidationError propagating out.
        assert isinstance(exc_info.value, JDAnalysisError)

    asyncio.run(_run())
