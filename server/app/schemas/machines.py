"""Machine response models."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MachineStatus, MachineType, MaintenanceStatus, MaintenanceType


class MachineSummary(BaseModel):
    """A machine as it appears on the machines board."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    machine_type: MachineType
    #: Spec section 45: never convey state by colour alone.
    machine_type_label: str = Field(description="Human-readable machine type.")

    line_id: UUID
    line_code: str
    line_name: str

    status: MachineStatus
    status_label: str = Field(description="Human-readable status.")

    current_component_id: UUID | None = None
    current_component_name: str | None = Field(
        default=None, description="What the machine is set up to run. Null when not running."
    )

    utilization_percentage: float = Field(ge=0, le=100)
    total_downtime_minutes: int = Field(ge=0)

    commissioned_date: date
    last_maintenance_date: date | None = None
    next_maintenance_date: date | None = None
    days_until_maintenance: int | None = Field(
        default=None,
        description="Days until the next scheduled service. Negative when overdue.",
    )
    maintenance_due: bool = Field(
        description="True when the next service is due within the attention window or overdue."
    )


class MachineProductionStats(BaseModel):
    """A machine's production over the requested window."""

    produced_quantity: int = Field(ge=0)
    accepted_quantity: int = Field(ge=0)
    rejected_quantity: int = Field(ge=0)
    planned_quantity: int = Field(ge=0)
    operating_minutes: int = Field(ge=0)
    planned_minutes: int = Field(ge=0)
    downtime_minutes: int = Field(ge=0)
    run_count: int = Field(ge=0, description="Production runs in the window.")

    availability_percentage: float = Field(ge=0, le=100)
    performance_percentage: float = Field(ge=0, le=100)
    quality_percentage: float = Field(ge=0, le=100)
    oee_percentage: float = Field(ge=0, le=100)
    defect_rate_percentage: float = Field(ge=0, le=100)


class MaintenanceRecord(BaseModel):
    """One maintenance job."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    machine_id: UUID
    machine_code: str
    machine_name: str
    maintenance_type: MaintenanceType
    maintenance_type_label: str
    status: MaintenanceStatus
    status_label: str
    scheduled_date: date
    started_at: datetime | None = None
    completed_at: datetime | None = None
    downtime_minutes: int = Field(ge=0)
    technician: str
    description: str
    cost: float | None = Field(default=None, ge=0)
    is_overdue: bool = Field(
        description="True when scheduled in the past and not yet completed or cancelled."
    )


class MachineDetail(MachineSummary):
    """A single machine with its production statistics and maintenance history."""

    production: MachineProductionStats
    recent_maintenance: list[MaintenanceRecord] = Field(
        default_factory=list, description="Most recent maintenance jobs, newest first."
    )
    upcoming_maintenance: list[MaintenanceRecord] = Field(
        default_factory=list, description="Scheduled work, soonest first."
    )


class MachineStatusCount(BaseModel):
    """How many machines are in one operational state."""

    status: MachineStatus
    status_label: str
    count: int = Field(ge=0)


class MachineFleetSummary(BaseModel):
    """Fleet-level machine availability, for the dashboard."""

    total_machines: int = Field(ge=0)
    running_count: int = Field(ge=0)
    idle_count: int = Field(ge=0)
    maintenance_count: int = Field(ge=0)
    offline_count: int = Field(ge=0)

    availability_percentage: float = Field(
        ge=0,
        le=100,
        description=(
            "Share of the fleet that is running. Idle machines are counted as "
            "unavailable: an idle machine is not producing."
        ),
    )
    average_utilization_percentage: float = Field(ge=0, le=100)
    maintenance_due_count: int = Field(
        ge=0, description="Machines due for service within the attention window, or overdue."
    )
    status_breakdown: list[MachineStatusCount] = Field(default_factory=list)
