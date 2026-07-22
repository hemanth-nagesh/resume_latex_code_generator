"""Shared type definitions and SSE event models.

These types bridge the LangGraph nodes, API layer, and client. Every node
outputs fields defined here; every SSE event conforms to these shapes.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, TypedDict

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Node identifiers
# ---------------------------------------------------------------------------

class NodeId(StrEnum):
    """LangGraph node identifiers — single source of truth for node names."""

    SESSION_VALIDATOR = "n1_session_validator"
    INPUT_PARSER = "n2_input_parser"
    JD_ANALYZER = "n3_jd_analyzer"
    KG_LOADER = "n4_kg_loader"
    PROJECT_SCORER = "n5_project_scorer"
    CONTENT_SELECTOR = "n6_content_selector"
    SUMMARY_GEN = "n7a_summary_gen"
    EXPERIENCE_GEN = "n7b_experience_gen"
    PROJECTS_GEN = "n7c_projects_gen"
    SKILLS_GEN = "n7d_skills_gen"
    LATEX_ASSEMBLER = "n8_latex_assembler"
    LATEX_VALIDATOR = "n9_latex_validator"
    LATEX_FIXER = "n9r_latex_fixer"
    PDF_COMPILER = "n10_pdf_compiler"
    FALLBACK_HANDLER = "n10f_fallback_handler"
    STATE_PERSISTER = "n11_state_persister"
    RESPONSE_BUILDER = "n12_response_builder"


# ---------------------------------------------------------------------------
# SSE event models
# ---------------------------------------------------------------------------

class SSEEventType(StrEnum):
    SESSION_READY = "session_ready"
    NODE_START = "node_start"
    NODE_COMPLETE = "node_complete"
    NODE_ERROR = "node_error"
    COMPLETE = "complete"
    PIPELINE_ERROR = "pipeline_error"
    HEARTBEAT = "heartbeat"


class SSEEvent(BaseModel):
    """Base SSE event. All events extend this shape."""

    event: SSEEventType
    session_key: str
    timestamp: str  # ISO 8601

    def to_sse(self) -> str:
        """Serialize to the Server-Sent Events wire format."""
        data = self.model_dump_json()
        return f"event: {self.event.value}\ndata: {data}\n\n"


class SessionReadyEvent(SSEEvent):
    session_id: str
    resume_from_node: str | None = None


class NodeStartEvent(SSEEvent):
    node: NodeId


class NodeCompleteEvent(SSEEvent):
    node: NodeId
    duration_ms: int


class NodeErrorEvent(SSEEvent):
    node: NodeId
    error: str
    will_retry: bool = False


class CompleteEvent(SSEEvent):
    latex_source: str
    filename: str
    warnings: list[str] = Field(default_factory=list)
    template_fallback: bool = False


class PipelineErrorEvent(SSEEvent):
    """Emitted when the pipeline fails entirely — no LaTeX generated."""
    error: str
    failed_node: NodeId


class HeartbeatEvent(SSEEvent):
    """Sent every 15 seconds when no other events fire, to keep the SSE alive."""

    pass


# ---------------------------------------------------------------------------
# JD Profile (output of N3, consumed by N5, N6, N7a-N7d)
# ---------------------------------------------------------------------------

class RequiredSkill(BaseModel):
    skill: str
    is_technical: bool
    ats_exact_phrase: str = ""


class PreferredSkill(BaseModel):
    skill: str
    is_technical: bool


class JDProfile(BaseModel):
    required_skills: list[RequiredSkill]
    preferred_skills: list[PreferredSkill]
    seniority_level: str
    domain: str
    industry: str
    role_type: str
    ats_keywords: list[str]
    company_values: list[str]
    red_flags_to_avoid: list[str]

    @field_validator("seniority_level")
    @classmethod
    def validate_seniority(cls, value: str) -> str:
        valid = {"junior", "mid", "senior", "lead", "staff"}
        if value.lower() not in valid:
            raise ValueError(f"seniority_level must be one of {valid}")
        return value.lower()


# ---------------------------------------------------------------------------
# Knowledge Graph models (output of N4, consumed by N5, N6)
# ---------------------------------------------------------------------------

class ProjectKG(TypedDict, total=False):
    id: str
    title: str
    description: str
    impact_metric: str | None
    start_date: str | None
    end_date: str | None
    status: str
    tech_stack: list[str]
    tags: list[str]
    latex_bullet_cache: dict[str, Any]
    is_active: bool
    skills: list[str]  # populated by JOIN in N4


class SkillKG(TypedDict, total=False):
    id: str
    name: str
    display_name: str
    category: str
    proficiency: int
    last_used_date: str | None


class RoleKG(TypedDict, total=False):
    id: str
    company_name: str
    role_title: str
    start_date: str
    end_date: str | None
    location: str | None
    employment_type: str
    base_responsibilities: list[str]
    project_ids: list[str]


class KnowledgeGraph(BaseModel):
    projects: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    roles: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scored / Selected projects (output of N5, N6)
# ---------------------------------------------------------------------------

class ScoredProject(BaseModel):
    project_id: str
    title: str
    score: float
    matched_skills: list[str]
    covered_skill_count: int


class SelectedProject(ScoredProject):
    """Final selected project with generated content."""

    latex_content: str = ""  # populated by N7c


# ---------------------------------------------------------------------------
# Section configuration (from user input)
# ---------------------------------------------------------------------------

class SectionConfig(BaseModel):
    name: str
    max_count: int | None = None  # projects only
    matched_only: bool | None = None  # experience only

    @field_validator("name")
    @classmethod
    def validate_section_name(cls, value: str) -> str:
        valid = {"summary", "experience", "projects", "skills"}
        if value.lower() not in valid:
            raise ValueError(f"Unknown section: {value}. Must be one of {valid}")
        return value.lower()


# ---------------------------------------------------------------------------
# Session state (persisted to PostgreSQL by N11)
# ---------------------------------------------------------------------------

class SessionRecord(BaseModel):
    session_key: str
    session_id: str
    jd_profile: dict[str, Any] | None = None
    selected_project_ids: list[str] = Field(default_factory=list)
    selected_role_ids: list[str] = Field(default_factory=list)
    covered_skills: list[str] = Field(default_factory=list)
    uncovered_skills: list[str] = Field(default_factory=list)
    blob_path: str | None = None
    status: str = "pending"
