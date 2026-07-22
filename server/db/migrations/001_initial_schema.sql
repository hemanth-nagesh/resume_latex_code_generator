-- Phase 2: Knowledge Graph Schema
-- Run once: creates all tables, indexes, and constraints.
-- Uses UUID primary keys, JSONB for flexible cache fields, GIN indexes for array search.

BEGIN;

-- ------------------------------------------------------------------
-- Enum types
-- ------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE skill_category AS ENUM ('technical', 'domain', 'tool', 'soft');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE employment_type AS ENUM ('full-time', 'contract', 'freelance');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE project_status AS ENUM ('completed', 'ongoing');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE session_status AS ENUM ('pending', 'running', 'completed', 'failed');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ------------------------------------------------------------------
-- Skills
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS skills (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,              -- normalized lowercase
    display_name TEXT NOT NULL,                    -- human-readable
    category    skill_category NOT NULL,
    proficiency INTEGER NOT NULL CHECK (proficiency BETWEEN 1 AND 5),
    last_used_date DATE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_skills_category ON skills (category);
CREATE INDEX IF NOT EXISTS idx_skills_name ON skills (name);

-- ------------------------------------------------------------------
-- Projects
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    description     TEXT NOT NULL CHECK (char_length(description) >= 50),
    impact_metric   TEXT,
    start_date      DATE,
    end_date        DATE,
    status          project_status NOT NULL DEFAULT 'completed',
    tech_stack      TEXT[] NOT NULL,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    latex_bullet_cache JSONB NOT NULL DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projects_active ON projects (is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_projects_tech_stack ON projects USING GIN (tech_stack);
CREATE INDEX IF NOT EXISTS idx_projects_tags ON projects USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects (status);
CREATE INDEX IF NOT EXISTS idx_projects_dates ON projects (start_date, end_date);

-- ------------------------------------------------------------------
-- Project-Skill edges (many-to-many)
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS project_skills (
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    skill_id        UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    is_primary_skill BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (project_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_ps_skill ON project_skills (skill_id);
CREATE INDEX IF NOT EXISTS idx_ps_primary ON project_skills (project_id, is_primary_skill)
    WHERE is_primary_skill = true;

-- ------------------------------------------------------------------
-- Roles (work experience)
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roles (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name        TEXT NOT NULL,
    role_title          TEXT NOT NULL,
    start_date          DATE NOT NULL,
    end_date            DATE,                          -- NULL = current position
    location            TEXT,
    employment_type     employment_type NOT NULL DEFAULT 'full-time',
    base_responsibilities TEXT[] NOT NULL DEFAULT '{}',
    is_active           BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_roles_active ON roles (is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_roles_dates ON roles (start_date DESC, end_date DESC NULLS FIRST);

-- ------------------------------------------------------------------
-- Role-Project edges (many-to-many)
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS role_projects (
    role_id     UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, project_id)
);

CREATE INDEX IF NOT EXISTS idx_rp_project ON role_projects (project_id);

-- ------------------------------------------------------------------
-- Certifications & Publications
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS certifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    year        INTEGER,
    description TEXT,
    url         TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------
-- Sessions (application-level, not LangGraph checkpoints)
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    session_key         CHAR(64) NOT NULL,
    session_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jd_profile          JSONB,
    selected_project_ids UUID[] NOT NULL DEFAULT '{}',
    selected_role_ids   UUID[] NOT NULL DEFAULT '{}',
    covered_skills      JSONB,
    uncovered_skills    JSONB,
    blob_path           TEXT,
    status              session_status NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sessions_key ON sessions (session_key);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions (status);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions (created_at);

-- ------------------------------------------------------------------
-- Updated-at triggers (auto-set on row modification)
-- ------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    CREATE TRIGGER trg_skills_updated
        BEFORE UPDATE ON skills
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_projects_updated
        BEFORE UPDATE ON projects
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_roles_updated
        BEFORE UPDATE ON roles
        FOR EACH ROW EXECUTE FUNCTION update_timestamp();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

COMMIT;
