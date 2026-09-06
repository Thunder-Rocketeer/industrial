"""Tests for configuration validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

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


def test_wildcard_cors_origin_is_rejected() -> None:
    """Spec section 61: '*' is invalid because requests carry credentials."""
    with pytest.raises(ValidationError, match=r"must not contain"):
        Settings(cors_allowed_origins=["*"], _env_file=None)


def test_comma_separated_origins_are_parsed() -> None:
    """A .env file carries lists as a comma-separated string."""
    settings = Settings(
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


def test_docs_are_disabled_in_production() -> None:
    """Spec section 40: OpenAPI docs are a development affordance."""
    production = Settings(**SECURE_PRODUCTION, _env_file=None)

    assert production.is_production is True
    assert production.docs_url is None
    assert production.openapi_url is None
