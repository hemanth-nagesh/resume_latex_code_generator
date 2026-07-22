# Resume AI Builder — Implementation Plan & Status

## Project Overview

An AI-powered resume tailoring system. User pastes a job description → the system matches it against a personal knowledge graph (projects, skills, roles in PostgreSQL) → Gemini generates tailored section content constrained to custom LaTeX commands → content is inserted into a locked master .tex template via string substitution → compiled to PDF via pdflatex → delivered via SSE streaming to a React frontend.

**Stack:** FastAPI (Python) + LangGraph + Gemini 2.5 Pro + Azure CosmosDB PostgreSQL + Azure Blob Storage + React (TypeScript, Vite)

**Key constraint:** Gemini never touches the LaTeX template preamble — only fills strictly-typed content slots.

**Infrastructure:** Azure CosmosDB PostgreSQL (B1ms) + Azure Blob Storage (`resume-archive` container with `resumes/{company}/{role}/{sessionKey}/` versioning)

---

## Phase Status Summary

| Phase | What | Status |
|-------|------|--------|
| 0 | Project scaffold, Docker, Azure provisioning, cross-cutting abstractions | ✅ COMPLETE |
| 1 | Locked master template with strictly-typed content slots | ✅ COMPLETE |
| 2 | PostgreSQL schema (7 tables), seed data, admin CRUD, N4 loader | ✅ COMPLETE |
| 3 | LangGraph N1–N6 (core pipeline nodes with Gemini Call 1) | ✅ COMPLETE |
| 4 | LangGraph N7a–N7d (4 parallel section generators, Gemini Calls 2–5) | ✅ COMPLETE |
| 5 | N8 assembler + N9 validator (custom command schema) + N9r fixer (Call 6) | ✅ COMPLETE |
| 6 | N10 pdf_compiler + N10f fallback + N11 persister + N12 response | ✅ COMPLETE |
| 7 | FastAPI routes (POST /generate, SSE /stream) + full graph wiring | ✅ COMPLETE |
| 8 | React frontend (IndexedDB cache, SSE step tracker, PDF download) | ✅ COMPLETE |
| 9 | React admin panel (Projects, Skills, Roles, Certifications CRUD) | 🔲 Pending |
| 10 | Azure packaging + CI/CD + Tests | 🔲 Pending |

**Current test count:** 39 passing (21 Phase 0 + 18 Phase 1) + 24 Phase 2 tests written (verified via direct DB scripts)

---

## Phase 0: Foundation & Project Setup ✅

### Files Created

**Backend infrastructure:**

