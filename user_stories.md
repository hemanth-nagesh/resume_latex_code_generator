# Resume Tailoring App — Detailed Architecture User Stories

## Stack Decisions (No Confirmation Needed)
- **App Server:** FastAPI (Python) — LangGraph is Python-native; zero impedance mismatch
- **Orchestration:** LangGraph stateful graph with checkpointing
- **AI:** Gemini API — multiple targeted calls (6 total across happy path)
- **Knowledge Graph DB:** Azure Database for PostgreSQL Flexible Server — JSONB + relational handles graph queries without a dedicated graph DB overhead; free tier sufficient for personal use
- **File Storage:** Azure Blob Storage — PDFs, compiled LaTeX, template versions
- **Browser Cache:** IndexedDB (via `idb` library) — survives tab close, holds binary blobs, queryable
- **Cache Key Strategy:** `SHA256(sorted_sections.join(',') + jd_text_trimmed)` — deterministic per unique input combination

---

## LangGraph Node Map (Reference for All Stories)

```
[N1]  session_validator
[N2]  input_parser
[N3]  jd_analyzer          ← Gemini Call 1       ┐ PARALLEL
[N4]  kg_loader             ← PostgreSQL query    ┘
[N5]  project_scorer
[N6]  content_selector
                            ┌─ [N7a] summary_gen     ← Gemini Call 2 ┐
                            ├─ [N7b] experience_gen  ← Gemini Call 3 │ PARALLEL
                            ├─ [N7c] projects_gen    ← Gemini Call 4 │
                            └─ [N7d] skills_gen      ← Gemini Call 5 ┘
[N8]  latex_assembler        ← Template-locked, string substitution only; no PyLaTeX
[N9]  latex_validator       ← Generic LaTeX checks + custom command schema validation
        └── [N9r] latex_fixer ← Gemini Call 6 (conditional, max 2 retries)
[N10] pdf_compiler
        └── [N10f] fallback_template_handler (conditional)
[N11] state_persister
[N12] response_builder
```

**Parallel Opportunities:**
- N3 + N4 run together (JD analysis does not need KG; KG load does not need JD result)
- N7a + N7b + N7c + N7d all run together after N6 selects content
- N9 static validation checks across LaTeX sections can be parallelized internally

---

---

# EPIC 1 — Browser Session & Caching

**Goal:** User never has to re-paste JD or re-select sections when returning after a closed tab or network failure.

---

### US-1.1 — Persist JD Input and Section Selections on Entry

**As a user**, I want my JD text and selected sections saved to browser storage the moment I type/paste them, so if I close the tab mid-workflow, nothing is lost.

**Acceptance Criteria:**
- Given I paste JD text into the input field, when I stop typing for 500ms (debounce), then the JD text is written to IndexedDB under key `draft:jd_text`
- Given I toggle any section checkbox (Summary, Experience, Projects, Skills), when the toggle fires, then the current full sections array is written to IndexedDB under `draft:sections`
- Given the app reloads, when IndexedDB contains a `draft:jd_text` value, then the JD field is pre-populated and a "Resume last draft?" banner is shown
- The banner shows the timestamp of when the draft was last saved
- Draft data expires after 7 days (TTL stored alongside the value)

**Technical Notes — LangGraph Node:** N/A (client-side only)
- Use `idb` wrapper over IndexedDB; avoid raw IDB API
- Write is async but non-blocking to UI; fire-and-forget with silent error catch
- Store schema: `{ jd_text: string, sections: string[], saved_at: ISO_timestamp, ttl_days: 7 }`

---

### US-1.2 — Cache Partial Pipeline Progress Per Unique Input

**As a user**, I want the app to remember how far the generation pipeline got for my specific JD + sections combination, so if the server completes some nodes before I close, those results are not re-computed when I return.

**Acceptance Criteria:**
- Given the server starts processing, when each LangGraph node completes, then the server sends a server-sent event (SSE) with `{ node_id, node_name, output, session_key }`
- Given the client receives a node completion event, when it arrives, then it writes the node output to IndexedDB under `session:{session_key}:node:{node_id}`
- Given I return to the app with the same JD and sections, when I click Generate, then the client sends the session_key and the list of already-completed node IDs to the server
- Given the server receives completed node IDs, then it restores LangGraph state from those checkpoints and resumes from the first incomplete node
- If more than 6 hours have passed since the session was created, the session is treated as stale and restarted fresh

**Technical Notes — LangGraph Node:** N1 (session_validator)
- Session key = `SHA256(jd_text.trim() + sections.sort().join(','))` computed client-side before API call
- Server stores LangGraph checkpoint state in PostgreSQL `sessions` table (LangGraph has built-in PostgreSQL checkpointer support via `langgraph-checkpoint-postgres`)
- Client sends `{ session_key, completed_nodes: [] }` in request body
- N1 queries PostgreSQL for checkpoint; if found and fresh, restores graph state and skips completed nodes

---

### US-1.3 — Cache Final Generated PDF for Instant Re-download

**As a user**, I want the final PDF stored in my browser so I can re-download it without triggering the full pipeline again, for as long as the JD + sections combination hasn't changed.

**Acceptance Criteria:**
- Given the pipeline completes and returns a PDF, when the client receives the base64 PDF, then it stores the blob in IndexedDB under `session:{session_key}:pdf`
- Given I return to the app with the same JD and sections loaded from draft cache, when I click Generate, then the client checks IndexedDB for an existing PDF under that session key before making any server request
- Given a cached PDF exists and is less than 7 days old, then the app renders a "Download Previous Result" button without hitting the server
- Given I explicitly click "Regenerate" (a separate button), then the cache for that session key is cleared and a fresh server request is made
- PDF blob TTL is 7 days, matching draft TTL

