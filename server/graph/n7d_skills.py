r"""N7d — Skills Generator (deterministic, no LLM call).

Generates the TECHNICAL SKILLS section as \textbf{Category}{: skills} blocks.

The skills section is pure formatting — no content generation needed. Using
Gemini for this was unreliable (it dropped skills, mimicked empty example
categories, and invented categorizations). This module classifies skills
into standard resume categories via keyword matching and formats them
directly as LaTeX.

The master template wraps this in an itemize environment — this module
only emits the \textbf{} blocks inside the template's \item{} wrapper.

Runs in parallel with N7a, N7b, N7c.
"""

from __future__ import annotations

import logging

from server.graph.state import ResumeState

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill classifier — maps skill names to resume display categories.
#
# Order matters: categories are checked in this order, and the first match
# wins. More specific categories (Gen AI, Databases) are checked before
# generic ones (Programming Languages) so "LangGraph" doesn't accidentally
# land in "Frameworks" when it belongs in "Gen AI & Agentic AI".
# ---------------------------------------------------------------------------

_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    (
        "Gen AI & Agentic AI",
        [
            "langchain", "langgraph", "llamaindex", "rag", "retrieval",
            "prompt", "llm", "multimodal", "react pattern", "mcp",
            "agent", "agentic", "fine-tuning", "fine tuning", "finetuning",
            "embedding", "vector", "pinecone", "chroma", "pgvector",
            "openai", "gemini", "mistral", "huggingface", "transformers",
            "langfuse", "llmops", "llm-as-judge", "llm as judge",
        ],
    ),
    (
        "Databases & Storage",
        [
            "sql", "postgres", "postgresql", "mysql", "mongo", "mongodb",
            "redis", "database", "databases", "supabase", "firebase",
            "dynamodb", "cassandra", "elasticsearch", "sqlite", "oracle",
            "vector database", "time-series", "timeseries", "memcached",
            "prisma", "orm", "sqlalchemy",
        ],
    ),
    (
        "Cloud & DevOps",
        [
            "aws", "azure", "gcp", "google cloud", "docker", "kubernetes",
            "k8s", "ci/cd", "cicd", "jenkins", "gitlab", "github actions",
            "terraform", "ansible", "cloud", "serverless", "lambda",
            "app services", "ecs", "eks", "aks", "s3", "ec2", "northflank",
            "vercel", "netlify", "nginx", "microservices",
        ],
    ),
    (
        "AI/ML & Data Science",
        [
            "pytorch", "tensorflow", "scikit", "sklearn", "pandas", "numpy",
            "matplotlib", "seaborn", "jupyter", "ml", "machine learning",
            "deep learning", "cnn", "rnn", "gan", "regression", "classification",
            "clustering", "hyperparameter", "feature engineering", "data preprocessing",
            "opencv", "computer vision", "nlp", "ocr", "tensorflow",
            "data processing", "data", "inference", "model", "neural",
        ],
    ),
    (
        "Frameworks & Libraries",
        [
            "fastapi", "flask", "django", "react", "vue", "angular", "node",
            "express", "next", "nuxt", "spring", "rails", "graphql",
            "rest", "api", "websocket", "asyncio", "celery", "rabbitmq",
            "kafka", "temporal", "grpc", "uvicorn", "gunicorn",
        ],
    ),
    (
        "Programming Languages",
        [
            "python", "javascript", "typescript", "java", "c++", "c#",
            "go", "rust", "ruby", "php", "swift", "kotlin", "scala",
            "r ", "r lang", "bash", "shell", "powershell", "sql",
        ],
    ),
    (
        "Tools & Platforms",
        [
            "git", "github", "gitlab", "linux", "unix", "vs code",
            "vscode", "postman", "swagger", "jira", "confluence",
            "docker", "kubernetes", "devops", "agile", "scrum",
        ],
    ),
]


def _classify_skill(skill_name: str) -> str:
    """Classify a skill into a resume display category via keyword matching.

    Falls back to 'Tools & Platforms' if no rule matches.
    """
    lower = skill_name.lower().strip()

    for category, keywords in _CATEGORY_RULES:
        for kw in keywords:
            if kw in lower:
                return category

    return "Tools & Platforms"


# ---------------------------------------------------------------------------
# Category display order — most relevant/impactful first for a resume.
# ---------------------------------------------------------------------------

