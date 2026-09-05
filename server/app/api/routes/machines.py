"""Machine endpoints (spec section 9)."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.routes.production import COMMON_ERRORS
from app.dependencies import MachineServiceDep
from app.schemas.common import Envelope
from app.schemas.filters import MachineFilters
from app.schemas.machines import MachineDetail, MachineFleetSummary, MachineSummary

router = APIRouter(prefix="/machines", tags=["Machines"])


@router.get(
    "",
    response_model=Envelope[list[MachineSummary]],
    summary="List machines",
    description=(
        "Returns the machine fleet with status, utilisation and maintenance "
        "dates. Unpaginated: the fleet is small and the board shows all of it.\n\n"
        "`status_label` and `machine_type_label` carry display text so state is "
        "never conveyed by colour alone. `maintenance_due` is true when the next "
        "service falls within seven days or is already overdue."
    ),
    responses=COMMON_ERRORS,
)
async def list_machines(
    service: MachineServiceDep,
    filters: Annotated[MachineFilters, Query()],
) -> Envelope[list[MachineSummary]]:
    return Envelope(data=await service.list_machines(filters))


@router.get(
    "/summary",
    response_model=Envelope[MachineFleetSummary],
    summary="Machine fleet summary",
    description=(
        "Fleet counts per status and overall availability.\n\n"
        "Availability counts only RUNNING machines. An idle machine is capable "
        "but not producing, so counting it as available would make a stopped "
        "line look healthy."
    ),
    responses=COMMON_ERRORS,
)
async def machine_summary(service: MachineServiceDep) -> Envelope[MachineFleetSummary]:
    return Envelope(data=await service.get_fleet_summary())


@router.get(
    "/{machine_id}",
    response_model=Envelope[MachineDetail],
    summary="Get one machine",
    description=(
        "Returns a machine with its production statistics for the requested "
        "window (last 30 days by default), its OEE terms, recent completed "
        "maintenance and upcoming scheduled work."
    ),
    responses={
        **COMMON_ERRORS,
        404: {"description": "The requested machine does not exist."},
    },
)
async def get_machine(
    machine_id: UUID,
    service: MachineServiceDep,
    start_date: Annotated[
        date | None, Query(description="Start of the statistics window (UTC).")
    ] = None,
    end_date: Annotated[
        date | None, Query(description="End of the statistics window (UTC).")
    ] = None,
) -> Envelope[MachineDetail]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_date must be on or before end_date.",
        )

    machine = await service.get_machine(machine_id, start_date=start_date, end_date=end_date)
    if machine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found.")
    return Envelope(data=machine)
