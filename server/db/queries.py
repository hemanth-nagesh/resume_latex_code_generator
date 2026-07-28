"""Raw SQL queries for all database operations.

Organized by domain. Every function takes a DatabasePool and returns
asyncpg Records. No ORM — direct SQL for full control over JOINs,
JSONB operations, and array aggregations.

Date parameters are auto-converted from str to datetime.date for asyncpg.
"""

from __future__ import annotations

import json
from datetime import date as date_type
from typing import Any
from uuid import UUID

import asyncpg

from server.services.database import DatabasePool


def _to_date(value: str | date_type | None) -> date_type | None:
    """Convert a date string or object to datetime.date for asyncpg."""
    if value is None:
        return None
    if isinstance(value, date_type):
        return value
    return date_type.fromisoformat(value)


def _record_to_dict(record: asyncpg.Record | None) -> dict[str, Any]:
    """Convert an asyncpg Record to a plain dict."""
    if record is None:
        return {}
    return dict(record)

_LOAD_FULL_GRAPH = """
SELECT
    p.id,
    p.title,
    p.description,
    p.impact_metric,
    p.start_date,
    p.end_date,
    p.status,
    p.tech_stack,
    p.tags,
    p.latex_bullet_cache,
    p.is_active,
    array_remove(array_agg(DISTINCT s.name), NULL) AS skills,
    array_agg(DISTINCT ps.skill_id) FILTER (WHERE ps.is_primary_skill) AS primary_skill_ids
FROM projects p
LEFT JOIN project_skills ps ON p.id = ps.project_id
LEFT JOIN skills s ON ps.skill_id = s.id
WHERE p.is_active = true
GROUP BY p.id
ORDER BY p.end_date DESC NULLS FIRST, p.start_date DESC
"""


async def load_full_knowledge_graph(pool: DatabasePool) -> dict[str, Any]:
    """Single query returning all active projects with aggregated skills,
    plus all skills and roles.

    Returns dict matching the KnowledgeGraph model shape for N4.
    """
    projects = await pool.fetch(_LOAD_FULL_GRAPH)
    skills = await pool.fetch(
        "SELECT id, name, display_name, category, proficiency, last_used_date "
        "FROM skills ORDER BY category, proficiency DESC"
    )
    roles = await pool.fetch(
        "SELECT r.id, r.company_name, r.role_title, r.start_date, r.end_date, "
        "r.location, r.employment_type, r.base_responsibilities, "
        "array_agg(rp.project_id ORDER BY rp.project_id) FILTER (WHERE rp.project_id IS NOT NULL) AS project_ids "
        "FROM roles r "
        "LEFT JOIN role_projects rp ON r.id = rp.role_id "
        "WHERE r.is_active = true "
        "GROUP BY r.id "
        "ORDER BY r.end_date DESC NULLS FIRST, r.start_date DESC"
    )
    certifications = await pool.fetch(
        "SELECT id, title, year, description, url FROM certifications WHERE is_active = true ORDER BY year DESC NULLS LAST"
    )

    return {
        "projects": [_record_to_dict(r) for r in projects],
        "skills": [_record_to_dict(r) for r in skills],
        "roles": [_record_to_dict(r) for r in roles],
        "certifications": [_record_to_dict(r) for r in certifications],
    }


# ===========================================================================
# Skills CRUD
# ===========================================================================

async def list_skills(pool: DatabasePool) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        "SELECT id, name, display_name, category, proficiency, last_used_date, "
        "created_at, updated_at FROM skills ORDER BY category, proficiency DESC"
    )
    return [_record_to_dict(r) for r in rows]


async def get_skill(pool: DatabasePool, skill_id: UUID) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        "SELECT id, name, display_name, category, proficiency, last_used_date "
        "FROM skills WHERE id = $1",
        skill_id,
    )
    return _record_to_dict(row) if row else None


async def create_skill(
    pool: DatabasePool,
    name: str,
    display_name: str,
    category: str,
    proficiency: int = 3,
    last_used_date: str | None = None,
) -> dict[str, Any]:
    row = await pool.fetchrow(
        "INSERT INTO skills (name, display_name, category, proficiency, last_used_date) "
        "VALUES ($1, $2, $3, $4, $5) RETURNING id, name, display_name, category, proficiency, last_used_date",
        name.lower().strip(),
        display_name.strip(),
        category,
        proficiency,
        last_used_date,
    )
    return _record_to_dict(row)


