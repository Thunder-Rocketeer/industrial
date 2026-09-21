"""Shared pytest fixtures.

Settings are overridden with a deterministic test configuration before the
application is imported, so tests never read the developer's real .env and
never require live Supabase or Redis instances.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Must be set before app.config is imported, since Settings reads the
# environment at construction time.
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-in-any-real-deployment")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:3000")

# Tests must not touch external services. Without these the application
# lifespan attempts a Redis connection on every TestClient context, which added
# roughly two minutes to a full run purely in connection timeouts.
os.environ.setdefault("CACHE_ENABLED", "false")
# The API suite runs against an *absent* database and asserts on the clean 503
# that produces. The default data source is the CSV export folder, which is
# present in this repository and would quietly turn those tests into
# integration tests, so the PostgreSQL path is selected explicitly here.
os.environ.setdefault("DATA_SOURCE", "postgres")
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("RATE_LIMIT_ENABLED", "true")

# Google credentials are cleared rather than defaulted: `setdefault` would leave
# a developer's real .env values in place, and the tests assert on whether OAuth
# reports itself configured. Overridden outright so the result does not depend
# on whose machine the suite runs on.
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""

from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture(scope="session")
def settings() -> Settings:
    """The application settings used throughout the test session."""
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def app(settings: Settings) -> FastAPI:
    """The FastAPI application instance.

    Depends on `settings` for ordering: the settings cache must be primed
    before the application reads configuration during construction.
    """
    assert settings is not None
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Synchronous test client bound to the application."""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