**Technical Notes — LangGraph Node:** N/A (client-side) and N12 (response_builder returns metadata for cache tagging)
- Store as ArrayBuffer in IndexedDB (not base64 string) to avoid memory overhead
- `{ pdf_blob: ArrayBuffer, generated_at: ISO_timestamp, session_key: string, jd_preview: string (first 120 chars) }`
- On load, display cached results as a dismissible card above the main form

---

### US-1.4 — Cache Invalidation on Input Change

**As a user**, I want the cache to be automatically invalidated if I change anything in the JD or sections, so I never accidentally download an outdated resume.

**Acceptance Criteria:**
- Given a cached PDF exists for session key X, when I modify any character in the JD text, then the client recomputes the session key and it changes to Y
- Given the session key changes, then the "Download Previous Result" button disappears and the "Generate" button is shown
- Given I restore the original JD text (undo), then key X is restored and the cached PDF reappears
- Deletion of all IndexedDB entries for a session key is triggered only when TTL expires or user clicks "Clear All Cache" in a settings panel

**Technical Notes:** Pure client-side key recomputation on every debounced input change; no server call needed

---

---

# EPIC 2 — Input Ingestion & Validation

**Goal:** Clean, validated input reaches the pipeline; garbage in is caught before a single Gemini token is spent.

---

### US-2.1 — JD Text Ingestion and Pre-Validation

**As a user**, I want the app to validate my JD input before sending it to the server, so I don't waste time waiting for a pipeline that will fail due to bad input.

**Acceptance Criteria:**
- Given I paste text into the JD field, when the text is less than 100 characters, then a warning "JD seems too short — accuracy may be low" is shown (non-blocking)
- Given the text exceeds 15,000 characters, then the field shows a "JD is very long — the system will use the most relevant portions" notice
- Given the JD field is empty and I click Generate, then the button is disabled and a red inline error "Paste a job description first" is shown
- Given valid JD text is present, when I click Generate, then the JD text is sent to the server as plain text with no pre-processing strip (preserve formatting for the JD analyzer node)

**Technical Notes — LangGraph Node:** N2 (input_parser)
- Server-side N2 also validates: strips HTML tags if pasted from browser, normalises Unicode whitespace, trims to 12,000 tokens if needed (Gemini 1.5 Pro context window is large but cost is proportional)
- N2 outputs: `{ jd_raw: string, jd_cleaned: string, char_count: int, estimated_tokens: int }`

---

### US-2.2 — Section Selection with Defaults and Lock Rules

**As a user**, I want to select which sections of my resume to generate or update, with sensible defaults, so I have control over what gets overwritten.

**Acceptance Criteria:**
- Given the app loads, then Summary, Experience, Projects, and Skills are selected by default
- Given I deselect all sections, then the Generate button is disabled with error "Select at least one section"
- Given I select Projects section, then a sub-option "Max projects to include" (slider: 2–6, default 4) is shown
- Given I select Experience section, then a sub-option "Include only JD-matched roles" toggle is shown (default: on)
- The sections array sent to server is exactly the user's selection with any sub-options embedded: `[{ name: "projects", max_count: 4 }, { name: "experience", matched_only: true }]`

**Technical Notes — LangGraph Node:** N2 (input_parser)
- N2 validates sections array schema; rejects unknown section names
- N2 outputs: `{ sections: SectionConfig[], validation_passed: bool }`

---

---

# EPIC 3 — JD Deep Analysis

**Goal:** Extract a structured, machine-usable JD profile that every downstream node can use with precision instead of re-interpreting raw JD text.

---

### US-3.1 — Structured JD Profile Extraction (Gemini Call 1)

**As a system**, I need the JD text converted into a structured profile that identifies exactly what the employer is optimizing for, so every section generator uses the same signal.

**Acceptance Criteria:**
- Given cleaned JD text from N2, when N3 calls Gemini, then the response is a validated JSON object with schema:
  ```
  {
    required_skills: [{ skill: string, is_technical: bool, ats_exact_phrase: string }],
    preferred_skills: [{ skill: string, is_technical: bool }],
    seniority_level: "junior" | "mid" | "senior" | "lead" | "staff",
    domain: string,
    industry: string,
    role_type: string,
    ats_keywords: string[],
    company_values: string[],
    red_flags_to_avoid: string[]
  }
  ```
- Given Gemini returns malformed JSON, then N3 retries once with an explicit "respond only in valid JSON, no markdown fences" instruction added
- Given two retries both fail, then N3 raises a pipeline error and the session is marked failed with reason "JD analysis failed"
- N3 must complete in under 15 seconds; if it exceeds this, the node times out and retries once

**Technical Notes — LangGraph Node:** N3 (jd_analyzer)
- Gemini model: `gemini-1.5-pro` (not flash — accuracy over speed as per requirement)
- System prompt strategy: role-play as "a senior technical recruiter who has screened 10,000 resumes for ATS systems"; give explicit JSON schema in prompt; set temperature=0.2 for consistency
- Output is stored in LangGraph state as `state.jd_profile`
- N3 runs in parallel with N4; uses `asyncio.gather` in the LangGraph node executor

---

### US-3.2 — ATS Keyword Prioritisation

**As a system**, I need to know which exact phrases (not paraphrases) from the JD are likely used by ATS scanners, so section generators embed them verbatim.

**Acceptance Criteria:**
- Given the JD profile is produced by N3, then `ats_keywords` contains only phrases that appear verbatim or near-verbatim in the JD (not inferred synonyms)
- Given `ats_keywords` contains more than 20 items, then N3 trims to top 20 ranked by frequency of appearance in the JD text
- Each keyword in the list must be 1–4 words; single-character strings are rejected at validation
- The `ats_keywords` array is passed as a separate field to all section generators (N7a–N7d) with explicit instruction to embed at least 60% of them across the generated content

