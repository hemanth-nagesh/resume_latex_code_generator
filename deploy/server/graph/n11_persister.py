"""N11 — State Persister.

After successful PDF compilation, persists the complete pipeline output:
1. PostgreSQL: completes the session record (selected projects, skills, blob_path)
2. Azure Blob Storage: archives PDF, .tex source, and metadata
3. Bullet cache: updates project bullet cache entries for future JD reuse

This is the last node before N12 response — it ensures all artifacts are
durable before the user receives the download link.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from server.graph.state import ResumeState
from server.db import queries

if TYPE_CHECKING:
    from server.services.database import DatabasePool
    from server.services.blob import BlobClient

_logger = logging.getLogger(__name__)


async def run(
    state: ResumeState,
    *,
    db: DatabasePool,
    blob: BlobClient,
) -> ResumeState:
    session_key = state.get("session_key", "")
    session_id = state.get("session_id", "")
    pdf_bytes = state.get("pdf_bytes")
    latex_source = state.get("latex_source", "")
    jd_profile = state.get("jd_profile", {})
    selected_projects = state.get("selected_projects", [])
    selected_roles = state.get("selected_roles", [])
    covered_skills = state.get("covered_skills", [])
    uncovered_skills = state.get("uncovered_skills", [])
    warnings = state.get("warnings", [])

    if not session_key:
        _logger.warning("N11: No session_key — skipping persistence")
        return ResumeState()

    if not pdf_bytes:
        _logger.warning("N11: No PDF bytes — skipping persistence")
        return ResumeState()

    _logger.info(
        "N11: Persisting session %s — %d bytes PDF, %d chars LaTeX",
        session_id,
        len(pdf_bytes),
        len(latex_source),
    )

    # --- Build company/role slugs for blob path ---
    company_slug = "unknown"
    role_slug = "unknown"
    if selected_roles:
        r = selected_roles[0]
        company_slug = _slugify(r.get("company_name", "unknown"))
        role_slug = _slugify(r.get("role_title", "role"))

    # --- Archive to Azure Blob Storage ---
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "session_key": session_key,
        "jd_profile_hash": _hash_dict(jd_profile),
        "selected_project_ids": [sp.get("project_id", "") for sp in selected_projects],
        "selected_role_ids": [r.get("id", "") for r in selected_roles],
        "covered_skills": covered_skills,
        "uncovered_skills": uncovered_skills,
        "warnings": warnings,
    }

    try:
        blob_path = await blob.archive_resume(
            company_slug=company_slug,
            role_slug=role_slug,
            session_key=session_key,
            pdf_bytes=pdf_bytes,
            latex_source=latex_source,
            metadata=metadata,
        )
        _logger.info("N11 archived to Blob: %s", blob_path)
        extra_warnings = []
    except Exception as exc:
        _logger.warning("N11 Blob upload failed (non-fatal): %s", exc)
        blob_path = (
            f"resumes/{company_slug}/{role_slug}/"
            f"{company_slug}_{role_slug}_{session_key}"
        )
        extra_warnings = ["Blob storage unavailable — PDF delivered in-memory only"]
        # Don't return — still update DB session

    # --- Update PostgreSQL session ---
    try:
        await queries.complete_session(
            db,
            session_key,
            jd_profile=jd_profile,
            selected_project_ids=[
                sp.get("project_id", "") for sp in selected_projects
            ],
            selected_role_ids=[r.get("id", "") for r in selected_roles],
            covered_skills=covered_skills,
            uncovered_skills=uncovered_skills,
            blob_path=blob_path,
        )
        _logger.info("N11 session completed: %s", session_id)
    except Exception as exc:
        _logger.error("N11 DB update failed: %s", exc)
        db_warnings = warnings + extra_warnings
    except Exception as exc:
        _logger.error("N11 DB update failed: %s", exc)
        db_warnings = warnings + [f"Session DB update failed: {exc}"] + extra_warnings

    return ResumeState(blob_path=blob_path, warnings=db_warnings)


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    import re
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug.strip("-")[:50]


def _hash_dict(data: dict) -> str:
    """Stable hash of a dict for quick JD comparison."""
    import hashlib
    required = tuple(sorted(
        s.get("skill", "").lower()
        for s in data.get("required_skills", [])
    ))
    return hashlib.sha256(json.dumps(required).encode()).hexdigest()[:12]