async def update_skill(
    pool: DatabasePool,
    skill_id: UUID,
    display_name: str | None = None,
    category: str | None = None,
    proficiency: int | None = None,
    last_used_date: str | None = None,
) -> dict[str, Any] | None:
    sets: list[str] = []
    args: list[Any] = []
    idx = 1

    if display_name is not None:
        sets.append(f"display_name = ${idx}")
        args.append(display_name.strip())
        idx += 1
    if category is not None:
        sets.append(f"category = ${idx}")
        args.append(category)
        idx += 1
    if proficiency is not None:
        sets.append(f"proficiency = ${idx}")
        args.append(proficiency)
        idx += 1
    if last_used_date is not None:
        sets.append(f"last_used_date = ${idx}")
        args.append(last_used_date)
        idx += 1

    if not sets:
        return None

    args.append(skill_id)
    row = await pool.fetchrow(
        f"UPDATE skills SET {', '.join(sets)} WHERE id = ${idx} "
        "RETURNING id, name, display_name, category, proficiency, last_used_date",
        *args,
    )
    return _record_to_dict(row) if row else None


async def delete_skill(pool: DatabasePool, skill_id: UUID) -> bool:
    """Hard delete (skills are small and referenced via FK cascade)."""
    result = await pool.execute("DELETE FROM skills WHERE id = $1", skill_id)
    return "DELETE 1" in result


# ===========================================================================
# Projects CRUD
# ===========================================================================

async def list_projects(pool: DatabasePool) -> list[dict[str, Any]]:
    rows = await pool.fetch(_LOAD_FULL_GRAPH)
    return [_record_to_dict(r) for r in rows]


async def get_project(pool: DatabasePool, project_id: UUID) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        "SELECT p.*, array_remove(array_agg(DISTINCT s.name), NULL) AS skills "
        "FROM projects p "
        "LEFT JOIN project_skills ps ON p.id = ps.project_id "
        "LEFT JOIN skills s ON ps.skill_id = s.id "
        "WHERE p.id = $1 GROUP BY p.id",
        project_id,
    )
    return _record_to_dict(row) if row else None


async def create_project(
    pool: DatabasePool,
    title: str,
    description: str,
    tech_stack: list[str],
    impact_metric: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    status: str = "completed",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    row = await pool.fetchrow(
        "INSERT INTO projects (title, description, impact_metric, start_date, end_date, status, tech_stack, tags) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *",
        title.strip(),
        description.strip(),
        impact_metric,
        _to_date(start_date),
        _to_date(end_date),
        status,
        tech_stack,
        tags or [],
    )
    return _record_to_dict(row)


async def update_project(
    pool: DatabasePool,
    project_id: UUID,
    title: str | None = None,
    description: str | None = None,
    tech_stack: list[str] | None = None,
    impact_metric: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any] | None:
    sets: list[str] = []
    args: list[Any] = []
    idx = 1

    updates: dict[str, Any] = {
        "title": title, "description": description, "impact_metric": impact_metric,
        "start_date": start_date, "end_date": end_date, "status": status,
    }
    for col, val in updates.items():
        if val is not None:
            sets.append(f"{col} = ${idx}")
            args.append(val.strip() if isinstance(val, str) else val)
            idx += 1

    if tech_stack is not None:
        sets.append(f"tech_stack = ${idx}")
        args.append(tech_stack)
        idx += 1
    if tags is not None:
        sets.append(f"tags = ${idx}")
        args.append(tags)
        idx += 1

    if not sets:
        return None

    # Describing the project invalidates its bullet cache
    if description is not None:
        sets.append(f"latex_bullet_cache = '{{}}'")

    args.append(project_id)
    row = await pool.fetchrow(
        f"UPDATE projects SET {', '.join(sets)} WHERE id = ${idx} RETURNING *",
        *args,
    )
    return _record_to_dict(row) if row else None


async def soft_delete_project(pool: DatabasePool, project_id: UUID) -> bool:
    result = await pool.execute(
        "UPDATE projects SET is_active = false, updated_at = now() WHERE id = $1",
        project_id,
    )
    return "UPDATE 1" in result


async def link_project_skill(
    pool: DatabasePool, project_id: UUID, skill_id: UUID, is_primary: bool = False
) -> None:
    await pool.execute(
        "INSERT INTO project_skills (project_id, skill_id, is_primary_skill) "
        "VALUES ($1, $2, $3) ON CONFLICT (project_id, skill_id) DO UPDATE "
        "SET is_primary_skill = $3",
        project_id, skill_id, is_primary,
    )


async def unlink_project_skill(pool: DatabasePool, project_id: UUID, skill_id: UUID) -> None:
    await pool.execute(
        "DELETE FROM project_skills WHERE project_id = $1 AND skill_id = $2",
        project_id, skill_id,
    )


# ===========================================================================
# Roles CRUD
# ===========================================================================

async def list_roles(pool: DatabasePool) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        "SELECT r.*, array_agg(rp.project_id) FILTER (WHERE rp.project_id IS NOT NULL) AS project_ids "
        "FROM roles r LEFT JOIN role_projects rp ON r.id = rp.role_id "
        "WHERE r.is_active = true "
        "GROUP BY r.id ORDER BY r.end_date DESC NULLS FIRST, r.start_date DESC"
    )
    return [_record_to_dict(r) for r in rows]


