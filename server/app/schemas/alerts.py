"""Alert response models (spec section 34)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AlertSeverity, AlertStatus, AlertType


class Alert(BaseModel):
    """One operational alert.

    Spec section 34 requires a title, description, timestamp, severity and the
    related machine or component. Section 45 requires that severity is readable
    as text rather than conveyed by colour, which is why `severity_label` and
    `description` are both mandatory and non-empty.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_type: AlertType
    alert_type_label: str = Field(description="Human-readable alert category.")
    severity: AlertSeverity
    severity_label: str = Field(description="Info, Warning or Critical, as display text.")
    status: AlertStatus
    status_label: str

    title: str = Field(min_length=1)
    description: str = Field(min_length=1, description="Full sentence describing the condition.")

    machine_id: UUID | None = None
    machine_code: str | None = None
    machine_name: str | None = None
    component_id: UUID | None = None
    component_name: str | None = None
    inventory_item_id: UUID | None = None
    inventory_item_name: str | None = None
    line_id: UUID | None = None
    line_name: str | None = None

    triggered_at: datetime = Field(description="When the condition was detected (UTC).")
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    age_minutes: int = Field(ge=0, description="Minutes since the alert was triggered.")


class AlertSeverityCount(BaseModel):
    """How many open alerts sit at one severity."""

    severity: AlertSeverity
    severity_label: str
    count: int = Field(ge=0)


class AlertSummary(BaseModel):
    """Counts for the dashboard alerts panel."""

    total_open: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    info_count: int = Field(ge=0)
    acknowledged_count: int = Field(ge=0)
    severity_breakdown: list[AlertSeverityCount] = Field(default_factory=list)
