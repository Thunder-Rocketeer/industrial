"""Liveness and readiness endpoints.

Deliberately unauthenticated and dependency-free so an orchestrator can tell
whether the process is up without a working database, cache or identity
provider. Readiness checks against Supabase and Redis are added in Phase 3,
once those connections exist.
"""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.dependencies import SettingsDep
from app.schemas.common import Envelope, HealthStatus

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=Envelope[HealthStatus],
    summary="Liveness check",
    description="Returns the process status without touching the database or cache.",
)
async def health(settings: SettingsDep) -> Envelope[HealthStatus]:
    """Report that the API process is serving requests."""
    return Envelope(
        data=HealthStatus(
            status="ok",
            app=settings.app_name,
            version=__version__,
            environment=settings.app_env.value,
        )
    )
