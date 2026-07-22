"""Database migration runner.

Executes SQL migration files in order. Each migration is idempotent
(uses IF NOT EXISTS / DO $$ blocks). Safe to run multiple times.
"""

from __future__ import annotations

import logging
from pathlib import Path

from server.services.database import DatabasePool

_logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


async def run_migrations(pool: DatabasePool) -> None:
    """Execute all SQL migration files in sorted order.

    Each migration file is wrapped in a transaction. If a migration
    fails, the transaction rolls back and the error propagates.
    """
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        _logger.warning("No migration files found in %s", MIGRATIONS_DIR)
        return

    _logger.info("Running %d migrations...", len(migration_files))

    for filepath in migration_files:
        sql = filepath.read_text(encoding="utf-8")
        _logger.info("  Executing: %s (%d bytes)", filepath.name, len(sql))

        async with pool.transaction() as conn:
            await conn.execute(sql)

    _logger.info("All migrations complete")
