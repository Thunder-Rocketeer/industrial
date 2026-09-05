"""Quality response models.

Schema note that shapes everything here: `quality_records` has two row shapes
(see `docs/database.md` section 5). A pass line has `defect_id IS NULL` and
carries the accepted units; each rejection line names one defect and carries the
units rejected for it. Summaries therefore aggregate across both shapes, while
the defect breakdown filters to `defect_id IS NOT NULL`.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DefectSeverity


class QualityRecord(BaseModel):
    """One inspection line."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    production_record_id: UUID
    inspected_at: datetime = Field(description="When the inspection was recorded (UTC).")

    machine_id: UUID
    machine_code: str
    component_id: UUID
    component_code: str
    component_name: str

    #: Null on the pass line, set on a rejection line.
    defect_id: UUID | None = None
    defect_code: str | None = None
    defect_name: str | None = None
    severity: DefectSeverity | None = None

    inspected_quantity: int = Field(ge=0)
    passed_quantity: int = Field(ge=0)
    rejected_quantity: int = Field(ge=0)
    first_pass_quantity: int = Field(
        ge=0, description="Units passing with no rework. Non-zero only on the pass line."
    )
    rework_quantity: int = Field(ge=0)

    is_rejection: bool = Field(description="True when this line records a defect.")


class QualitySummary(BaseModel):
    """Aggregate quality for a filtered period."""

    start_date: date
    end_date: date

    total_inspected: int = Field(ge=0, description="Units inspected across all lines.")
    total_passed: int = Field(ge=0)
    total_rejected: int = Field(ge=0)
    total_first_pass: int = Field(ge=0, description="Units that passed without rework.")
    total_rework: int = Field(ge=0)

    defect_rate_percentage: float = Field(ge=0, le=100, description="Rejected / inspected.")
    first_pass_yield_percentage: float = Field(
        ge=0, le=100, description="First-pass units / all units inspected."
    )
    quality_rate_percentage: float = Field(ge=0, le=100, description="Passed / inspected.")

    distinct_defect_types: int = Field(ge=0, description="Defect categories seen in the period.")
    record_count: int = Field(ge=0)
    has_data: bool


class DefectSummary(BaseModel):
    """One defect category's contribution, for the Pareto chart.

    `cumulative_percentage` is computed server-side. It depends on the position
    of a row within the sorted set, which is exactly the kind of thing that goes
    wrong when each chart component recalculates it from a differently sorted
    copy.
    """

    defect_id: UUID
    defect_code: str
    defect_name: str
    category: str
    default_severity: DefectSeverity

    rejected_quantity: int = Field(ge=0)
    occurrence_count: int = Field(ge=0, description="Inspection lines recording this defect.")
    share_percentage: float = Field(
        ge=0, le=100, description="This defect's share of all rejections."
    )
    cumulative_percentage: float = Field(
        ge=0, le=100, description="Running total of share, descending. Drives the Pareto line."
    )


class DefectTrendPoint(BaseModel):
    """One day on the defect trend chart."""

    bucket_date: date
    inspected_quantity: int = Field(ge=0)
    rejected_quantity: int = Field(ge=0)
    defect_rate_percentage: float = Field(ge=0, le=100)


class QualityByDimension(BaseModel):
    """Rejection totals grouped by machine, component or shift."""

    key_id: UUID
    key_code: str
    key_name: str
    inspected_quantity: int = Field(ge=0)
    rejected_quantity: int = Field(ge=0)
    defect_rate_percentage: float = Field(ge=0, le=100)