async def get_role(pool: DatabasePool, role_id: UUID) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        "SELECT r.*, array_agg(rp.project_id) FILTER (WHERE rp.project_id IS NOT NULL) AS project_ids "
        "FROM roles r LEFT JOIN role_projects rp ON r.id = rp.role_id "
        "WHERE r.id = $1 GROUP BY r.id",
        role_id,
    )
    return _record_to_dict(row) if row else None


async def create_role(
    pool: DatabasePool,
    company_name: str,
    role_title: str,
    start_date: str | date_type,
    end_date: str | date_type | None = None,
    location: str | None = None,
    employment_type: str = "full-time",
    base_responsibilities: list[str] | None = None,
) -> dict[str, Any]:
    row = await pool.fetchrow(
        "INSERT INTO roles (company_name, role_title, start_date, end_date, location, employment_type, base_responsibilities) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *",
        company_name.strip(), role_title.strip(),
        _to_date(start_date), _to_date(end_date),
        location, employment_type,
        base_responsibilities or [],
    )
    return _record_to_dict(row)


async def update_role(
    pool: DatabasePool,
    role_id: UUID,
    company_name: str | None = None,
    role_title: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    location: str | None = None,
    employment_type: str | None = None,
    base_responsibilities: list[str] | None = None,
) -> dict[str, Any] | None:
    sets: list[str] = []
    args: list[Any] = []
    idx = 1

    updates: dict[str, Any] = {
        "company_name": company_name, "role_title": role_title,
        "start_date": start_date, "end_date": end_date,
        "location": location, "employment_type": employment_type,
    }
    for col, val in updates.items():
        if val is not None:
            sets.append(f"{col} = ${idx}")
            args.append(val.strip() if isinstance(val, str) else val)
            idx += 1

    if base_responsibilities is not None:
        sets.append(f"base_responsibilities = ${idx}")
        args.append(base_responsibilities)
        idx += 1

    if not sets:
        return None

    args.append(role_id)
    row = await pool.fetchrow(
        f"UPDATE roles SET {', '.join(sets)} WHERE id = ${idx} RETURNING *",
        *args,
    )
    return _record_to_dict(row) if row else None


async def soft_delete_role(pool: DatabasePool, role_id: UUID) -> bool:
    result = await pool.execute(
        "UPDATE roles SET is_active = false, updated_at = now() WHERE id = $1",
        role_id,
    )
    return "UPDATE 1" in result


async def link_role_project(pool: DatabasePool, role_id: UUID, project_id: UUID) -> None:
    await pool.execute(
        "INSERT INTO role_projects (role_id, project_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        role_id, project_id,
    )


async def unlink_role_project(pool: DatabasePool, role_id: UUID, project_id: UUID) -> None:
    await pool.execute(
        "DELETE FROM role_projects WHERE role_id = $1 AND project_id = $2",
        role_id, project_id,
    )


# ===========================================================================
# Certifications CRUD
# ===========================================================================

async def list_certifications(pool: DatabasePool) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        "SELECT * FROM certifications WHERE is_active = true ORDER BY year DESC NULLS LAST"
    )
    return [_record_to_dict(r) for r in rows]


async def create_certification(
    pool: DatabasePool,
    title: str,
    year: int | None = None,
    description: str | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    row = await pool.fetchrow(
        "INSERT INTO certifications (title, year, description, url) "
        "VALUES ($1, $2, $3, $4) RETURNING *",
        title.strip(), year, description, url,
    )
    return _record_to_dict(row)


async def soft_delete_certification(pool: DatabasePool, cert_id: UUID) -> bool:
    result = await pool.execute(
        "UPDATE certifications SET is_active = false WHERE id = $1", cert_id
    )
    return "UPDATE 1" in result


# ===========================================================================
# Sessions (N1, N11)
# ===========================================================================

async def find_session(
    pool: DatabasePool, session_key: str, max_age_hours: int = 6
) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        "SELECT * FROM sessions WHERE session_key = $1 "
        "AND created_at > now() - ($2 || ' hours')::interval "
        "AND status != 'failed' "
        "ORDER BY created_at DESC LIMIT 1",
        session_key, str(max_age_hours),
    )
    return _record_to_dict(row) if row else None


