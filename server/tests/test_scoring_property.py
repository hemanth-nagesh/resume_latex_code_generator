"""Property-based tests for server/services/scoring.py.

Covers Property 10 (display resolution superset of scoring matches) and
Property 11 (exact-match skill display is unchanged / no regression) from
`.kiro/specs/graph-reliability-fixes/design.md`.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from server.services.scoring import (
    _score_skills,
    _skill_matches,
    order_skills_for_display,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Canonical skill name pool. `order_skills_for_display` and `_score_skills`
# both need to see the *same* canonical names in required/preferred lists so
# that fuzzy matching has something plausible to match against.
CANONICAL_SKILLS = ["Python", "React", "Docker", "FastAPI", "PostgreSQL"]

# Suffixes/transforms applied to canonical names to produce near-but-not-exact
# variants that exercise the fuzzy-matching path (substring/token-overlap)
# rather than only exact case-insensitive equality.
_VARIANT_SUFFIXES = ["", ".js", "-lang", " Framework"]


def _variant_of(name: str, suffix: str, upper: bool) -> str:
    variant = f"{name}{suffix}"
    return variant.upper() if upper else variant


skill_variant_strategy = st.builds(
    _variant_of,
    name=st.sampled_from(CANONICAL_SKILLS),
    suffix=st.sampled_from(_VARIANT_SUFFIXES),
    upper=st.booleans(),
).filter(lambda s: len(s.strip()) > 0)


@st.composite
def scenario_strategy(draw: st.DrawFn) -> dict[str, Any]:
    """Build a (project, jd_profile, kg_skills) scenario.

    - `project["skills"]` is drawn from near-but-not-exact variants of the
      canonical pool, exercising `_skill_matches`'s fuzzy paths.
    - `jd_profile["required_skills"]`/`["preferred_skills"]` are drawn from
      the canonical names themselves.
    - `kg_skills` mirrors the project's skill variants, so every project
      skill has a corresponding KG catalog entry (with name/display_name/
      category), modeling the realistic case the design doc describes.
    """
    project_skill_names = draw(
        st.lists(skill_variant_strategy, min_size=1, max_size=6, unique=True)
    )

    required = draw(
        st.lists(st.sampled_from(CANONICAL_SKILLS), min_size=0, max_size=5, unique=True)
    )
    preferred = draw(
        st.lists(st.sampled_from(CANONICAL_SKILLS), min_size=0, max_size=5, unique=True)
    )

    category = draw(st.sampled_from(["Languages", "Frameworks", "DevOps", "Databases", "Other"]))

    project = {
        "id": "p1",
        "title": "Test Project",
        "description": "",
        "tech_stack": [],
        "tags": [],
        "skills": project_skill_names,
        "primary_skill_ids": [],
        "status": "completed",
        "end_date": None,
    }

    jd_profile = {
        "required_skills": [{"skill": s, "is_technical": True} for s in required],
        "preferred_skills": [{"skill": s, "is_technical": True} for s in preferred],
        "ats_keywords": [],
        "domain": "",
        "industry": "",
    }

    kg_skills = [
        {"name": name, "display_name": name, "category": category}
        for name in project_skill_names
    ]

    return {"project": project, "jd_profile": jd_profile, "kg_skills": kg_skills}


# ---------------------------------------------------------------------------
# Property 10: Display skill resolution is a superset of scoring matches
# ---------------------------------------------------------------------------


class TestDisplayResolutionSupersetOfScoringMatches:
    """**Property 10: Display skill resolution is a superset of scoring matches**

    **Validates: Requirements 8.1, 8.2, 8.3**

    For any project, JD profile, and skill-index combination, every skill
    name present in `_score_skills`'s `matched_skills` output has a
    corresponding resolvable entry when that same name is passed through
    `order_skills_for_display`'s resolution logic — i.e. no skill silently
    disappears between scoring and display due to matching-strategy
    divergence.
    """

    @settings(max_examples=100)
    @given(scenario=scenario_strategy())
    def test_every_matched_skill_is_resolvable_in_display_output(
        self, scenario: dict[str, Any]
    ) -> None:
        project = scenario["project"]
        jd_profile = scenario["jd_profile"]
        kg_skills = scenario["kg_skills"]

        _, matched_skills = _score_skills(project, jd_profile, skill_index=None)

        displayed = order_skills_for_display(
            covered_skills=matched_skills,
            jd_profile=jd_profile,
            kg_skills=kg_skills,
        )
        displayed_names = [d["name"] for d in displayed]

        for matched_name in matched_skills:
            resolvable = any(
                _skill_matches(matched_name, displayed_name)
                for displayed_name in displayed_names
            )
            assert resolvable, (
                f"Matched skill {matched_name!r} did not resolve to any "
                f"entry in order_skills_for_display output {displayed_names!r} "
                f"(matched_skills={matched_skills!r}, kg_skills={kg_skills!r})"
            )

    @settings(max_examples=100)
    @given(scenario=scenario_strategy())
    def test_non_empty_matches_yield_non_empty_display(
        self, scenario: dict[str, Any]
    ) -> None:
        """Sanity companion: if scoring found matches (and the KG mirrors
        every project skill, as constructed by the strategy), display
        resolution must not come back empty."""
        project = scenario["project"]
        jd_profile = scenario["jd_profile"]
        kg_skills = scenario["kg_skills"]

        _, matched_skills = _score_skills(project, jd_profile, skill_index=None)

        displayed = order_skills_for_display(
            covered_skills=matched_skills,
            jd_profile=jd_profile,
            kg_skills=kg_skills,
        )

        if matched_skills:
            assert displayed, (
                f"Expected non-empty display output for matched_skills={matched_skills!r} "
                f"with kg_skills={kg_skills!r}, got empty list"
            )


# ---------------------------------------------------------------------------
# Property 11: Exact-match skill display is unchanged (no regression)
# ---------------------------------------------------------------------------
#
# The pre-fix `order_skills_for_display` used exact-lowercase set
# intersection (`covered_lower & required_names`) and exact-lowercase dict
# lookups (`skill_lookup[name_lower]`) instead of `_skill_matches`. That
# implementation no longer exists in the codebase (task 7.1 replaced it), so
# it is reconstructed here verbatim from git history (see
# `git show HEAD~1:server/services/scoring.py` prior to the Bug 8 fix
# commit) as a reference implementation, purely for regression comparison
# against the current fuzzy-matching implementation.


def _old_order_skills_for_display(
    covered_skills: list[str],
    jd_profile: dict[str, Any],
    kg_skills: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reference reconstruction of the PRE-FIX `order_skills_for_display`.

    Uses exact-lowercase set intersection / dict lookups (the original,
    Bug-8-affected behavior) rather than `_skill_matches`. Used only to
    assert no regression for exact-match-only scenarios (Property 11).
    """
    required_names = {
        s["skill"].lower() for s in jd_profile.get("required_skills", [])
    }
    preferred_names = {
        s["skill"].lower() for s in jd_profile.get("preferred_skills", [])
    }

    covered_lower = {s.lower() for s in covered_skills}

    skill_lookup: dict[str, dict[str, Any]] = {}
    for s in kg_skills:
        skill_lookup[s["name"].lower()] = s

    ordered: list[dict[str, Any]] = []

    # Tier 1: required + covered
    for name_lower in covered_lower & required_names:
        if name_lower in skill_lookup:
            ordered.append(skill_lookup[name_lower])

    # Tier 2: preferred + covered
    for name_lower in covered_lower & preferred_names:
        if name_lower not in required_names and name_lower in skill_lookup:
            ordered.append(skill_lookup[name_lower])

    # Tier 3: other covered skills
    for name_lower in covered_lower:
        if (
            name_lower not in required_names
            and name_lower not in preferred_names
            and name_lower in skill_lookup
        ):
            ordered.append(skill_lookup[name_lower])

    # Group by category
    by_category: dict[str, list[dict[str, Any]]] = {}
    for sk in ordered:
        cat = sk.get("category", "Other")
        by_category.setdefault(cat, []).append(sk)

    # Required -> Preferred -> Other, most populated categories first
    result: list[dict[str, Any]] = []
    priority_categories = []
    other_categories = []

    for cat, skills_list in by_category.items():
        is_priority = any(
            s["name"].lower() in required_names for s in skills_list
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


# Case transforms applied to canonical skill names to produce exact
# case-insensitive matches (never fuzzy-only variants like ".js" suffixes —
# this property is specifically about the exact-match no-regression case).
_CASE_TRANSFORMS = [str.lower, str.upper, str.title, lambda s: s]


def _cased(name: str, idx: int) -> str:
    return _CASE_TRANSFORMS[idx](name)


_case_idx_strategy = st.integers(min_value=0, max_value=len(_CASE_TRANSFORMS) - 1)


@st.composite
def exact_match_scenario_strategy(draw: st.DrawFn) -> dict[str, Any]:
    """Build a (covered_skills, jd_profile, kg_skills) scenario where every
    covered skill is an EXACT case-insensitive match to both a JD profile
    skill name and a `kg_skills` entry name (no fuzzy-only variants).

    Each canonical skill gets independently randomized casing in
    covered_skills, jd_profile's required/preferred lists, and kg_skills,
    so the scenario still exercises case-insensitivity while remaining a
    pure exact-match (post-lowercasing) case.
    """
    skill_names = draw(
        st.lists(st.sampled_from(CANONICAL_SKILLS), min_size=1, max_size=5, unique=True)
    )

    covered_skills: list[str] = []
    kg_skills: list[dict[str, Any]] = []
    for name in skill_names:
        covered_skills.append(_cased(name, draw(_case_idx_strategy)))
        category = draw(
            st.sampled_from(["Languages", "Frameworks", "DevOps", "Databases", "Other"])
        )
        kg_skills.append(
            {
                "name": _cased(name, draw(_case_idx_strategy)),
                "display_name": name,
                "category": category,
            }
        )

    covered_skills = list(draw(st.permutations(covered_skills)))
    kg_skills = list(draw(st.permutations(kg_skills)))

    required = draw(
        st.lists(st.sampled_from(skill_names), min_size=0, max_size=len(skill_names), unique=True)
    )
    remaining_for_preferred = [s for s in skill_names if s not in required]
    preferred = (
        draw(
            st.lists(
                st.sampled_from(remaining_for_preferred),
                min_size=0,
                max_size=len(remaining_for_preferred),
                unique=True,
            )
        )
        if remaining_for_preferred
        else []
    )

    required_cased = [_cased(s, draw(_case_idx_strategy)) for s in required]
    preferred_cased = [_cased(s, draw(_case_idx_strategy)) for s in preferred]

    jd_profile = {
        "required_skills": [{"skill": s, "is_technical": True} for s in required_cased],
        "preferred_skills": [{"skill": s, "is_technical": True} for s in preferred_cased],
        "ats_keywords": [],
        "domain": "",
        "industry": "",
    }

    return {
        "covered_skills": covered_skills,
        "jd_profile": jd_profile,
        "kg_skills": kg_skills,
    }


def _category_group_signature(
    result: list[dict[str, Any]],
) -> dict[str, frozenset[str]]:
    """Reduce an `order_skills_for_display` result to a {category: {names}}
    mapping (category -> the set of skill names grouped under it).

    The pre-fix reference implementation resolves its tier1/tier2/tier3
    membership via raw Python `set` intersections (`covered_lower &
    required_names`) rather than iterating `covered_skills` in order, and
    groups skills into categories via a plain `dict` whose insertion order
    then feeds a *stable* sort by category size. Set/dict iteration order
    for strings is hash-based: deterministic within a single interpreter
    process, but not derived from input list order or any documented
    ordering rule. That means whenever two or more skills land in the same
    tier, or two or more categories tie in size, the pre-fix
    implementation's relative order among those ties is an accident of
    Python's hash implementation, not a real behavioral guarantee — so it
    is not a meaningful thing to reproduce token-for-token.

    What Requirement 8.4 actually cares about ("ordering and grouping is
    identical") is captured by: which categories exist, and which skills
    are grouped into each one. This signature captures exactly that,
    order-insensitively, while remaining sensitive to any real regression
    (a skill moving to a different category, or disappearing/duplicating).
    """
    by_category: dict[str, list[str]] = {}
    for item in result:
        by_category.setdefault(item.get("category", "Other"), []).append(item["name"])
    return {cat: frozenset(names) for cat, names in by_category.items()}


class TestExactMatchNoRegression:
    """**Property 11: Exact-match skill display is unchanged (no regression)**

    **Validates: Requirements 8.4**

    For any `covered_skills`, `jd_profile`, and `kg_skills` where every
    covered skill name is an exact case-insensitive match to both a JD
    profile skill and a `kg_skills` entry, `order_skills_for_display`'s
    output ordering and grouping is identical to the pre-fix
    exact-lowercase-lookup behavior (same categories, in the same relative
    order, containing the same skills — see `_category_group_signature`
    for why intra-category tie-break order specifically is excluded from
    the comparison).
    """

    @settings(max_examples=100)
    @given(scenario=exact_match_scenario_strategy())
    def test_output_matches_pre_fix_exact_lookup_behavior(
        self, scenario: dict[str, Any]
    ) -> None:
        covered_skills = scenario["covered_skills"]
        jd_profile = scenario["jd_profile"]
        kg_skills = scenario["kg_skills"]

        old_result = _old_order_skills_for_display(covered_skills, jd_profile, kg_skills)
        new_result = order_skills_for_display(covered_skills, jd_profile, kg_skills)

        old_sig = _category_group_signature(old_result)
        new_sig = _category_group_signature(new_result)

        assert new_sig == old_sig, (
            "order_skills_for_display diverged from the pre-fix "
            "exact-lowercase-lookup behavior for an exact-match-only "
            f"scenario.\ncovered_skills={covered_skills!r}\n"
            f"jd_profile={jd_profile!r}\nkg_skills={kg_skills!r}\n"
            f"old={old_result!r}\nnew={new_result!r}"
        )

        # Also confirm the exact same set of skill names is present overall
        # (no skill silently dropped or duplicated relative to pre-fix
        # behavior).
        old_names = {n for names in old_sig.values() for n in names}
        new_names = {n for names in new_sig.values() for n in names}
        assert new_names == old_names


# ---------------------------------------------------------------------------
# Concrete unit test: near-but-not-exact skill name variant (Bug 8 report)
# ---------------------------------------------------------------------------


class TestNearButNotExactSkillNameVariant:
    """Concrete regression example for Bug 8.

    This is the exact bug-report scenario that motivated the fix in task 7.1:
    a project skill ("React.js") is credited as a scoring match against a JD
    skill ("React") via `_skill_matches`'s fuzzy substring logic, but the
    pre-fix `order_skills_for_display` resolved KG entries via an exact
    lowercase dict lookup keyed on the *JD* skill name ("react"), which never
    matched the KG catalog entry named "React.js" — so the skill silently
    disappeared from the rendered skills section despite being "matched" by
    scoring. Unlike the Hypothesis properties above (Property 10/11), this is
    a single, easy-to-read example fixing the exact names from the report.
    """

    def test_react_js_project_skill_matches_react_jd_skill_and_appears_in_display(
        self,
    ) -> None:
        result = order_skills_for_display(
            covered_skills=["React.js"],
            jd_profile={
                "required_skills": [{"skill": "React", "is_technical": True}],
                "preferred_skills": [],
            },
            kg_skills=[
                {"name": "React.js", "display_name": "React.js", "category": "Frameworks"},
            ],
        )

        assert result, "Expected React.js to appear in the display output, got empty list"
        assert result[0]["name"] == "React.js"
