"""Azure Blob Storage client — template fetching, PDF/LaTeX archival with versioning.

Storage structure:
  templates/
    master_resume.tex              ← Locked master template (read-only, manually uploaded)
  
  resumes/
    {company_slug}/
      {role_slug}/
        {company}_{role}_{session_key}/
          resume.pdf               ← Generated binary PDF
          resume.tex               ← Validated LaTeX source
          metadata.json            ← { generated_at, jd_profile, selected_project_ids, warnings }

Versioning by company + role allows browsing past resumes by employer.
The session_key provides uniqueness per JD + sections combination.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from azure.storage.blob.aio import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError

_logger = logging.getLogger(__name__)


class BlobClient:
    """Async wrapper around Azure Blob Storage SDK.

    Only this class touches the Azure SDK. All other modules work through
    this abstraction, making the storage backend swappable.
    """

    def __init__(self, connection_string: str, container_name: str) -> None:
        self._connection_string = connection_string
        self._container_name = container_name
        self._service: BlobServiceClient | None = None

    async def _get_service(self) -> BlobServiceClient:
        if self._service is None:
            self._service = BlobServiceClient.from_connection_string(
                self._connection_string
            )
        return self._service

    # ------------------------------------------------------------------
    # Template operations (read-only)
    # ------------------------------------------------------------------

    async def download_template(self, path: str) -> str:
        """Download the locked master .tex template."""
        return await self.download_text(path)

    # ------------------------------------------------------------------
    # Generic blob operations
    # ------------------------------------------------------------------

    async def download_text(self, blob_path: str) -> str:
        """Download a blob and return its contents as a UTF-8 string."""
        service = await self._get_service()
        async with service.get_blob_client(
            container=self._container_name, blob=blob_path
        ) as client:
            try:
                stream = await client.download_blob()
                raw = await stream.readall()
                return raw.decode("utf-8")
            except ResourceNotFoundError:
                raise FileNotFoundError(
                    f"Blob not found: {self._container_name}/{blob_path}"
                ) from None

    async def upload_text(self, blob_path: str, content: str) -> None:
        """Upload a UTF-8 string as a blob."""
        service = await self._get_service()
        async with service.get_blob_client(
            container=self._container_name, blob=blob_path
        ) as client:
            await client.upload_blob(content.encode("utf-8"), overwrite=True)
            _logger.debug("Uploaded text blob: %s", blob_path)

    async def upload_bytes(self, blob_path: str, data: bytes) -> None:
        """Upload raw bytes (e.g., PDF) as a blob."""
        service = await self._get_service()
        async with service.get_blob_client(
            container=self._container_name, blob=blob_path
        ) as client:
            await client.upload_blob(data, overwrite=True)
            _logger.debug("Uploaded byte blob: %s (%d bytes)", blob_path, len(data))

    async def upload_json(self, blob_path: str, data: dict[str, Any]) -> None:
        """Upload a Python dict as JSON blob."""
        await self.upload_text(blob_path, json.dumps(data, default=str, indent=2))

    async def download_stream(
        self, blob_path: str, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        """Stream a blob in chunks — useful for large PDF downloads."""
        service = await self._get_service()
        async with service.get_blob_client(
            container=self._container_name, blob=blob_path
        ) as client:
            try:
                stream = await client.download_blob()
                streamer = await stream.chunks()
                async for chunk in streamer:
                    yield chunk
            except ResourceNotFoundError:
                raise FileNotFoundError(
                    f"Blob not found: {self._container_name}/{blob_path}"
                ) from None

    async def exists(self, blob_path: str) -> bool:
        """Check if a blob exists."""
        service = await self._get_service()
        async with service.get_blob_client(
            container=self._container_name, blob=blob_path
        ) as client:
            try:
                await client.get_blob_properties()
                return True
            except ResourceNotFoundError:
                return False

    async def list_blobs(self, prefix: str) -> list[str]:
        """List all blob names under a prefix (non-recursive by default)."""
        service = await self._get_service()
        container = service.get_container_client(self._container_name)
        names: list[str] = []
        async for blob in container.list_blobs(name_starts_with=prefix):
            names.append(blob.name)
        return names

    # ------------------------------------------------------------------
    # Versioned resume archival (high-level API)
    # ------------------------------------------------------------------

    async def archive_resume(
        self,
        company_slug: str,
        role_slug: str,
        session_key: str,
        pdf_bytes: bytes,
        latex_source: str,
        metadata: dict[str, Any],
    ) -> str:
        """Archive a generated resume with company+role versioning.

        Args:
            company_slug: URL-safe company name (e.g., "tata-consultancy-services")
            role_slug: URL-safe role title (e.g., "ai-ml-engineer")
            session_key: SHA256 hash from the pipeline session
            pdf_bytes: Binary PDF content
            latex_source: Validated .tex source
            metadata: { generated_at, jd_profile_hash, selected_project_ids, warnings }

        Returns:
            The base blob path for this archive entry.
        """
        base = (
            f"resumes/{company_slug}/{role_slug}/"
            f"{company_slug}_{role_slug}_{session_key}"
        )

        await self.upload_bytes(f"{base}/resume.pdf", pdf_bytes)
        await self.upload_text(f"{base}/resume.tex", latex_source)
        await self.upload_json(f"{base}/metadata.json", metadata)

        _logger.info("Archived resume: %s (PDF: %d bytes)", base, len(pdf_bytes))
        return base

    async def get_archived_pdf_stream(self, archive_path: str) -> AsyncIterator[bytes]:
        """Stream an archived PDF by its base path.

        Args:
            archive_path: The base path returned by archive_resume()
                          (e.g., "resumes/tcs/eng/tcs_eng_abc123")

        Yields:
            PDF binary chunks.
        """
        async for chunk in self.download_stream(f"{archive_path}/resume.pdf"):
            yield chunk

    async def list_resumes_by_company(self, company_slug: str) -> list[str]:
        """List all role folders for a given company."""
        prefix = f"resumes/{company_slug}/"
        blobs = await self.list_blobs(prefix)
        # Extract unique role slugs (second path segment after company)
        roles: set[str] = set()
        for name in blobs:
            parts = name.removeprefix(prefix).split("/")
            if parts:
                roles.add(parts[0])
        return sorted(roles)

    async def list_resumes_by_company_role(
        self, company_slug: str, role_slug: str
    ) -> list[str]:
        """List all session archives for a specific company+role combo."""
        prefix = f"resumes/{company_slug}/{role_slug}/"
        blobs = await self.list_blobs(prefix)
        sessions: set[str] = set()
        for name in blobs:
            parts = name.removeprefix(prefix).split("/")
            if parts:
                sessions.add(parts[0])
        return sorted(sessions)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._service is not None:
            await self._service.close()
            self._service = None