async def create_session(
    pool: DatabasePool, session_key: str, jd_profile: dict | None = None
) -> dict[str, Any]:
    row = await pool.fetchrow(
        "INSERT INTO sessions (session_key, jd_profile, status) "
        "VALUES ($1, $2, 'pending') RETURNING session_id, session_key, status, created_at",
        session_key, json.dumps(jd_profile) if jd_profile else None,
    )
    return _record_to_dict(row)


async def complete_session(
    pool: DatabasePool,
    session_key: str,
    jd_profile: dict | None = None,
    selected_project_ids: list[str] | None = None,
    selected_role_ids: list[str] | None = None,
    covered_skills: list[str] | None = None,
    uncovered_skills: list[str] | None = None,
    pdf_data: bytes | None = None,
    pdf_filename: str | None = None,
    latex_source: str | None = None,
) -> None:
    """Mark a session complete and persist its generated PDF/LaTeX in Postgres.

    Storing the PDF directly on the row (instead of an external blob store)
    keeps the whole app on a single Postgres database — no other storage
    service to provision.
    """
    await pool.execute(
        "UPDATE sessions SET status = 'completed', completed_at = now(), "
        "jd_profile = COALESCE($2, jd_profile), "
        "selected_project_ids = COALESCE($3, selected_project_ids), "
        "selected_role_ids = COALESCE($4, selected_role_ids), "
        "covered_skills = COALESCE($5, covered_skills), "
        "uncovered_skills = COALESCE($6, uncovered_skills), "
        "pdf_data = COALESCE($7, pdf_data), "
        "pdf_filename = COALESCE($8, pdf_filename), "
        "latex_source = COALESCE($9, latex_source) "
        "WHERE session_key = $1 AND status = 'pending'",
        session_key,
        json.dumps(jd_profile) if jd_profile else None,
        selected_project_ids,
        selected_role_ids,
        json.dumps(covered_skills) if covered_skills else None,
        json.dumps(uncovered_skills) if uncovered_skills else None,
        pdf_data,
        pdf_filename,
        latex_source,
    )


async def get_session_pdf(
    pool: DatabasePool, session_key: str
) -> dict[str, Any] | None:
    """Fetch the archived PDF/LaTeX for a completed session, by session_key.

    Returns the most recent completed session with a non-null pdf_data,
    or None if nothing has been generated yet for this key.
    """
    row = await pool.fetchrow(
        "SELECT pdf_data, pdf_filename, latex_source FROM sessions "
        "WHERE session_key = $1 AND status = 'completed' AND pdf_data IS NOT NULL "
        "ORDER BY completed_at DESC LIMIT 1",
        session_key,
    )
    return _record_to_dict(row) if row else None


async def fail_session(pool: DatabasePool, session_key: str, reason: str = "") -> None:
    await pool.execute(
        "UPDATE sessions SET status = 'failed', completed_at = now() "
        "WHERE session_key = $1",
        session_key,
    )


# ===========================================================================
# Project bullet cache (N11)
# ===========================================================================

async def update_bullet_cache(
    pool: DatabasePool, project_id: UUID, jd_profile_hash: str, bullets: list[str]
) -> None:
    """Upsert bullet cache entry for a specific JD profile hash.

    Uses PostgreSQL JSONB merge (||) to add/overwrite a single key
    without affecting other cache entries.
    """
    cache_entry = json.dumps({
        jd_profile_hash: {
            "bullets": bullets,
            "generated_at": "now()",  # will be replaced server-side
        }
    })
    await pool.execute(
        "UPDATE projects SET latex_bullet_cache = "
        "latex_bullet_cache || $1::jsonb WHERE id = $2",
        cache_entry, project_id,
    )


async def prune_bullet_cache(
    pool: DatabasePool, project_id: UUID, max_age_days: int = 90
) -> None:
    """Remove cache entries older than max_age_days.

    This is a best-effort cleanup — entries that don't have a parseable
    generated_at timestamp are left in place.
    """
    await pool.execute(
        "UPDATE projects SET latex_bullet_cache = "
        "(SELECT jsonb_object_agg(key, value) FROM jsonb_each(latex_bullet_cache) "
        " WHERE (value->>'generated_at')::timestamptz > now() - ($1 || ' days')::interval) "
        "WHERE id = $2",
        str(max_age_days), project_id,
    )


# ===========================================================================
# Helpers
# ===========================================================================

def _record_to_dict(record: asyncpg.Record | None) -> dict[str, Any]:
    """Convert an asyncpg Record to a plain dict.

    Handles datetime/date/UUID serialization automatically.
    """
    if record is None:
        return {}
    return dict(record)
