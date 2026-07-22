"""N7a — Summary Generator (Gemini Call 2).

Generates a 3-sentence professional summary that:
- Maps the candidate's background to the target role
- Weaves in ATS keywords from the JD
- Avoids blacklisted phrases (e.g., "I am", "looking for", "eager to")

The summary slot in the master template takes PLAIN TEXT ONLY — no LaTeX
commands, no formatting. Gemini is explicitly instructed to return nothing
but the 3 sentences, no markdown fences, no prefixes.

Temperature: 0.3 for moderate creativity.
Runs in parallel with N7b, N7c, N7d.
"""

from __future__ import annotations

import logging

from server.graph.state import ResumeState
from server.services.gemini import GeminiClient

_logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """You are an expert resume writer. Write a 3-sentence professional summary
for a candidate applying to the role described below.

Candidate background:
{background}

Target role from job description:
{target_context}

ATS keywords to naturally include (do NOT force all — only those that fit):
{ats_keywords}

Red flags to AVOID mentioning or implying:
{red_flags}

---

OUTPUT FORMAT (strict):
Return exactly 3 sentences of plain text. No LaTeX commands, no markdown,
no bullet points, no prefixes like "Summary:" or "Professional Summary:".
Just the raw paragraph text.

Each sentence should be 15–25 words. The three sentences should cover:
1. Years of experience + core technical domain + key achievement signal
2. Specific skills/technologies mapped to the JD requirements
3. Professional impact or value proposition for the target role

BLACKLISTED PHRASES — NEVER use any of these:
- "I am", "I have", "I possess"
- "looking for", "seeking", "eager to", "excited to"
- "results-driven", "proven track record", "team player"
- "think outside the box", "go-getter", "self-starter"
- "my passion", "my dream", "I believe"
- Any first-person pronouns (I, me, my, myself)

Use only third-person, factual statements. Lead with action verbs or subject nouns.

Return ONLY the 3 sentences, nothing else."""


async def run(state: ResumeState, *, gemini: GeminiClient) -> ResumeState:
    jd_profile = state.get("jd_profile", {})
    kg = state.get("kg_snapshot", {})
    selected_projects = state.get("selected_projects", [])
    selected_roles = state.get("selected_roles", [])
    covered_skills = state.get("covered_skills", [])

    _logger.info("N7a: Generating summary...")

    background = _build_background(selected_roles, selected_projects, kg, covered_skills)
    target_context = _build_target_context(jd_profile)
    ats_keywords = ", ".join(jd_profile.get("ats_keywords", [])[:8])
    red_flags = "\n".join(
        f"- {rf}" for rf in jd_profile.get("red_flags_to_avoid", [])[:3]
    ) or "(none)"

    prompt = SUMMARY_PROMPT.format(
        background=background,
        target_context=target_context,
        ats_keywords=ats_keywords,
        red_flags=red_flags,
    )

    raw = await gemini.generate(
        prompt,
        temperature=0.3,
        expect_json=False,
        max_retries=2,
    )

    # Strip any stray markdown or labels
    summary = _clean_summary(raw)

    _logger.info(
        "N7a summary generated: %d chars, %d sentences",
        len(summary),
        summary.count("."),
    )

    # Write to sections_output list (appends via operator.add reducer)
    return ResumeState(
        sections_output=[{"section": "summary", "content": summary}],
    )


def _build_background(
    roles: list[dict],
    projects: list[dict],
    kg: dict,
    covered_skills: list[str],
) -> str:
    parts = []

    if roles:
        r = roles[0]
        parts.append(
            f"Current role: {r.get('role_title', '')} at {r.get('company_name', '')} "
            f"({r.get('start_date', '')} to {r.get('end_date') or 'Present'})"
        )

    if projects:
        parts.append(
            f"Most relevant projects: {', '.join(p['title'][:60] for p in projects)}"
        )

    if covered_skills:
        parts.append(f"Top matching skills: {', '.join(covered_skills[:10])}")

    # Total summary of KG
    total_projects = len(kg.get("projects", []))
    total_skills = len(kg.get("skills", []))
    parts.append(
        f"Overall: {total_projects} completed projects, {total_skills} technical skills"
    )

    return "\n".join(parts)


def _build_target_context(jd_profile: dict) -> str:
    parts = [
        f"Role type: {jd_profile.get('role_type', 'IC')}",
        f"Seniority: {jd_profile.get('seniority_level', 'mid')}",
        f"Domain: {jd_profile.get('domain', '')}",
        f"Industry: {jd_profile.get('industry', '')}",
    ]

    required = jd_profile.get("required_skills", [])
    if required:
        skills = ", ".join(s["skill"] for s in required[:10])
        parts.append(f"Required skills: {skills}")

    return "\n".join(parts)


def _clean_summary(text: str) -> str:
    """Strip common markdown/prefix cruft from Gemini output."""
    text = text.strip()
    # Remove markdown fences
    if text.startswith("```"):
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Remove common prefixes
    import re
    text = re.sub(r"^(?:Summary:|Professional Summary:)\s*", "", text, flags=re.IGNORECASE)

    return text
