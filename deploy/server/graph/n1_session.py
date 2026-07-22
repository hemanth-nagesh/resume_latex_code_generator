"""N1 — Session Validator.

Computes a deterministic session key from user input, then finds or creates
a session in PostgreSQL. If a completed session with a blob_path already exists
for the same key (cached result), the node sets a flag to skip generation.

The session key is computed client-side (SHA-256 of JD text + sections config)
and passed as state["session_key"]. This node only handles lookup/creation.
"""

from __future__ import annotations

import logging

from server.graph.state import ResumeState
from server.services.database import DatabasePool
from server.db import queries

_logger = logging.getLogger(__name__)


async def run(state: ResumeState, *, db: DatabasePool) -> ResumeState:
    session_key = state.get("session_key", "")
    if not session_key:
        raise ValueError("session_key is required — must be computed client-side")

    # Check for existing completed session
    existing = await queries.find_session(db, session_key)
    if existing:
        session_id = existing["session_id"]
        status = existing.get("status", "")

        _logger.info("Session %s found with status=%s", session_id, status)

        if status == "completed" and existing.get("blob_path"):
            _logger.info(
                "Session %s has cached PDF at %s — short-circuiting",
                session_id, existing["blob_path"],
            )
            return ResumeState(
                session_id=session_id,
                warnings=["Using cached result. Regenerate for a fresh version."],
            )

        if status == "pending":
            return ResumeState(session_id=session_id, resume_from_node=None)

    session = await queries.create_session(db, session_key)
    _logger.info("Created new session %s", session["session_id"])
    return ResumeState(
        session_id=session["session_id"],
        resume_from_node=None,
    )
