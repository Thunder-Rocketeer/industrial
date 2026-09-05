"""Validated query parameter models (spec sections 6, 63, 64).

Every filter the API accepts is declared here as a Pydantic model bound to the
query string with `Depends`. Three things follow from that.

**Nothing unvalidated reaches a repository.** A UUID is parsed as a UUID, an
enum as an enum, a date as a date. An injection payload in `machine_id` fails at
the boundary with 422, long before any SQL exists.

**Unknown parameters are rejected.** `extra="forbid"` means `?admin=true` is a
422 rather than being silently ignored -- which surfaces typos and removes the
guesswork about whether an undocumented parameter does something.

**Ranges are bounded.** Page size is capped, and analytics windows have a
maximum span, so no request can ask the database for an unbounded amount of work
(spec section 64).

One FastAPI constraint shapes these models: a route may bind **one** Pydantic
model to the query string, and cannot combine it with additional scalar `Query`
parameters -- the model is then treated as a required body-style field and every
request fails with "filters: Field required". So anything a route needs from the
query string lives on the model, including `limit` on the grouping endpoints.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    InventoryStatus,
    MachineStatus,
    MaintenanceStatus,
)
from app.repositories.base import SortDirection
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

#: Longest window an analytics or trend query may span. Beyond roughly a year
#: the aggregate stops being a dashboard question and becomes a reporting job
#: (spec section 64: "Expensive date-range analytics should have reasonable
#: limits").
MAX_DATE_RANGE_DAYS = 366

#: Window used when a caller supplies no dates. Long enough to show a trend,
#: short enough to stay fast.
DEFAULT_RANGE_DAYS = 30


class PageParams(BaseModel):
    """Pagination, bounded so a client cannot request the whole table."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1, le=100_000, description="1-based page number.")
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Rows per page. Maximum {MAX_PAGE_SIZE}.",
    )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class DateRange(BaseModel):
    """An inclusive date window, defaulted and bounded.

    Both dates are optional. Supplying neither gives the last
    `DEFAULT_RANGE_DAYS`; supplying one anchors the window against the other.
    """

    model_config = ConfigDict(extra="forbid")

    start_date: date | None = Field(
        default=None, description="Inclusive start of the window (UTC)."
    )
    end_date: date | None = Field(default=None, description="Inclusive end of the window (UTC).")

    @model_validator(mode="after")
    def _resolve_and_validate(self) -> DateRange:
        if self.end_date is None:
            object.__setattr__(self, "end_date", date.today())
        if self.start_date is None:
            object.__setattr__(
                self, "start_date", self.end_date - timedelta(days=DEFAULT_RANGE_DAYS - 1)
            )

        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date.")

        span = (self.end_date - self.start_date).days + 1
        if span > MAX_DATE_RANGE_DAYS:
            raise ValueError(
                f"The requested range spans {span} days; the maximum is "
                f"{MAX_DATE_RANGE_DAYS}. Narrow the window."
            )
        return self

    @property
    def resolved_start(self) -> date:
        """The start date, guaranteed non-null after validation."""
        assert self.start_date is not None
        return self.start_date

    @property
    def resolved_end(self) -> date:
        assert self.end_date is not None
        return self.end_date

    @property
    def days(self) -> int:
        return (self.resolved_end - self.resolved_start).days + 1

    def cache_filters(self) -> dict[str, object]:
        return {"start": self.resolved_start, "end": self.resolved_end}


class ProductionFilters(DateRange):
    """Filters for the production endpoints."""

    machine_id: UUID | None = Field(default=None, description="Restrict to one machine.")
    component_id: UUID | None = Field(default=None, description="Restrict to one component.")
    shift_id: UUID | None = Field(default=None, description="Restrict to one shift.")
    line_id: UUID | None = Field(default=None, description="Restrict to one production line.")

    def cache_filters(self) -> dict[str, object]:
        return {
            **super().cache_filters(),
            "machine": self.machine_id,
            "component": self.component_id,
            "shift": self.shift_id,
            "line": self.line_id,
        }


class ProductionListFilters(ProductionFilters, PageParams):
    """Production list: filters plus pagination and a validated sort."""

    sort_by: str | None = Field(
        default=None,
        description=(
            "Sort key. One of: date, produced, planned, accepted, rejected, downtime, efficiency."
        ),
    )
    sort_dir: SortDirection = Field(default=SortDirection.DESC, description="Sort direction.")


