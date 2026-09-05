"""Health endpoints (spec section 20).

Liveness and readiness answer different questions and must not be conflated.

**Liveness** asks whether the process is running. It touches no dependency, so
an orchestrator restarting on a failed liveness probe restarts only a genuinely
broken process. If liveness checked the database, a database blip would cause
every instance to be killed and restarted -- turning a recoverable dependency
outage into an application outage.

**Readiness** asks whether this instance should receive traffic, so it does
check dependencies. It reports rather than raises: a `200` with
`status: degraded` is more useful to an operator than a `503` with no detail,
and the body says which dependency is unhappy.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app import __version__
from app.dependencies import CacheDep, PoolDep, SettingsDep
from app.schemas.common import Envelope, HealthStatus

router = APIRouter(tags=["Health"])


class DependencyHealth(BaseModel):
    """Health of one external dependency."""

    name: str
    healthy: bool
    detail: str = Field(default="", description="Human-readable status.")


class ReadinessStatus(BaseModel):
    """Readiness response.

    `status` is `ready` when every required dependency is healthy, `degraded`
    when an optional one is not, and `not_ready` when a required one is down.
    """

    status: Literal["ready", "degraded", "not_ready"]
    app: str
    version: str
    environment: str
    dependencies: list[DependencyHealth]


@router.get(
    "/health",
    response_model=Envelope[HealthStatus],
    summary="Liveness check",
    description=(
        "Reports that the process is serving requests. Touches no database or "
        "cache, so it stays truthful during a dependency outage and an "
        "orchestrator does not restart healthy instances."
    ),
)
async def health(settings: SettingsDep) -> Envelope[HealthStatus]:
    return Envelope(
        data=HealthStatus(
            status="ok",
            app=settings.app_name,
            version=__version__,
            environment=settings.app_env.value,
        )
    )


@router.get(
    "/health/live",
    response_model=Envelope[HealthStatus],
    summary="Liveness check (alias)",
    description="Identical to `/health`. Provided for orchestrators that expect this path.",
)
async def live(settings: SettingsDep) -> Envelope[HealthStatus]:
    return await health(settings)


@router.get(
    "/health/ready",
    response_model=Envelope[ReadinessStatus],
    summary="Readiness check",
    description=(
        "Reports whether this instance can serve real traffic, checking the "
        "database and the cache.\n\n"
        "The database is **required**: without it no endpoint can answer, so an "
        "unhealthy database returns 503. Redis is **optional**: the API degrades "
        "to reading the database directly, so an unhealthy cache returns 200 "
        "with `status: degraded` rather than removing the instance from service."
    ),
    responses={503: {"description": "A required dependency is unavailable."}},
)
async def ready(
    response: Response,
    settings: SettingsDep,
    pool: PoolDep,
    cache: CacheDep,
) -> Envelope[ReadinessStatus]:
    database_healthy = await pool.healthcheck()

    cache_enabled = cache.client.enabled
    cache_healthy = await cache.client.ping() if cache_enabled else True

    dependencies = [
        DependencyHealth(
            name="database",
            healthy=database_healthy,
            detail="Connected." if database_healthy else "Unreachable or not configured.",
        ),
        DependencyHealth(
            name="cache",
            healthy=cache_healthy,
            detail=(
                "Connected."
                if cache_enabled and cache_healthy
                else "Disabled; reads go directly to the database."
                if not cache_enabled
                else "Unreachable; reads fall back to the database."
            ),
        ),
    ]

    if not database_healthy:
        overall: Literal["ready", "degraded", "not_ready"] = "not_ready"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif cache_enabled and not cache_healthy:
        overall = "degraded"
    else:
        overall = "ready"

    return Envelope(
        data=ReadinessStatus(
            status=overall,
            app=settings.app_name,
            version=__version__,
            environment=settings.app_env.value,
            dependencies=dependencies,
        )
    )
