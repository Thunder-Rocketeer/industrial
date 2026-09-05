"""Alert and maintenance endpoints (spec sections 34 and 5.5).

Grouped in one module because both are operational-attention lists over the same
machines, but they mount as separate routers so the OpenAPI tags stay distinct
(spec section 21).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.routes.production import COMMON_ERRORS
from app.dependencies import AlertServiceDep, MaintenanceServiceDep
from app.schemas.alerts import Alert, AlertSummary
from app.schemas.common import Envelope, PaginatedResponse, PaginationMeta
from app.schemas.filters import AlertFilters, MaintenanceFilters
from app.schemas.machines import MaintenanceRecord

alerts_router = APIRouter(prefix="/alerts", tags=["Alerts"])
maintenance_router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


@alerts_router.get(
    "",
    response_model=PaginatedResponse[Alert],
    summary="List alerts",
    description=(
        "Operational alerts, most severe and most recent first.\n\n"
        "Every alert carries a title, a full-sentence description, a severity "
        "label and its age in minutes, so it is comprehensible without colour "
        "or an icon. Each names at least one subject: a machine, component, "
        "inventory item or production line."
    ),
    responses=COMMON_ERRORS,
)
async def list_alerts(
    service: AlertServiceDep,
    filters: Annotated[AlertFilters, Query()],
) -> PaginatedResponse[Alert]:
    alerts, total = await service.list_alerts(filters)
    return PaginatedResponse(
        data=alerts,
        pagination=PaginationMeta(page=filters.page, page_size=filters.page_size, total=total),
    )


@alerts_router.get(
    "/active",
    response_model=Envelope[list[Alert]],
    summary="Active alerts",
    description="Open alerts only, most urgent first. Backs the dashboard alerts panel.",
    responses=COMMON_ERRORS,
)
async def active_alerts(
    service: AlertServiceDep,
    limit: Annotated[int, Query(ge=1, le=50, description="Maximum alerts.")] = 10,
) -> Envelope[list[Alert]]:
    return Envelope(data=await service.get_active_alerts(limit))


@alerts_router.get(
    "/summary",
    response_model=Envelope[AlertSummary],
    summary="Alert counts by severity",
    description="Counts of open alerts per severity, plus the acknowledged count.",
    responses=COMMON_ERRORS,
)
async def alert_summary(service: AlertServiceDep) -> Envelope[AlertSummary]:
    return Envelope(data=await service.get_summary())


@maintenance_router.get(
    "",
    response_model=PaginatedResponse[MaintenanceRecord],
    summary="List maintenance records",
    description=(
        "Maintenance jobs, filterable by status and machine.\n\n"
        "History is returned newest first; `upcoming_only=true` switches to "
        "scheduled and in-progress work ordered soonest first, so the next job "
        "is at the top rather than buried. `is_overdue` marks work scheduled in "
        "the past that has not been completed or cancelled."
    ),
    responses=COMMON_ERRORS,
)
async def list_maintenance(
    service: MaintenanceServiceDep,
    filters: Annotated[MaintenanceFilters, Query()],
) -> PaginatedResponse[MaintenanceRecord]:
    records, total = await service.list_records(filters)
    return PaginatedResponse(
        data=records,
        pagination=PaginationMeta(page=filters.page, page_size=filters.page_size, total=total),
    )
