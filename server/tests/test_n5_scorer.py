"""Property tests for N5 — Project Scorer graceful degradation (Bug 7 fix).

Property 9: N5 degrades on empty projects, still guards missing JD profile
**Validates: Requirements 7.1, 7.2, 7.3**

- For any falsy `jd_profile` (missing key, explicit `{}`, or explicit `None`),
  combined with ANY `kg_snapshot` content, `n5_scorer.run` raises `ValueError`
  mentioning "No JD profile".
- For a truthy `jd_profile` combined with an empty `kg_snapshot["projects"]`
  (either `[]` explicitly or the "projects" key missing entirely),
  `n5_scorer.run` returns `ranked_projects=[]`, appends a warning mentioning
  "No projects available", and does not raise.
- For a truthy `jd_profile` with a non-empty `kg_snapshot["projects"]` list,
  scoring runs normally and matches a direct call to `rank_projects`.

No Gemini/DB calls — `n5_scorer.run` is a pure async function over `state`.
"""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import given, settings, strategies as st

from server.graph import n5_scorer
from server.services.scoring import rank_projects


def _run(state: dict) -> dict:
    """Synchronously drive the async `n5_scorer.run` coroutine."""
    return asyncio.run(n5_scorer.run(state))


# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# The three ways a falsy jd_profile can show up in state, per the bug report
# and the .get("jd_profile", {}) defaulting behavior in n5_scorer.run.
_JD_PROFILE_FALSY_VARIANTS = st.sampled_from(["omit_key", "explicit_empty_dict", "explicit_none"])

_SKILL_NAMES = ["Python", "FastAPI", "Docker", "Java", "React", "SQL", "Kubernetes"]

_project_strategy = st.builds(
    lambda id_, title, skills: {
        "id": id_,
        "title": title,
        "skills": skills,
        "tech_stack": skills,
        "tags": [],
        "status": "completed",
        "end_date": None,
    },
    id_=st.uuids().map(str),
    title=st.text(min_size=1, max_size=20),
    skills=st.lists(st.sampled_from(_SKILL_NAMES), min_size=0, max_size=4, unique=True),
)

# Arbitrary kg_snapshot shapes that must NOT change the "raise on falsy
# jd_profile" outcome: missing entirely, empty dict, empty projects, or
# non-empty projects.
_kg_snapshot_variant = st.one_of(
    st.none(),  # kg_snapshot key omitted from state
    st.just({}),
    st.just({"projects": []}),
    st.builds(lambda projects: {"projects": projects}, projects=st.lists(_project_strategy, min_size=1, max_size=3)),
)

_skill_dict_strategy = st.fixed_dictionaries(
    {
        "skill": st.sampled_from(_SKILL_NAMES),
        "is_technical": st.booleans(),
    }
)

# A truthy jd_profile is any non-empty dict — required_skills/preferred_skills
# may themselves be empty lists, the dict as a whole is still truthy.
_truthy_jd_profile = st.fixed_dictionaries(
    {
        "required_skills": st.lists(_skill_dict_strategy, max_size=3),
        "preferred_skills": st.lists(_skill_dict_strategy, max_size=3),
    }
)


def _build_state(jd_variant: str, kg_snapshot: dict | None) -> dict:
    state: dict = {}
    if jd_variant == "explicit_empty_dict":
        state["jd_profile"] = {}
    elif jd_variant == "explicit_none":
        state["jd_profile"] = None
    # "omit_key": leave state without a "jd_profile" key at all.

    if kg_snapshot is not None:
        state["kg_snapshot"] = kg_snapshot
    return state


# ---------------------------------------------------------------------------
# Property: falsy jd_profile always raises, regardless of kg_snapshot content
# ---------------------------------------------------------------------------


class TestMissingJDProfileAlwaysRaises:
    @given(jd_variant=_JD_PROFILE_FALSY_VARIANTS, kg_snapshot=_kg_snapshot_variant)
    @settings(max_examples=100)
    def test_falsy_jd_profile_raises_regardless_of_kg_snapshot(self, jd_variant, kg_snapshot):
        state = _build_state(jd_variant, kg_snapshot)

        with pytest.raises(ValueError, match="No JD profile"):
            _run(state)


# ---------------------------------------------------------------------------
# Property: truthy jd_profile + empty projects -> no raise, empty ranked
# list, warning present
# ---------------------------------------------------------------------------