class ProductionGroupFilters(ProductionFilters):
    """Production filters plus the group limit, for the by-dimension endpoints."""

    limit: int = Field(default=20, ge=1, le=100, description="Maximum groups to return.")


class QualityFilters(DateRange):
    """Filters for the quality endpoints."""

    machine_id: UUID | None = Field(default=None, description="Restrict to one machine.")
    component_id: UUID | None = Field(default=None, description="Restrict to one component.")
    defect_id: UUID | None = Field(default=None, description="Restrict to one defect type.")

    def cache_filters(self) -> dict[str, object]:
        return {
            **super().cache_filters(),
            "machine": self.machine_id,
            "component": self.component_id,
            "defect": self.defect_id,
        }


class QualityListFilters(QualityFilters, PageParams):
    """Quality list: filters plus pagination and a validated sort."""

    #: Rejection lines only. The default view of "quality records" is the
    #: defects, since the pass lines carry no defect information.
    rejections_only: bool = Field(
        default=False,
        description="Return only inspection lines that recorded a defect.",
    )
    sort_by: str | None = Field(
        default=None,
        description="Sort key. One of: inspected_at, inspected, rejected, passed.",
    )
    sort_dir: SortDirection = Field(default=SortDirection.DESC, description="Sort direction.")


class QualityGroupFilters(QualityFilters):
    """Quality filters plus the group limit, for the by-dimension endpoints."""

    limit: int = Field(default=20, ge=1, le=100, description="Maximum groups to return.")


class DefectBreakdownFilters(QualityFilters):
    """Quality filters plus the Pareto limit.

    Capped lower than the other groupings: a Pareto chart with fifty bars is not
    a Pareto chart.
    """

    limit: int = Field(default=20, ge=1, le=50, description="Maximum defect categories.")


class InventoryFilters(PageParams):
    """Filters for the inventory list."""

    model_config = ConfigDict(extra="forbid")

    status: InventoryStatus | None = Field(default=None, description="Restrict to one stock state.")
    component_id: UUID | None = Field(
        default=None, description="Restrict to stock linked to one component."
    )
    sort_by: str | None = Field(
        default=None,
        description="Sort key. One of: name, sku, status, quantity, utilization.",
    )
    sort_dir: SortDirection = Field(default=SortDirection.ASC, description="Sort direction.")

    def cache_filters(self) -> dict[str, object]:
        return {"status": self.status, "component": self.component_id}


class MachineFilters(BaseModel):
    """Filters for the machine list. Unpaginated: the fleet is small."""

    model_config = ConfigDict(extra="forbid")

    status: MachineStatus | None = Field(
        default=None, description="Restrict to one operational state."
    )
    line_id: UUID | None = Field(default=None, description="Restrict to one production line.")

    def cache_filters(self) -> dict[str, object]:
        return {"status": self.status, "line": self.line_id}


class AnalyticsFilters(DateRange):
    """Filters for the analytics endpoints."""

    machine_id: UUID | None = Field(default=None, description="Restrict to one machine.")
    component_id: UUID | None = Field(default=None, description="Restrict to one component.")
    line_id: UUID | None = Field(default=None, description="Restrict to one production line.")

    def cache_filters(self) -> dict[str, object]:
        return {
            **super().cache_filters(),
            "machine": self.machine_id,
            "component": self.component_id,
            "line": self.line_id,
        }


class AlertFilters(PageParams):
    """Filters for the alerts list."""

    model_config = ConfigDict(extra="forbid")

    status: AlertStatus | None = Field(default=None, description="Restrict to one status.")
    severity: AlertSeverity | None = Field(default=None, description="Restrict to one severity.")
    machine_id: UUID | None = Field(default=None, description="Restrict to one machine.")

    def cache_filters(self) -> dict[str, object]:
        return {
            "status": self.status,
            "severity": self.severity,
            "machine": self.machine_id,
        }


class MaintenanceFilters(PageParams):
    """Filters for the maintenance list."""

    model_config = ConfigDict(extra="forbid")

    status: MaintenanceStatus | None = Field(default=None, description="Restrict to one status.")
    machine_id: UUID | None = Field(default=None, description="Restrict to one machine.")
    upcoming_only: bool = Field(
        default=False, description="Return only work scheduled on or after today."
    )


class TrendFilters(DateRange):
    """Filters for the dashboard trends endpoint."""

    line_id: UUID | None = Field(default=None, description="Restrict to one production line.")

    def cache_filters(self) -> dict[str, object]:
        return {**super().cache_filters(), "line": self.line_id}