**Technical Notes:** This is a sub-output of US-3.1; no separate Gemini call. The ranking by frequency is computed in N3 post-processing after JSON is received, using simple string matching against `jd_cleaned`.

---

---

# EPIC 4 — Knowledge Graph Management

**Goal:** The PostgreSQL database holds all your career data as a queryable graph; the pipeline selects the most relevant subset, not all of it.

---

### US-4.1 — Project Node Schema and CRUD

**As a user**, I want to store each of my projects with enough metadata that the scoring system can match them to any JD, without me having to re-enter details each time.

**Acceptance Criteria:**
- Each project record contains: `id, title, description (long), impact_metric (quantified result), start_date, end_date, status (completed/ongoing), tech_stack: string[], tags: string[], latex_bullet_cache: jsonb`
- Given I add a new project, then the system requires at minimum: title, description (>50 chars), at least one tech_stack entry
- Given I update a project description, then the `latex_bullet_cache` for that project is cleared (set to null) since existing generated bullets are now stale
- Projects are never deleted; they are soft-deleted with `is_active: bool` so scoring can still reference history for context

**Technical Notes:**
- PostgreSQL table: `projects` with GIN index on `tech_stack` array column for fast skill-match queries
- `latex_bullet_cache` stores the last-generated LaTeX bullets per JD profile hash; structure: `{ [jd_profile_hash]: { bullets: string[], generated_at: timestamp } }`
- CRUD is a separate admin endpoint in FastAPI; not part of the LangGraph pipeline

---

### US-4.2 — Skill Node Schema and Project-Skill Edges

**As a user**, I want each skill I have to be stored with a category and linked to the projects that demonstrate it, so the system can prove skills through projects rather than just listing them.

**Acceptance Criteria:**
- Skill record: `id, name (normalized lowercase), category: "technical" | "domain" | "tool" | "soft", proficiency: 1–5, last_used_date`
- Project-Skill edge table: `project_id, skill_id, is_primary_skill: bool` (primary = the project was mainly about this skill, not just incidentally used)
- Given a new project is added, then I must tag at least one primary skill from the existing skills list
- Given I query "projects that demonstrate skill X," then only projects where `is_primary_skill = true` for skill X are returned as primary matches; others are returned as secondary matches

**Technical Notes — LangGraph Node:** N4 (kg_loader)
- N4 query: `SELECT p.*, array_agg(s.name) as skills FROM projects p JOIN project_skills ps ON p.id = ps.project_id JOIN skills s ON ps.skill_id = s.id WHERE p.is_active = true GROUP BY p.id`
- Full graph loaded into LangGraph state as `state.kg_snapshot` — not queried repeatedly during pipeline
- N4 runs in parallel with N3 (no dependency between them)

---

### US-4.3 — Role Node Schema for Experience Section

**As a user**, I want each job role I have held to be stored separately from projects, so the experience section can be generated with accurate company/title/date information.

**Acceptance Criteria:**
- Role record: `id, company_name, role_title, start_date, end_date (nullable for current), location, employment_type: "full-time" | "contract" | "freelance", project_ids: int[] (FK to projects that belong to this role), base_responsibilities: text[]`
- Given a role is linked to projects, then the experience generator (N7b) uses those project outputs to build achievement bullets under that role's LaTeX block
- Given a role has no linked projects, then `base_responsibilities` is used as fallback content for that role's bullets

**Technical Notes:** PostgreSQL table `roles`; linked to `projects` via `role_projects` join table. N4 loads roles alongside projects in the same query batch.

---

### US-4.4 — Project Scoring Against JD Profile

**As a system**, I need to score each project in the knowledge graph against the extracted JD profile, so only the most relevant projects are passed to content generators.

**Acceptance Criteria:**
- Given `state.jd_profile` and `state.kg_snapshot` are both available, when N5 runs, then each project is scored using:
  ```
  skill_match_score  = (matched_required_skills / total_required_skills) × 0.6
  keyword_overlap    = (project_tags ∩ ats_keywords / ats_keywords.length) × 0.25
  recency_score      = normalise(end_date or present) × 0.15
  total_score        = skill_match_score + keyword_overlap + recency_score
  ```
- Given all projects are scored, then N5 outputs the ranked list with scores in `state.ranked_projects`
- Projects with `total_score < 0.1` are excluded from the ranked list entirely (they add noise, not signal)

**Technical Notes — LangGraph Node:** N5 (project_scorer)
- Pure Python computation; no AI call, no DB call (all data is in LangGraph state already)
- Skill matching: compare `project.tech_stack` array against `jd_profile.required_skills[].ats_exact_phrase` using normalized lowercase comparison
- Recency normalization: `(end_date - oldest_date_in_portfolio) / (today - oldest_date_in_portfolio)`, clipped to [0,1]

---

### US-4.5 — Optimal Project Combination Selection

**As a system**, I need to select the final set of projects that maximises JD skill coverage, not just picks the top-N individually highest-scoring projects, since two high-scoring projects can cover the same skills.

**Acceptance Criteria:**
- Given `state.ranked_projects` and `sections.projects.max_count` (user-defined, default 4), when N6 runs, then it uses a greedy set-cover selection:
  1. Pick the highest-scoring project
  2. Remove the skills it covers from the uncovered set
  3. Re-score remaining projects against uncovered skills only
  4. Repeat until max_count reached or all required skills are covered
- Given two projects tie in score, then the more recent one is selected
- N6 outputs `state.selected_projects` (final project objects) and `state.covered_skills` (skills now covered)
- N6 also outputs `state.uncovered_skills` — required JD skills not demonstrated by any project; this list is passed to N7d (skills generator) so it handles them in the skills section differently

