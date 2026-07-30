r"""N7b — Experience Generator (Gemini Call 3).

Generates the EXPERIENCE section using only \resumeSubheading{4 args}
and \resumeItem{1 arg} commands. Each selected role gets one subheading
block followed by 2-4 bullet points targeted to the JD.

The master template already contains \resumeSubHeadingListStart and
\resumeSubHeadingListEnd — Gemini must NOT emit these or any other
\begin{} / \end{} / \section{} commands.

Temperature: 0.2 for consistency.
Runs in parallel with N7a, N7c, N7d.
"""

from __future__ import annotations

import logging

from server.graph.state import ResumeState
from server.services.gemini import GeminiClient

_logger = logging.getLogger(__name__)

EXPERIENCE_PROMPT = """You are a resume writer specializing in ATS-optimized experience sections.

Generate the EXPERIENCE section for a resume using ONLY the custom LaTeX commands
shown below. You MUST follow the exact format — every line is either a
\\resumeSubheading or a \\resumeItem call.

---

SELECTED ROLES:
{roles}

JOB DESCRIPTION CONTEXT:
{jd_context}

IMPORTANT CONTEXT — The candidate's responsibilities in these roles:
{responsibilities}

SKILLS THAT MUST BE FEATURED IN BULLETS:
{covered_skills}

---

OUTPUT FORMAT (follow this EXACTLY — no deviations):

\\resumeSubheading
  {{Tata Consultancy Services}}{{Dec 2023 -- Present}}
  {{AI/ML Engineer}}{{Bangalore, India}}
      \\resumeItemListStart
        \\resumeItem
          {{Designed and deployed scalable REST APIs using FastAPI, reducing response time by 40\\% across 12 microservices.}}
        \\resumeItem
          {{Built an automated ML pipeline with Python and PostgreSQL, processing 2M+ records daily for predictive analytics.}}
      \\resumeItemListEnd

\\resumeSubheading
  {{Startup Inc.}}{{Mar 2023 -- May 2023}}
  {{Intern}}{{Remote}}
      \\resumeItemListStart
        \\resumeItem
          {{Developed a real-time chatbot system using Python and WebSockets, handling 500+ concurrent users.}}
      \\resumeItemListEnd

---

CRITICAL RULES:

1. Use ONLY these commands: \\resumeSubheading{{4 args}}, \\resumeItem{{1 arg}}, \\resumeItemListStart, \\resumeItemListEnd
2. NEVER emit \\begin{{}}, \\end{{}}, \\section{{}}, \\textbf{{}}, or any structural commands
3. Each \\resumeSubheading takes exactly 4 arguments in this order: {{Company}}{{Dates}}{{Role Title}}{{Location}}
4. Every role gets exactly one \\resumeSubheading block
5. Wrap ALL \\resumeItem bullets inside \\resumeItemListStart ... \\resumeItemListEnd
6. Each role gets 2–4 \\resumeItem bullets between its ListStart/ListEnd
8. Dates format: "Mon YYYY -- Mon YYYY" or "Mon YYYY -- Present"
9. Bullets must be 15–25 words, start with action verb, include metrics where possible
10. Never escape % signs in LaTeX — they are not comments in this context
11. Roles should be in reverse-chronological order (most recent first)
12. Never use first-person pronouns (I, me, my, we)
13. CRITICAL: Always escape "&" as "\\&" in ALL text content.
    Example: "R\\&D" NOT "R&D". Example: "AI \\& ML" NOT "AI & ML"

Return ONLY the LaTeX commands, no markdown fences, no explanations."""


async def run(state: ResumeState, *, gemini: GeminiClient) -> ResumeState:
    roles = state.get("selected_roles", [])
    jd_profile = state.get("jd_profile", {})
    covered_skills = state.get("covered_skills", [])
    selected_projects = state.get("selected_projects", [])

    _logger.info(
        "N7b: Generating experience for %d roles with %d covered skills",
        len(roles),
        len(covered_skills),
    )

    roles_text = _format_roles(roles)
    jd_context = _format_jd_context(jd_profile)
    responsibilities = _format_responsibilities(roles, selected_projects)
    skills_text = ", ".join(covered_skills) if covered_skills else "(use JD as guide)"

    prompt = EXPERIENCE_PROMPT.format(
        roles=roles_text,
        jd_context=jd_context,
        responsibilities=responsibilities,
        covered_skills=skills_text,
    )

    raw = await gemini.generate(
        prompt,
        temperature=0.2,
        expect_json=False,
        max_retries=2,
    )

    experience = _clean_output(raw)

    _logger.info(
        "N7b experience generated: %d chars, %d subheadings",
        len(experience),
        experience.count("\\resumeSubheading"),
    )

    return ResumeState(
        sections_output=[{"section": "experience", "content": experience}],
    )


def _format_roles(roles: list[dict]) -> str:
    if not roles:
        return "(no roles — use default: AI/ML Engineer at TCS, Dec 2023–Present)"
    parts = []
    for r in roles:
        parts.append(
            f"Role: {r.get('role_title', '')}\n"
            f"  Company: {r.get('company_name', '')}\n"
            f"  Dates: {r.get('start_date', '')} to {r.get('end_date') or 'Present'}\n"
            f"  Location: {r.get('location', 'India')}\n"
            f"  Type: {r.get('employment_type', 'full-time')}"
        )
    return "\n\n".join(parts)


def _format_jd_context(jd_profile: dict) -> str:
    required = ", ".join(
        s["skill"] for s in jd_profile.get("required_skills", [])[:8]
    )
    keywords = ", ".join(jd_profile.get("ats_keywords", [])[:5])
    return (
        f"Target role: {jd_profile.get('role_type', 'IC')}, "
        f"{jd_profile.get('seniority_level', 'mid')} level\n"
        f"Required skills: {required}\n"
        f"ATS keywords: {keywords}\n"
        f"Domain: {jd_profile.get('domain', '')}"
    )


def _format_responsibilities(roles: list[dict], projects: list[dict]) -> str:
    parts = []
    for r in roles:
        resp = r.get("base_responsibilities", [])
        if resp:
            parts.append(
                f"At {r.get('company_name', '')}: " + "; ".join(resp[:5])
            )
    # Add project context
    for p in projects[:2]:
        parts.append(
            f"Key project: {p.get('title', '')} — {p.get('description', '')[:200]}"
        )
    return "\n".join(parts) if parts else "(use JD to infer responsibilities)"


def _clean_output(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
