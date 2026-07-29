"""N3 — JD Analyzer (Gemini Call 1).

Parses the job description into a structured JDProfile with:
- Required and preferred skills (differentiated)
- Seniority level (junior/mid/senior/lead/staff)
- Domain and industry
- Role type (IC, manager, hybrid)
- ATS keywords (exact phrases from JD)
- Company values (culture signals)
- Red flags to avoid (toxic terms, unrealistic requirements)

Temperature: 0.2 for deterministic extraction.
JSON schema is enforced via expect_json=True in the Gemini client.
"""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from server.graph.state import ResumeState
from server.services.gemini import GeminiClient
from server.services.types import JDProfile

_logger = logging.getLogger(__name__)


class JDAnalysisError(Exception):
    """Raised when Gemini's JD analysis response fails JDProfile validation
    even after one retry attempt with the same prompt."""


JD_ANALYZER_PROMPT = """You are a resume-matching expert. Extract structured information
from the job description below. Be precise and factual — never invent details
not present in the text.

Return a JSON object with exactly these fields:

{{
  "required_skills": [
    {{"skill": "Python", "is_technical": true, "ats_exact_phrase": "Python"}}
  ],
  "preferred_skills": [
    {{"skill": "Docker", "is_technical": true}}
  ],
  "seniority_level": "senior",
  "domain": "Backend Engineering",
  "industry": "Enterprise SaaS",
  "role_type": "IC",
  "ats_keywords": ["agile", "CI/CD", "test-driven"],
  "company_values": ["innovation", "collaboration"],
  "red_flags_to_avoid": ["fast-paced means overtime"]
}}

Rules:
- seniority_level: ONLY "junior", "mid", "senior", "lead", or "staff"
- role_type: pick the best fit from IC, manager, or hybrid
- required_skills: skills explicitly listed as required, mandatory, must-have
- preferred_skills: skills listed as nice-to-have, preferred, bonus
- is_technical: true for programming languages, frameworks, tools, platforms.
  false for soft skills like communication, leadership.
- ats_exact_phrase: the exact multi-word phrase from the JD that indicates this skill.
  Use for ATS keyword matching.
- ats_keywords: important non-skill keywords from the JD (methodologies, processes, certifications)
- company_values: cultural signals (max 3)
- red_flags_to_avoid: anything that might make the resume seem misaligned (max 3)
- Extract 5-15 required_skills and 3-10 preferred_skills
- If you're unsure about a skill classification, default to preferred

Job Description:
---
{jd_text}
---

Return ONLY the JSON object, no markdown fences, no explanations."""


async def run(
    state: ResumeState,
    *,
    gemini: GeminiClient,
) -> ResumeState:
    jd_text = state["jd_cleaned"]

    _logger.info(
        "Analyzing JD: %d chars, ~%d tokens",
        len(jd_text),
        state.get("estimated_tokens", 0),
    )

    prompt = JD_ANALYZER_PROMPT.format(jd_text=jd_text)

    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        response = await gemini.generate(
            prompt,
            temperature=0.2,
            expect_json=True,
            max_retries=2,
        )

        raw = json.loads(response)

        try:
            jd_profile = JDProfile(**raw)
        except ValidationError as e:
            if attempt == max_attempts:
                raise JDAnalysisError(
                    f"JD analysis produced an invalid profile after retry: {e}"
                ) from e
            _logger.warning(
                "JDProfile validation failed on attempt %d, retrying: %s",
                attempt,
                e,
            )
            continue

        _logger.info(
            "JD analysis complete: %d required skills, %d preferred, %s level, %s domain",
            len(jd_profile.required_skills),
            len(jd_profile.preferred_skills),
            jd_profile.seniority_level,
            jd_profile.domain,
        )

        return ResumeState(jd_profile=jd_profile.model_dump())