**Technical Notes — LangGraph Node:** N6 (content_selector)
- Pure Python; greedy set-cover is O(n×k) where n = projects, k = skills — negligible for personal resume scale
- Also selects experience roles: if `matched_only = true` in section config, only roles whose `project_ids` contain at least one selected project are included
- Outputs: `state.selected_roles`, `state.selected_projects`, `state.covered_skills`, `state.uncovered_skills`, `state.selected_skills_ordered` (skills list sorted by JD match rank)

---

---

# EPIC 5 — LangGraph Pipeline Orchestration

**Goal:** The pipeline is explicit, resumable, parallelised correctly, and every state transition is logged for debugging and caching.

---

### US-5.1 — Session Initialisation and Graph State Bootstrap

**As a system**, I need every pipeline run to have a unique session, a shared state object, and a PostgreSQL-backed checkpoint, so the graph can be resumed or debugged at any node.

**Acceptance Criteria:**
- Given a new request arrives at `POST /generate`, when N1 runs, then it checks PostgreSQL `sessions` table for an existing session matching the `session_key` and `created_at > (now - 6 hours)`
- Given no session exists, then N1 creates a new session row, initialises LangGraph state with `{ session_key, jd_raw, sections, node_statuses: {}, outputs: {} }`, and returns `session_id` to the client
- Given a valid session exists, then N1 restores the LangGraph checkpoint state and sets `resume_from_node` in the state to the first node with status not "completed"
- Given N1 completes, then a server-sent event `{ event: "session_ready", session_id, resume_from }` is pushed to the client

**Technical Notes — LangGraph Node:** N1 (session_validator)
- Use LangGraph's `PostgresSaver` checkpointer: `from langgraph.checkpoint.postgres import PostgresSaver`
- `sessions` table: `session_key CHAR(64), session_id UUID, created_at TIMESTAMP, last_updated TIMESTAMP, status TEXT, langgraph_thread_id UUID`
- SSE stream opened at `GET /stream/{session_id}`; client opens this before clicking Generate

---

### US-5.2 — Parallel Execution of JD Analyzer and KG Loader

**As a system**, I need N3 and N4 to run simultaneously since they have no dependency on each other, to reduce total pipeline latency.

**Acceptance Criteria:**
- Given N2 (input_parser) completes, when the graph transitions to the next stage, then N3 and N4 are dispatched concurrently using `asyncio.gather`
- Given N3 completes before N4, then N3 waits for N4 before proceeding (fan-in at N5)
- Given N4 completes before N3, then N4 waits for N3 before proceeding (fan-in at N5)
- Given either N3 or N4 fails, then the entire parallel branch is aborted and a pipeline error is raised; the failed node is marked in `node_statuses`
- Client receives SSE events for each node independently: `{ event: "node_complete", node: "jd_analyzer" }` and `{ event: "node_complete", node: "kg_loader" }` as they each finish

**Technical Notes:**
- LangGraph supports `Send` API for parallel branches; use a fan-out node that dispatches to N3 and N4, and a fan-in conditional edge that waits for both `state.jd_profile` and `state.kg_snapshot` to be non-null before routing to N5

---

### US-5.3 — Parallel Execution of Section Generators

**As a system**, I need all four section generators to run simultaneously after content selection, since they each have independent inputs and outputs.

**Acceptance Criteria:**
- Given N6 completes, when the graph fans out, then N7a, N7b, N7c, and N7d are all dispatched concurrently
- Each section generator receives only its relevant slice of state (not full state) to avoid token waste in prompts:
  - N7a (summary): `jd_profile`, `selected_skills_ordered`, `selected_roles[0]` (most recent)
  - N7b (experience): `jd_profile`, `selected_roles`, `ats_keywords`
  - N7c (projects): `jd_profile`, `selected_projects`, `ats_keywords`, `covered_skills`
  - N7d (skills): `jd_profile`, `selected_skills_ordered`, `uncovered_skills`
- Given all four complete, fan-in at N8 (latex_assembler) waits for all four `state.sections.*` outputs
- Given any single section generator fails, then it is retried once; if retry also fails, that section falls back to a static template populated with raw data (no AI output)

**Technical Notes:** LangGraph `Send` API with `StateGraph` using `Annotated[list, operator.add]` for collecting parallel branch outputs into a list that N8 reads

---

### US-5.4 — Node Status Broadcasting to Client

**As a user**, I want to see which pipeline step is currently running so I know the system is working and roughly how long is left.

**Acceptance Criteria:**
- Given any node starts, then the server emits: `{ event: "node_start", node: string, timestamp: ISO }`
- Given any node completes, then the server emits: `{ event: "node_complete", node: string, duration_ms: int, timestamp: ISO }`
- Given a node fails, then the server emits: `{ event: "node_error", node: string, error: string, will_retry: bool }`
- The React client shows a step tracker UI: each node name with a spinner (running), checkmark (done), or X (failed)
- Parallel nodes (N3+N4, N7a–N7d) show as a grouped row with individual statuses

**Technical Notes:** FastAPI `StreamingResponse` with `text/event-stream` content type; LangGraph node callbacks emit to an `asyncio.Queue` that the SSE endpoint drains

---

---

# EPIC 6 — Per-Section Content Generation

**Goal:** Each section is generated by a focused Gemini call with a precise prompt, using only the relevant context slice, maximising accuracy per token spent.

---

### US-6.1 — Professional Summary Generation (Gemini Call 2 — N7a)

**As a user**, I want the summary section to be a 3-line paragraph that sounds like I wrote it, targeting the specific role, not a generic overview.

