"""Dashboard endpoints (spec sections 9 and 10)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.routes.production import COMMON_ERRORS
from app.dependencies import DashboardServiceDep
from app.schemas.common import Envelope
from app.schemas.dashboard import DashboardSummary, DashboardTrends
from app.schemas.filters import TrendFilters

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get(
    "/summary",
    response_model=Envelope[DashboardSummary],
    summary="Executive dashboard summary",
    description=(
        "Everything the main dashboard needs, in one request: KPI cards, "
        "production, quality, inventory, machine availability, OEE and the "
        "open alerts.\n\n"
        "Nine aggregates are executed concurrently server-side, so the response "
        "costs roughly one query's latency rather than nine.\n\n"
        "**Business date.** The 'today' figures are anchored to the most recent "
        "date that has production, not to the wall clock. Demo data is seeded up "
        "to the day it was generated, so anchoring to the calendar would show an "
        "empty dashboard on any later day. The date used is returned as "
        "`business_date`.\n\n"
        "Cached for 30 seconds by default; `cache_hit` reports whether this "
        "response came from cache."
    ),
    responses=COMMON_ERRORS,
)
async def dashboard_summary(service: DashboardServiceDep) -> Envelope[DashboardSummary]:
    return Envelope(data=await service.get_summary())


@router.get(
    "/trends",
    response_model=Envelope[DashboardTrends],
    summary="Dashboard chart series",
    description=(
        "Chart-ready series for the dashboard: daily production against target, "
        "daily defect rate, daily OEE, and the Pareto-ordered defect breakdown "
        "for the period.\n\n"
        "Defaults to the last 30 days. The window is capped at 366 days."
    ),
    responses=COMMON_ERRORS,
)
async def dashboard_trends(
    service: DashboardServiceDep,
    filters: Annotated[TrendFilters, Query()],
) -> Envelope[DashboardTrends]:
    return Envelope(data=await service.get_trends(filters))
