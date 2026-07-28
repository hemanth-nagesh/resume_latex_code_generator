"""Dependency injection container with singleton lifecycle management.

All services are lazily initialized on first access. The container owns resource
cleanup (connection pools, clients) through an explicit `dispose()` method called
during FastAPI shutdown.

Pattern: Abstract Factory for creating concrete service implementations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.config import AppConfig
    from server.services.gemini import GeminiClient
    from server.services.database import DatabasePool
    from server.services.logger import StructuredLogger
    from server.services.latex_mcp import LatexMcpClient
    from server.services.pdf_compilation import PdfCompilationService

_logger = logging.getLogger(__name__)


class Container:
    """Central registry for all application services.

    Each property is lazily constructed on first access. This avoids
    initialization order dependencies and ensures services only exist
    if actually needed during the request lifecycle.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._gemini: GeminiClient | None = None
        self._gemini_clients: dict[int, GeminiClient] = {}
        self._db: DatabasePool | None = None
        self._template: str | None = None
        self._latex_mcp: LatexMcpClient | None = None
        self._pdf_service: PdfCompilationService | None = None
        self._disposed = False

    # ------------------------------------------------------------------
    # Service factories (lazy singleton)
    # ------------------------------------------------------------------

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def gemini(self) -> GeminiClient:
        """Primary Gemini client — used by N1, fallback for all."""
        if self._gemini is None:
            from server.services.gemini import GeminiClient
            self._gemini = GeminiClient(
                api_key=self._config.gemini_api_key,
                default_model=self._config.gemini_model,
                fallback_model=self._config.gemini_model_fallback,
            )
        return self._gemini

    def gemini_for(self, call_number: int) -> GeminiClient:
        """Get a GeminiClient for a specific pipeline call (1-6).

        Rotates through GEMINI_API_KEY, GEMINI_API_KEY2, ..., GEMINI_API_KEY6.
        Falls back to the primary key if a specific key is empty.
        """
        if call_number not in self._gemini_clients:
            from server.services.gemini import GeminiClient
            key = self._config.gemini_api_key  # default
            if call_number == 2 and self._config.gemini_api_key2:
                key = self._config.gemini_api_key2
            elif call_number == 3 and self._config.gemini_api_key3:
                key = self._config.gemini_api_key3
            elif call_number == 4 and self._config.gemini_api_key4:
                key = self._config.gemini_api_key4
            elif call_number == 5 and self._config.gemini_api_key5:
                key = self._config.gemini_api_key5
            elif call_number == 6 and self._config.gemini_api_key6:
                key = self._config.gemini_api_key6

            self._gemini_clients[call_number] = GeminiClient(
                api_key=key,
                default_model=self._config.gemini_model,
                fallback_model=self._config.gemini_model_fallback,
            )
        return self._gemini_clients[call_number]

    @property
    def latex_mcp(self) -> LatexMcpClient:
        """Client for the external LaTeX -> PDF MCP server (custom_latex_mcp.md)."""
        if self._latex_mcp is None:
            from server.services.latex_mcp import LatexMcpClient

            self._latex_mcp = LatexMcpClient(
                base_url=self._config.latex_mcp_url,
                api_key=self._config.latex_mcp_api_key,
                timeout_seconds=self._config.latex_mcp_timeout_seconds,
                max_retries=self._config.latex_mcp_max_retries,
            )
            _logger.info("LatexMcpClient initialized (%s)", self._config.latex_mcp_url)
        return self._latex_mcp

    @property
    def pdf_service(self) -> PdfCompilationService:
        """Use-case service: validated LaTeX -> compiled & persisted PDF."""
        if self._pdf_service is None:
            from server.services.pdf_compilation import PdfCompilationService

            self._pdf_service = PdfCompilationService(mcp_client=self.latex_mcp)
        return self._pdf_service

    @property
    def db(self) -> DatabasePool:
        if self._db is None:
            from server.services.database import DatabasePool

            self._db = DatabasePool(
                dsn=self._config.database_url,
                min_size=self._config.db_pool_min_size,
                max_size=self._config.db_pool_max_size,
            )
            _logger.info("DatabasePool initialized")
        return self._db

    @property
    async def template(self) -> str:
        """Load the locked master .tex template from the local filesystem.

        The template is bundled into the Docker image (template/master_resume.tex)
        — there is no external blob/object store. Cached as a string constant
        after first read since the template is read-only at runtime.
        """
        if self._template is None:
            import os
            template_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "template", "master_resume.tex",
            )
            with open(template_path, "r", encoding="utf-8") as f:
                self._template = f.read()
            _logger.info("Master template loaded (%d chars)", len(self._template))
        return self._template

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def dispose(self) -> None:
        """Close all pooled resources. Idempotent."""
        if self._disposed:
            return
        self._disposed = True

        if self._db is not None:
            await self._db.close()
            _logger.info("DatabasePool closed")

        if self._latex_mcp is not None:
            await self._latex_mcp.close()
            _logger.info("LatexMcpClient closed")

        _logger.info("Container disposed")