**Acceptance Criteria:**
- Given `jd_profile`, `selected_skills_ordered`, and most recent role, when N7a calls Gemini, then the output is exactly 3 sentences:
  1. Who I am + years of experience + domain
  2. What I am specifically strong at that matches this JD
  3. What I bring that is unique (from `company_values` in jd_profile, inverted as my trait)
- Output must contain at least 3 items from `ats_keywords`
- Output must not contain phrases: "passionate about", "results-driven", "team player", "dynamic" (these are explicitly blacklisted in the prompt)
- Output is returned as raw LaTeX paragraph text (no `\section{}` wrapper — assembler adds that)

**Technical Notes — LangGraph Node:** N7a
- Gemini Call 2: model `gemini-1.5-pro`, temperature=0.4 (slightly higher than N3 for natural language variety)
- System prompt: "You are a professional resume writer who has placed 500 engineers at FAANG. Write a resume summary. Respond only with the 3-sentence paragraph — no labels, no preamble, no markdown. Return PLAIN TEXT only. Do not use any LaTeX commands."
- The `%%SUMMARY_TEXT%%` content slot in the master template is plain-text only — no LaTeX structural commands are permitted here
- Output stored in `state.sections.summary` as a raw string (not LaTeX)

---

### US-6.2 — Experience Section Generation (Gemini Call 3 — N7b)

**As a user**, I want each role in my experience section to have 3–5 achievement bullets that use the XYZ format (Accomplished X by doing Y resulting in Z) and embed JD keywords.

**Acceptance Criteria:**
- Given `selected_roles` (1–3 roles) and `ats_keywords`, when N7b calls Gemini, then for each role:
  - 3–5 bullets are generated
  - Each bullet starts with a strong past-tense action verb
  - At least one bullet per role contains a quantified metric (number, percentage, or time saving)
  - At least 2 bullets per role contain verbatim ATS keywords
- Output consists ONLY of `\resumeSubheading{}{}{}{}` and `\resumeItem{}` calls. The `%%EXPERIENCE_BLOCK%%` content slot is strictly typed to accept only these two commands
- Each role block is: one `\resumeSubheading{role_title}{start_date -- end_date}{company_name}{location}` followed by 3–5 `\resumeItem{achievement bullet}` calls
- Given a role has `base_responsibilities` but no linked projects (fallback scenario), then Gemini is given those responsibilities and asked to reframe them as achievement bullets targeting the JD

**Technical Notes — LangGraph Node:** N7b
- Gemini Call 3: temperature=0.3
- Prompt explicitly includes: `ats_keywords` list, role metadata, linked project `impact_metric` fields
- System prompt MUST include verbatim format example:
  ```
  You must use ONLY these LaTeX commands, exactly as shown:
  
  \resumeSubheading{Software Engineer}{Jan 2022 -- Present}{Company Name}{Bengaluru, India}
  
  For each achievement bullet:
  \resumeItem{Achieved 40\% reduction in API latency by migrating to async workers}
  
  Do not use \item, \textbf, \begin{itemize}, \end{itemize}, or any other LaTeX command.
  Return only the \resumeSubheading and \resumeItem blocks. No preamble. No explanations.
  ```
- Each role is sent in a separate user message turn within a single multi-turn Gemini call (not separate API calls) to maintain context about the progression of roles

---

### US-6.3 — Projects Section Generation (Gemini Call 4 — N7c)

**As a user**, I want each selected project to have 2–3 bullets that emphasise the JD-relevant skills from that project and suppress details that are irrelevant to this role.

**Acceptance Criteria:**
- Given `selected_projects` and `covered_skills`, when N7c calls Gemini, then for each project:
  - 2–3 bullets are generated inside one `\resumeProject{title}{all bullets combined}` call
  - Bullet 1: what the project did and the technical skills used (emphasise `covered_skills` that this project contributes)
  - Bullet 2: the method/approach (embed relevant `ats_keywords`)
  - Bullet 3 (optional): outcome with metric from `impact_metric` field
- Skills not in `covered_skills` are not emphasised in the bullets even if they appear in `tech_stack`
- Given `latex_bullet_cache` exists for this project and current `jd_profile_hash`, then N7c uses cached bullets directly (no Gemini call for that project); only generates for projects without a cache hit

**Technical Notes — LangGraph Node:** N7c
- Gemini Call 4: temperature=0.3
- Output consists ONLY of `\resumeProject{project_title}{bullet_text}` calls. The `%%PROJECTS_BLOCK%%` content slot is strictly typed to accept only this command
- System prompt MUST include verbatim format example:
  ```
  You must use ONLY this LaTeX command, exactly as shown:
  
  \resumeProject{Project Title}{Bullet 1: What the project did, emphasizing JD-relevant skills. Bullet 2: Method/approach with ATS keywords. Bullet 3 (optional): Outcome with metric.}
  
  Do not use \item, \textbf, \begin{itemize}, \end{itemize}, or any other LaTeX command.
  Return only the \resumeProject blocks. No preamble. No explanations.
  ```
- Cache check: `project.latex_bullet_cache[jd_profile_hash]` — if exists and generated within 30 days, use cache and update `state.sections.projects` directly; skip Gemini for that project
- Cache hit is stored back to PostgreSQL `projects` table after N11 (state_persister) completes

---

### US-6.4 — Skills Section Generation (Gemini Call 5 — N7d)

**As a user**, I want the skills section to be ordered so that JD-matched skills appear first, and skills I have but the JD doesn't mention appear last (or are suppressed).

**Acceptance Criteria:**
- Given `selected_skills_ordered` and `uncovered_skills`, when N7d runs, then:
  - Group 1 (Technical Skills — JD matched): all skills in `selected_skills_ordered` where `category = "technical"` and skill is in `jd_profile.required_skills`
  - Group 2 (Additional Technical Skills): remaining technical skills from knowledge graph
  - Group 3 (Tools & Platforms): `category = "tool"` skills
  - Group 4 (Domain Knowledge): `category = "domain"` skills
