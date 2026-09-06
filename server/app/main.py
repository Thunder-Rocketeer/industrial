"""FastAPI application factory and ASGI entry point.

Development:
    uvicorn app.main:app --reload

Production (spec section 22 -- never use --reload in production):
    gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w $WORKERS

Startup opens the database pool and the Redis connection once per worker.
Neither failure is fatal: the liveness endpoint must answer regardless
(spec section 20), and readiness is what reports a dependency as unhealthy.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.api.router import api_router
from app.cache.client import CacheClient, CircuitBreaker, create_redis
from app.cache.keys import CacheKeys
from app.cache.service import CacheService
from app.config import Settings, get_settings
from app.db.connection import DatabaseNotConfiguredError
from app.db.pool import DatabasePool
from app.repositories.base import UnknownSortFieldError
from app.runtime import configure_event_loop_policy
from app.schemas.common import ErrorDetail, ErrorResponse
from app.security.csrf import CsrfError, validate as validate_csrf
from app.security.oauth import build_oauth_registry, is_configured
from app.security.rate_limit import RateLimiter, client_identifier, parse_rate_limit
from app.security.revocation import TokenRevocationStore
from app.utils.logging import configure_logging, get_logger

# Must run before any event loop is created. Uvicorn imports this module
# first and builds its loop afterwards, so module scope is early enough.
# Without it, psycopg's async pool cannot connect on Windows at all.
configure_event_loop_policy()

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

#: OpenAPI tag metadata (spec section 21). Descriptions appear as section
#: introductions in the generated docs, so the API is navigable without reading
#: the code.
OPENAPI_TAGS = [
    {
        "name": "Dashboard",
        "description": (
            "Composite endpoints for the executive dashboard. The summary "
            "returns production, quality, inventory, machines, OEE and alerts "
            "in a single request."
        ),
    },
    {
        "name": "Production",
        "description": (
            "Production runs, aggregates and trends by machine, component, line and shift."
        ),
    },
    {
        "name": "Quality",
        "description": "Inspection records, defect rates, first pass yield and the defect Pareto.",
    },
    {
        "name": "Inventory",
        "description": "Stock lines, derived stock status, reorder alerts and movement history.",
    },
    {
        "name": "Machines",
        "description": (
            "Machine fleet status, utilisation, per-machine OEE and maintenance history."
        ),
    },
    {
        "name": "Analytics",
        "description": (
            "OEE, production efficiency, downtime and defect analysis. These are "
            "the most expensive queries in the API and carry a stricter rate limit."
        ),
    },
    {
        "name": "Authentication",
        "description": (
            "Google OAuth 2.0 / OpenID Connect sign-in, session management and "
            "the current user. Every other tag requires a session."
        ),
    },
    {"name": "Alerts", "description": "Operational alerts by severity and status."},
    {"name": "Maintenance", "description": "Scheduled and completed maintenance work."},
    {"name": "Health", "description": "Liveness and readiness probes."},
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open and close the resources that live for the process.

    The pool and the Redis connection are created once per worker rather than
    per request: against a hosted database, connection setup dominates the cost
    of a fast aggregate.
    """
    settings = get_settings()

    pool = DatabasePool(settings)
    await pool.open()
    app.state.db_pool = pool

    redis = await create_redis(settings)
    cache_client = CacheClient(
        redis,
        CircuitBreaker(
            failure_threshold=settings.cache_circuit_breaker_failures,
            cooldown_seconds=settings.cache_circuit_breaker_seconds,
        ),
    )
    app.state.cache = CacheService(cache_client, CacheKeys(settings.cache_key_prefix), settings)
    app.state.rate_limiter = RateLimiter(cache_client)
    # Shares the Redis client with the cache and the limiter, so all three
    # degrade together rather than each discovering an outage separately.
    app.state.revocation_store = TokenRevocationStore(cache_client)
    app.state.oauth = build_oauth_registry(settings)

    logger.info(
        "Application starting",
        extra={
            "environment": settings.app_env.value,
            "version": __version__,
            "cache_enabled": cache_client.enabled,
            "database_configured": pool.is_open,
            "google_oauth_configured": is_configured(settings),
        },
    )
    yield

    await pool.close()
    if redis is not None:
        await redis.aclose()
    logger.info("Application shutting down", extra={"cache_stats": cache_client.stats})


