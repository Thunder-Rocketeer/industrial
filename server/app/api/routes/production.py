"""Production endpoints (spec section 9).

Handlers are thin by design (spec principle 5): parse, delegate, return. Every
one has a response model, a summary and a description, so the OpenAPI document
is usable without reading this file (spec sections 21 and 40).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import ProductionServiceDep
from app.schemas.common import Envelope, PaginatedResponse, PaginationMeta
from app.schemas.filters import (
    ProductionFilters,
    ProductionGroupFilters,
    ProductionListFilters,
)
from app.schemas.production import (
    ProductionByDimension,
    ProductionRecord,
    ProductionSummary,
    ProductionTrendPoint,
)

router = APIRouter(prefix="/production", tags=["Production"])

#: Reused so every route documents the same failure modes.
COMMON_ERRORS = {
    422: {"description": "A query parameter failed validation."},
    429: {"description": "Rate limit exceeded."},
    503: {"description": "The database is unavailable."},
}


@router.get(
    "",
    response_model=PaginatedResponse[ProductionRecord],
    summary="List production records",
    description=(
        "Returns production runs at (date, shift, machine, component) grain, "
        "filtered and paginated. Each record carries its own efficiency and "
        "defect rate so the caller does not recompute them.\n\n"
        "Sorting accepts an allow-listed key: `date`, `produced`, `planned`, "
        "`accepted`, `rejected`, `downtime`, `machine`, `component`. Any other "
        "value is rejected with 422."
    ),
    responses=COMMON_ERRORS,
)
async def list_production(
    service: ProductionServiceDep,
    filters: Annotated[ProductionListFilters, Query()],
) -> PaginatedResponse[ProductionRecord]:
    records, total = await service.list_records(filters)
    return PaginatedResponse(
        data=records,
        pagination=PaginationMeta(page=filters.page, page_size=filters.page_size, total=total),
    )


@router.get(
    "/summary",
    response_model=Envelope[ProductionSummary],
    summary="Production summary",
    description=(
        "Aggregate production for the filtered period: quantities, minutes, "
        "achievement against target, efficiency and defect rate.\n\n"
        "Targets are recorded per (date, line, component) and have no machine "
        "or shift dimension. When the filter includes a machine or a shift, "
        "`target_quantity` and `achievement_percentage` are returned as 0 "
        "rather than comparing a machine's output against a whole line's "
        "target. Check `has_data` to distinguish an empty period from a zero."
    ),
    responses=COMMON_ERRORS,
)
async def production_summary(
    service: ProductionServiceDep,
    filters: Annotated[ProductionFilters, Query()],
) -> Envelope[ProductionSummary]:
    return Envelope(data=await service.get_summary(filters))


@router.get(
    "/trend",
    response_model=Envelope[list[ProductionTrendPoint]],
    summary="Daily production trend",
    description=(
        "Daily produced, planned, accepted, rejected and target quantities for "
        "the filtered period. Days with no production are omitted rather than "
        "returned as zero, so a chart can distinguish a shutdown from a failure."
    ),
    responses=COMMON_ERRORS,
)
async def production_trend(
    service: ProductionServiceDep,
    filters: Annotated[ProductionFilters, Query()],
) -> Envelope[list[ProductionTrendPoint]]:
    return Envelope(data=await service.get_trend(filters))


@router.get(
    "/by-machine",
    response_model=Envelope[list[ProductionByDimension]],
    summary="Production grouped by machine",
    description="Production totals per machine for the filtered period, highest output first.",
    responses=COMMON_ERRORS,
)
async def production_by_machine(
    service: ProductionServiceDep,
    filters: Annotated[ProductionGroupFilters, Query()],
) -> Envelope[list[ProductionByDimension]]:
    return Envelope(data=await service.get_by_dimension(filters, "machine", filters.limit))


@router.get(
    "/by-component",
    response_model=Envelope[list[ProductionByDimension]],
    summary="Production grouped by component",
    description="Production totals per component for the filtered period, highest output first.",
    responses=COMMON_ERRORS,
)
async def production_by_component(
    service: ProductionServiceDep,
    filters: Annotated[ProductionGroupFilters, Query()],
) -> Envelope[list[ProductionByDimension]]:
    return Envelope(data=await service.get_by_dimension(filters, "component", filters.limit))


@router.get(
    "/by-shift",
    response_model=Envelope[list[ProductionByDimension]],
    summary="Production grouped by shift",
    description="Production totals per shift for the filtered period.",
    responses=COMMON_ERRORS,
)
async def production_by_shift(
    service: ProductionServiceDep,
    filters: Annotated[ProductionGroupFilters, Query()],
) -> Envelope[list[ProductionByDimension]]:
    return Envelope(data=await service.get_by_dimension(filters, "shift", filters.limit))


@router.get(
    "/by-line",
    response_model=Envelope[list[ProductionByDimension]],
    summary="Production grouped by production line",
    description="Production totals per line for the filtered period.",
    responses=COMMON_ERRORS,
)
async def production_by_line(
    service: ProductionServiceDep,
    filters: Annotated[ProductionGroupFilters, Query()],
) -> Envelope[list[ProductionByDimension]]:
    return Envelope(data=await service.get_by_dimension(filters, "line", filters.limit))
