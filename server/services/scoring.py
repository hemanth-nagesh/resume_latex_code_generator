"""Multi-factor project scoring against a JD profile.

Pure functions — no side effects, no database access, fully unit-testable.
Weighted scoring:
  60% skill match  — required skills covered by project, primary skills weighted higher
  25% keyword match — ats_keywords + domain terms in project description/tags/stack
  15% recency       — how recently the project was completed

All weights are constants at module level for transparency.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

from server.services.types import ScoredProject

# ---------------------------------------------------------------------------
# Weights (must sum to 1.0)
# ---------------------------------------------------------------------------
SKILL_WEIGHT = 0.60
KEYWORD_WEIGHT = 0.25
RECENCY_WEIGHT = 0.15

assert abs(SKILL_WEIGHT + KEYWORD_WEIGHT + RECENCY_WEIGHT - 1.0) < 0.001


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_project(
    project: dict[str, Any],
    jd_profile: dict[str, Any],
    skill_index: dict[str, dict[str, Any]] | None = None,
) -> ScoredProject:
    """Score a single project against a JD profile.

    Args:
        project: Project dict from kg_snapshot with keys:
            id, title, description, tech_stack, tags, skills, primary_skill_ids,
            start_date, end_date, status
        jd_profile: Parsed JD profile with keys:
            required_skills, preferred_skills, ats_keywords, domain, industry
        skill_index: Optional lookup dict skill_name → {id, display_name, category}
            for resolving primary_skill_ids to names.

    Returns:
        ScoredProject with score 0.0–100.0 and matched skill names.
    """
    skill_score, matched_skills = _score_skills(project, jd_profile, skill_index)
    keyword_score = _score_keywords(project, jd_profile)
    recency_score = _score_recency(project)

    raw = (
        skill_score * SKILL_WEIGHT
        + keyword_score * KEYWORD_WEIGHT
        + recency_score * RECENCY_WEIGHT
    )

    return ScoredProject(
        project_id=str(project["id"]),
        title=project["title"],
        score=round(raw * 100.0, 2),
        matched_skills=matched_skills,
        covered_skill_count=len(matched_skills),
    )


def rank_projects(
    projects: list[dict[str, Any]],
    jd_profile: dict[str, Any],
    skill_index: dict[str, dict[str, Any]] | None = None,
) -> list[ScoredProject]:
    """Score and rank all projects. Highest score first."""
    scored = [
        score_project(p, jd_profile, skill_index)
        for p in projects
    ]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored


def select_projects_greedy_set_cover(
    ranked: list[ScoredProject],
    jd_profile: dict[str, Any],
    max_projects: int = 3,
) -> tuple[list[ScoredProject], list[str], list[str]]:
    """Greedy set-cover: minimum projects covering maximum required skills.

    At each iteration, pick the project that covers the most *currently uncovered*
    required skills. Stop when all required skills are covered or max_projects
    is reached.

    Args:
        ranked: Projects sorted by score (highest first).
        jd_profile: JD profile with required_skills and preferred_skills.
        max_projects: Maximum projects to select.

    Returns:
        (selected, covered_skills, uncovered_skills)
    """
    all_required = {
        s["skill"].lower() for s in jd_profile.get("required_skills", [])
        if s.get("is_technical")
    }
    if not all_required:
        all_required = {
            s["skill"].lower() for s in jd_profile.get("required_skills", [])
        }

    remaining = set(all_required)
    selected: list[ScoredProject] = []

    working = list(ranked)

    while remaining and len(selected) < max_projects:
        best: ScoredProject | None = None
        best_new = 0

        for sp in working:
            new_skills = {s.lower() for s in sp.matched_skills} & remaining
            count = len(new_skills)
            if count > best_new:
                best_new = count
                best = sp
            elif count == best_new and best is not None and sp.score > best.score:
                best = sp

        if best is None or best_new == 0:
            break

        selected.append(best)
        remaining -= {s.lower() for s in best.matched_skills}
        working.remove(best)

    covered = sorted(all_required - remaining)
    uncovered = sorted(remaining)

    return selected, covered, uncovered


def select_roles(
    selected_projects: list[ScoredProject],
    roles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select roles that own any of the selected projects.

    A role matches if its project_ids list contains any selected project's id.
    """
    selected_ids = {sp.project_id for sp in selected_projects}
    matched = [
        r for r in roles
        if set(r.get("project_ids") or []) & selected_ids
    ]
    matched.sort(
        key=lambda r: (r.get("end_date") or "9999-12-31"),
        reverse=True,
    )
    if not matched:
        # Fallback: use most recent active role
        matched = [roles[0]] if roles else []
    return matched


