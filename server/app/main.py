"""FastAPI application factory and ASGI entry point.

Development:
    uvicorn app.main:app --reload

Production (spec section 22 -- never use --reload in production):
    gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w $WORKERS

Phase 1 wires up configuration, logging, CORS, request correlation and error
handling. Database, cache, authentication and the domain routers arrive in
later phases; the composition points for them are marked below.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.router import api_router
from app.config import Settings, get_settings
from app.schemas.common import ErrorDetail, ErrorResponse
from app.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001 - required by FastAPI
    """Manage resources that live for the duration of the process.

    Redis and database connection pools are opened here in Phase 3 so they are
    created once per worker rather than per request.
    """
    settings = get_settings()
    logger.info(
        "Application starting",
        extra={"environment": settings.app_env.value, "version": __version__},
    )
    yield
    logger.info("Application shutting down")


def _error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str | None = None,
    details: dict[str, list[str]] | None = None,
) -> JSONResponse:
    """Build the error envelope defined in spec section 68."""
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details))
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers=headers,
    )


def register_middleware(app: FastAPI, settings: Settings) -> None:
    """Install middleware. Order matters: the last added runs outermost."""

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[JSONResponse]],
    ) -> JSONResponse:
        """Assign a correlation ID and log the outcome of every request.

        Spec section 28: log method, path, status and duration, with a
        correlation ID that ties the entry to the client's request.
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

    # Spec section 61: explicit origin allow-list, never a wildcard. Credentials
    # are enabled because the session travels in an HTTP-only cookie.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER, "X-CSRF-Token"],
        expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
        max_age=600,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers that keep internal details out of client responses.

    Spec section 68: responses carry a stable code and a safe message; the
    technical cause goes to the server log under the same request ID.
    """

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return _error_response(
            status_code=exc.status_code,
            code=f"HTTP_{exc.status_code}",
            message=str(exc.detail),
            request_id=request_id,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)

        # Group messages by field so the frontend can show them inline.
        details: dict[str, list[str]] = {}
        for error in exc.errors():
            # Drop the leading location ("query", "body", ...) for readability.
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

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        # exc_info sends the traceback to the log only -- never to the client.
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
            "automobile component factory."
        ),
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
