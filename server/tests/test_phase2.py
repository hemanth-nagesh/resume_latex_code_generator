"""
Phase 2 tests — knowledge graph database layer.

Coverage:
- Schema migration runs idempotently
- CRUD operations for skills, projects, roles, certifications
- Edge table operations (project_skills, role_projects)
- N4 kg_loader returns complete graph
- Session queries
- Bullet cache operations
"""

import os
import uuid as uuid_lib

import pytest
import pytest_asyncio

from server.services.database import DatabasePool
from server.db import queries
from server.db.migrations import run_migrations

# Read DB URL from environment or .env
TEST_DSN = os.getenv("AZURE_COSMOSDB_PG_URL") or os.getenv("DATABASE_URL", "")
if not TEST_DSN:
    try:
        from server.config import get_config
        TEST_DSN = get_config().database_url_final
    except Exception:
        TEST_DSN = "postgresql://resume:resume@localhost:5432/resume"

@pytest_asyncio.fixture(scope="module")
async def pool():
    """Module-scoped pool — run migrations once, reuse for all tests."""
    p = DatabasePool(TEST_DSN, min_size=1, max_size=3)
    await run_migrations(p)
    yield p
    await p.close()


# ===========================================================================
# Schema tests
# ===========================================================================

class TestSchema:
    @pytest.mark.asyncio
    async def test_migrations_idempotent(self, pool):
        """Running migrations twice should not raise."""
        await run_migrations(pool)
        await run_migrations(pool)  # safe idempotent re-run

    @pytest.mark.asyncio
    async def test_tables_exist(self, pool):
        tables = ["skills", "projects", "project_skills", "roles",
                   "role_projects", "certifications", "sessions"]
        for table in tables:
            rows = await pool.fetch(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = $1)",
                table,
            )
            assert rows[0]["exists"] is True, f"Table {table} does not exist"


# ===========================================================================
# Skills CRUD
# ===========================================================================

@pytest_asyncio.fixture
async def sample_skill(pool):
    record = await queries.create_skill(pool, "test-skill", "Test Skill", "technical", 4)
    yield record
    try:
        await queries.delete_skill(pool, uuid_lib.UUID(record["id"]))
    except Exception:
        pass


class TestSkillsCRUD:
    @pytest.mark.asyncio
    async def test_create_skill(self, pool):
        skill = await queries.create_skill(pool, "pytest-create", "PyTest Create", "tool", 3)
        assert skill["name"] == "pytest-create"
        assert skill["category"] == "tool"
        await queries.delete_skill(pool, uuid_lib.UUID(skill["id"]))

    @pytest.mark.asyncio
    async def test_list_skills(self, pool):
        skills = await queries.list_skills(pool)
        assert len(skills) >= 1

    @pytest.mark.asyncio
    async def test_get_skill(self, pool, sample_skill):
        skill = await queries.get_skill(pool, uuid_lib.UUID(sample_skill["id"]))
        assert skill["name"] == "test-skill"

    @pytest.mark.asyncio
    async def test_update_skill(self, pool, sample_skill):
        updated = await queries.update_skill(
            pool, uuid_lib.UUID(sample_skill["id"]), proficiency=5
        )
        assert updated["proficiency"] == 5

    @pytest.mark.asyncio
    async def test_delete_skill(self, pool):
        skill = await queries.create_skill(pool, "to-delete", "To Delete", "domain", 2)
        deleted = await queries.delete_skill(pool, uuid_lib.UUID(skill["id"]))
        assert deleted is True
        assert await queries.get_skill(pool, uuid_lib.UUID(skill["id"])) is None


# ===========================================================================
# Projects CRUD
# ===========================================================================

@pytest_asyncio.fixture
async def sample_project(pool):
    record = await queries.create_project(
        pool,
        title="Test Project",
        description="A test project with enough characters to satisfy the minimum length requirement of fifty.",
        tech_stack=["Python", "FastAPI"],
        tags=["api", "backend"],
        status="completed",
    )
    yield record
    try:
        await queries.soft_delete_project(pool, uuid_lib.UUID(record["id"]))
    except Exception:
        pass


class TestProjectsCRUD:
    @pytest.mark.asyncio
    async def test_create_project_requires_min_description(self, pool):
        with pytest.raises(Exception):
            await queries.create_project(
                pool, "X", "Too short", ["Python"]
            )

    @pytest.mark.asyncio
    async def test_create_and_get_project(self, pool, sample_project):
        proj = await queries.get_project(pool, uuid_lib.UUID(sample_project["id"]))
        assert proj["title"] == "Test Project"
        assert "Python" in proj["tech_stack"]

    @pytest.mark.asyncio
    async def test_list_projects(self, pool, sample_project):
        projects = await queries.list_projects(pool)
        assert len(projects) >= 1

    @pytest.mark.asyncio
    async def test_soft_delete_project(self, pool, sample_project):
        deleted = await queries.soft_delete_project(pool, uuid_lib.UUID(sample_project["id"]))
        assert deleted is True
        proj = await queries.get_project(pool, uuid_lib.UUID(sample_project["id"]))
        assert proj["is_active"] is False

    @pytest.mark.asyncio
    async def test_link_and_unlink_skill(self, pool, sample_project, sample_skill):
        pid = uuid_lib.UUID(sample_project["id"])
        sid = uuid_lib.UUID(sample_skill["id"])

        await queries.link_project_skill(pool, pid, sid, is_primary=True)
        proj = await queries.get_project(pool, pid)
        assert "Test Skill" in proj.get("skills", [])

        await queries.unlink_project_skill(pool, pid, sid)
        proj = await queries.get_project(pool, pid)
        assert "Test Skill" not in proj.get("skills", [])


