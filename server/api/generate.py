"""POST /api/generate — initiate a resume generation pipeline run.

Request body:
{
    "jd_text": "...",
    "sections": [{"name": "summary"}, {"name": "projects"}],
    "session_key": null  // computed client-side via SHA-256 if omitted
}

Flow:
1. Validate JD text (100–15000 chars)
2. Compute/resolve session key
3. Create SSE session queue
4. Start LangGraph in background task (Run 1: N1→N9 → review_pending)
5. Return { session_key, session_id } immediately → client opens SSE stream

After user reviews and approves the LaTeX, POST /api/review/approve triggers
Run 2: PDF compilation via N10→N12.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.container import Container
from server.graph.graph import build_graph
from server.graph.state import ResumeState
from server.services.sse_manager import get_sse_manager, SSEEventManager
from server.services.types import NodeId

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["generate"])


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class SectionInput(BaseModel):
    name: str


class GenerateRequest(BaseModel):
    jd_text: str = Field(..., min_length=50, max_length=20_000)
    sections: list[SectionInput] = Field(
        default_factory=lambda: [
            SectionInput(name="summary"),
            SectionInput(name="experience"),
            SectionInput(name="projects"),
            SectionInput(name="skills"),
        ]
    )
    session_key: str | None = None


class GenerateResponse(BaseModel):
    session_key: str
    session_id: str


class ApproveRequest(BaseModel):
    session_key: str
    latex_source: str = Field(..., min_length=100)


class ApproveResponse(BaseModel):
    status: str
    session_key: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=GenerateResponse)
async def generate(
    body: GenerateRequest,
    request: Request,
) -> GenerateResponse:
    container: Container = request.app.state.container
    sse_manager = get_sse_manager()

    # --- Resolve session key (client-provided or compute server-side) ---
    session_key = body.session_key or _compute_session_key(
        body.jd_text, [s.name for s in body.sections]
    )

    # --- Create SSE session ---
    session_id = f"ses_{_short_hash(session_key)}"
    await sse_manager.create_session(session_key, session_id)

    # --- Build initial state ---
    initial_state = ResumeState(
        session_key=session_key,
        session_id=session_id,
        jd_raw=body.jd_text,
        sections=[s.model_dump() for s in body.sections],
        node_statuses={},
        warnings=[],
        sections_output=[],
        selected_projects=[],
        covered_skills=[],
        uncovered_skills=[],
        selected_skills_ordered=[],
    )

    # --- Build graph ---
    graph = build_graph(container)

    # --- Launch pipeline in background ---
    asyncio.create_task(
        _run_pipeline(
            graph=graph,
            initial_state=initial_state,
            container=container,
            sse_manager=sse_manager,
            session_key=session_key,
        )
    )

    _logger.info("Pipeline started for session %s", session_key)
    return GenerateResponse(session_key=session_key, session_id=session_id)


@router.post("/review/approve", response_model=ApproveResponse)
async def approve_review(
    body: ApproveRequest,
    request: Request,
) -> ApproveResponse:
    """Receive user-edited LaTeX and compile to PDF (Run 2: N10→N12)."""
    container: Container = request.app.state.container
    sse_manager = get_sse_manager()

    # Re-validate the user-edited LaTeX
    from server.graph.n9_validator import _run_validation_checks
    errors = await _run_validation_checks(body.latex_source)
    if errors:
        raise HTTPException(
            status_code=400,
            detail=f"LaTeX validation failed: {'; '.join(errors[:3])}",
        )

    # Launch PDF compilation in background
    asyncio.create_task(
        _compile_approved_latex(
            container=container,
            sse_manager=sse_manager,
            session_key=body.session_key,
            latex_source=body.latex_source,
        )
    )

    return ApproveResponse(status="compiling", session_key=body.session_key)


# ---------------------------------------------------------------------------
# Pipeline runner — Run 1: N1 → N9 (stops at review_pending)
# ---------------------------------------------------------------------------

async def _run_pipeline(
    graph,
    initial_state: ResumeState,
    container: Container,
    sse_manager: SSEEventManager,
    session_key: str,
) -> None:
    """Run LangGraph N1→N9, then emit review_pending for human approval."""
    try:
        config = {"configurable": {"thread_id": session_key}}

        last_result = initial_state
        async for event in graph.astream(initial_state, config, stream_mode="updates"):
            for node_name, node_output in event.items():
                node_id = _to_node_id(node_name)

                # Stop before N10 — we pause for human review instead
                if node_id == NodeId.PDF_COMPILER:
                    continue

                await sse_manager.emit_node_start(session_key, node_id)
                t0 = time.monotonic()

                elapsed = int((time.monotonic() - t0) * 1000)
                await sse_manager.emit_node_complete(session_key, node_id, elapsed)

                if isinstance(node_output, dict):
                    last_result = {**last_result, **node_output}

        # Emit review_pending — frontend shows editable LaTeX
        latex_source = last_result.get("latex_source", "")
        warnings = last_result.get("warnings", [])

        if not latex_source:
            await sse_manager.emit_pipeline_error(
                session_key=session_key,
                error="No LaTeX was generated",
                failed_node=NodeId.RESPONSE_BUILDER,
            )
            return

        await sse_manager.emit_review_pending(
            session_key=session_key,
            latex_source=latex_source,
            warnings=warnings,
        )

    except Exception as exc:
        _logger.exception("Pipeline failed for session %s", session_key)
        await sse_manager.emit_pipeline_error(
            session_key=session_key,
            error=str(exc),
            failed_node=NodeId.RESPONSE_BUILDER,
        )

    # Do NOT remove session — the SSE connection stays alive waiting for
    # the approve endpoint to trigger Run 2.


# ---------------------------------------------------------------------------
# Run 2: PDF compilation (triggered by approve endpoint)
# ---------------------------------------------------------------------------

async def _compile_approved_latex(
    container: Container,
    sse_manager: SSEEventManager,
    session_key: str,
    latex_source: str,
) -> None:
    """Compile the user-approved LaTeX to PDF and emit complete via SSE."""
    try:
        filename = f"resume_{session_key[:8]}.tex"

        result = await container.pdf_service.compile_and_prepare(
            latex_source=latex_source,
            filename=filename,
            sections_output=[],
            session_key=session_key,
            jd_profile={},
            selected_projects=[],
            selected_roles=[],
            covered_skills=[],
            uncovered_skills=[],
            db=container.db,
        )

        await sse_manager.emit_complete(
            session_key=session_key,
            latex_source=latex_source,
            filename=filename,
            pdf_base64=result.pdf_base64,
            warnings=result.warnings,
        )

    except Exception as exc:
        _logger.exception("PDF compilation failed for session %s", session_key)
        await sse_manager.emit_pipeline_error(
            session_key=session_key,
            error=str(exc),
            failed_node=NodeId.PDF_COMPILER,
        )

    finally:
        await asyncio.sleep(5)
        await sse_manager.remove_session(session_key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_session_key(jd_text: str, section_names: list[str]) -> str:
    import hashlib
    input_str = jd_text.strip() + "|" + ",".join(sorted(section_names))
    return hashlib.sha256(input_str.encode()).hexdigest()


def _short_hash(key: str) -> str:
    return key[:16]


_NODE_NAME_MAP: dict[str, NodeId] = {
    "n1_session_validator": NodeId.SESSION_VALIDATOR,
    "n2_input_parser": NodeId.INPUT_PARSER,
    "n3_jd_analyzer": NodeId.JD_ANALYZER,
    "n4_kg_loader": NodeId.KG_LOADER,
    "n5_project_scorer": NodeId.PROJECT_SCORER,
    "n6_content_selector": NodeId.CONTENT_SELECTOR,
    "n7a_summary_gen": NodeId.SUMMARY_GEN,
    "n7b_experience_gen": NodeId.EXPERIENCE_GEN,
    "n7c_projects_gen": NodeId.PROJECTS_GEN,
    "n7d_skills_gen": NodeId.SKILLS_GEN,
    "n8_latex_assembler": NodeId.LATEX_ASSEMBLER,
    "n9_latex_validator": NodeId.LATEX_VALIDATOR,
    "n9r_latex_fixer": NodeId.LATEX_FIXER,
    "n10_pdf_stage": NodeId.PDF_COMPILER,
    "n10_pdf_compiler": NodeId.PDF_COMPILER,
    "n10f_fallback_handler": NodeId.FALLBACK_HANDLER,
    "n11_state_persister": NodeId.STATE_PERSISTER,
    "n12_response_builder": NodeId.RESPONSE_BUILDER,
}


def _to_node_id(node_name: str) -> NodeId:
    return _NODE_NAME_MAP.get(node_name, NodeId.RESPONSE_BUILDER)
