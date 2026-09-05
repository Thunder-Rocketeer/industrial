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