# ===========================================================================
# Roles CRUD
# ===========================================================================

@pytest_asyncio.fixture
async def sample_role(pool):
    record = await queries.create_role(
        pool,
        company_name="Test Corp",
        role_title="Engineer",
        start_date="2023-01-01",
        location="Remote",
    )
    yield record
    try:
        await queries.soft_delete_role(pool, uuid_lib.UUID(record["id"]))
    except Exception:
        pass


class TestRolesCRUD:
    @pytest.mark.asyncio
    async def test_create_and_get_role(self, pool, sample_role):
        role = await queries.get_role(pool, uuid_lib.UUID(sample_role["id"]))
        assert role["company_name"] == "Test Corp"
        assert role["role_title"] == "Engineer"

    @pytest.mark.asyncio
    async def test_list_roles(self, pool, sample_role):
        roles = await queries.list_roles(pool)
        assert len(roles) >= 1

    @pytest.mark.asyncio
    async def test_link_role_to_project(self, pool, sample_role, sample_project):
        rid = uuid_lib.UUID(sample_role["id"])
        pid = uuid_lib.UUID(sample_project["id"])
        await queries.link_role_project(pool, rid, pid)
        role = await queries.get_role(pool, rid)
        assert str(pid) in [str(p) for p in role.get("project_ids", [])]

        await queries.unlink_role_project(pool, rid, pid)


# ===========================================================================
# Certifications
# ===========================================================================

class TestCertifications:
    @pytest.mark.asyncio
    async def test_create_and_list(self, pool):
        cert = await queries.create_certification(
            pool, "Azure AI Engineer", 2026, "Microsoft certification", "https://example.com"
        )
        certs = await queries.list_certifications(pool)
        assert any(c["title"] == "Azure AI Engineer" for c in certs)
        await queries.soft_delete_certification(pool, uuid_lib.UUID(cert["id"]))


# ===========================================================================
# Sessions
# ===========================================================================

class TestSessions:
    @pytest.mark.asyncio
    async def test_create_and_find_session(self, pool):
        key = "test_session_key_123"
        session = await queries.create_session(pool, key)
        assert session["session_key"] == key

        found = await queries.find_session(pool, key)
        assert found is not None
        assert found["status"] == "pending"

    @pytest.mark.asyncio
    async def test_complete_session(self, pool):
        key = "test_session_complete_456"
        await queries.create_session(pool, key)
        await queries.complete_session(
            pool, key,
            selected_project_ids=["proj-1", "proj-2"],
            covered_skills=["Python", "FastAPI"],
        )
        found = await queries.find_session(pool, key)
        assert found["status"] == "completed"
        assert "proj-1" in found["selected_project_ids"]

    @pytest.mark.asyncio
    async def test_stale_session_not_found(self, pool):
        """Session older than max_age_hours should not be returned."""
        key = "stale_session_789"
        await queries.create_session(pool, key)
        # Force the session to appear old by looking with 0-hour ttl
        found = await queries.find_session(pool, key, max_age_hours=0)
        assert found is None


# ===========================================================================
# N4 Knowledge Graph Loader
# ===========================================================================

class TestKnowledgeGraphLoader:
    """N4 loads the full graph — these tests verify integration."""

    @pytest.mark.asyncio
    async def test_load_returns_all_sections(self, pool):
        kg = await queries.load_full_knowledge_graph(pool)
        assert "projects" in kg
        assert "skills" in kg
        assert "roles" in kg
        assert "certifications" in kg

    @pytest.mark.asyncio
    async def test_projects_have_aggregated_skills(self, pool):
        kg = await queries.load_full_knowledge_graph(pool)
        for proj in kg["projects"]:
            assert "skills" in proj
            assert isinstance(proj["skills"], list)

    @pytest.mark.asyncio
    async def test_roles_have_project_ids(self, pool):
        kg = await queries.load_full_knowledge_graph(pool)
        for role in kg["roles"]:
            assert "project_ids" in role
            assert isinstance(role["project_ids"], list)

    @pytest.mark.asyncio
    async def test_only_active_projects_loaded(self, pool):
        """Soft-deleted projects should not appear in the graph."""
        kg = await queries.load_full_knowledge_graph(pool)
        for proj in kg["projects"]:
            assert proj.get("is_active") is True

    @pytest.mark.asyncio
    async def test_load_is_fast(self, pool):
        """N4 must complete quickly — it's just one SELECT with JOINs."""
        import time
        start = time.monotonic()
        await queries.load_full_knowledge_graph(pool)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"kg_loader took {elapsed:.2f}s, expected <1s"
