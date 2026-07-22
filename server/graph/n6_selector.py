"""N6 — Content Selector (greedy set-cover).

Selects the minimum number of projects that cover the maximum set of
required skills. Then picks matching roles and orders skills for display.

Reads:
  - state["ranked_projects"]     — scored projects from N5
  - state["kg_snapshot"]["roles"]— all roles from N4
  - state["kg_snapshot"]["skills"] — all skills from N4
  - state["jd_profile"]          — required/preferred skills
  - state["sections"]            — user section config (max_projects)

Writes:
  - state["selected_projects"]   — list[SelectedProject] for N7c
  - state["selected_roles"]      — list of role dicts for N7b
  - state["covered_skills"]      — skill names covered by selected projects
  - state["uncovered_skills"]    — required skills not covered
  - state["selected_skills_ordered"] — skills pre-ordered for N7d
"""

from __future__ import annotations

import logging

from server.graph.state import ResumeState
from server.services.scoring import (
    select_projects_greedy_set_cover,
    select_roles,
    order_skills_for_display,
)
from server.services.types import SelectedProject

_logger = logging.getLogger(__name__)

DEFAULT_MAX_PROJECTS = 3


async def run(state: ResumeState) -> ResumeState:
    ranked_raw = state.get("ranked_projects", [])
    jd_profile = state.get("jd_profile", {})
    kg = state.get("kg_snapshot", {})
    skills = kg.get("skills", [])
    roles = kg.get("roles", [])

    # Determine max projects from section config
    max_projects = _get_max_projects(state)

    # Deserialize ranked projects
    from server.services.types import ScoredProject
    ranked = [ScoredProject(**r) for r in ranked_raw]

    selected, covered, uncovered = select_projects_greedy_set_cover(
        ranked, jd_profile, max_projects,
    )

    # If greedy set-cover didn't fill max, add highest-scored remaining
    remaining = [r for r in ranked if r not in selected]
    while len(selected) < max_projects and remaining:
        selected.append(remaining[0])
        remaining = remaining[1:]

    # Convert to SelectedProject
    result = [
        SelectedProject(
            project_id=sp.project_id,
            title=sp.title,
            score=sp.score,
            matched_skills=sp.matched_skills,
            covered_skill_count=sp.covered_skill_count,
        )
        for sp in selected
    ]

    # Select matching roles
    matched_roles = select_roles(result, roles)

    # Pre-order skills for N7d
    all_covered = sorted(
        set(skill for sp in result for skill in sp.matched_skills)
    )
    ordered_skills = order_skills_for_display(all_covered, jd_profile, skills)

    return ResumeState(
        selected_projects=[r.model_dump() for r in result],
        selected_roles=matched_roles,
        covered_skills=covered,
        uncovered_skills=uncovered,
        selected_skills_ordered=ordered_skills,
    )


def _get_max_projects(state: ResumeState) -> int:
    """Extract max_projects from section config."""
    sections = state.get("sections", [])
    for s in sections:
        if isinstance(s, dict):
            name = s.get("name", "")
        else:
            name = s.name
        if name == "projects":
            if isinstance(s, dict):
                val = s.get("max_count")
            else:
                val = s.max_count
            if val is not None and val > 0:
                return val
    return DEFAULT_MAX_PROJECTS