- `uncovered_skills` (JD required skills not in knowledge graph) are NOT added to the resume; instead, a warning is sent to the client: "These required JD skills were not found in your knowledge graph: [list]"
- N7d uses Gemini for one task only: normalise skill name formatting (e.g., "nodejs" → "Node.js", "reactjs" → "React.js") based on the JD's own capitalisation of those terms
- Output consists ONLY of `\skillCategory{category_name}{comma-separated skills}` calls. The `%%SKILLS_BLOCK%%` content slot is strictly typed to accept only this command

**Technical Notes — LangGraph Node:** N7d
- Gemini Call 5: this is the lightest call; temperature=0.1; input is just the skills list and the JD text (for capitalisation reference)
- Ordering logic is deterministic Python; Gemini only handles name normalisation
- System prompt includes verbatim format example:
  ```
  You must use ONLY this LaTeX command, exactly as shown:
  
  \skillCategory{Technical Skills}{Python, React.js, Azure, PostgreSQL, Kubernetes}
  \skillCategory{Tools \& Platforms}{Docker, Git, VS Code, GitHub Actions}
  
  Do not use \begin{itemize}, \end{itemize}, \item, \textbf, or any other LaTeX command.
  Return only the \skillCategory blocks. No preamble. No explanations.
  ```
- Output stored in `state.sections.skills` as a raw string of `\skillCategory` calls

---

---

# EPIC 7 — LaTeX Assembly, Validation, and Auto-Correction

**Goal:** The LaTeX file that reaches the compiler is syntactically valid every time. Gemini-generated content is inserted into a locked master template via pure string substitution. Gemini never touches the preamble, font declarations, package imports, spacing commands, or any structural LaTeX. The template is the single source of truth for all formatting.

**Architecture Decision — No PyLaTeX:**
The template is a raw `.tex` file stored in Azure Blob Storage, manually written and verified once. N8 performs `str.replace()` substitution into named content slots. PyLaTeX is NOT used — it introduces programmatic style drift, requires subclassing for every custom command, and makes debugging harder than inspecting a raw `.tex` file directly.

---

### US-7.1 — Template-Locked LaTeX Assembly (Pure String Substitution)

**As a system**, I need to combine all section outputs into a single compilable `.tex` file by inserting them into a locked master template, where the template's structure, fonts, spacing, and margins are never modified by code or AI.

**Acceptance Criteria:**
- Given all four section generators have completed and `state.sections.*` is fully populated, when N8 runs, then it performs pure `str.replace()` insertion into the master template for each content slot
- The master template is stored in Azure Blob Storage under `templates/master_resume.tex` and is treated as **read-only** — it is never modified by the pipeline, only read
- Template updates are deliberate, manual version bumps — never an AI task
- Content slots are strictly typed:
  - `%%SUMMARY_TEXT%%` — plain text only, no LaTeX commands
  - `%%EXPERIENCE_BLOCK%%` — only `\resumeSubheading{}{}{}{}` and `\resumeItem{}` calls
  - `%%PROJECTS_BLOCK%%` — only `\resumeProject{}{}` calls
  - `%%SKILLS_BLOCK%%` — only `\skillCategory{}{}` calls
- Section order in the final `.tex` follows the user's section selection order (not hardcoded)
- Sections not selected by the user have their slot replaced with an empty string (not deleted) so the LaTeX structure is preserved without producing visible output
- N8 outputs `state.latex_source` (the full `.tex` string)

**Technical Notes — LangGraph Node:** N8 (latex_assembler)
- Template fetched once per server startup from Azure Blob Storage, held in memory as a string constant for all subsequent sessions
- Assembly is a series of `str.replace(template, "%%SUMMARY_TEXT%%", state.sections.summary)` etc. — no Jinja, no templating engine, no PyLaTeX
- Before substitution, each section's text content (not command calls) is run through `escape_special_chars()` for: `&`, `%`, `$`, `#`, `_`, `{`, `}`, `~`, `^` — only escaping raw text within command arguments, not the commands themselves
- The entire assembly runs in <50ms on any reasonable server — it's just string ops

---

### US-7.2 — Static LaTeX Syntax + Custom Command Schema Validation

**As a system**, I need to catch both generic LaTeX syntax errors AND custom command signature violations before compilation, because Gemini can produce syntactically valid LaTeX that calls template commands with the wrong number of arguments.