| File | Purpose | Status |
|------|---------|--------|
| `server/config.py` | Pydantic-settings config with Azure CosmosDB PG + Blob Storage. Supports both `AZURE_COSMOSDB_PG_URL` (primary) and `DATABASE_URL` (legacy). URL-encoding aware for Azure SSL. | ✅ |
| `server/container.py` | Lazy DI container (Abstract Factory pattern) for GeminiClient, BlobClient, DatabasePool. Singleton lifecycle with `dispose()`. | ✅ |
| `server/main.py` | FastAPI factory with lifespan (startup pre-fetches template), CORS, global exception handler, health check at `/health`. | ✅ |
| `server/services/logger.py` | Structured JSON logging with correlation IDs. | ✅ |
| `server/services/gemini.py` | Gemini client wrapper — retries, timeout enforcement, JSON parsing, backoff. All 6 nodes use this single instance. | ✅ |
| `server/services/blob.py` | Async Blob Storage client — template fetch, versioned resume archival (`resumes/{company}/{role}/{sessionKey}/`), streaming, list/navigate. | ✅ |
| `server/services/database.py` | asyncpg connection pool with `@asynccontextmanager` transaction support, `_to_date()` for Azure date format compatibility. | ✅ |
| `server/services/latex_utils.py` | Pure functions: escape/unescape special chars, brace balance, environment matching, placeholder check, custom command arg parser, LaTeX stripper. | ✅ |
| `server/services/types.py` | Shared types: 17 `NodeId` enums, SSE event models (session_ready, node_start, node_complete, node_error, complete, heartbeat), JDProfile, KnowledgeGraph, SectionConfig, SessionRecord. | ✅ |
| `server/graph/state.py` | LangGraph `ResumeState` TypedDict with `Annotated[list, operator.add]` reducers for parallel fan-in nodes. | ✅ |
| `server/graph/graph.py` | Full DAG topology — 17 nodes, 2 parallel fan-outs (N3+N4, N7a-N7d), conditional routing (validation/fix/fallback), stub node registration. | ✅ |
| `server/graph/n1_session.py` through `n12_response.py` | 17 node stubs (each a single `async def run(state) -> state` function). | ✅ |
| `server/api/generate.py` | `POST /api/generate` stub | ✅ |
| `server/api/stream.py` | `GET /api/stream/{session_id}` SSE stub | ✅ |
| `server/api/resume.py` | `GET /api/resume/{session_key}` stub | ✅ |
| `server/api/admin.py` | 22 admin CRUD endpoints for skills, projects, roles, certifications (Phase 2) | ✅ |
| `server/Dockerfile` | Based on `texlive/texlive:latest` with pdflatex | ✅ |
| `server/pyproject.toml` | All Python deps (fastapi, langgraph, google-genai, asyncpg, azure-storage-blob, pydantic-settings) | ✅ |
| `server/requirements.txt` | Pip-compatible requirements | ✅ |

**Frontend infrastructure:**

| File | Purpose | Status |
|------|---------|--------|
| `client/package.json` | React 19 + idb + Vite + TypeScript | ✅ |
| `client/src/types/index.ts` | Full TypeScript interfaces (JDProfile, Project, Skill, Role, SectionConfig, SSE events, DraftData, CachedPDF) | ✅ |
| `client/src/services/cache.ts` | IndexedDB via `idb` — drafts (7d TTL), sessions (6h TTL), PDFs (7d TTL) | ✅ |
| `client/src/services/sessionKey.ts` | `crypto.subtle.digest('SHA-256')` deterministic key | ✅ |
| `client/src/services/api.ts` | `postGenerate()`, `openSSE()` with EventSource | ✅ |
| `client/src/hooks/useCache.ts` | Draft auto-load, session key recompute on input change, cached PDF check | ✅ |
| `client/src/hooks/useSSE.ts` | SSE event dispatch, node status tracking, base64→download flow | ✅ |
| `client/src/App.tsx` | Full UI: JD textarea (500ms debounce), section selector (checkboxes + max count slider + matched-only toggle), step tracker, download/regenerate | ✅ |

**Infrastructure:**

| File | Purpose | Status |
|------|---------|--------|
| `.env` | Active config filled with Azure CosmosDB PG URL + Blob Storage connection string + Gemini API key placeholders | ✅ |
| `.env.example` | Template with URL-encoding cheat sheet | ✅ |
| `docker-compose.yml` | Server + Client only (PostgreSQL is cloud-hosted on Azure) | ✅ |
| `AZURE_SETUP.md` | Step-by-step Azure provisioning guide (CosmosDB PG + Blob Storage) | ✅ |
| `.gitignore` | Python, Node, Docker, Azure exclusions | ✅ |

**Test results:** 21/21 passing (config validation, LaTeX utils, type models, node stub coverage)

---

## Phase 1: Locked Master Template ✅

### What was built

