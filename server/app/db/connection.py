"""PostgreSQL connectivity.

Two access paths exist and they are not interchangeable:

  * **psycopg over DATABASE_URL** (this module) -- a direct PostgreSQL
    connection. Used for bulk work and aggregation: the seed, the verifier, and
    from Phase 3 the analytical queries where server-side aggregation matters
    (spec section 11: "Prefer aggregation in PostgreSQL rather than transferring
    huge datasets to the frontend").

  * **supabase-py over SUPABASE_URL + service-role key** -- the PostgREST API.
    Convenient for simple row access. Introduced in Phase 3 where it fits.

Both are backend-only. Neither credential ever reaches the browser
(spec section 66).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from app.config import Settings, get_settings


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when a database operation is attempted without a DATABASE_URL.

    Configuration deliberately allows an empty DATABASE_URL so the application
    can boot for health checks and tests before a Supabase project exists. This
    is the error that turns that permissiveness into a clear message at the
    point where a connection is actually needed, rather than an opaque failure
    deeper in psycopg.
    """


def require_database_url(settings: Settings | None = None) -> str:
    """Return the configured DATABASE_URL, or raise with actionable guidance."""
    settings = settings or get_settings()
    url = settings.database_url.strip()
    if not url:
        raise DatabaseNotConfiguredError(
            "DATABASE_URL is not set.\n\n"
            "Copy the PostgreSQL connection string from your Supabase project\n"
            "(Project Settings -> Database -> Connection string -> URI) into\n"
            "server/.env as DATABASE_URL, then try again."
        )
    return url


@contextmanager
def get_connection(
    settings: Settings | None = None,
    *,
    autocommit: bool = False,
) -> Iterator[psycopg.Connection]:
    """Open a PostgreSQL connection as a context manager.

    The connection is committed on clean exit and rolled back if the block
    raises, so a partially applied seed can never be left behind.

    Args:
        settings: Overrides the cached application settings. Mainly for tests.
        autocommit: Required for statements that cannot run inside a
            transaction. The seed does not need it; left available for
            maintenance scripts.
    """
    url = require_database_url(settings)
    with psycopg.connect(url, autocommit=autocommit) as connection:
        yield connection
