"""GET /api/resume/{session_key} — retrieve an archived resume PDF from Blob Storage.

The client calls this after getting a session_key from POST /generate
(or from a previously cached session). The endpoint returns the PDF
as a downloadable binary stream.

For cached results (when N1 detects a previously completed session),
the pipeline short-circuits to N12 which constructs the response from
archived blob data. The client can also use this directly to retrieve
historical resumes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from server.container import Container

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["resume"])


@router.get("/resume/{session_key}")
async def get_resume(session_key: str, request: Request) -> StreamingResponse:
    container: Container = request.app.state.container
    blob = container.blob

    # Find the archived resume by scanning for the session key
    archive_path = await _find_archive_by_session(blob, session_key)

    if archive_path is None:
        raise HTTPException(
            status_code=404,
            detail=f"No archived resume found for session {session_key}",
        )

    _logger.info("Serving archived resume: %s", archive_path)

    return StreamingResponse(
        _stream_pdf(blob, archive_path),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=resume_{session_key[:8]}.pdf",
            "Cache-Control": "public, max-age=86400",
        },
    )


async def _stream_pdf(blob, archive_path: str):
    """Stream PDF chunks from Blob Storage to the client."""
    try:
        async for chunk in blob.download_stream(f"{archive_path}/resume.pdf"):
            yield chunk
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="PDF blob not found")


async def _find_archive_by_session(blob, session_key: str) -> str | None:
    """Search blob storage for an archive containing this session key.

    Strategy: list all companies, then all roles, then check session folders.
    This is efficient for small-scale (few companies/roles) but should be
    replaced with a metadata index for production scale.
    """
    try:
        companies = await blob.list_resumes_by_company("")
        # list_resumes_by_company expects a prefix, so we list top-level
        # Actually, let's try the simpler approach: list under "resumes/"
        all_blobs = await blob.list_blobs("resumes/")
        for blob_path in all_blobs:
            if session_key in blob_path and blob_path.endswith("/resume.pdf"):
                # Strip trailing /resume.pdf to get archive base
                return blob_path.rsplit("/resume.pdf", 1)[0]
    except Exception as exc:
        _logger.warning("Error scanning blobs for session %s: %s", session_key, exc)

    return None
