"""Analytics response models (spec section 5.6).

OEE is always reported with its three terms alongside it. Spec section 5.6 is
explicit about why: "Display the three components separately so users can
understand why OEE changes." A single OEE number tells a manager something moved
but not whether to look at breakdowns, cycle times or scrap.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class OEEComponents(BaseModel):
    """The three OEE terms and their product.

    Each term is capped at 100%. Performance is the one that can genuinely
    exceed it, and a value above 100% means the recorded ideal cycle time is
    wrong rather than that a machine beat physics -- `performance_uncapped`
    keeps that visible instead of hiding it behind the cap.
    """

    availability_percentage: float = Field(
        ge=0, le=100, description="Operating time / planned production time."
    )
    performance_percentage: float = Field(
        ge=0, le=100, description="Actual output / ideal output for the operating time."
    )
    quality_percentage: float = Field(ge=0, le=100, description="Good units / total units.")
    oee_percentage: float = Field(ge=0, le=100, description="Availability x Performance x Quality.")
    performance_uncapped_percentage: float = Field(
        ge=0,
        description=(
            "Performance before capping. Above 100 indicates an ideal cycle time "
            "shorter than the machine's real capability -- a reference-data problem."
        ),
    )


class OEESummary(OEEComponents):
    """OEE across a filtered period, with the inputs it came from."""

    start_date: date
    end_date: date

    operating_minutes: int = Field(ge=0)
    planned_minutes: int = Field(ge=0)
    downtime_minutes: int = Field(ge=0)
    produced_quantity: int = Field(ge=0)
    accepted_quantity: int = Field(ge=0)
    rejected_quantity: int = Field(ge=0)
    ideal_output: float = Field(
        ge=0, description="Units producible in the operating time at rated cycle speed."
    )

    record_count: int = Field(ge=0)
    has_data: bool = Field(description="False when no production matched the filter.")


class OEETrendPoint(OEEComponents):
    """One day on the OEE trend chart."""

    bucket_date: date


class OEEByMachine(OEEComponents):
    """OEE for one machine, for fleet comparison."""

    machine_id: UUID
    machine_code: str
    machine_name: str
    produced_quantity: int = Field(ge=0)
    operating_minutes: int = Field(ge=0)


class EfficiencySummary(BaseModel):
    """Production efficiency against plan and target."""

    start_date: date
    end_date: date

    total_planned: int = Field(ge=0, description="Sum of planned quantities on production runs.")
    total_produced: int = Field(ge=0)
    total_target: int = Field(ge=0, description="Sum of daily targets from daily_targets.")

    efficiency_percentage: float = Field(ge=0, description="Produced / planned.")
    achievement_percentage: float = Field(ge=0, description="Produced / target.")

    total_planned_minutes: int = Field(ge=0)
    total_operating_minutes: int = Field(ge=0)
    total_downtime_minutes: int = Field(ge=0)
    downtime_percentage: float = Field(
        ge=0, le=100, description="Downtime as a share of planned production time."
    )

    record_count: int = Field(ge=0)
    has_data: bool


class EfficiencyTrendPoint(BaseModel):
    """One day on the efficiency trend chart."""

    bucket_date: date
    planned_quantity: int = Field(ge=0)
    produced_quantity: int = Field(ge=0)
    target_quantity: int = Field(ge=0)
    efficiency_percentage: float = Field(ge=0)
    achievement_percentage: float = Field(ge=0)


class DowntimeByMachine(BaseModel):
    """Downtime attributed to one machine."""

    machine_id: UUID
    machine_code: str
    machine_name: str
    downtime_minutes: int = Field(ge=0)
    planned_minutes: int = Field(ge=0)
    downtime_percentage: float = Field(ge=0, le=100)


class DefectAnalytics(BaseModel):
    """Defect analysis over a period: Pareto, trend and worst offenders."""

    start_date: date
    end_date: date

    total_inspected: int = Field(ge=0)
    total_rejected: int = Field(ge=0)
    defect_rate_percentage: float = Field(ge=0, le=100)

    # Imported lazily in the module that builds this to avoid a cycle; declared
    # here with forward references resolved at import time in `__init__`.
    by_defect: list[DefectSummary] = Field(
        default_factory=list, description="Pareto-ordered defect breakdown."
    )
    by_machine: list[QualityByDimension] = Field(
        default_factory=list, description="Rejection rate by machine, worst first."
    )
    by_component: list[QualityByDimension] = Field(
        default_factory=list, description="Rejection rate by component, worst first."
    )
    trend: list[DefectTrendPoint] = Field(
        default_factory=list, description="Daily defect rate over the period."
    )
    has_data: bool


from app.schemas.quality import (  # noqa: E402 - resolves the forward references above
    DefectSummary,
    DefectTrendPoint,
    QualityByDimension,
)

DefectAnalytics.model_rebuild()
