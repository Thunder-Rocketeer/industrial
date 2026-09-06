"""Quality endpoints (spec section 9)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.routes.production import COMMON_ERRORS
from app.dependencies import QualityServiceDep
from app.schemas.common import Envelope, PaginatedResponse, PaginationMeta
from app.schemas.filters import (
    DefectBreakdownFilters,
    QualityFilters,
    QualityGroupFilters,
    QualityListFilters,
)
from app.schemas.quality import (
    DefectSummary,
    DefectTrendPoint,
    QualityByDimension,
    QualityRecord,
    QualitySummary,
)
from app.security.dependencies import require_permission
from app.security.policy import Permission

#: Every endpoint on this router requires QUALITY_READ. Declared once at
#: the router rather than per route, so an endpoint added later inherits
#: the protection instead of being unguarded until someone notices.
router = APIRouter(
    prefix="/quality",
    tags=["Quality"],
    dependencies=[Depends(require_permission(Permission.QUALITY_READ))],
)


@router.get(
    "",
    response_model=PaginatedResponse[QualityRecord],
    summary="List quality records",
    description=(
        "Returns inspection lines, filtered and paginated.\n\n"
        "Each production run has one pass line (`defect_id` null, carrying the "
        "accepted units) and one further line per defect type found. Set "
        "`rejections_only=true` to return only the lines that recorded a "
        "defect.\n\n"
        "Sorting accepts: `inspected_at`, `inspected`, `rejected`, `passed`, "
        "`machine`, `component`."
    ),
    responses=COMMON_ERRORS,
)
async def list_quality(
    service: QualityServiceDep,
    filters: Annotated[QualityListFilters, Query()],
) -> PaginatedResponse[QualityRecord]:
    records, total = await service.list_records(filters)
    return PaginatedResponse(
        data=records,
        pagination=PaginationMeta(page=filters.page, page_size=filters.page_size, total=total),
    )


@router.get(
    "/summary",
    response_model=Envelope[QualitySummary],
    summary="Quality summary",
    description=(
        "Aggregate inspection totals for the filtered period, with defect rate, "
        "first pass yield and quality rate.\n\n"
        "First pass yield uses all inspected units as its denominator, not just "
        "units that passed, so it is always at or below the quality rate."
    ),
    responses=COMMON_ERRORS,
)
async def quality_summary(
    service: QualityServiceDep,
    filters: Annotated[QualityFilters, Query()],
) -> Envelope[QualitySummary]:
    return Envelope(data=await service.get_summary(filters))


@router.get(
    "/defects",
    response_model=Envelope[list[DefectSummary]],
    summary="Defect breakdown (Pareto)",
    description=(
        "Defect categories ordered by rejected quantity, descending, with each "
        "category's share and the running cumulative percentage. Feeds the "
        "Pareto chart directly -- the cumulative series is computed server-side "
        "so every consumer draws the same line."
    ),
    responses=COMMON_ERRORS,
)
async def defect_breakdown(
    service: QualityServiceDep,
    filters: Annotated[DefectBreakdownFilters, Query()],
) -> Envelope[list[DefectSummary]]:
    return Envelope(data=await service.get_defect_breakdown(filters, filters.limit))


@router.get(
    "/trend",
    response_model=Envelope[list[DefectTrendPoint]],
    summary="Daily defect rate trend",
    description="Daily inspected and rejected quantities with the resulting defect rate.",
    responses=COMMON_ERRORS,
)
async def defect_trend(
    service: QualityServiceDep,
    filters: Annotated[QualityFilters, Query()],
) -> Envelope[list[DefectTrendPoint]]:
    return Envelope(data=await service.get_defect_trend(filters))


@router.get(
    "/by-machine",
    response_model=Envelope[list[QualityByDimension]],
    summary="Rejection rate by machine",
    description="Inspection totals per machine, highest rejected quantity first.",
    responses=COMMON_ERRORS,
)
async def quality_by_machine(
    service: QualityServiceDep,
    filters: Annotated[QualityGroupFilters, Query()],
) -> Envelope[list[QualityByDimension]]:
    return Envelope(data=await service.get_by_dimension(filters, "machine", filters.limit))


@router.get(
    "/by-component",
    response_model=Envelope[list[QualityByDimension]],
    summary="Rejection rate by component",
    description="Inspection totals per component, highest rejected quantity first.",
    responses=COMMON_ERRORS,
)
async def quality_by_component(
    service: QualityServiceDep,
    filters: Annotated[QualityGroupFilters, Query()],
) -> Envelope[list[QualityByDimension]]:
    return Envelope(data=await service.get_by_dimension(filters, "component", filters.limit))