class TestEmptyProjectsDegradesGracefully:
    @given(
        jd_profile=_truthy_jd_profile,
        projects_variant=st.sampled_from(["missing_key", "explicit_empty_list"]),
    )
    @settings(max_examples=100)
    def test_empty_projects_returns_empty_ranked_with_warning_and_no_raise(
        self, jd_profile, projects_variant
    ):
        kg_snapshot = {} if projects_variant == "missing_key" else {"projects": []}
        state = {"jd_profile": jd_profile, "kg_snapshot": kg_snapshot}

        result = _run(state)  # must not raise

        assert result["ranked_projects"] == []
        assert any("No projects available" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Property: truthy jd_profile + non-empty projects -> scoring runs normally
# ---------------------------------------------------------------------------


class TestNonEmptyProjectsScoresNormally:
    @given(
        jd_profile=_truthy_jd_profile,
        projects=st.lists(_project_strategy, min_size=1, max_size=5),
    )
    @settings(max_examples=100)
    def test_scoring_runs_and_matches_direct_rank_projects_call(self, jd_profile, projects):
        kg_snapshot = {"projects": projects, "skills": []}
        state = {"jd_profile": jd_profile, "kg_snapshot": kg_snapshot}

        result = _run(state)

        skill_index: dict[str, dict] = {}
        for s in kg_snapshot.get("skills", []):
            name = s.get("name", "").lower()
            if name:
                skill_index[name] = s

        expected = [r.model_dump() for r in rank_projects(projects, jd_profile, skill_index)]

        assert result["ranked_projects"] == expected
        assert len(result["ranked_projects"]) == len(projects)


# ---------------------------------------------------------------------------
# Concrete example-based tests matching the exact bug report scenarios
# ---------------------------------------------------------------------------
#
# The property tests above already cover these cases exhaustively via
# Hypothesis. These concrete examples exist purely as readable documentation
# of the exact bug-report scenarios that motivated the Bug 7 fix.


class TestConcreteScenarios:
    def test_missing_jd_profile_key_still_raises_even_with_projects_present(self):
        """Bug report scenario: kg_snapshot has projects but jd_profile is
        entirely absent from state — N5 must still raise (this guard must
        not regress while fixing the overly-strict empty-projects case)."""
        state = {
            "kg_snapshot": {
                "projects": [
                    {
                        "id": "p1",
                        "title": "Internal Tooling Dashboard",
                        "skills": ["Python", "FastAPI"],
                        "tech_stack": ["Python", "FastAPI"],
                        "tags": [],
                        "status": "completed",
                        "end_date": "2023-06-01",
                    }
                ]
            }
        }

        with pytest.raises(ValueError, match="No JD profile"):
            _run(state)

    def test_empty_projects_with_jd_profile_returns_empty_ranked_list_no_raise(self):
        """Bug report scenario: a real JD profile is present but the
        knowledge graph has no projects (e.g. DB outage upstream in N4) —
        N5 must degrade gracefully instead of raising."""
        jd_profile = {
            "required_skills": [
                {"skill": "Python", "is_technical": True},
                {"skill": "Docker", "is_technical": True},
            ],
            "preferred_skills": [{"skill": "Kubernetes", "is_technical": True}],
            "ats_keywords": ["backend", "cloud"],
            "domain": "Backend Engineering",
            "industry": "SaaS",
        }
        state = {"jd_profile": jd_profile, "kg_snapshot": {"projects": []}}

        result = _run(state)

        assert result["ranked_projects"] == []
        assert (
            "No projects available for scoring — resume will omit project-based content."
            in result["warnings"]
        )

    def test_non_empty_projects_with_jd_profile_scores_and_ranks(self):
        """Sanity check that the non-error path still actually scores
        projects — a realistic JD profile against one matching and one
        non-matching project should produce a positive top score."""
        jd_profile = {
            "required_skills": [
                {"skill": "Python", "is_technical": True},
                {"skill": "FastAPI", "is_technical": True},
            ],
            "preferred_skills": [{"skill": "Docker", "is_technical": True}],
            "ats_keywords": ["api", "backend"],
            "domain": "Backend Engineering",
            "industry": "SaaS",
        }
        kg_snapshot = {
            "projects": [
                {
                    "id": "p1",
                    "title": "Resume Generation API",
                    "description": "Built a backend API for generating resumes",
                    "skills": ["Python", "FastAPI", "Docker"],
                    "tech_stack": ["Python", "FastAPI", "Docker"],
                    "tags": ["api", "backend"],
                    "status": "completed",
                    "end_date": "2024-01-01",
                },
                {
                    "id": "p2",
                    "title": "Marketing Landing Page",
                    "description": "A static marketing site",
                    "skills": ["HTML", "CSS"],
                    "tech_stack": ["HTML", "CSS"],
                    "tags": [],
                    "status": "completed",
                    "end_date": "2019-01-01",
                },
            ],
            "skills": [],
        }
        state = {"jd_profile": jd_profile, "kg_snapshot": kg_snapshot}

        result = _run(state)

        assert len(result["ranked_projects"]) == 2
        top = result["ranked_projects"][0]
        assert top["project_id"] == "p1"
        assert isinstance(top["score"], float)
        assert top["score"] > 0.0
