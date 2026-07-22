"""Phase 4 tests — section generators N7a–N7d.

Tests prompt construction, output cleaning, and helper functions.
Gemini calls are not tested here — they require a real API key.
Integration verified via direct scripts with live Gemini.
"""

from __future__ import annotations

import pytest

from server.graph.n7a_summary import (
    _build_background,
    _build_target_context,
    _clean_summary,
)
from server.graph.n7b_experience import (
    _format_roles,
    _format_jd_context,
    _format_responsibilities,
    _clean_output as _clean_exp,
)
from server.graph.n7c_projects import (
    _format_projects,
    _clean_output as _clean_proj,
    _hash_jd_profile,
)
from server.graph.n7d_skills import (
    _group_by_category,
    _clean_output as _clean_skills,
)


# ===========================================================================
# Sample test data
# ===========================================================================

@pytest.fixture
def sample_jd_profile():
    return {
        "required_skills": [
            {"skill": "Python", "is_technical": True, "ats_exact_phrase": "Python"},
            {"skill": "FastAPI", "is_technical": True, "ats_exact_phrase": "FastAPI"},
            {"skill": "Docker", "is_technical": True, "ats_exact_phrase": "Docker"},
        ],
        "preferred_skills": [
            {"skill": "Kubernetes", "is_technical": True},
        ],
        "seniority_level": "senior",
        "domain": "Backend Engineering",
        "industry": "Enterprise SaaS",
        "role_type": "IC",
        "ats_keywords": ["microservices", "API", "scalable"],
        "company_values": ["innovation"],
        "red_flags_to_avoid": ["overtime culture", "legacy maintenance"],
    }


@pytest.fixture
def sample_roles():
    return [
        {
            "id": "r1",
            "company_name": "Tata Consultancy Services",
            "role_title": "AI/ML Engineer",
            "start_date": "2023-12-01",
            "end_date": None,
            "location": "Bangalore, India",
            "employment_type": "full-time",
            "base_responsibilities": [
                "Designed and deployed REST APIs with FastAPI",
                "Built ML pipelines for predictive analytics",
            ],
        }
    ]


@pytest.fixture
def sample_projects():
    return [
        {
            "id": "p1",
            "title": "Backend API Gateway",
            "description": "Built high-availability API gateway serving 1M+ requests/day",
            "tech_stack": ["Python", "FastAPI", "Docker", "PostgreSQL"],
            "skills": ["Python", "FastAPI", "Docker", "PostgreSQL"],
            "start_date": "2024-06-01",
            "end_date": "2025-01-01",
            "status": "completed",
            "impact_metric": "99.9% uptime",
        },
    ]


@pytest.fixture
def sample_ordered_skills():
    return [
        {"id": "1", "name": "Python", "display_name": "Python", "category": "Programming Languages", "proficiency": 5},
        {"id": "2", "name": "FastAPI", "display_name": "FastAPI", "category": "Frameworks", "proficiency": 4},
        {"id": "3", "name": "Docker", "display_name": "Docker", "category": "DevOps", "proficiency": 4},
    ]


# ===========================================================================
# N7a — Summary Generator
# ===========================================================================

class TestN7aSummary:
    def test_background_includes_roles_and_projects(self, sample_roles, sample_projects):
        kg = {"projects": sample_projects, "skills": []}
        bg = _build_background(sample_roles, sample_projects, kg, ["Python", "FastAPI"])
        assert "AI/ML Engineer" in bg
        assert "Tata Consultancy Services" in bg
        assert "Backend API Gateway" in bg
        assert "Python" in bg

    def test_background_no_roles(self, sample_projects):
        kg = {"projects": sample_projects, "skills": []}
        bg = _build_background([], sample_projects, kg, ["Docker"])
        assert "Top matching skills" in bg
        assert "Docker" in bg

    def test_target_context_has_required_fields(self, sample_jd_profile):
        ctx = _build_target_context(sample_jd_profile)
        assert "senior" in ctx
        assert "Backend Engineering" in ctx
        assert "Python" in ctx

    def test_clean_summary_strips_markdown(self):
        assert _clean_summary("```\nThree sentences here.\n```") == "Three sentences here."
        assert _clean_summary("Summary: Some text.") == "Some text."
        assert _clean_summary("  Just text.  ") == "Just text."


# ===========================================================================
# N7b — Experience Generator
# ===========================================================================

