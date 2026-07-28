"""LaTeX → PDF MCP client — talks to the externally hosted compilation server.

See custom_latex_mcp.md for the full server documentation. This client uses
the plain REST endpoint (``POST {base_url}/api/convert``) rather than the
full MCP streamable-HTTP protocol, since it requires no MCP SDK dependency
and is a strictly simpler HTTP call for a FastAPI backend.

Responsibilities:
- Send LaTeX source + filename to the MCP server
- Retry transient failures (timeouts, 5xx) with exponential backoff
- Decode the returned base64 PDF payload
- Raise typed, non-leaking errors — never expose the API key in exception text

Does NOT:
- Know about ResumeState, LangGraph, or Blob Storage
- Retry authentication failures (401/403) — those are not transient
"""

from __future__ import annotations

import asyncio
import base64
import logging

import httpx

_logger = logging.getLogger(__name__)

# HTTP status codes that warrant a retry (transient failures)
_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}


class McpError(Exception):
    """Base class for all LaTeX MCP client errors."""


class McpAuthError(McpError):
    """Raised on 401/403 — invalid or missing API key. Never retried."""


class McpCompileError(McpError):
    """Raised when the MCP server responds with success: false."""


class McpTimeoutError(McpError):
    """Raised when all retry attempts are exhausted due to timeouts/5xx errors."""


class LatexMcpClient:
    """Thin async HTTP client for the LaTeX → PDF MCP server's REST API.

    One instance is shared across the app (lazily constructed by Container).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: int = 30,
        max_retries: int = 2,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
        return self._client

    async def compile(self, latex_source: str, filename: str) -> tuple[bytes, str]:
        """Compile LaTeX source to PDF via the MCP server.

        Args:
            latex_source: The full .tex document source.
            filename: Base filename (without extension) for the compiled PDF.

        Returns:
            (pdf_bytes, pdf_base64) — the decoded binary PDF and the raw
            base64 string as returned by the server.

        Raises:
            McpAuthError: On 401/403 (invalid/missing API key). Not retried.
            McpCompileError: When the server reports success: false.
            McpTimeoutError: When all retries are exhausted on timeout/5xx.
        """
        url = f"{self._base_url}/api/convert"
        client = self._get_client()
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await client.post(
                    url,
                    json={"latex_source": latex_source, "filename": filename},
                    headers={"X-API-Key": self._api_key},
                )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_error = exc
                _logger.warning(
                    "LaTeX MCP request failed (attempt %d/%d): %s",
                    attempt + 1, self._max_retries + 1, type(exc).__name__,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                raise McpTimeoutError(
                    f"LaTeX MCP server unreachable after {self._max_retries + 1} attempts"
                ) from exc

            if response.status_code in (401, 403):
                _logger.error("LaTeX MCP authentication failed (status %d)", response.status_code)
                raise McpAuthError(
                    "LaTeX MCP server rejected the API key (check LATEX_MCP_API_KEY)"
                )

            if response.status_code in _RETRYABLE_STATUS_CODES:
                last_error = McpError(f"MCP server returned {response.status_code}")
                _logger.warning(
                    "LaTeX MCP transient error %d (attempt %d/%d)",
                    response.status_code, attempt + 1, self._max_retries + 1,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                raise McpTimeoutError(
                    f"LaTeX MCP server returned {response.status_code} after "
                    f"{self._max_retries + 1} attempts"
                )

            if response.status_code != 200:
                raise McpCompileError(
                    f"LaTeX MCP server returned unexpected status {response.status_code}"
                )

            data = response.json()
            if not data.get("success"):
                raise McpCompileError(
                    f"LaTeX MCP compile failed: {data.get('error') or data.get('detail') or 'unknown error'}"
                )

            pdf_base64 = data.get("pdf_base64", "")
            if not pdf_base64:
                raise McpCompileError("LaTeX MCP server returned success but no pdf_base64")

            try:
                pdf_bytes = base64.b64decode(pdf_base64)
            except (ValueError, TypeError) as exc:
                raise McpCompileError(f"LaTeX MCP server returned invalid base64: {exc}") from exc

            if not pdf_bytes:
                raise McpCompileError("LaTeX MCP server returned an empty PDF")

            _logger.info(
                "LaTeX MCP compile succeeded: %s (%d bytes)",
                data.get("filename", filename), data.get("size_bytes", len(pdf_bytes)),
            )
            return pdf_bytes, pdf_base64

        # Unreachable — loop always returns or raises — but keeps type checkers happy.
        raise McpTimeoutError(f"LaTeX MCP compile failed: {last_error}")

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