**`template/master_resume.tex`** — The single source of truth for all LaTeX formatting:
- 140-line preamble (fonts, colors, spacing, margins, packages) — **Gemini never touches this**
- 6 strictly-typed content slots:
  - `%%SUMMARY_TEXT%%` — plain text only, no LaTeX commands
  - `%%EXPERIENCE_BLOCK%%` — only `\resumeSubheading{4args}` + `\resumeItemListStart/End` + `\resumeItem{1arg}`
  - `%%PROJECTS_BLOCK%%` — only `\resumeProjectHeading{2args}` + `\resumeItemListStart/End` + `\resumeItem{1arg}`
  - `%%SKILLS_BLOCK%%` — only `\textbf{Category}{: skills} \\ \vspace{2pt}` blocks
  - `%%EDUCATION_BLOCK%%` — `\resumeSubheading{4args}` (static, not AI-generated)
  - `%%CERTIFICATIONS_BLOCK%%` — `\item[] \textbf{Title} (year)` blocks
- Comment lines use "CONTENT SLOT:" phrasing (never `%%SLOTNAME%%`) → `str.replace()` can't accidentally touch comments
- Environment wrappers (`\resumeSubHeadingListStart/End`, `\resumeItemListStart/End`) stay locked in template — never generated by Gemini

**`server/graph/n9_validator.py`** — Custom command schema hardcoded:
```python
CUSTOM_COMMAND_SCHEMA = {
    r"\resumeItem":           1,   # {bullet text}
    r"\resumeSubheading":     4,   # {title}{date}{company}{location}
    r"\resumeSubSubheading":  2,   # {title}{date}
    r"\resumeProjectHeading": 2,   # {title}{date}
    r"\resumeSubItem":        1,   # {bullet text}
}
```

**Key constraints verified by tests:**
- Preamble contains ZERO content slot markers (validated programmatically)
- Each slot appears exactly once in the body
- All 5 custom commands defined in the preamble
- Sections follow correct order (Summary → Experience → Projects → Skills → Education → Certifications)
- `str.replace()` preserves preamble byte-identical after substitution
- N9 catches: wrong argument counts, unbalanced braces, empty sources

**Test results:** 18/18 passing (template structure, slot integrity, substitution, schema validation)

---

## Phase 2: Knowledge Graph Database ✅

### Azure CosmosDB PostgreSQL Instance

| Detail | Value |
|--------|-------|
| Host | `c-resume-postgresql-db.piaqqg3q7g4uh5.postgres.cosmos.azure.com` |
| User/Database | `citus` / `citus` |
| SSL | Required (`sslmode=require`) |
| Connection string | `postgresql://citus:****@c-resume-postgresql-db.piaqqg3q7g4uh5.postgres.cosmos.azure.com:5432/citus?sslmode=require` |

### Schema (7 tables, all with indexes)

| Table | Rows | Key Indexes |
|-------|------|-------------|
| `skills` | 39 | GIN on name, index on category |
| `projects` | 6 | GIN on tech_stack + tags, indexes on status/dates |
| `project_skills` | 28 | Indexes on skill_id, primary skills |
| `roles` | 2 | Indexes on active, date range (NULLS FIRST) |
| `role_projects` | 0 | Index on project_id |
| `certifications` | 2 | Standard |
| `sessions` | 1 | Indexes on session_key, status, created_at |

**Migration file:** `server/db/migrations/001_initial_schema.sql` — idempotent, uses `IF NOT EXISTS` / `DO $$` blocks
**Migration runner:** `server/db/migrations.py` — executes SQL files in order, each wrapped in a transaction

### Seed Data (from `E_Hemanth_Nagesh.tex`)

**39 Skills** across 6 categories:
- Backend Development (7): Python, FastAPI, REST APIs, Microservices, Docker, Kubernetes, Git, CI/CD Pipelines
- Databases (7): PostgreSQL, MySQL, MongoDB, Redis, Vector Databases, Time-Series Databases
- Data Processing (5): Pandas, NumPy, SQLAlchemy, Matplotlib, Data Preprocessing, Feature Engineering
- ML Algorithms & Deep Learning (8): Regression, Classification, Clustering, CNNs, RNNs, Transformers, GANs, Fine-tuning, Hyperparameter Optimization
- Gen AI & Agentic AI (6): LangGraph, RAG Pipelines, Prompt Engineering, Fine-tuning, Multimodal LLMs, ReAct Patterns, MCP Servers
- Cloud & MLOps (6): Azure AI Studio, AWS, LLMOps, LLM-as-Judge, Microservices

