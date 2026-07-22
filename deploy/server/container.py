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
    from server.services.blob import BlobClient
    from server.services.database import DatabasePool
    from server.services.logger import StructuredLogger

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
        self._blob: BlobClient | None = None
        self._db: DatabasePool | None = None
        self._template: str | None = None
        self._template_fallback: bool = False
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
    def blob(self) -> BlobClient:
        if self._blob is None:
            from server.services.blob import BlobClient

            self._blob = BlobClient(
                connection_string=self._config.azure_storage_connection_string,
                container_name=self._config.azure_storage_container,
            )
            _logger.info("BlobClient initialized")
        return self._blob

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
        """Fetch the locked master .tex template from Azure Blob Storage.

        If Blob is unavailable (local dev without Azure), falls back to
        reading template/master_resume.tex from the local filesystem.
        Sets _template_fallback flag so nodes can surface a fallback notice.

        Cached as a string constant after first fetch — the template is
        read-only and never modified at runtime.
        """
        if self._template is None:
            try:
                blob_client = self.blob
                self._template = await blob_client.download_template(
                    self._config.template_blob_path
                )
                self._template_fallback = False
                _logger.info(
                    "Master template loaded from Blob Storage (%d chars)",
                    len(self._template),
                )
            except Exception:
                _logger.warning(
                    "Blob Storage unavailable — loading template from local file"
                )
                import os
                template_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "template", "master_resume.tex",
                )
                with open(template_path, "r", encoding="utf-8") as f:
                    self._template = f.read()
                self._template_fallback = True
                _logger.info(
                    "Master template loaded from local file (%d chars)",
                    len(self._template),
                )
        return self._template

    @property
    def is_template_fallback(self) -> bool:
        """True if the template was loaded from local fallback instead of Blob."""
        return self._template_fallback

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

        if self._blob is not None:
            await self._blob.close()
            _logger.info("BlobClient closed")

        _logger.info("Container disposed")