def order_skills_for_display(
    covered_skills: list[str],
    jd_profile: dict[str, Any],
    kg_skills: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Order skills for the skills section: required first, then preferred,
    grouped by category.

    Returns:
        List of skill dicts with display_name and category, ordered for
        consumption by N7d.
    """
    required_names = [s["skill"] for s in jd_profile.get("required_skills", [])]
    preferred_names = [s["skill"] for s in jd_profile.get("preferred_skills", [])]

    def resolve_kg_skill(covered_name: str) -> dict[str, Any] | None:
        for kg_skill in kg_skills:
            if _skill_matches(covered_name, kg_skill["name"]):
                return kg_skill
        return None

    def is_in(covered_name: str, name_list: list[str]) -> bool:
        return any(_skill_matches(covered_name, n) for n in name_list)

    ordered: list[dict[str, Any]] = []

    # Tier 1: required + covered
    for name in covered_skills:
        if is_in(name, required_names) and resolve_kg_skill(name) is not None:
            ordered.append(resolve_kg_skill(name))  # type: ignore[arg-type]

    # Tier 2: preferred + covered (not already required)
    for name in covered_skills:
        if (
            is_in(name, preferred_names)
            and not is_in(name, required_names)
            and resolve_kg_skill(name) is not None
        ):
            ordered.append(resolve_kg_skill(name))  # type: ignore[arg-type]

    # Tier 3: other covered skills
    for name in covered_skills:
        if (
            not is_in(name, required_names)
            and not is_in(name, preferred_names)
            and resolve_kg_skill(name) is not None
        ):
            ordered.append(resolve_kg_skill(name))  # type: ignore[arg-type]

    # Group by category
    by_category: dict[str, list[dict[str, Any]]] = {}
    for sk in ordered:
        cat = sk.get("category", "Other")
        by_category.setdefault(cat, []).append(sk)

    # Required → Preferred → Other, with most populated categories first
    result: list[dict[str, Any]] = []
    priority_categories = []
    other_categories = []

    for cat, skills_list in by_category.items():
        is_priority = any(
            is_in(s["name"], required_names) for s in skills_list
        )
        if is_priority:
            priority_categories.append((cat, skills_list))
        else:
            other_categories.append((cat, skills_list))

    priority_categories.sort(key=lambda x: len(x[1]), reverse=True)
    other_categories.sort(key=lambda x: len(x[1]), reverse=True)

    for _, skills_list in priority_categories + other_categories:
        result.extend(skills_list)

    return result


# ---------------------------------------------------------------------------
# Scoring sub-functions
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.-]*[a-z0-9]")


def _normalize(text: str) -> str:
    return text.lower().strip()


def _tokenize(text: str) -> set[str]:
    """Extract meaningful tokens from text."""
    return set(_WORD_RE.findall(_normalize(text)))


def _skill_matches(project_skill: str, target_skill: str) -> bool:
    """Check if a project skill matches a required/preferred skill.

    Uses multi-level matching: exact, substring, token overlap.
    """
    ps = _normalize(project_skill)
    ts = _normalize(target_skill)

    if ps == ts:
        return True
    if ts in ps or ps in ts:
        return True

    ps_tokens = _tokenize(project_skill)
    ts_tokens = _tokenize(target_skill)
    if not ts_tokens:
        return False

    # At least 60% of target tokens appear in project skill
    overlap = len(ts_tokens & ps_tokens)
    return overlap / len(ts_tokens) >= 0.6


def _score_skills(
    project: dict[str, Any],
    jd_profile: dict[str, Any],
    skill_index: dict[str, dict[str, Any]] | None,
) -> tuple[float, list[str]]:
    """Score how many required/preferred skills this project covers.

    Returns (0.0–1.0, list of matched skill names).
    """
    project_skills: list[str] = project.get("skills", []) or []
    primary_ids: list[str] = project.get("primary_skill_ids", []) or []

    # Resolve primary skill IDs to names
    primary_names: set[str] = set()
    if skill_index and primary_ids:
        for pid in primary_ids:
            for name, info in skill_index.items():
                if str(info.get("id", "")) == str(pid):
                    primary_names.add(name)
                    break

    required = jd_profile.get("required_skills", [])
    preferred = jd_profile.get("preferred_skills", [])

    if not required and not preferred:
        return 0.5, []

    matched: list[str] = []
    total_weight = 0.0
    earned_weight = 0.0

    for req in required:
        target = req.get("skill", "")
        is_primary = target in primary_names
        weight = 3.0 if is_primary else 1.0
        total_weight += weight

        for ps in project_skills:
            if _skill_matches(ps, target) and target not in matched:
                matched.append(target)
                earned_weight += weight
                break

    for pref in preferred:
        target = pref.get("skill", "")
        is_primary = target in primary_names
        weight = 1.5 if is_primary else 0.5
        total_weight += weight

        for ps in project_skills:
            if _skill_matches(ps, target) and target not in matched:
                matched.append(target)
                earned_weight += weight
                break

    if total_weight == 0:
        return 0.0, []

    return min(earned_weight / total_weight, 1.0), matched


def _score_keywords(
    project: dict[str, Any],
    jd_profile: dict[str, Any],
) -> float:
    """Score keyword overlap between project content and JD.

    Returns 0.0–1.0.
    """
    keywords = set(_normalize(k) for k in jd_profile.get("ats_keywords", []))
    domain = _normalize(jd_profile.get("domain", ""))
    industry = _normalize(jd_profile.get("industry", ""))

    if domain:
        keywords.update(_tokenize(domain))
    if industry:
        keywords.update(_tokenize(industry))

    if not keywords:
        return 0.5

    project_text = " ".join([
        project.get("title", ""),
        project.get("description", ""),
        *project.get("tech_stack", []),
        *project.get("tags", []),
    ])

    project_tokens = _tokenize(project_text)

    hits = sum(1 for kw in keywords if kw in project_tokens)
    return min(hits / len(keywords), 1.0)


def _score_recency(project: dict[str, Any]) -> float:
    """Score how recent this project is. Returns 0.0–1.0.

    Current/active projects get max score.
    Past projects decay over time.
    """
    status = project.get("status", "").lower()
    if status in ("current", "active", "in-progress", "in_progress"):
        return 1.0

    end_str = project.get("end_date")
    if not end_str:
        return 0.1  # unknown end date → low recency

    try:
        if isinstance(end_str, str):
            end_date = datetime.fromisoformat(end_str).date()
        elif isinstance(end_str, datetime):
            end_date = end_str.date()
        elif isinstance(end_str, date):
            end_date = end_str
        else:
            return 0.1
    except (ValueError, TypeError):
        return 0.1

    today = date.today()
    age_years = (today - end_date).days / 365.0

    if age_years <= 1.0:
        return 1.0
    elif age_years <= 2.0:
        return 0.75
    elif age_years <= 3.0:
        return 0.50
    elif age_years <= 5.0:
        return 0.25
    else:
        return 0.10