**6 Projects** with 28 skill links:
- Enterprise AI Copilot & Multi-Agent Orchestration Platform (2025–present) — 6 skills linked
- AI Copilot for Accessible Code Generation (2024–2025) — 3 skills linked
- Automated Document Verification Engine (2023–2024) — 3 skills linked
- GenAI Internal Automation & Dialogue Systems (2023–2024) — 3 skills linked
- ML-Based Predictive Analytics Platform (2024) — 6 skills linked
- Backend API Gateway & Microservices Architecture (2024) — 7 skills linked

**2 Roles:**
- AI/ML & Prompt Engineer at Tata Consultancy Services (Dec 2023–Present)
- AI Engineer Intern at BOTSIO Chatbot LLP (Mar 2023–May 2023)

**2 Certifications:**
- Microsoft Certified: Azure AI Engineer Associate (2026)
- AI-Powered Information Retrieval Systems (2023)

### Database Layer Code

| File | Purpose | Status |
|------|---------|--------|
| `server/db/migrations.py` | Idempotent migration runner | ✅ |
| `server/db/migrations/001_initial_schema.sql` | 4 enums, 7 tables, GIN indexes, triggers | ✅ |
| `server/db/queries.py` | Full raw SQL: 4 CRUD submodules + sessions + bullet cache + `load_full_knowledge_graph()` | ✅ |
| `server/db/seed.py` | Brace-group parser extracts data from .tex, seeds all tables, idempotent | ✅ |
| `server/graph/n4_kg_loader.py` | LangGraph node: calls `load_full_knowledge_graph()`, populates `state.kg_snapshot` | ✅ |
| `server/api/admin.py` | 22 CRUD endpoints: skills, projects, roles, certifications + edge operations | ✅ |

### Verification Results

- Schema migrations run idempotently ✅
- Seed script fully idempotent (all existing records skipped on re-run) ✅
- N4 loader returns complete knowledge graph in <1s ✅
- Session create → find → complete lifecycle works ✅
- `complete_session()` stores JSONB fields (selected_project_ids, covered_skills) ✅
- Projects have aggregated skills arrays via JOIN ✅
- Roles have aggregated project_ids via LEFT JOIN ✅

### Known Issues Fixed

1. `asyncpg` requires `datetime.date` objects, not strings → Added `_to_date()` converter
2. PostgreSQL 16 rejects `ORDER BY` in `array_agg(DISTINCT ...)` → Removed inner ORDER BY
3. Sessions table has `last_updated` (not `updated_at`) → Removed auto-update trigger
4. LaTeX `\textbf{}` and `\&` in section content broke regex → Replaced with brace-group parser
5. Docker daemon not available locally → Switched to Azure CosmosDB PostgreSQL directly

---

## Phase 3: LangGraph N1–N6 (Core Pipeline) 🔲

### To be built
- **N1 (session_validator):** SHA256 key computation, session lookup/creation, LangGraph checkpoint restore
- **N2 (input_parser):** JD validation (100-15K chars), HTML strip, sections schema validation
- **N3 (jd_analyzer):** Gemini Call 1 — structured JD profile extraction, `gemini-1.5-pro`, temp=0.2, JSON schema enforcement
- **N4 (kg_loader):** ✅ Already built — loads full knowledge graph
- **N5 (project_scorer):** Weighted scoring (60% skill match + 25% keyword overlap + 15% recency)
- **N6 (content_selector):** Greedy set-cover algorithm for optimal project selection

---

## Phase 4: Section Generators N7a–N7d 🔲