**Acceptance Criteria:**
- Given `state.latex_source`, when N9 runs these checks in parallel:
  - **Brace balance check (generic):** count of `{` equals count of `}` (excluding escaped `\{`, `\}`)
  - **Environment matching (generic):** every `\begin{X}` has a matching `\end{X}` (stack-based parser)
  - **Placeholder check (generic):** no `%%SECTION%%` or `%%__BLOCK%%` strings remain unsubstituted
  - **Forbidden character check (generic):** raw `&` outside tabular, unescaped `%` not preceded by `\`
  - **Custom command schema validation (template-specific):** every custom command call is parsed and its argument count is validated against a hardcoded `CUSTOM_COMMAND_SCHEMA`
- If all checks pass, then N9 sets `state.latex_valid = true` and routes to N10
- If any check fails, then N9 sets `state.validation_errors: string[]` with specific error messages including line numbers and routes to N9r (latex_fixer)
- Checks run as concurrent Python coroutines within N9 (internal parallelism)

**Technical Notes — LangGraph Node:** N9 (latex_validator)
- Custom command schema is hardcoded in N9 (not configurable at runtime, not fetched from Blob Storage):
  ```python
  CUSTOM_COMMAND_SCHEMA = {
      "\\resumeItem":          {"args": 1},   # 1 arg: the bullet text
      "\\resumeSubheading":    {"args": 4},   # {title}{date}{company}{location}
      "\\resumeProject":       {"args": 2},   # {title}{all bullets combined}
      "\\skillCategory":       {"args": 2},   # {category_name}{comma-separated skills}
  }
  ```
- Argument parsing: regex `\\(command_name)\{` to locate calls, then brace-count to extract each `{...}` argument group
- If a command like `\resumeSubheading` is called with 3 args instead of 4, N9 reports: `\resumeSubheading on line 42: expected 4 arguments, got 3`
- Brace balance: O(n) scan; treat escaped braces `\{` `\}` as non-structural
- Environment matching: stack-based parser scanning for `\begin{` and `\end{`; ~10ms on any realistic resume
- If custom command schema validation passes but generic checks fail, Gemini fixer (N9r) still gets the specific error lines

---

### US-7.3 — Automated LaTeX Error Correction (Gemini Call 6 — N9r)

**As a system**, I need to fix LaTeX errors using Gemini rather than failing, because Gemini-generated content is mostly correct but occasionally has isolated syntax or argument-count issues.

**Acceptance Criteria:**
- Given `state.validation_errors` is non-empty, when N9r calls Gemini, then the prompt includes:
  - The full `latex_source`
  - The exact `validation_errors` list with line numbers
  - The `CUSTOM_COMMAND_SCHEMA` definitions so Gemini knows the required argument counts
  - The instruction: "Fix only the listed errors. Do not change any text content, wording, or structure. Do not modify the preamble, \documentclass, font declarations, or spacing commands. Return only the corrected LaTeX source, nothing else."
- Given Gemini returns corrected LaTeX, then N9r passes it back to N9 for full re-validation (both generic and schema checks)
- Given N9 fails again after correction, then N9r runs a second correction attempt
- Given the second correction also fails, then the pipeline does NOT retry a third time; instead it falls back: replace the broken section with a static error-recovery template for that section containing the raw text content, bypassing further AI generation
- Max correction attempts: 2 (configurable in server config)

**Technical Notes — LangGraph Node:** N9r (latex_fixer)
- Gemini Call 6: temperature=0.1 (lowest — this is deterministic correction, not creative)
- Retry counter stored in LangGraph state: `state.latex_fix_attempts: int`
- Conditional edge from N9: `if state.latex_valid → N10 else if fix_attempts < 2 → N9r else → fallback_assembler`
- Note: error correction still only touches content slots — Gemini never receives or modifies the template preamble in the error correction prompt

---

---

# EPIC 8 — PDF Compilation and Delivery

**Goal:** The validated LaTeX is compiled to a PDF and delivered to the user as a download, with no intermediate file exposed publicly.

---

### US-8.1 — PDF Compilation from Validated LaTeX

**As a system**, I need to compile the validated `.tex` file using `pdflatex` on the app server, producing a binary PDF without exposing the LaTeX source to the client.

**Acceptance Criteria:**
- Given `state.latex_valid = true` and `state.latex_source` is set, when N10 runs, then:
  - Write `state.latex_source` to a temp file at `/tmp/{session_id}/resume.tex`
  - Execute `pdflatex -interaction=nonstopmode -output-directory=/tmp/{session_id} /tmp/{session_id}/resume.tex`
  - Run pdflatex **twice** (required for cross-references and page numbers to resolve correctly)
  - Read `/tmp/{session_id}/resume.pdf` as bytes
- Given compilation succeeds (exit code 0 and `resume.pdf` exists), then `state.pdf_bytes` is set
- Given compilation fails (non-zero exit code), then N10 captures the pdflatex log, extracts the error line, and routes to N10f (fallback handler)
- Temp directory is cleaned up after N11 regardless of success or failure

**Technical Notes — LangGraph Node:** N10 (pdf_compiler)
- App server must have TeX Live installed (full or medium scheme); Docker image is recommended: `FROM texlive/texlive:latest`
- `asyncio.create_subprocess_exec` for non-blocking pdflatex execution
- Timeout: 30 seconds per pdflatex run; kill process and route to fallback if exceeded

---

### US-8.2 — Compilation Failure Fallback with Simplified Template

**As a system**, I need a fallback path when pdflatex fails so the user always receives something usable, even if formatting is degraded.

**Acceptance Criteria:**
- Given N10 compilation fails, when N10f runs, then:
  - Substitute the generated LaTeX source with a stripped-down fallback template (plain article class, no custom packages, minimal formatting)
  - Populate the fallback template with raw text extracted from `state.sections.*` (strip LaTeX commands with regex)
  - Attempt pdflatex compilation once on the fallback template
- Given fallback compilation succeeds, then deliver the fallback PDF with a client notification: "Formatting was simplified due to a compilation issue. Your content is complete."
- Given fallback also fails, then return HTTP 500 with error payload containing `state.sections.*` as JSON so the user's content is not lost

**Technical Notes — LangGraph Node:** N10f (fallback_template_handler)
- Fallback template: `\documentclass{article}\usepackage[margin=1in]{geometry}\begin{document}` — stored as string constant in server code, not in Blob Storage
- LaTeX command stripping regex: `r'\\[a-zA-Z]+\{([^}]*)\}'` → extract group 1; `r'\\[a-zA-Z]+'` → remove

---

### US-8.3 — PDF Delivery to React Client as Download

**As a user**, I want to receive the generated PDF as an immediate download trigger in my browser, without seeing or navigating to a separate URL.

**Acceptance Criteria:**
- Given `state.pdf_bytes` is set, when N12 runs, then it base64-encodes the bytes and includes them in the final SSE event: `{ event: "complete", pdf_base64: string, filename: string, session_key: string, warnings: string[] }`
- The `filename` is generated as: `resume_{role_title_slug}_{date}.pdf` where `role_title_slug` is derived from `jd_profile.role_type`
- Given the client receives the `complete` event, then it: decodes base64 → `ArrayBuffer` → `Blob` → creates object URL → triggers `<a>` click → revokes URL after 60 seconds
- The `warnings` array contains any advisory messages (e.g., "uncovered JD skills", "fallback formatting used")
- The client also stores the ArrayBuffer in IndexedDB as per US-1.3

**Technical Notes — LangGraph Node:** N12 (response_builder)
- Base64 encoding: `base64.b64encode(state.pdf_bytes).decode('utf-8')` in Python
- Client-side: `URL.createObjectURL(new Blob([buffer], { type: 'application/pdf' }))`
- SSE `complete` event closes the stream; client event listener removes itself

---

---

# EPIC 9 — Persistence, Archival, and Knowledge Graph Updates

**Goal:** Every successful generation is persisted; the knowledge graph is updated with new cache data; nothing is lost between sessions.

---

### US-9.1 — Pipeline State Persistence to PostgreSQL

**As a system**, I need to persist the final LangGraph state (excluding binary PDF) to PostgreSQL so session restoration works on return, and so I can debug past runs.

**Acceptance Criteria:**
- Given N11 runs after N10 succeeds, then it upserts to `sessions` table: `{ session_key, status: "completed", completed_at, jd_profile: jsonb, selected_project_ids: int[], selected_role_ids: int[], covered_skills: jsonb, uncovered_skills: jsonb }`
- Given a session row already exists (resume scenario), then `last_updated` is set to now; no duplicate rows
- Session rows older than 30 days are soft-deleted by a nightly cleanup job

**Technical Notes — LangGraph Node:** N11 (state_persister)
- Do not persist `state.pdf_bytes` or `state.latex_source` to PostgreSQL — these go to Blob Storage
- LangGraph checkpoint (full graph state) is already in PostgreSQL via `PostgresSaver`; this upsert is for the application-level `sessions` table, separate from the checkpoint table

---

### US-9.2 — PDF and LaTeX Archival to Azure Blob Storage

**As a system**, I need to store the final PDF and LaTeX source in Azure Blob Storage so I can retrieve any previously generated resume without re-running the pipeline.

**Acceptance Criteria:**
- Given N11 runs, then it uploads to Azure Blob Storage:
  - `resumes/{session_key}/resume.pdf` — the binary PDF
  - `resumes/{session_key}/resume.tex` — the validated LaTeX source
  - `resumes/{session_key}/metadata.json` — `{ generated_at, jd_profile, selected_project_ids, warnings }`
- Given the upload succeeds, then `sessions.blob_path` is set to `resumes/{session_key}/`
- Given I want to retrieve a past resume (not yet UI-built), then a `GET /resume/{session_key}` endpoint fetches the PDF from Blob Storage and streams it

**Technical Notes — LangGraph Node:** N11
- Use Azure SDK: `azure-storage-blob` Python package; `BlobServiceClient` with connection string from environment variable
- Blob container name: `resume-archive` (private, no public access)
- Upload is async; uses `asyncio` Azure SDK methods to not block the SSE stream

---

### US-9.3 — Project LaTeX Bullet Cache Update

**As a system**, I need to update the `latex_bullet_cache` on each project after a successful generation so future runs with similar JDs skip the Gemini call for unchanged projects.

**Acceptance Criteria:**
- Given N11 runs and `state.selected_projects` is non-empty, then for each project where Gemini was called (not cache-hit), N11 upserts the generated bullets into `project.latex_bullet_cache[jd_profile_hash]` with the current timestamp
- Given a project was served from cache (US-6.3 cache hit), then N11 updates `latex_bullet_cache[jd_profile_hash].last_used_at` but does not overwrite the bullet content
- Cache entries older than 90 days per key are pruned during the upsert

**Technical Notes — LangGraph Node:** N11
- PostgreSQL update: `UPDATE projects SET latex_bullet_cache = latex_bullet_cache || $1::jsonb WHERE id = $2`
- The `||` operator merges JSONB in PostgreSQL; existing keys are overwritten, others preserved

---

---

# Non-Functional Requirements Embedded in the Architecture

**Accuracy over speed (as explicitly stated):**
- 6 Gemini calls total (not 1 monolithic call) — each call has a narrow, verifiable purpose
- `gemini-1.5-pro` for all calls (not Flash) — higher accuracy on nuanced language tasks
- LaTeX correction loop (max 2 retries) — avoids delivering broken output
- Project scoring is deterministic Python, not AI — removes hallucination risk from selection logic

**Caching layers (three levels):**
- Browser IndexedDB: draft inputs, node outputs, final PDF (7-day TTL)
- LangGraph checkpoint: full graph state in PostgreSQL (6-hour resume window)
- Project bullet cache: JSONB in PostgreSQL, per JD profile hash (90-day TTL)

**Parallelism (four points in the graph):**
- N3 + N4 run concurrently (first fan-out)
- N7a + N7b + N7c + N7d run concurrently (second fan-out)
- N9 internal validation checks run as concurrent coroutines
- Azure Blob uploads in N11 use async SDK (non-blocking against SSE stream)

**Data storage rationale:**
- PostgreSQL (Azure Flexible Server): structured graph data, session state, checkpoints — queryable, relational, supports JSONB for flexible schema fields; ~$15/month smallest tier, adequate for personal use
- Azure Blob Storage: binary files (PDF, LaTeX) — cheap at-rest storage, ~$0.02/GB/month; separates file concerns from relational data