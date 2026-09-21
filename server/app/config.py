"""Application configuration.

All settings come from the environment (spec section 27: environment-based
secrets). Nothing here connects to anything -- this module only declares and
validates configuration so that a misconfigured deployment fails at startup
with a clear message rather than at the first request.

Settings are read once and cached; import :func:`get_settings` rather than
constructing :class:`Settings` directly.
"""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, computed_field, field_validator, model_validator
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


class DataSource(str, Enum):
    """Backend the repositories read table data from."""

    CSV = "csv"
    POSTGRES = "postgres"


def _env_files() -> tuple[Path, ...]:
    """The dotenv files to read, lowest precedence first.

    `server/.env` is the developer's local file and is never committed. On
    Render -- detected by the `RENDER` variable the platform sets on every
    service -- the committed `server/render.env` is read as well, so the
    deployment's public configuration (hostnames, feature switches) lives in
    the repository rather than being retyped into a dashboard. Real
    environment variables still override both files, which is where the
    secrets stay.
    """
    files = [BASE_DIR / ".env"]
    if os.environ.get("RENDER"):
        files.append(BASE_DIR / "render.env")
    return tuple(files)


class Settings(BaseSettings):
    """Typed, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=_env_files(),
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

    # -- Data source ----------------------------------------------------------
    #: Where table data is read from. `csv` loads the exports in
    #: `supabase_csv_exports/` into an in-memory database at startup and never
    #: contacts Supabase; `postgres` uses DATABASE_URL as before.
    data_source: DataSource = DataSource.CSV
    #: Folder holding one `<table>.csv` per table. Defaults to
    #: `server/supabase_csv_exports`, which is inside the directory a
    #: deployment builds from (Render's root directory, the Docker context).
    csv_data_dir: Path = BASE_DIR / "supabase_csv_exports"

    # -- Supabase / PostgreSQL (spec section 11) ------------------------------
    # Optional at import time so the app can boot for health checks and tests
    # before Phase 2 provisions the database. The db layer validates presence
    # when it actually needs to connect.
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""

    # Connection pool. Each Gunicorn worker holds its own pool, so the total
    # connection count against Supabase is workers x db_pool_max_size -- keep
    # that product below the project's connection limit.
    db_pool_min_size: int = Field(default=1, ge=0, le=50)
    db_pool_max_size: int = Field(default=10, ge=1, le=100)
    #: Seconds to wait for a free pooled connection before giving up.
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    #: TCP connect timeout, so an unreachable database fails fast.
    db_connect_timeout_seconds: int = Field(default=10, ge=1, le=120)
    #: Server-side statement timeout. A runaway aggregate is cancelled by
    #: PostgreSQL rather than holding a connection open indefinitely.
    db_statement_timeout_ms: int = Field(default=15_000, ge=100, le=300_000)
    #: Bounds how many aggregate queries the dashboard runs concurrently. Each
    #: takes its own pooled connection, so this must stay below the pool size.
    db_max_concurrent_queries: int = Field(default=5, ge=1, le=32)

    # -- Redis (spec sections 12 and 60) --------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    #: Master switch. Disabling it makes every read go to the database, which is
    #: the correct behaviour for a test run and a useful production kill switch.
    cache_enabled: bool = True
    cache_key_prefix: str = "acf"
    cache_ttl_dashboard: int = Field(default=30, ge=0)
    cache_ttl_trends: int = Field(default=300, ge=0)
    cache_ttl_analytics: int = Field(default=900, ge=0)
    cache_ttl_reference: int = Field(default=3600, ge=0)
    #: Redis timeouts are deliberately short. The cache exists to make requests
    #: faster; waiting on an unhealthy Redis would make them slower than not
    #: caching at all.
    redis_connect_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    redis_command_timeout_seconds: float = Field(default=1.0, gt=0, le=30)
    #: After repeated failures the cache stops being consulted for this long, so
    #: an outage costs one timeout rather than one per request.
    cache_circuit_breaker_seconds: float = Field(default=30.0, ge=0, le=600)
    cache_circuit_breaker_failures: int = Field(default=3, ge=1, le=100)

    # -- Security / JWT (spec section 55) -------------------------------------
    # `JWT_SECRET_KEY` is accepted as an alias so either name works in .env.
    secret_key: str = Field(
        default="", validation_alias=AliasChoices("SECRET_KEY", "JWT_SECRET_KEY")
    )
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "acf-dashboard"
    jwt_audience: str = "acf-dashboard-api"
    # `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` is accepted as an alias. The upper bound
    # is a hard limit, not a default: a token that cannot be un-issued should
    # not outlive the attention span of an incident (spec section 55.3).
    access_token_expire_minutes: int = Field(
        default=15,
        ge=1,
        le=60,
        validation_alias=AliasChoices(
            "ACCESS_TOKEN_EXPIRE_MINUTES", "JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
        ),
    )
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)

    # -- Cookies (spec sections 7 and 55.4) -----------------------------------
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    cookie_domain: str = ""
    session_cookie_name: str = "acf_session"
    csrf_cookie_name: str = "acf_csrf"
    #: Cookie carrying the in-flight OAuth transaction (state and nonce). Scoped
    #: to the auth path so it is not sent with every API request.
    oauth_cookie_name: str = "acf_oauth"
    #: An OAuth round trip through Google should take seconds. A short life
    #: bounds how long a captured state value is worth anything.
    oauth_transaction_max_age_seconds: int = Field(default=600, ge=60, le=3600)

    # -- Account restriction (spec section 28) ---------------------------------
    #: Empty means "any Google account". Both lists are enforced server-side
    #: after the identity has been cryptographically verified.
    auth_allowed_email_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)
    auth_allowed_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)
    #: When false, only users already present in the database may sign in.
    auth_auto_provision: bool = True
    #: Role given to an auto-provisioned user. Never taken from the request.
    auth_default_role: str = "VIEWER"

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
    #: Liveness probes are polled frequently by orchestrators and must not be
    #: throttled into reporting a false outage.
    rate_limit_health: str = "600/minute"
    #: Number of reverse proxies in front of the application. Only this many
    #: entries are trusted from the right of X-Forwarded-For; at 0 the header is
    #: ignored entirely. Spec section 60: never trust an arbitrary XFF, because
    #: a client can otherwise forge one and reset its own rate-limit bucket.
    trusted_proxy_count: int = Field(default=0, ge=0, le=10)

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

    @field_validator("auth_allowed_email_domains", "auth_allowed_emails", mode="before")
    @classmethod
    def _split_auth_lists(cls, value: object) -> object:
        """Accept a comma-separated string, and normalise to lowercase.

        Email comparison must be case-insensitive: Google returns the address in
        whatever case the user typed, and `Admin@Factory.com` and
        `admin@factory.com` are the same mailbox. Normalising here means the
        comparison at sign-in is a plain equality check.
        """
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        return value

    @field_validator("auth_default_role")
    @classmethod
    def _validate_default_role(cls, value: str) -> str:
        """The default role must be a real role code.

        Checked here so a typo fails at startup rather than at the first
        sign-in, which would leave a user provisioned with no role at all.
        """
        from app.models.enums import RoleCode

        allowed = {role.value for role in RoleCode}
        upper = value.strip().upper()
        if upper not in allowed:
            raise ValueError(f"AUTH_DEFAULT_ROLE must be one of {sorted(allowed)}, got {value!r}.")
        return upper

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

    @field_validator(
        "rate_limit_oauth",
        "rate_limit_authenticated",
        "rate_limit_analytics",
        "rate_limit_unauthenticated",
        "rate_limit_health",
    )
    @classmethod
    def _validate_rate_limit(cls, value: str) -> str:
        """Reject a malformed policy at startup rather than at first request."""
        from app.security.rate_limit import parse_rate_limit

        parse_rate_limit(value)
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return upper

    @model_validator(mode="after")
    def _fail_closed_in_production(self) -> Settings:
        """Refuse to start with an insecure production configuration.

        Spec section 34: "Do not create a configuration that accidentally
        disables critical security controls in production. Fail closed on
        insecure production authentication configuration."

        Every check below describes a setting that is correct for local
        development and dangerous in production. Defaulting them the safe way
        would break local development; warning about them would be ignored. So
        they are permitted, and the environment decides whether they are fatal.

        Development is deliberately unaffected: `http://localhost` and a
        non-Secure cookie are exactly what a developer needs.
        """
        if self.app_env is not Environment.PRODUCTION:
            return self

        problems: list[str] = []

        if not self.secret_key or len(self.secret_key) < 32:
            problems.append(
                "SECRET_KEY must be set and at least 32 characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        if not self.cookie_secure:
            problems.append(
                "COOKIE_SECURE must be true in production, or the session cookie "
                "travels over plain HTTP."
            )
        if self.debug:
            problems.append("DEBUG must be false in production.")

        # An http:// redirect URI in production means the authorization code
        # comes back over a channel anyone on the path can read.
        insecure_urls = {
            "GOOGLE_REDIRECT_URI": self.google_redirect_uri,
            "FRONTEND_LOGIN_SUCCESS_URL": self.frontend_login_success_url,
            "FRONTEND_LOGIN_FAILURE_URL": self.frontend_login_failure_url,
        }
        for name, url in insecure_urls.items():
            if url and url.startswith("http://"):
                problems.append(f"{name} must use https in production, got {url!r}.")

        for origin in self.cors_allowed_origins:
            if origin.startswith("http://") and "localhost" not in origin:
                problems.append(f"CORS origin {origin!r} must use https in production.")

        # SameSite=None requires Secure, and is only correct for a genuinely
        # cross-site frontend. Reaching for it to "fix" a cookie problem is how
        # CSRF protection gets removed by accident.
        if self.cookie_samesite == "none" and not self.cookie_secure:
            problems.append("COOKIE_SAMESITE=none requires COOKIE_SECURE=true.")

        if problems:
            bullet = chr(10) + "  - "
            raise ValueError(
                "Insecure production configuration; refusing to start."
                + bullet
                + bullet.join(problems)
            )
        return self

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
