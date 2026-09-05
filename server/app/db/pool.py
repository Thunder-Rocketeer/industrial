"""Async PostgreSQL connection pool.

One pool per worker process, opened in the application lifespan. Opening a
connection per request would add a TCP handshake, TLS negotiation and
authentication round trip to every dashboard load; against a hosted Supabase
instance that is the dominant cost of a fast aggregate query.

Sizing: total connections against Supabase is `workers x db_pool_max_size`. That
product must stay under the project's connection limit, which is why both are
configurable and why the default max is a conservative 10.

Every connection is configured with a server-side `statement_timeout`, so a
runaway aggregate is cancelled by PostgreSQL rather than pinning a pooled
connection until the client gives up.

`app/db/connection.py` keeps the synchronous path used by the seed and verify
CLIs. They are one-shot scripts where a pool has nothing to amortise.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import Settings, get_settings
from app.db.connection import DatabaseNotConfiguredError, require_database_url
from app.utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

logger = get_logger(__name__)


class DatabasePool:
    """Owns the lifecycle of the async connection pool.

    Held on `app.state` and injected into repositories through a dependency, so
    nothing constructs its own connection.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._pool: AsyncConnectionPool | None = None

    @property
    def is_open(self) -> bool:
        return self._pool is not None

    async def open(self) -> None:
        """Create and open the pool.

        Does not fail the application when the database is unreachable: the
        liveness endpoint must answer regardless (spec section 20), and the
        readiness endpoint is what reports the dependency as unhealthy. A
        request that genuinely needs the database raises then, with a clear
        message.
        """
        if self._pool is not None:
            return

        try:
            url = require_database_url(self._settings)
        except DatabaseNotConfiguredError:
            logger.warning("db.not_configured", extra={"reason": "database_url_empty"})
            return

        # `statement_timeout` is applied per connection through options, so it
        # covers every query without each call site remembering it.
        options = f"-c statement_timeout={self._settings.db_statement_timeout_ms}"

        pool = AsyncConnectionPool(
            conninfo=url,
            min_size=self._settings.db_pool_min_size,
            max_size=self._settings.db_pool_max_size,
            timeout=self._settings.db_pool_timeout_seconds,
            kwargs={
                "row_factory": dict_row,
                "connect_timeout": self._settings.db_connect_timeout_seconds,
                "options": options,
                "application_name": "acf-dashboard-api",
            },
            # Opened explicitly below so a failure is caught here rather than
            # emitted as a warning from the constructor.
            open=False,
        )

        try:
            await pool.open(wait=True, timeout=self._settings.db_connect_timeout_seconds)
        except Exception as exc:
            logger.warning(
                "db.pool_open_failed",
                extra={"error_type": type(exc).__name__},
            )
            # Keep the pool object: psycopg_pool reconnects on demand, so the
            # first successful request will find it working.
            self._pool = pool
            return

        self._pool = pool
        logger.info(
            "db.pool_opened",
            extra={
                "min_size": self._settings.db_pool_min_size,
                "max_size": self._settings.db_pool_max_size,
                "statement_timeout_ms": self._settings.db_statement_timeout_ms,
            },
        )

    async def close(self) -> None:
        """Close the pool and wait for connections to be returned."""
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None
        logger.info("db.pool_closed")

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection]:
        """Borrow a connection for the duration of the block.

        psycopg wraps the block in a transaction and commits on clean exit,
        rolling back if it raises. Every read therefore runs inside a consistent
        snapshot -- which matters for the dashboard summary, where several
        aggregates should describe the same moment rather than drifting apart
        mid-request.

        Raises:
            DatabaseNotConfiguredError: If no DATABASE_URL was configured.
        """
        if self._pool is None:
            raise DatabaseNotConfiguredError(
                "The database connection pool is not available.\n\n"
                "Set DATABASE_URL in server/.env to the PostgreSQL connection "
                "string from your Supabase project\n"
                "(Project Settings -> Database -> Connection string -> URI)."
            )

        async with self._pool.connection() as connection:
            yield connection

    async def healthcheck(self) -> bool:
        """Return True when a trivial query succeeds. For readiness only."""
        if self._pool is None:
            return False
        try:
            async with self.connection() as connection, connection.cursor() as cursor:
                await cursor.execute("select 1")
                await cursor.fetchone()
        except Exception as exc:
            logger.warning("db.healthcheck_failed", extra={"error_type": type(exc).__name__})
            return False
        return True
