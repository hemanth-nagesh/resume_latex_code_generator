"""PostgreSQL connection pool — single source for all DB access.

Uses asyncpg directly (not SQLAlchemy) for zero-ORM-overhead queries. The
knowledge graph queries are ad-hoc joins; an ORM adds indirection without
benefit for this use case.

Pattern: Connection Pool (from asyncpg) wrapped in a thin async context
manager. All raw SQL is in db/queries.py; this module handles only the
pool lifecycle.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg

_logger = logging.getLogger(__name__)


class DatabasePool:
    """Manages an asyncpg connection pool with lifecycle hooks.

    Created once at FastAPI startup. Shared across all requests. Closed
    at shutdown via Container.dispose().
    """

    def __init__(self, dsn: str, *, min_size: int = 2, max_size: int = 10) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None

    async def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            import ssl as ssl_module
            # Supabase and most managed Postgres providers require SSL.
            # Create a context that requires SSL but doesn't verify the
            # certificate (avoids CA cert issues in slim Docker images).
            ctx = ssl_module.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl_module.CERT_NONE

            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                command_timeout=30,
                ssl=ctx,
            )
            _logger.info(
                "Database pool created (min=%d, max=%d, ssl=on)",
                self._min_size,
                self._max_size,
            )
        return self._pool

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        """Execute a SELECT query and return all rows."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        """Execute a SELECT query and return the first row or None."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        """Execute an INSERT/UPDATE/DELETE. Returns the command tag."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def execute_many(self, query: str, args_list: list[tuple]) -> None:
        """Execute a parameterized query for each tuple in args_list."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.executemany(query, args_list)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """Async context manager for multi-query transactions.

        Usage:
            async with pool.transaction() as conn:
                await conn.execute(...)
                await conn.execute(...)
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def close(self) -> None:
        """Close the pool gracefully."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            _logger.info("Database pool closed")
