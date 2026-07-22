"""Admin CRUD endpoints for the knowledge graph.

Routes:
- /api/admin/projects
- /api/admin/skills
- /api/admin/roles
- /api/admin/certifications

All endpoints require knowledge graph data seeded in PostgreSQL.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.api.auth import require_auth
from server.container import Container
from server.db import queries

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_auth)],
)


def _container(request: Request) -> Container:
    """Get Container from app state."""
    return request.app.state.container


# ===========================================================================
# Request/Response models
# ===========================================================================

class SkillCreate(BaseModel):
    name: str
    display_name: str
    category: str = "technical"
    proficiency: int = Field(default=3, ge=1, le=5)
    last_used_date: str | None = None

class SkillUpdate(BaseModel):
    display_name: str | None = None
    category: str | None = None
    proficiency: int | None = Field(default=None, ge=1, le=5)
    last_used_date: str | None = None

class ProjectCreate(BaseModel):
    title: str
    description: str = Field(min_length=50)
    tech_stack: list[str] = Field(min_length=1)
    impact_metric: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str = "completed"
    tags: list[str] | None = None

class ProjectUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    tech_stack: list[str] | None = None
    impact_metric: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str | None = None
    tags: list[str] | None = None

class ProjectSkillLink(BaseModel):
    skill_id: UUID
    is_primary: bool = False

class RoleCreate(BaseModel):
    company_name: str
    role_title: str
    start_date: str
    end_date: str | None = None
    location: str | None = None
    employment_type: str = "full-time"
    base_responsibilities: list[str] | None = None

class RoleUpdate(BaseModel):
    company_name: str | None = None
    role_title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    location: str | None = None
    employment_type: str | None = None
    base_responsibilities: list[str] | None = None

class RoleProjectLink(BaseModel):
    project_id: UUID

class CertificationCreate(BaseModel):
    title: str
    year: int | None = None
    description: str | None = None
    url: str | None = None


# ===========================================================================
# Skills
# ===========================================================================

@router.get("/skills")
async def list_skills(request: Request) -> list[dict[str, Any]]:
    container = _container(request)
    return await queries.list_skills(container.db)

@router.get("/skills/{skill_id}")
async def get_skill(skill_id: UUID, request: Request) -> dict[str, Any]:
    container = _container(request)
    skill = await queries.get_skill(container.db, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill

@router.post("/skills", status_code=201)
async def create_skill_handler(body: SkillCreate, request: Request) -> dict[str, Any]:
    container = _container(request)
    return await queries.create_skill(
        container.db,
        name=body.name,
        display_name=body.display_name,
        category=body.category,
        proficiency=body.proficiency,
        last_used_date=body.last_used_date,
    )

@router.patch("/skills/{skill_id}")
async def update_skill_handler(
    skill_id: UUID, body: SkillUpdate, request: Request
) -> dict[str, Any]:
    container = _container(request)
    updated = await queries.update_skill(
        container.db, skill_id,
        display_name=body.display_name,
        category=body.category,
        proficiency=body.proficiency,
        last_used_date=body.last_used_date,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return updated

@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill_handler(skill_id: UUID, request: Request):
    container = _container(request)
    deleted = await queries.delete_skill(container.db, skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")

# ===========================================================================
# Projects
# ===========================================================================

@router.get("/projects")
async def list_projects(request: Request) -> list[dict[str, Any]]:
    container = _container(request)
    return await queries.list_projects(container.db)

@router.get("/projects/{project_id}")
async def get_project(project_id: UUID, request: Request) -> dict[str, Any]:
    container = _container(request)
    proj = await queries.get_project(container.db, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj

@router.post("/projects", status_code=201)
async def create_project_handler(body: ProjectCreate, request: Request) -> dict[str, Any]:
    container = _container(request)
    return await queries.create_project(
        container.db,
        title=body.title,
        description=body.description,
        tech_stack=body.tech_stack,
        impact_metric=body.impact_metric,
        start_date=body.start_date,
        end_date=body.end_date,
        status=body.status,
        tags=body.tags,
    )

@router.patch("/projects/{project_id}")
async def update_project_handler(
    project_id: UUID, body: ProjectUpdate, request: Request
) -> dict[str, Any]:
    container = _container(request)
    updated = await queries.update_project(
        container.db, project_id,
        title=body.title,
        description=body.description,
        tech_stack=body.tech_stack,
        impact_metric=body.impact_metric,
        start_date=body.start_date,
        end_date=body.end_date,
        status=body.status,
        tags=body.tags,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return updated

@router.delete("/projects/{project_id}", status_code=204)
async def delete_project_handler(project_id: UUID, request: Request):
    container = _container(request)
    deleted = await queries.soft_delete_project(container.db, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")

@router.post("/projects/{project_id}/skills")
async def link_skill_to_project(
    project_id: UUID, body: ProjectSkillLink, request: Request
) -> dict[str, str]:
    container = _container(request)
    await queries.link_project_skill(
        container.db, project_id, body.skill_id, body.is_primary
    )
    return {"status": "linked"}

@router.delete("/projects/{project_id}/skills/{skill_id}", status_code=204)
async def unlink_skill_from_project(
    project_id: UUID, skill_id: UUID, request: Request
):
    container = _container(request)
    await queries.unlink_project_skill(container.db, project_id, skill_id)

# ===========================================================================
# Roles
# ===========================================================================

@router.get("/roles")
async def list_roles(request: Request) -> list[dict[str, Any]]:
    container = _container(request)
    return await queries.list_roles(container.db)

@router.get("/roles/{role_id}")
async def get_role(role_id: UUID, request: Request) -> dict[str, Any]:
    container = _container(request)
    role = await queries.get_role(container.db, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role

@router.post("/roles", status_code=201)
async def create_role_handler(body: RoleCreate, request: Request) -> dict[str, Any]:
    container = _container(request)
    return await queries.create_role(
        container.db,
        company_name=body.company_name,
        role_title=body.role_title,
        start_date=body.start_date,
        end_date=body.end_date,
        location=body.location,
        employment_type=body.employment_type,
        base_responsibilities=body.base_responsibilities,
    )

@router.patch("/roles/{role_id}")
async def update_role_handler(
    role_id: UUID, body: RoleUpdate, request: Request
) -> dict[str, Any]:
    container = _container(request)
    updated = await queries.update_role(
        container.db, role_id,
        company_name=body.company_name,
        role_title=body.role_title,
        start_date=body.start_date,
        end_date=body.end_date,
        location=body.location,
        employment_type=body.employment_type,
        base_responsibilities=body.base_responsibilities,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return updated

@router.delete("/roles/{role_id}", status_code=204)
async def delete_role_handler(role_id: UUID, request: Request):
    container = _container(request)
    deleted = await queries.soft_delete_role(container.db, role_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Role not found")

@router.post("/roles/{role_id}/projects")
async def link_project_to_role(
    role_id: UUID, body: RoleProjectLink, request: Request
) -> dict[str, str]:
    container = _container(request)
    await queries.link_role_project(container.db, role_id, body.project_id)
    return {"status": "linked"}

@router.delete("/roles/{role_id}/projects/{project_id}", status_code=204)
async def unlink_project_from_role(
    role_id: UUID, project_id: UUID, request: Request
):
    container = _container(request)
    await queries.unlink_role_project(container.db, role_id, project_id)

# ===========================================================================
# Certifications
# ===========================================================================

@router.get("/certifications")
async def list_certifications(request: Request) -> list[dict[str, Any]]:
    container = _container(request)
    return await queries.list_certifications(container.db)

@router.post("/certifications", status_code=201)
async def create_certification_handler(
    body: CertificationCreate, request: Request
) -> dict[str, Any]:
    container = _container(request)
    return await queries.create_certification(
        container.db,
        title=body.title,
        year=body.year,
        description=body.description,
        url=body.url,
    )

@router.delete("/certifications/{cert_id}", status_code=204)
async def delete_certification_handler(cert_id: UUID, request: Request):
    container = _container(request)
    deleted = await queries.soft_delete_certification(container.db, cert_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Certification not found")
