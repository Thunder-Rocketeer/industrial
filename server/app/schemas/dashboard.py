"""Dashboard response models (spec sections 5.1 and 9).

`DashboardSummary` is deliberately one large composite. Spec section 9 asks for
a single endpoint that renders the main screen "without requiring many
independent requests", and spec section 44 wants a manager to understand the
factory in 5-10 seconds. Six round trips against a hosted database, each with
its own latency, is the thing that makes that impossible -- so the composition
happens server-side where the queries can run concurrently against one pool.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.alerts import Alert, AlertSummary
from app.schemas.analytics import OEEComponents
from app.schemas.inventory import InventorySummary
from app.schemas.machines import MachineFleetSummary
from app.schemas.production import ProductionSummary, ProductionTrendPoint
from app.schemas.quality import DefectSummary, DefectTrendPoint, QualitySummary


class KpiTrend(BaseModel):
    """Movement of a KPI against the previous comparable period.

    `change_percentage` is nullable on purpose: "no previous period to compare
    against" and "no change" are different facts, and a KPI card showing
    "0.0% vs yesterday" when yesterday has no data states something false.
    """

    change_percentage: float | None = Field(
        default=None, description="Change against the previous period. Null when incomparable."
    )
    direction: str = Field(
        default="flat",
        description="One of: up, down, flat, unknown. Text so it is not conveyed by colour alone.",
    )
    comparison_label: str = Field(
        default="", description="What the comparison is against, e.g. 'vs yesterday'."
    )


class DashboardKpi(BaseModel):
    """One KPI card (spec section 5.1).

    Carries everything the card renders -- value, unit, context, trend and a
    textual status -- so the frontend formats rather than calculates. Spec
    section 42: KPI formulas must not live in UI components.
    """

    key: str = Field(description="Stable identifier, e.g. 'production_today'.")
    label: str = Field(description="Display name of the KPI.")
    value: float = Field(description="Current value.")
    unit: str = Field(description="Unit, e.g. 'units', '%'.")
    context_label: str = Field(
        default="", description="Short supporting text, e.g. '9,250 / 10,000 units'."
    )
    status: str = Field(
        default="neutral",
        description="One of: good, warning, critical, neutral. Text, never a colour.",
    )
    status_label: str = Field(default="", description="Human-readable status.")
    trend: KpiTrend = Field(default_factory=KpiTrend)


class DashboardSummary(BaseModel):
    """Everything the executive dashboard needs, in one response."""

    generated_at: datetime = Field(description="When this snapshot was computed (UTC).")
    business_date: date = Field(description="The date the 'today' figures cover (UTC).")

    kpis: list[DashboardKpi] = Field(
        default_factory=list, description="KPI cards, in display order."
    )

    production: ProductionSummary
    quality: QualitySummary
    inventory: InventorySummary
    machines: MachineFleetSummary
    oee: OEEComponents

    alerts: AlertSummary
    recent_alerts: list[Alert] = Field(
        default_factory=list, description="Most urgent open alerts, most severe first."
    )

    #: True when the summary was assembled without the cache. Useful when
    #: diagnosing a stale dashboard, and harmless to expose: it says nothing
    #: about the data itself.
    cache_hit: bool = Field(default=False, description="Whether this response came from cache.")


class DashboardTrends(BaseModel):
    """Chart series for the dashboard (spec section 10)."""

    start_date: date
    end_date: date

    production: list[ProductionTrendPoint] = Field(
        default_factory=list, description="Daily produced, planned and target quantities."
    )
    defects: list[DefectTrendPoint] = Field(default_factory=list, description="Daily defect rate.")
    oee: list[OEETrendPoint] = Field(
        default_factory=list, description="Daily OEE and its three terms."
    )
    top_defects: list[DefectSummary] = Field(
        default_factory=list, description="Pareto-ordered defect categories for the period."
    )
    has_data: bool = Field(description="False when nothing matched the requested window.")


from app.schemas.analytics import OEETrendPoint  # noqa: E402 - resolves the forward reference

DashboardTrends.model_rebuild()