class TestN7bExperience:
    def test_format_roles(self, sample_roles):
        result = _format_roles(sample_roles)
        assert "AI/ML Engineer" in result
        assert "Tata Consultancy Services" in result
        assert "Bangalore" in result

    def test_format_roles_empty(self):
        result = _format_roles([])
        assert "no roles" in result.lower()

    def test_format_jd_context(self, sample_jd_profile):
        ctx = _format_jd_context(sample_jd_profile)
        assert "Python" in ctx
        assert "Docker" in ctx
        assert "microservices" in ctx

    def test_format_responsibilities(self, sample_roles, sample_projects):
        result = _format_responsibilities(sample_roles, sample_projects)
        assert "FastAPI" in result
        assert "Backend API Gateway" in result

    def test_clean_output(self):
        assert _clean_exp("```latex\n\\resumeSubheading{...}\n```") == "\\resumeSubheading{...}"
        assert _clean_exp("  \\resumeItem{text}  ") == "\\resumeItem{text}"


# ===========================================================================
# N7c — Projects Generator
# ===========================================================================

class TestN7cProjects:
    def test_format_projects_with_matching_skills(self, sample_projects):
        kg = {"projects": sample_projects}
        selected = [
            {"project_id": "p1", "title": "Backend API Gateway", "score": 80.0,
             "matched_skills": ["Python", "FastAPI"], "covered_skill_count": 2}
        ]
        result = _format_projects(selected, kg, ["Python", "FastAPI"])
        assert "Backend API Gateway" in result
        assert "Python" in result
        assert "FastAPI" in result

    def test_format_projects_active_status(self):
        kg = {
            "projects": [
                {"id": "p1", "title": "Active Project", "description": "...",
                 "tech_stack": ["Python"],
                 "skills": [], "start_date": "2025-01-01", "end_date": None,
                 "status": "active", "impact_metric": ""}
            ]
        }
        selected = [{"project_id": "p1", "title": "Active Project"}]
        result = _format_projects(selected, kg, [])
        assert "Present" in result

    def test_hash_jd_profile_deterministic(self, sample_jd_profile):
        h1 = _hash_jd_profile(sample_jd_profile)
        h2 = _hash_jd_profile(sample_jd_profile)
        assert h1 == h2
        assert len(h1) == 12

    def test_hash_changes_with_different_skills(self):
        a = {"required_skills": [{"skill": "Python", "is_technical": True, "ats_exact_phrase": "Python"}]}
        b = {"required_skills": [{"skill": "Java", "is_technical": True, "ats_exact_phrase": "Java"}]}
        assert _hash_jd_profile(a) != _hash_jd_profile(b)


# ===========================================================================
# N7d — Skills Generator
# ===========================================================================

class TestN7dSkills:
    def test_group_by_category(self, sample_ordered_skills):
        result = _group_by_category(sample_ordered_skills)
        assert "Programming Languages" in result
        assert "Python" in result
        assert "Frameworks" in result
        assert "FastAPI" in result
        assert "DevOps" in result
        assert "Docker" in result

    def test_group_dedup_same_category(self):
        skills = [
            {"id": "1", "name": "python", "display_name": "Python", "category": "Languages", "proficiency": 5},
            {"id": "2", "name": "python", "display_name": "Python", "category": "Languages", "proficiency": 5},
        ]
        result = _group_by_category(skills)
        # Should only appear once
        assert result.count("Python") == 1

    def test_max_8_per_category(self):
        skills = []
        for i in range(10):
            skills.append({
                "id": str(i),
                "name": f"skill{i}",
                "display_name": f"Skill{i}",
                "category": "Languages",
                "proficiency": 5,
            })
        result = _group_by_category(skills)
        names = [s.split(": ")[1] if ": " in s else "" for s in result.split("\n") if ": " in s]
        if names:
            count = len(names[0].split(", "))
            assert count <= 8

    def test_clean_output(self):
        assert _clean_skills("```\n\\textbf{Languages}{: Python}\n```") == "\\textbf{Languages}{: Python}"


# ===========================================================================
# N7c — Bullet cache hash tests
# ===========================================================================

class TestBulletCache:
    def test_hash_stable_across_skill_order(self):
        a = {"required_skills": [
            {"skill": "Python", "is_technical": True, "ats_exact_phrase": "Python"},
            {"skill": "Docker", "is_technical": True, "ats_exact_phrase": "Docker"},
        ]}
        b = {"required_skills": [
            {"skill": "Docker", "is_technical": True, "ats_exact_phrase": "Docker"},
            {"skill": "Python", "is_technical": True, "ats_exact_phrase": "Python"},
        ]}
        assert _hash_jd_profile(a) == _hash_jd_profile(b)
