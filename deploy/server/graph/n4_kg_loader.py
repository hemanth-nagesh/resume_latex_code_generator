"""N4 — Knowledge Graph Loader.

Loads the full knowledge graph (projects, skills, roles, certifications)
from PostgreSQL in a single batch. Runs in parallel with N3 (JD Analyzer).

This node has zero AI dependency — it's a pure database read. The
resulting kg_snapshot is used by N5 (scorer), N6 (selector), and
all section generators (N7a-N7d).
"""

from __future__ import annotations

import logging

from server.graph.state import ResumeState
from server.services.database import DatabasePool
from server.db.queries import load_full_knowledge_graph

_logger = logging.getLogger(__name__)


async def run(state: ResumeState, *, db: DatabasePool) -> ResumeState:
    """Load all active projects, skills, roles, and certifications.

    Args:
        state: LangGraph state (reads nothing, writes kg_snapshot).
        db: DatabasePool injected from the Container at graph invocation time.

    Returns:
        Updated state with kg_snapshot populated.
    """
    _logger.info("Loading knowledge graph from database...")

    kg = await load_full_knowledge_graph(db)

    return ResumeState(kg_snapshot=kg)
