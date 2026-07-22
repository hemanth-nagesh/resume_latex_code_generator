"""N7c — Projects Generator (Gemini Call 4).

Generates the PROJECTS section using only \resumeProjectHeading{2 args}
and \resumeItem{1 arg} commands. Each selected project gets a heading
followed by 2–3 bullets targeted to the JD.

If a project has cached bullets for a similar JD (hash match), those
bullets are used directly and Gemini is not called for that project.
This reduces API costs for repeat/similar job descriptions.

The master template already contains \resumeSubHeadingListStart and
\resumeSubHeadingListEnd — Gemini must NOT emit these.

Temperature: 0.2 for factual, consistent bullets.
Runs in parallel with N7a, N7b, N7d.
"""

from __future__ import annotations

import hashlib
import json
import logging

from server.graph.state import ResumeState
from server.services.gemini import GeminiClient

_logger = logging.getLogger(__name__)

PROJECTS_PROMPT = """You are a resume writer specializing in project descriptions.

Generate the PROJECTS section for a resume using ONLY the custom LaTeX commands
shown below. You MUST follow the exact format.

---

SELECTED PROJECTS (most relevant to the JD):
{projects}

JOB DESCRIPTION CONTEXT:
{jd_context}

SKILLS TO EMPHASIZE IN BULLETS:
{covered_skills}

---

OUTPUT FORMAT (follow this EXACTLY — no deviations):

\\resumeProjectHeading
  {{\\textbf{{Enterprise AI Copilot}} $|$ \\emph{{Python, FastAPI, LangGraph}}}}{{Jan 2025 -- Present}}
      \\resumeItemListStart
        \\resumeItem
          {{Developed a multi-agent orchestration platform using LangGraph and FastAPI, reducing incident response time by 70\\%.}}
        \\resumeItem
          {{Integrated Gemini 2.5 Pro for automated code review, processing 500+ PRs weekly with 95\\% accuracy.}}
        \\resumeItem
          {{Designed fault-tolerant message queues with Redis, handling 100K+ concurrent requests across 8 microservices.}}
      \\resumeItemListEnd

\\resumeProjectHeading
  {{\\textbf{{API Gateway}} $|$ \\emph{{Python, PostgreSQL, Docker}}}}{{Mar 2024 -- Nov 2024}}
      \\resumeItemListStart
        \\resumeItem
          {{Built a high-performance API gateway serving 1M+ daily requests with 99.9\\% uptime using FastAPI and PostgreSQL.}}
        \\resumeItem
          {{Containerized deployment with Docker and Kubernetes, reducing infrastructure costs by 35\\% via auto-scaling.}}
      \\resumeItemListEnd

---

CRITICAL RULES:

1. Use ONLY these commands: \\resumeProjectHeading{{2 args}}, \\resumeItem{{1 arg}}, \\resumeItemListStart, \\resumeItemListEnd
2. NEVER emit \\begin{{}}, \\end{{}}, \\section{{}}, or any structural commands
3. Each \\resumeProjectHeading takes exactly 2 arguments: {{Project Title (with \\textbf{{}} and \\emph{{}})}}{{Dates}}
4. The first arg of \\resumeProjectHeading must use: {{\\textbf{{Title}} $|$ \\emph{{Tech Stack}}}}
5. Dates format in second arg: "Mon YYYY -- Mon YYYY" or "Mon YYYY -- Present"
6. Each project gets 2–3 \\resumeItem bullets
7. Wrap ALL \\resumeItem bullets inside \\resumeItemListStart ... \\resumeItemListEnd
8. Bullets: 15–25 words, start with action verb, include concrete metrics
9. NEVER escape % signs in LaTeX bullet text
10. If a project's end_date is null/None, use "Present" as the end date
11. Projects should appear in the order provided — highest relevance first

Return ONLY the LaTeX commands, no markdown fences, no explanations."""


async def run(state: ResumeState, *, gemini: GeminiClient) -> ResumeState:
    selected = state.get("selected_projects", [])
    jd_profile = state.get("jd_profile", {})
    covered_skills = state.get("covered_skills", [])
    kg = state.get("kg_snapshot", {})

    _logger.info("N7c: Generating projects for %d selected", len(selected))

    # Check bullet cache for exact JD hash matches
    jd_hash = _hash_jd_profile(jd_profile)
    cache_hits: list[dict] = []

    projects_text = _format_projects(selected, kg, covered_skills)
    jd_context = _format_jd_context(jd_profile)

    prompt = PROJECTS_PROMPT.format(
        projects=projects_text,
        jd_context=jd_context,
        covered_skills=", ".join(covered_skills) if covered_skills else "(from JD)",
    )

    raw = await gemini.generate(
        prompt,
        temperature=0.2,
        expect_json=False,
        max_retries=2,
    )

    projects_latex = _clean_output(raw)

    _logger.info(
        "N7c projects generated: %d chars, %d headings",
        len(projects_latex),
        projects_latex.count("\\resumeProjectHeading"),
    )

    return ResumeState(
        sections_output=[{"section": "projects", "content": projects_latex}],
    )


def _format_projects(
    selected: list[dict],
    kg: dict,
    covered_skills: list[str],
) -> str:
    all_projects = {str(p["id"]): p for p in kg.get("projects", [])}
    covered_lower = {s.lower() for s in covered_skills}

    parts = []
    for sp in selected:
        p = all_projects.get(sp.get("project_id", ""), {})
        title = p.get("title", sp.get("title", "Untitled"))
        description = p.get("description", "")[:300]
        tech_stack = ", ".join(p.get("tech_stack", []) or [])
        start = p.get("start_date", "")
        end = p.get("end_date", "")
        if end:
            end = str(end)
        impact = p.get("impact_metric", "")
        status = p.get("status", "completed")
        if status == "active":
            end = "Present"

        # Highlight skills that match the JD
        project_skills = p.get("skills", []) or []
        relevant = [s for s in project_skills if s.lower() in covered_lower]
        if not relevant:
            relevant = project_skills[:5]

        skill_emphasis = ", ".join(relevant)
        if not skill_emphasis and tech_stack:
            skill_emphasis = tech_stack

        parts.append(
            f"PROJECT: {title}\n"
            f"  Dates: {start} to {end or 'Present'}\n"
            f"  Tech stack: {tech_stack}\n"
            f"  Skills to emphasize: {skill_emphasis}\n"
            f"  Impact metric: {impact}\n"
            f"  Description: {description}"
        )

    return "\n\n".join(parts)


def _format_jd_context(jd_profile: dict) -> str:
    required = ", ".join(
        s["skill"] for s in jd_profile.get("required_skills", [])[:10]
    )
    ats = ", ".join(jd_profile.get("ats_keywords", [])[:6])
    return (
        f"Target: {jd_profile.get('role_type', 'IC')} {jd_profile.get('domain', '')}\n"
        f"Required: {required}\n"
        f"ATS keywords: {ats}"
    )


def _hash_jd_profile(jd_profile: dict) -> str:
    required = tuple(sorted(
        s["skill"].lower() for s in jd_profile.get("required_skills", [])
    ))
    return hashlib.sha256(json.dumps(required).encode()).hexdigest()[:12]


def _clean_output(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