### To be built
- **N7a (summary_gen):** Gemini Call 2 — 3-sentence plain text, blacklisted phrases, ats_keywords
- **N7b (experience_gen):** Gemini Call 3 — `\resumeSubheading`+`\resumeItem` format enforced in prompt
- **N7c (projects_gen):** Gemini Call 4 — `\resumeProjectHeading`+`\resumeItem` format, bullet cache check
- **N7d (skills_gen):** Gemini Call 5 — `\textbf{}{}` format, deterministic grouping + name normalization

---

## Phase 5: LaTeX Assembly & Validation 🔲

### To be built
- **N8 (latex_assembler):** Template fetch + `str.replace()` substitution, `escape_special_chars()`
- **N9 (latex_validator):** ✅ Already built — 5 parallel checks including custom command schema
- **N9r (latex_fixer):** Gemini Call 6 — temperature=0.1, fix-only-LISTED-errors, max 2 retries

---

## Phase 6: PDF Compilation & Delivery 🔲

### To be built
- **N10 (pdf_compiler):** pdflatex x2 in temp dir, 30s timeout, exit code check
- **N10f (fallback):** Minimal article-class template, LaTeX command stripping
- **N11 (state_persister):** PostgreSQL upsert, Azure Blob upload (PDF + .tex + metadata), bullet cache update
- **N12 (response_builder):** Base64 encode, SSE complete event, filename generation

---

## Phase 7: API Layer & SSE Streaming 🔲

### To be built
- `POST /api/generate` — validates input, creates session, invokes LangGraph
- `GET /api/stream/{session_id}` — SSE streaming with asyncio.Queue, node callbacks
- Full LangGraph wiring with Send API for parallel branches, PostgresSaver checkpointing

---

## Phase 8: React Frontend — Core Flow 🔲

### Already scaffolded
- All components stubbed (`App.tsx`, `useCache`, `useSSE`, `api.ts`, `cache.ts`, `sessionKey.ts`)
- Full TypeScript types

### To complete
- Wire up to live backend
- Debug SSE event parsing edge cases
- Polish draft restoration UX
- Handle error states

---

## Phase 9: React Admin Panel 🔲

### To be built
- Projects Manager (list, add, edit, soft-delete, link skills)
- Skills Manager (list, add, edit, delete, show project usage)
- Roles Manager (list, add, edit, link projects)
- Certifications Manager (list, add, delete)

---

## Phase 10: Testing & CI/CD 🔲

### To be built
- Unit tests for N5 scorer, N6 set-cover, N9 validator
- Integration tests with mock Gemini
- Docker Compose for local dev (server + client only, DB is cloud)
- GitHub Actions CI/CD to Azure

---

## Architecture Principles Applied

| Principle | How |
|-----------|-----|
| **SOLID - Single Responsibility** | Each LangGraph node does one thing. GeminiClient knows nothing about templates. BlobClient knows nothing about PostgreSQL. |
| **SOLID - Open/Closed** | New section generators can be added without touching N8/N9/N10. Custom command schema is a dict — add entries without changing validator logic. |
| **SOLID - Dependency Inversion** | Container injects dependencies. Nodes receive `db: DatabasePool` via kwargs, never construct their own. |
| **DRY** | Types defined once in `services/types.py`. Queries centralized in `db/queries.py`. Single `CUSTOM_COMMAND_SCHEMA` in N9. |
| **KISS** | `str.replace()` for template assembly, not Jinja/PyLaTeX. Raw SQL via asyncpg, not an ORM. Regex + stack parsing for LaTeX validation. |
| **Cross-cutting concerns** | Logging (structured JSON), error handling (global handler in FastAPI), date conversion (`_to_date()`), escaping (`escape_special_chars()`) — all centralized. |
| **Factory Pattern** | `Container` lazily creates GeminClient, BlobClient, DatabasePool on first access. `create_app()` is the FastAPI factory. |
| **Template Lock** | Master .tex template is read-only. Gemini receives verbatim format examples in prompts. N9 validates custom command signatures. Gemini never writes structural LaTeX. |
