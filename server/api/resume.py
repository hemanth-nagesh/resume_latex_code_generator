"""GET /api/resume/{session_key} — retrieve a previously generated resume PDF.

Generated PDFs are stored directly in the `sessions` table (see
migrations/002_*.sql) — there is no external blob/object store. The client
calls this after getting a session_key from POST /generate (or from a
previously completed session) to download the archived PDF.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from server.container import Container
from server.db import queries

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["resume"])


@router.get("/resume/{session_key}")
async def get_resume(session_key: str, request: Request) -> Response:
    container: Container = request.app.state.container

    record = await queries.get_session_pdf(container.db, session_key)

    if record is None or not record.get("pdf_data"):
        raise HTTPException(
            status_code=404,
            detail=f"No archived resume found for session {session_key}",
        )

    filename = record.get("pdf_filename") or f"resume_{session_key[:8]}"
    if not filename.endswith(".pdf"):
        filename = f"{filename}.pdf"

    _logger.info("Serving archived resume for session %s: %s", session_key, filename)

    return Response(
        content=bytes(record["pdf_data"]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "public, max-age=86400",
        },
    )
