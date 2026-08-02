"""N6 — Content Selector.

Passes all ranked projects through (no filtering), selects matching roles,
and orders skills for display.

Reads:
  - state["ranked_projects"]     — scored projects from N5
  - state["kg_snapshot"]["roles"]— all roles from N4
  - state["kg_snapshot"]["skills"] — all skills from N4
  - state["jd_profile"]          — required/preferred skills

Writes:
  - state["selected_projects"]   — list[SelectedProject] for N7c (ALL projects)
  - state["selected_roles"]      — list of role dicts for N7b
  - state["covered_skills"]      — skill names covered by selected projects
  - state["uncovered_skills"]    — required skills not covered
  - state["selected_skills_ordered"] — skills pre-ordered for N7d
"""

from __future__ import annotations

import logging

from server.graph.state import ResumeState
from server.services.scoring import (
    select_roles,
    order_skills_for_display,
)
from server.services.types import SelectedProject

_logger = logging.getLogger(__name__)


async def run(state: ResumeState) -> ResumeState:
    ranked_raw = state.get("ranked_projects", [])
    jd_profile = state.get("jd_profile", {})
    kg = state.get("kg_snapshot", {})
    skills = kg.get("skills", [])
    roles = kg.get("roles", [])

    from server.services.types import ScoredProject
    ranked = [ScoredProject(**r) for r in ranked_raw]

    # Pass ALL ranked projects — no filtering
    result = [
        SelectedProject(
            project_id=sp.project_id,
            title=sp.title,
            score=sp.score,
            matched_skills=sp.matched_skills,
            covered_skill_count=sp.covered_skill_count,
        )
        for sp in ranked
    ]

    # Build covered/uncovered from all projects
    covered = list(dict.fromkeys(
        skill for sp in ranked for skill in sp.matched_skills
    ))
    required_skills = jd_profile.get("required_skills", [])
    required_names = {s.get("skill", "").lower() for s in required_skills}
    covered_lower = {s.lower() for s in covered}
    uncovered = [s for s in required_names if s not in covered_lower]

    # Select matching roles
    matched_roles = select_roles(result, roles)

    # Pre-order skills for N7d
    all_covered = list(dict.fromkeys(
        skill for sp in result for skill in sp.matched_skills
    ))
    ordered_skills = order_skills_for_display(all_covered, jd_profile, skills)

    _logger.info("N6: %d projects, %d roles, %d covered skills, %d uncovered",
                  len(result), len(matched_roles), len(covered), len(uncovered))

    return ResumeState(
        selected_projects=[r.model_dump() for r in result],
        selected_roles=matched_roles,
        covered_skills=covered,
        uncovered_skills=uncovered,
        selected_skills_ordered=ordered_skills,
    )
