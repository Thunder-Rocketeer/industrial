"""Analytics endpoints (spec section 9).

These are the most expensive queries in the API, so they carry the strictest
rate limit and the longest cache TTL.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.routes.production import COMMON_ERRORS
from app.dependencies import AnalyticsServiceDep
from app.schemas.analytics import (
    DefectAnalytics,
    DowntimeByMachine,
    EfficiencySummary,
    EfficiencyTrendPoint,
    OEEByMachine,
    OEESummary,
    OEETrendPoint,
)
from app.schemas.common import Envelope
from app.schemas.filters import AnalyticsFilters

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get(
    "/oee",
    response_model=Envelope[OEESummary],
    summary="Overall Equipment Effectiveness",
    description=(
        "OEE for the filtered period, with its three terms reported separately "
        "so a change can be attributed.\n\n"
        "`OEE = Availability x Performance x Quality`, where Availability is "
        "operating time over planned production time, Performance is actual "
        "output over the ideal output for that operating time, and Quality is "
        "good units over total units.\n\n"
        "Each term is capped at 100%. `performance_uncapped_percentage` exposes "
        "the raw value: above 100 means a component's recorded ideal cycle time "
        "is shorter than the machine's real capability, which is a "
        "reference-data problem rather than a machine outperforming physics."
    ),
    responses=COMMON_ERRORS,
)
async def oee(
    service: AnalyticsServiceDep,
    filters: Annotated[AnalyticsFilters, Query()],
) -> Envelope[OEESummary]:
    return Envelope(data=await service.get_oee(filters))


@router.get(
    "/oee/trend",
    response_model=Envelope[list[OEETrendPoint]],
    summary="Daily OEE trend",
    description="Daily OEE and its three terms over the filtered period.",
    responses=COMMON_ERRORS,
)
async def oee_trend(
    service: AnalyticsServiceDep,
    filters: Annotated[AnalyticsFilters, Query()],
) -> Envelope[list[OEETrendPoint]]:
    return Envelope(data=await service.get_oee_trend(filters))


@router.get(
    "/oee/by-machine",
    response_model=Envelope[list[OEEByMachine]],
    summary="OEE per machine",
    description=(
        "OEE for each machine over the filtered period, lowest first so the "
        "machines needing attention appear at the top."
    ),
    responses=COMMON_ERRORS,
)
async def oee_by_machine(
    service: AnalyticsServiceDep,
    filters: Annotated[AnalyticsFilters, Query()],
) -> Envelope[list[OEEByMachine]]:
    return Envelope(data=await service.get_oee_by_machine(filters))


@router.get(
    "/production-efficiency",
    response_model=Envelope[EfficiencySummary],
    summary="Production efficiency",
    description=(
        "Production against both plan and target for the filtered period, with "
        "downtime as a share of planned production time.\n\n"
        "As with the production summary, `achievement_percentage` is returned as "
        "0 when the filter includes a machine, because daily targets have no "
        "machine dimension and the comparison would understate achievement."
    ),
    responses=COMMON_ERRORS,
)
async def production_efficiency(
    service: AnalyticsServiceDep,
    filters: Annotated[AnalyticsFilters, Query()],
) -> Envelope[EfficiencySummary]:
    return Envelope(data=await service.get_efficiency(filters))


@router.get(
    "/production-efficiency/trend",
    response_model=Envelope[list[EfficiencyTrendPoint]],
    summary="Daily efficiency trend",
    description="Daily efficiency and target achievement over the filtered period.",
    responses=COMMON_ERRORS,
)
async def efficiency_trend(
    service: AnalyticsServiceDep,
    filters: Annotated[AnalyticsFilters, Query()],
) -> Envelope[list[EfficiencyTrendPoint]]:
    return Envelope(data=await service.get_efficiency_trend(filters))


@router.get(
    "/downtime",
    response_model=Envelope[list[DowntimeByMachine]],
    summary="Downtime by machine",
    description="Unplanned downtime per machine over the filtered period, worst first.",
    responses=COMMON_ERRORS,
)
async def downtime_by_machine(
    service: AnalyticsServiceDep,
    filters: Annotated[AnalyticsFilters, Query()],
) -> Envelope[list[DowntimeByMachine]]:
    return Envelope(data=await service.get_downtime_by_machine(filters))


@router.get(
    "/defects",
    response_model=Envelope[DefectAnalytics],
    summary="Defect analysis",
    description=(
        "Complete defect analysis for the filtered period: the Pareto "
        "breakdown by category, rejection rates by machine and by component, "
        "and the daily defect-rate trend, in one response."
    ),
    responses=COMMON_ERRORS,
)
async def defect_analytics(
    service: AnalyticsServiceDep,
    filters: Annotated[AnalyticsFilters, Query()],
) -> Envelope[DefectAnalytics]:
    return Envelope(data=await service.get_defect_analytics(filters))