def _error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str | None = None,
    details: dict[str, list[str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the error envelope from spec sections 17 and 68."""
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details, request_id=request_id)
    )
    response_headers = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers=response_headers or None,
    )


def _policy_for(request: Request, settings: Settings) -> str:
    """Choose the rate-limit policy for a request.

    Path-based rather than per-route so a new endpoint inherits a sensible limit
    instead of being unlimited until someone remembers to annotate it.
    """
    path = request.url.path

    if "/health" in path:
        # Orchestrators poll liveness frequently; throttling it would produce a
        # false outage.
        return settings.rate_limit_health
    if "/auth/google" in path:
        # The OAuth endpoints, strictest of all: they are unauthenticated, they
        # reach an external provider, and they are the natural target for
        # someone hammering sign-in.
        return settings.rate_limit_oauth
    if "/auth" in path:
        # /auth/me, /auth/logout, /auth/csrf. Called routinely by a signed-in
        # frontend, so moderate rather than strict.
        return settings.rate_limit_authenticated
    if "/analytics" in path:
        return settings.rate_limit_analytics
    # Phase 4 populates `user_id`; until then every request is unauthenticated.
    if getattr(request.state, "user_id", None):
        return settings.rate_limit_authenticated
    return settings.rate_limit_unauthenticated


def register_middleware(app: FastAPI, settings: Settings) -> None:
    """Install middleware. The last added runs outermost."""

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Assign a correlation ID and log the outcome of every request.

        Spec section 18: log method, path, status and duration with a
        correlation ID. Nothing about the request's headers or body is logged,
        so an Authorization header or cookie cannot leak here.
        """
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request.completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    @app.middleware("http")
    async def csrf_protection(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Reject cross-site state-changing requests (spec sections 10 and 59).

        Only applies to unsafe methods on requests that carry a session cookie.
        A GET changes nothing, and an anonymous POST has no session for an
        attacker to ride.
        """
        try:
            validate_csrf(request, settings)
        except CsrfError as exc:
            request_id = getattr(request.state, "request_id", None)
            logger.warning(
                "security.csrf_rejected",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "reason": exc.reason,
                },
            )
            return _error_response(
                status_code=status.HTTP_403_FORBIDDEN,
                code="CSRF_VALIDATION_FAILED",
                message=("This request could not be verified. Reload the page and try again."),
                request_id=request_id,
            )
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Add the response security headers (spec section 62).

        `nosniff` is the one that matters for this API. Every response is JSON,
        and a JSON body can legitimately contain a string like
        `<script>alert(1)</script>` -- it is data, and the frontend escapes it on
        render. Without `nosniff`, a browser asked to open such a response
        directly could sniff it as HTML and execute the payload. The header
        removes that path entirely.

        `Content-Security-Policy` is deliberately absent: a meaningful policy has
        to be written against the frontend's real script and style sources, so it
        belongs with the application shell rather than here, where it could only
        be a placeholder that gives false assurance. HSTS likewise belongs at the
        TLS-terminating proxy, which knows whether the connection is HTTPS.
        """
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        # The API serves no HTML, so it should never be framed.
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.middleware("http")
    async def rate_limit(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Enforce the Redis-backed rate limit (spec section 60).

        Runs inside the request-context middleware so a 429 still carries a
        correlation ID. Fails open when Redis is unavailable: a cache outage
        must not close the API.
        """
        if not settings.rate_limit_enabled:
            return await call_next(request)

        # Preflight carries no credentials and no cost; throttling it would
        # break CORS for a client that is within its real limit.
        if request.method == "OPTIONS":
            return await call_next(request)

        limiter: RateLimiter = request.app.state.rate_limiter
        policy = parse_rate_limit(_policy_for(request, settings))
        identifier = client_identifier(request, settings.trusted_proxy_count)
        scope = request.url.path.split("/")[3] if request.url.path.count("/") >= 3 else "root"

        result = await limiter.check(identifier=identifier, scope=scope, policy=policy)

        if not result.allowed:
            request_id = getattr(request.state, "request_id", None)
            # The identifier is not logged: it can be an IP address, and spec
            # section 18 keeps personal data out of the log.
            logger.warning(
                "ratelimit.exceeded",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "policy": policy.source,
                    "scope": scope,
                },
            )
            return _error_response(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                code="RATE_LIMIT_EXCEEDED",
                message=(
                    f"Too many requests. The limit is {policy.limit} per "
                    f"{policy.window_seconds} seconds. Retry in "
                    f"{result.retry_after} seconds."
                ),
                request_id=request_id,
                headers=result.headers(),
            )

        response = await call_next(request)
        for header, value in result.headers().items():
            response.headers[header] = value
        return response

    # Carries the in-flight OAuth transaction -- Authlib stores the `state`,
    # `nonce` and PKCE verifier here between the redirect to Google and the
    # callback. Signed with SECRET_KEY, HttpOnly, and scoped to the auth path so
    # it is not sent with every API request. Short-lived: an OAuth round trip
    # takes seconds, and a stale transaction is only useful to an attacker.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key or "insecure-development-only",
        session_cookie=settings.oauth_cookie_name,
        max_age=settings.oauth_transaction_max_age_seconds,
        same_site="lax",
        https_only=settings.cookie_secure,
        path=f"{settings.api_v1_prefix}/auth",
    )

    # Spec section 61: explicit origin allow-list, never a wildcard. Credentials
    # are enabled because the session travels in an HTTP-only cookie.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER, "X-CSRF-Token"],
        # The frontend reads X-Auth-Error to tell an expired session from an
        # absent one without parsing the body.
        expose_headers=[
            REQUEST_ID_HEADER,
            "Retry-After",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "X-Auth-Error",
        ],
        max_age=600,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers that keep internal details out of client responses.

    Spec sections 17 and 68: responses carry a stable code, a safe message and
    the correlation ID. The technical cause goes to the server log under the
    same ID, so an operator can find it without the client ever seeing it.
    """

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Headers set on the exception are preserved. The auth dependencies use
        # this to send `WWW-Authenticate` and `X-Auth-Error`, which is how the
        # frontend distinguishes an expired session from an absent one without
        # parsing the body or matching on message text.
        headers = dict(getattr(exc, "headers", None) or {})
        code = headers.pop("X-Auth-Error", None) or f"HTTP_{exc.status_code}"
        return _error_response(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
            request_id=getattr(request.state, "request_id", None),
            headers=headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)

        details: dict[str, list[str]] = {}
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"][1:]) or "request"
            details.setdefault(location, []).append(error["msg"])

        logger.warning(
            "request.validation_failed",
            extra={"request_id": request_id, "path": request.url.path},
        )
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="One or more supplied values were not valid.",
            request_id=request_id,
            details=details,
        )

    @app.exception_handler(UnknownSortFieldError)
    async def unknown_sort_handler(request: Request, exc: UnknownSortFieldError) -> JSONResponse:
        """A sort key outside the allow-list (spec section 57).

        The permitted keys are returned so a legitimate caller can correct
        themselves. That discloses nothing: they are already in the OpenAPI
        document, and the rejection itself is the security control.
        """
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="INVALID_SORT_FIELD",
            message=str(exc),
            request_id=getattr(request.state, "request_id", None),
            details={"sort_by": [f"Permitted values: {', '.join(exc.allowed)}."]},
        )

    @app.exception_handler(DatabaseNotConfiguredError)
    async def database_not_configured_handler(
        request: Request,
        exc: DatabaseNotConfiguredError,  # noqa: ARG001 - required by the handler signature
    ) -> JSONResponse:
        """No DATABASE_URL, or the pool never opened.

        The exception's own message names environment variables and Supabase
        settings, so it goes to the log only; the client gets a generic 503.
        """
        request_id = getattr(request.state, "request_id", None)
        logger.error(
            "db.not_configured",
            extra={"request_id": request_id, "path": request.url.path},
        )
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="DATABASE_UNAVAILABLE",
            message="The service cannot reach its database. Please try again shortly.",
            request_id=request_id,
        )

    @app.exception_handler(psycopg.Error)
    async def database_error_handler(request: Request, exc: psycopg.Error) -> JSONResponse:
        """Any database failure.

        A psycopg error message can contain the failing SQL, a column name, or a
        connection string. None of it reaches the client: `exc_info` sends the
        detail to the log and the response carries only a code and the request
        ID (spec section 68).
        """
        request_id = getattr(request.state, "request_id", None)
        logger.error(
            "db.query_failed",
            exc_info=exc,
            extra={"request_id": request_id, "path": request.url.path},
        )
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="DATABASE_ERROR",
            message="The request could not be completed because of a database problem.",
            request_id=request_id,
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        """A domain rule rejected the input.

        Services raise `ValueError` for things Pydantic cannot express, such as
        an unsupported grouping dimension. The message is written to be
        client-safe; anything sensitive would be raised as a different type.
        """
        request_id = getattr(request.state, "request_id", None)
        logger.warning(
            "request.invalid_value",
            extra={"request_id": request_id, "path": request.url.path},
        )
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="INVALID_REQUEST",
            message=str(exc),
            request_id=request_id,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.error(
            "request.unhandled_exception",
            exc_info=exc,
            extra={"request_id": request_id, "path": request.url.path},
        )
        return _error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="The server encountered an unexpected problem.",
            request_id=request_id,
        )


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(level=settings.log_level, use_json=settings.is_production)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Production, quality, inventory and machine monitoring API for an "
            "automobile component factory.\n\n"
            "All responses are enveloped: single resources and aggregates as "
            '`{"data": ...}`, lists as `{"data": [...], "pagination": {...}}`, '
            'and errors as `{"error": {"code", "message", "request_id"}}`.\n\n'
            "Every response carries an `X-Request-ID` header that also appears in "
            "the server logs, so a failure can be traced end to end."
        ),
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        # Spec section 40: interactive docs in development, disabled in production.
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
        openapi_url=settings.openapi_url,
    )

    register_middleware(app, settings)
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
