"""Production response models (spec section 10).

Every field is explicit. No repository row is ever returned directly: an
endpoint that serialises whatever the query happened to select will leak a
column the moment someone adds one, and gives the frontend no contract to type
against.

Rates are computed in the service layer and carried alongside the counts they
came from, so a caller can tell a genuine zero from an absent denominator.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProductionRecord(BaseModel):
    """One production run: a machine, a component, a shift, a day."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    record_date: date = Field(description="Production date (UTC).")

    machine_id: UUID
    machine_code: str = Field(description="Human-readable machine identifier, e.g. CNC-T-001.")
    machine_name: str

    component_id: UUID
    component_code: str
    component_name: str

    line_id: UUID
    line_code: str
    line_name: str

    shift_id: UUID
    shift_code: str
    shift_name: str

    started_at: datetime = Field(description="Start of the run (UTC).")
    ended_at: datetime = Field(description="End of the run (UTC).")

    planned_quantity: int = Field(ge=0, description="Units planned for this run.")
    produced_quantity: int = Field(ge=0, description="Units actually produced.")
    accepted_quantity: int = Field(ge=0, description="Units that passed inspection.")
    rejected_quantity: int = Field(ge=0, description="Units rejected.")

    planned_minutes: int = Field(ge=0, description="Scheduled productive minutes.")
    operating_minutes: int = Field(ge=0, description="Minutes actually producing.")
    downtime_minutes: int = Field(ge=0, description="Minutes lost to unplanned stoppages.")

    efficiency_percentage: float = Field(
        ge=0, description="Produced against planned, as a percentage."
    )
    defect_rate_percentage: float = Field(
        ge=0, le=100, description="Rejected against produced, as a percentage."
    )


class ProductionSummary(BaseModel):
    """Aggregate production for a filtered period."""

    start_date: date
    end_date: date

    total_planned: int = Field(ge=0, description="Sum of planned quantities.")
    total_produced: int = Field(ge=0, description="Sum of produced quantities.")
    total_accepted: int = Field(ge=0)
    total_rejected: int = Field(ge=0)

    target_quantity: int = Field(
        ge=0, description="Sum of daily targets for the period, from daily_targets."
    )
    achievement_percentage: float = Field(
        ge=0, description="Produced against target. Uncapped: exceeding target is real."
    )
    efficiency_percentage: float = Field(ge=0, description="Produced against planned.")
    defect_rate_percentage: float = Field(ge=0, le=100)

    total_planned_minutes: int = Field(ge=0)
    total_operating_minutes: int = Field(ge=0)
    total_downtime_minutes: int = Field(ge=0)

    record_count: int = Field(ge=0, description="Production runs contributing to these totals.")
    #: Present so a caller can distinguish "0% because nothing ran" from
    #: "0% because everything failed" -- the percentage alone cannot.
    has_data: bool = Field(description="False when no production records matched the filter.")


class ProductionTrendPoint(BaseModel):
    """One day on the production trend chart."""

    bucket_date: date = Field(description="The day these totals cover (UTC).")
    planned_quantity: int = Field(ge=0)
    produced_quantity: int = Field(ge=0)
    accepted_quantity: int = Field(ge=0)
    rejected_quantity: int = Field(ge=0)
    target_quantity: int = Field(ge=0, description="Daily target for the same day.")
    achievement_percentage: float = Field(ge=0)


class ProductionByDimension(BaseModel):
    """Production totals grouped by machine, component, line or shift.

    One model for all four groupings: they differ only in what `key` names, and
    four near-identical schemas would drift.
    """

    key_id: UUID = Field(description="Identifier of the grouping entity.")
    key_code: str = Field(description="Short code of the grouping entity.")
    key_name: str = Field(description="Display name of the grouping entity.")
    produced_quantity: int = Field(ge=0)
    accepted_quantity: int = Field(ge=0)
    rejected_quantity: int = Field(ge=0)
    planned_quantity: int = Field(ge=0)
    efficiency_percentage: float = Field(ge=0)
    defect_rate_percentage: float = Field(ge=0, le=100)
