"""N5 — Project Scorer.

Scores all projects in the knowledge graph against the parsed JD profile
using the multi-factor scoring engine (services/scoring.py).

Reads:
  - state["kg_snapshot"]["projects"]  — all active projects with skills
  - state["jd_profile"]               — parsed required/preferred skills

Writes:
  - state["ranked_projects"]          — list[ScoredProject] sorted by score desc

Runs after both N3 (JD analysis) and N4 (KG loader) complete — this is the
fan-in point in the DAG.
"""

from __future__ import annotations

import logging

from server.graph.state import ResumeState
from server.services.scoring import rank_projects

_logger = logging.getLogger(__name__)


async def run(state: ResumeState) -> ResumeState:
    jd_profile = state.get("jd_profile", {})
    kg = state.get("kg_snapshot", {})
    projects = kg.get("projects", [])
    skills = kg.get("skills", [])

    if not projects:
        raise ValueError("No projects found in knowledge graph — check N4 loader")

    if not jd_profile:
        raise ValueError("No JD profile available — check N3 analyzer")

    # Build skill index (name → skill dict) for primary skill resolution
    skill_index: dict[str, dict] = {}
    for s in skills:
        name = s.get("name", "").lower()
        if name:
            skill_index[name] = s

    ranked = rank_projects(projects, jd_profile, skill_index)

    return ResumeState(
        ranked_projects=[r.model_dump() for r in ranked],
    )
