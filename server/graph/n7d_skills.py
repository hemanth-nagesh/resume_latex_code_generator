r"""N7d — Skills Generator (Gemini Call 5).

Generates the TECHNICAL SKILLS section as \textbf{Category}{: skills} blocks.
Uses the pre-ordered skill list from N6, grouped by category. Gemini's role
is minimal here — mostly assembling the pre-ranked skills into the required format.

The master template wraps this in an itemize environment — Gemini must only emit
the skill blocks as plain text/calls inside the template's \item{{}} wrapper.

Temperature: 0.1 for deterministic output.
Runs in parallel with N7a, N7b, N7c.
"""

from __future__ import annotations

import logging

from server.graph.state import ResumeState
from server.services.gemini import GeminiClient

_logger = logging.getLogger(__name__)

SKILLS_PROMPT = """You are a resume formatter. Assemble the technical skills section
using ONLY the format shown below. Do NOT create new skills — use only what is provided.

---

SELECTED SKILLS (ordered by relevance, grouped by category):
{skill_groups}

JOB DESCRIPTION CONTEXT:
{jd_context}

---

OUTPUT FORMAT (follow this EXACTLY — no deviations):

\\textbf{{Programming Languages}}{{: Python, JavaScript, TypeScript, Java, SQL}} \\\\ \\vspace{{2pt}}
\\textbf{{Frameworks \& Libraries}}{{: FastAPI, React, Node.js, NumPy, TensorFlow}} \\\\ \\vspace{{2pt}}
\\textbf{{Databases \& Storage}}{{: PostgreSQL, MongoDB, Redis, Pinecone}} \\\\ \\vspace{{2pt}}
\\textbf{{Cloud \& DevOps}}{{: Docker, Kubernetes, Azure, AWS, CI/CD}} \\\\ \\vspace{{2pt}}
\\textbf{{Tools \& Platforms}}{{: Git, Linux, VS Code, Jupyter, MLflow}} \\\\ \\vspace{{2pt}}

---

CRITICAL RULES:

1. Each line is: \\textbf{{Category Name}}{{: skill1, skill2, skill3, ...}} \\\\ \\vspace{{2pt}}
2. NEVER emit \\begin{{}}, \\end{{}}, \\section{{}}, or any structural commands
3. NEVER emit \\item — the template already wraps skills in an \\item{{}} block
4. Use ONLY the skills provided — never invent new ones
5. Use ONLY the categories provided — never create new categories
6. Skills within a category must be separated by commas
7. At most 8 skills per category (drop lowest-proficiency if needed)
8. Categories should appear in the order given — most relevant first
9. Never use % as a comment character — it breaks LaTeX
10. NEVER escape regular characters in the output
11. CRITICAL: If a category name contains "&", you MUST escape it as "\\&"
    Example: "Frameworks \\& Libraries" NOT "Frameworks & Libraries"
    Example: "Gen AI \\& Agentic AI" NOT "Gen AI & Agentic AI"
12. ALWAYS use \\& instead of raw & in ANY text content

Return ONLY the formatted \\textbf{{}} lines, no markdown fences, no explanations."""


async def run(state: ResumeState, *, gemini: GeminiClient) -> ResumeState:
    ordered_skills = state.get("selected_skills_ordered", [])
    jd_profile = state.get("jd_profile", {})

    _logger.info("N7d: Formatting %d skills", len(ordered_skills))

    # Group by category
    skill_groups = _group_by_category(ordered_skills)
    jd_context = _format_jd_context(jd_profile)

    prompt = SKILLS_PROMPT.format(
        skill_groups=skill_groups,
        jd_context=jd_context,
    )

    raw = await gemini.generate(
        prompt,
        temperature=0.1,
        expect_json=False,
        max_retries=1,
    )

    skills_latex = _clean_output(raw)

    _logger.info(
        "N7d skills generated: %d chars, %d categories",
        len(skills_latex),
        skills_latex.count("\\textbf{"),
    )

    return ResumeState(
        sections_output=[{"section": "skills", "content": skills_latex}],
    )


def _group_by_category(ordered_skills: list[dict]) -> str:
    """Group skills by category, keeping N6's priority order."""
    by_cat: dict[str, list[str]] = {}
    cat_order: list[str] = []

    for sk in ordered_skills:
        cat = sk.get("category", "Other")
        name = sk.get("display_name", sk.get("name", ""))
        if cat not in by_cat:
            by_cat[cat] = []
            cat_order.append(cat)
        if name and name not in by_cat[cat]:
            by_cat[cat].append(name)

    parts = []
    for cat in cat_order:
        skills = by_cat[cat][:8]  # max 8 per category
        parts.append(f"  {cat}: {', '.join(skills)}")

    return "\n".join(parts)


def _format_jd_context(jd_profile: dict) -> str:
    required = ", ".join(
        s["skill"] for s in jd_profile.get("required_skills", [])[:8]
    )
    return f"Required skills: {required}\nDomain: {jd_profile.get('domain', '')}"


def _clean_output(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        text = text[newline + 1:] if newline != -1 else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
