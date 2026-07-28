"""N1 — Session Validator.

Computes a deterministic session key from user input, then finds or creates
a session in PostgreSQL. If a completed session with a blob_path already exists
for the same key (cached result), the node sets a flag to skip generation.

The session key is computed client-side (SHA-256 of JD text + sections config)
and passed as state["session_key"]. This node only handles lookup/creation.
"""

from __future__ import annotations

import base64
import logging

from server.graph.state import ResumeState
from server.services.database import DatabasePool
from server.db import queries

_logger = logging.getLogger(__name__)


def _to_base64(data: bytes) -> str:
    return base64.b64encode(bytes(data)).decode("ascii")


async def run(state: ResumeState, *, db: DatabasePool) -> ResumeState:
    session_key = state.get("session_key", "")
    if not session_key:
        raise ValueError("session_key is required — must be computed client-side")

    try:
        # Check for existing completed session
        existing = await queries.find_session(db, session_key)
        if existing:
            session_id = existing["session_id"]
            status = existing.get("status", "")

            _logger.info("Session %s found with status=%s", session_id, status)

            if status == "completed":
                cached = await queries.get_session_pdf(db, session_key)
                if cached and cached.get("pdf_data"):
                    _logger.info(
                        "Session %s has a cached PDF — short-circuiting", session_id,
                    )
                    return ResumeState(
                        session_id=session_id,
                        latex_source=cached.get("latex_source") or "",
                        pdf_bytes=bytes(cached["pdf_data"]),
                        pdf_base64=_to_base64(cached["pdf_data"]),
                        pdf_filename=cached.get("pdf_filename") or "",
                        latex_filename=(cached.get("pdf_filename") or "resume") + ".tex",
                        warnings=["Using cached result. Regenerate for a fresh version."],
                    )

            if status == "pending":
                return ResumeState(session_id=session_id, resume_from_node=None)

        session = await queries.create_session(db, session_key)
        session_id = session["session_id"]
        _logger.info("Created new session %s", session_id)
    except Exception as e:
        _logger.warning("Database unavailable — using in-memory session: %s", e)
        import uuid
        session_id = f"mem_{uuid.uuid4().hex[:12]}"

    return ResumeState(
        session_id=session_id,
        resume_from_node=None,
    )
