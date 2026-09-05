"""Application configuration.

All settings come from the environment (spec section 27: environment-based
secrets). Nothing here connects to anything -- this module only declares and
validates configuration so that a misconfigured deployment fails at startup
with a clear message rather than at the first request.

Settings are read once and cached; import :func:`get_settings` rather than
constructing :class:`Settings` directly.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Environment(str, Enum):
    """Deployment environment.

    Subclasses ``str`` rather than ``enum.StrEnum`` so the project runs on
    Python 3.10, where ``StrEnum`` is not yet available.
    """

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Typed, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Tolerate unrelated variables in the shell environment.
        extra="ignore",
    )

    # -- Application ----------------------------------------------------------
    app_name: str = "Automobile Component Factory API"
    app_env: Environment = Environment.DEVELOPMENT
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    host: str = "0.0.0.0"  # noqa: S104 - binding all interfaces is intended for containers
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=4, ge=1, le=64)
    log_level: str = "INFO"

    # -- CORS (spec section 61) -----------------------------------------------
    # NoDecode suppresses pydantic-settings' default JSON decoding for complex
    # types, so the validator below can accept a plain comma-separated string --
    # which is the only practical way to express a list in a .env file.
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # -- Supabase / PostgreSQL (spec section 11) ------------------------------
    # Optional at import time so the app can boot for health checks and tests
    # before Phase 2 provisions the database. The db layer validates presence
    # when it actually needs to connect.
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""

    # -- Redis (spec sections 12 and 60) --------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_dashboard: int = Field(default=30, ge=0)
    cache_ttl_trends: int = Field(default=300, ge=0)
    cache_ttl_analytics: int = Field(default=900, ge=0)
    cache_ttl_reference: int = Field(default=3600, ge=0)

    # -- Security / JWT (spec section 55) -------------------------------------
    secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "acf-dashboard"
    jwt_audience: str = "acf-dashboard-api"
    access_token_expire_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    cookie_domain: str = ""

    # -- Google OAuth 2.0 / OIDC (spec section 54.2) --------------------------
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    google_oidc_issuer: str = "https://accounts.google.com"
    frontend_login_success_url: str = "http://localhost:3000/dashboard"
    frontend_login_failure_url: str = "http://localhost:3000/login?error=auth_failed"

    # -- Rate limiting (spec section 60) --------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_oauth: str = "10/minute"
    rate_limit_authenticated: str = "120/minute"
    rate_limit_analytics: str = "30/minute"
    rate_limit_unauthenticated: str = "60/minute"

    # -- Seed data (spec section 30) ------------------------------------------
    seed_random_seed: int = 20240101
    seed_history_days: int = Field(default=90, ge=1, le=365)

    # -- Validators -----------------------------------------------------------

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string, which is how .env files carry lists."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: list[str]) -> list[str]:
        """Spec section 61: a wildcard origin is invalid for credentialed requests."""
        if "*" in value:
            raise ValueError(
                "CORS_ALLOWED_ORIGINS must not contain '*'. The browser sends "
                "credentialed requests, so origins must be explicitly listed."
            )
        return value

    @field_validator("api_v1_prefix")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        """Guarantee a leading slash and no trailing slash."""
        return "/" + value.strip("/")

    @field_validator("cookie_samesite")
    @classmethod
    def _validate_samesite(cls, value: str) -> str:
        allowed = {"lax", "strict", "none"}
        lowered = value.lower()
        if lowered not in allowed:
            raise ValueError(f"COOKIE_SAMESITE must be one of {sorted(allowed)}")
        return lowered

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return upper

    # -- Derived --------------------------------------------------------------

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    @computed_field  # type: ignore[prop-decorator]
    @property
    def docs_url(self) -> str | None:
        """Spec section 40: OpenAPI docs stay enabled in development only."""
        return None if self.is_production else "/docs"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redoc_url(self) -> str | None:
        return None if self.is_production else "/redoc"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def openapi_url(self) -> str | None:
        return None if self.is_production else "/openapi.json"


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance.

    Cached so the .env file is parsed once per process and so the same object is
    shared by every dependency that injects it.
    """
    return Settings()
