"""Tests for configuration validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import FRONTEND_ORIGIN, Environment, Settings

#: A production configuration that satisfies the fail-closed checks in
#: `Settings`. Used by tests that need `APP_ENV=production` for some *other*
#: reason -- without it they now fail on the security validation, which is the
#: validator working rather than a test problem.
SECURE_PRODUCTION = {
    "app_env": "production",
    "secret_key": "t" * 64,
    "cookie_secure": True,
    "debug": False,
    "google_redirect_uri": "https://api.example.com/api/v1/auth/google/callback",
    "frontend_login_success_url": "https://app.example.com/dashboard",
    "frontend_login_failure_url": "https://app.example.com/login",
    "cors_allowed_origins": ["https://app.example.com"],
}


def test_fixed_deployment_settings_ignore_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """These values live in code. Env vars must not move the hosted service."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/cb")
    monkeypatch.setenv("FRONTEND_LOGIN_SUCCESS_URL", "http://localhost:3000/dashboard")
    monkeypatch.setenv("FRONTEND_LOGIN_FAILURE_URL", "http://localhost:3000/login")

    settings = Settings(_env_file=None)

    assert settings.app_env is Environment.PRODUCTION
    assert settings.cookie_secure is True
    assert settings.cache_enabled is False
    assert settings.cors_allowed_origins == [FRONTEND_ORIGIN]
    assert settings.google_redirect_uri == f"{FRONTEND_ORIGIN}/api/v1/auth/google/callback"
    assert settings.frontend_login_success_url == f"{FRONTEND_ORIGIN}/dashboard"
    assert settings.frontend_login_failure_url == f"{FRONTEND_ORIGIN}/login?error=auth_failed"


def test_wildcard_cors_origin_allows_every_domain() -> None:
    """'*' is accepted and treats any browser origin as allowed."""
    from app.security.redirects import is_allowed_origin

    settings = Settings(cors_allowed_origins="*", _env_file=None)

    assert settings.cors_allowed_origins == ["*"]
    assert is_allowed_origin("https://anywhere.example", settings)
    assert is_allowed_origin("http://192.168.1.20:3000", settings)
    assert is_allowed_origin(None, settings) is False


def test_comma_separated_origins_are_parsed() -> None:
    """A .env file carries lists as a comma-separated string."""
    settings = Settings(
        app_env="development",
        cors_allowed_origins="http://localhost:3000, http://127.0.0.1:3000",
        _env_file=None,
    )

    assert settings.cors_allowed_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_api_prefix_is_normalized() -> None:
    """The prefix always has a leading slash and no trailing slash."""
    assert Settings(api_v1_prefix="api/v1/", _env_file=None).api_v1_prefix == "/api/v1"


def test_invalid_samesite_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(cookie_samesite="banana", _env_file=None)


def test_access_token_lifetime_is_bounded() -> None:
    """Spec section 55.3: access tokens must stay short-lived."""
    with pytest.raises(ValidationError):
        Settings(access_token_expire_minutes=1440, _env_file=None)


def test_local_development_points_at_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """The local flag is what a developer machine uses. Render must not be set."""
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("LOCAL_DEVELOPMENT", "true")

    settings = Settings(_env_file=None)

    assert settings.local_development is True
    assert settings.app_env is Environment.DEVELOPMENT
    assert settings.google_redirect_uri == "http://localhost:8000/api/v1/auth/google/callback"
    assert settings.frontend_login_success_url == "http://localhost:3000/dashboard"


def test_render_ignores_local_development(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hosted service keeps the Vercel callback even if the local flag is set."""
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("LOCAL_DEVELOPMENT", "true")
    monkeypatch.setenv("SECRET_KEY", "t" * 64)
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")
    monkeypatch.setenv("FRONTEND_LOGIN_SUCCESS_URL", "http://localhost:3000/dashboard")

    settings = Settings(_env_file=None)

    assert settings.local_development is False
    assert settings.app_env is Environment.PRODUCTION
    assert settings.google_redirect_uri == f"{FRONTEND_ORIGIN}/api/v1/auth/google/callback"
    assert settings.frontend_login_success_url == f"{FRONTEND_ORIGIN}/dashboard"
    assert settings.cookie_secure is True


def test_docs_are_disabled_in_production() -> None:
    """Spec section 40: OpenAPI docs are a development affordance."""
    production = Settings(**SECURE_PRODUCTION, _env_file=None)

    assert production.is_production is True
    assert production.docs_url is None
    assert production.openapi_url is None