_CATEGORY_ORDER: list[str] = [
    "Programming Languages",
    "Frameworks & Libraries",
    "AI/ML & Data Science",
    "Gen AI & Agentic AI",
    "Databases & Storage",
    "Cloud & DevOps",
    "Tools & Platforms",
]

_MAX_SKILLS_PER_CATEGORY = 10


async def run(state: ResumeState) -> ResumeState:
    ordered_skills = state.get("selected_skills_ordered", [])
    jd_profile = state.get("jd_profile", {})
    kg = state.get("kg_snapshot", {})

    _logger.info("N7d: Formatting %d skills", len(ordered_skills))

    # If N6 didn't provide ordered skills (e.g. empty KG), fall back to
    # all skills in the knowledge graph, prioritized by JD required skills.
    if not ordered_skills:
        ordered_skills = _fallback_from_kg(kg, jd_profile)
        _logger.info("N7d: Using %d skills from KG fallback", len(ordered_skills))

    # Also ensure JD-required skills are included even if not covered by projects
    required_from_jd = _extract_required_from_jd(jd_profile, kg)
    all_skills = _merge_skills(ordered_skills, required_from_jd)

    # Classify into categories
    categorized: dict[str, list[str]] = {cat: [] for cat in _CATEGORY_ORDER}
    seen: set[str] = set()

    for sk in all_skills:
        name = sk.get("display_name") or sk.get("name", "")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())

        category = _classify_skill(name)
        if category not in categorized:
            categorized[category] = []
        categorized[category].append(name)

    # Build LaTeX lines — only non-empty categories, in display order
    lines: list[str] = []
    for category in _CATEGORY_ORDER:
        skills = categorized.get(category, [])
        if not skills:
            continue
        # Cap at max per category, preserving priority order
        skills = skills[:_MAX_SKILLS_PER_CATEGORY]
        # Escape & in category names for LaTeX (e.g. "Frameworks & Libraries")
        safe_cat = category.replace(" & ", r" \& ")
        lines.append(
            rf"\textbf{{{safe_cat}}}{{: {', '.join(skills)}}} \\ \vspace{{2pt}}"
        )

    skills_latex = "\n".join(lines)

    _logger.info(
        "N7d skills generated: %d chars, %d categories, %d total skills",
        len(skills_latex),
        len(lines),
        sum(len(v) for v in categorized.values()),
    )

    return ResumeState(
        sections_output=[{"section": "skills", "content": skills_latex}],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fallback_from_kg(kg: dict, jd_profile: dict) -> list[dict]:
    """When N6 produced no ordered skills, use all KG skills."""
    skills = kg.get("skills", [])
    if not skills:
        return []

    required_names = [
        s.get("skill", "").lower()
        for s in jd_profile.get("required_skills", [])
    ]

    def sort_key(sk: dict) -> tuple[int, int]:
        name = sk.get("name", "").lower()
        is_required = 1 if any(r in name or name in r for r in required_names) else 0
        proficiency = sk.get("proficiency", 3)
        return (-is_required, -proficiency)

    return sorted(skills, key=sort_key)


def _extract_required_from_jd(jd_profile: dict, kg: dict) -> list[dict]:
    """Extract JD-required skills that exist in the KG, so the skills
    section always includes the keywords the ATS is scanning for."""
    required = jd_profile.get("required_skills", [])
    kg_skills = kg.get("skills", [])

    kg_names_lower = {sk.get("name", "").lower(): sk for sk in kg_skills}

    result: list[dict] = []
    for req in required:
        req_name = req.get("skill", "")
        req_lower = req_name.lower()
        # Check if this required skill exists in KG
        for kg_lower, kg_skill in kg_names_lower.items():
            if req_lower in kg_lower or kg_lower in req_lower:
                result.append(kg_skill)
                break
        else:
            # Not in KG — add as a plain skill entry so it appears
            result.append({"display_name": req_name, "name": req_lower})

    return result


def _merge_skills(
    ordered: list[dict], required: list[dict]
) -> list[dict]:
    """Merge ordered skills with JD-required skills, deduplicating by name.

    Ordered skills (from N6) come first — they're priority-ranked.
    JD-required skills that aren't already in the list are appended.
    """
    seen: set[str] = set()
    merged: list[dict] = []

    for sk in ordered:
        name = (sk.get("display_name") or sk.get("name", "")).lower()
        if name and name not in seen:
            seen.add(name)
            merged.append(sk)

    for sk in required:
        name = (sk.get("display_name") or sk.get("name", "")).lower()
        if name and name not in seen:
            seen.add(name)
            merged.append(sk)

    return merged
