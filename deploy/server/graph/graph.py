"""LangGraph wiring — nodes, edges, conditional routing.

All nodes are imported from their respective modules. This module only
handles the DAG topology: which edges connect which nodes, where fan-outs
happen, and what conditions route to which node.

Dependencies (db, gemini, blob) are injected by wrapping node functions
in closures. The graph is rebuilt per-container at startup.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from server.graph.state import ResumeState
from server.container import Container


def build_graph(
    container: Container,
    checkpointer=None,
) -> StateGraph:
    """Construct and compile the full LangGraph pipeline.

    Args:
        container: DI container with db, gemini, blob services.
        checkpointer: Optional LangGraph checkpointer (PostgresSaver for
                      production, None for in-memory/testing).

    Returns:
        Compiled StateGraph ready for invocation.
    """
    graph = StateGraph(ResumeState)

    # Register nodes with dependency injection
    _register_nodes(graph, container)

    # --- Edges ---
    graph.add_edge(START, "n1_session_validator")

    # N1 → N1.5 (cached result check) or N2
    graph.add_conditional_edges(
        "n1_session_validator",
        _after_session,
        {
            "n12_response_builder": "n12_response_builder",
            "n2_input_parser": "n2_input_parser",
        },
    )

    graph.add_edge("n2_input_parser", "n3_jd_analyzer")
    graph.add_edge("n2_input_parser", "n4_kg_loader")

    # N3 + N4 → N5 (fan-in: both must complete)
    graph.add_edge("n3_jd_analyzer", "n5_project_scorer")
    graph.add_edge("n4_kg_loader", "n5_project_scorer")

    graph.add_edge("n5_project_scorer", "n6_content_selector")

    # Parallel fan-out: N7a–N7d
    graph.add_conditional_edges(
        "n6_content_selector",
        _fan_out_n7,
        [
            "n7a_summary_gen",
            "n7b_experience_gen",
            "n7c_projects_gen",
            "n7d_skills_gen",
        ],
    )

    # Fan-in at N8
    graph.add_edge("n7a_summary_gen", "n8_latex_assembler")
    graph.add_edge("n7b_experience_gen", "n8_latex_assembler")
    graph.add_edge("n7c_projects_gen", "n8_latex_assembler")
    graph.add_edge("n7d_skills_gen", "n8_latex_assembler")

    graph.add_edge("n8_latex_assembler", "n9_latex_validator")
    graph.add_edge("n9_latex_validator", "n12_response_builder")
    graph.add_edge("n12_response_builder", END)

    return graph.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Node registration with DI closures
# ---------------------------------------------------------------------------

def _register_nodes(graph: StateGraph, container: Container) -> None:
    """Add all nodes to the graph. Wrap each node in a closure that
    injects its required dependencies from the container."""

    from server.graph import (
        n1_session, n2_input, n3_jd_analyzer, n4_kg_loader,
        n5_scorer, n6_selector,
        n7a_summary, n7b_experience, n7c_projects, n7d_skills,
        n8_assembler, n9_validator,
        n12_response,
    )

    # N1: db
    async def _n1(state: ResumeState) -> ResumeState:
        return await n1_session.run(state, db=container.db)

    # N2: pure
    async def _n2(state: ResumeState) -> ResumeState:
        return await n2_input.run(state)

    # N3: gemini — Call 1 (JD analysis)
    async def _n3(state: ResumeState) -> ResumeState:
        return await n3_jd_analyzer.run(state, gemini=container.gemini_for(1))

    # N4: db
    async def _n4(state: ResumeState) -> ResumeState:
        return await n4_kg_loader.run(state, db=container.db)

    # N5, N6: pure
    async def _n5(state: ResumeState) -> ResumeState:
        return await n5_scorer.run(state)

    async def _n6(state: ResumeState) -> ResumeState:
        return await n6_selector.run(state)

    # N7a-N7d: gemini — Calls 2-5 (rotated per key)
    async def _n7a(state: ResumeState) -> ResumeState:
        return await n7a_summary.run(state, gemini=container.gemini_for(2))

    async def _n7b(state: ResumeState) -> ResumeState:
        return await n7b_experience.run(state, gemini=container.gemini_for(3))

    async def _n7c(state: ResumeState) -> ResumeState:
        return await n7c_projects.run(state, gemini=container.gemini_for(4))

    async def _n7d(state: ResumeState) -> ResumeState:
        return await n7d_skills.run(state, gemini=container.gemini_for(5))

    # N8: template (fetched once from blob, cached in container)
    async def _n8(state: ResumeState) -> ResumeState:
        template = await container.template
        return await n8_assembler.run(
            state, template=template, template_fallback=container.is_template_fallback,
        )

    # N9: pure
    async def _n9(state: ResumeState) -> ResumeState:
        return await n9_validator.run(state)

    # N12: blob (optional — for cached PDF retrieval)
    async def _n12(state: ResumeState) -> ResumeState:
        return await n12_response.run(state, blob=container.blob)

    graph.add_node("n1_session_validator", _n1)
    graph.add_node("n2_input_parser", _n2)
    graph.add_node("n3_jd_analyzer", _n3)
    graph.add_node("n4_kg_loader", _n4)
    graph.add_node("n5_project_scorer", _n5)
    graph.add_node("n6_content_selector", _n6)
    graph.add_node("n7a_summary_gen", _n7a)
    graph.add_node("n7b_experience_gen", _n7b)
    graph.add_node("n7c_projects_gen", _n7c)
    graph.add_node("n7d_skills_gen", _n7d)
    graph.add_node("n8_latex_assembler", _n8)
    graph.add_node("n9_latex_validator", _n9)
    graph.add_node("n12_response_builder", _n12)


# ---------------------------------------------------------------------------
# Routing conditions
# ---------------------------------------------------------------------------

def _after_session(
    state: ResumeState,
) -> Literal["n12_response_builder", "n2_input_parser"]:
    """After N1: if cached result exists, skip to response."""
    warnings = state.get("warnings", [])
    has_cached = any("cached" in w.lower() for w in warnings)
    if has_cached:
        return "n12_response_builder"
    return "n2_input_parser"


def _fan_out_n7(state: ResumeState) -> list[str]:
    """N6 → [N7a, N7b, N7c, N7d] parallel dispatch."""
    return [
        "n7a_summary_gen",
        "n7b_experience_gen",
        "n7c_projects_gen",
        "n7d_skills_gen",
    ]
