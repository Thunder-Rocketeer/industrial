"""Fakes for testing the API without a database.

Spec section 22: "Do not require a live Supabase project for unit tests that can
be tested with mocks/fakes."

The API tests override the *service* dependencies rather than faking a
connection. That draws the seam where the layering already puts one: routes are
responsible for validation, envelope shape and error mapping, and those are what
these tests exercise. Faking a cursor instead would couple every API test to the
SQL, which is covered separately by the parse tests and, against a real
database, by the integration tests.

`FakeDatabasePool` exists for the handful of tests that need the *absence* of a
database to be observable -- readiness reporting, and the 503 path.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from app.db.connection import DatabaseNotConfiguredError
from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    AlertType,
    DefectSeverity,
    InventoryStatus,
    MachineStatus,
    MachineType,
    MaintenanceStatus,
    MaintenanceType,
    RoleCode,
)
from app.schemas.alerts import Alert, AlertSeverityCount, AlertSummary
from app.schemas.analytics import (
    DefectAnalytics,
    DowntimeByMachine,
    EfficiencySummary,
    EfficiencyTrendPoint,
    OEEByMachine,
    OEEComponents,
    OEESummary,
    OEETrendPoint,
)
from app.schemas.dashboard import DashboardKpi, DashboardSummary, DashboardTrends, KpiTrend
from app.schemas.inventory import (
    InventoryAlert,
    InventoryItem,
    InventoryStatusCount,
    InventorySummary,
    InventoryTransaction,
    InventoryTrendPoint,
)
from app.schemas.machines import (
    MachineDetail,
    MachineFleetSummary,
    MachineProductionStats,
    MachineStatusCount,
    MachineSummary,
    MaintenanceRecord,
)
from app.schemas.production import (
    ProductionByDimension,
    ProductionRecord,
    ProductionSummary,
    ProductionTrendPoint,
)
from app.schemas.quality import (
    DefectSummary,
    DefectTrendPoint,
    QualityByDimension,
    QualityRecord,
    QualitySummary,
)
from app.services.auth_service import AuthenticatedUser

#: `datetime.UTC` is Python 3.11+; this project targets 3.10.
UTC = timezone.utc

# Fixed identifiers so assertions can name them.
MACHINE_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPONENT_ID = UUID("22222222-2222-4222-8222-222222222222")
LINE_ID = UUID("33333333-3333-4333-8333-333333333333")
SHIFT_ID = UUID("44444444-4444-4444-8444-444444444444")
DEFECT_ID = UUID("55555555-5555-4555-8555-555555555555")
ITEM_ID = UUID("66666666-6666-4666-8666-666666666666")
RECORD_ID = UUID("77777777-7777-4777-8777-777777777777")
ALERT_ID = UUID("88888888-8888-4888-8888-888888888888")

TODAY = date(2026, 9, 5)
NOW = datetime(2026, 9, 5, 6, 30, tzinfo=UTC)

#: A string that would execute if any layer treated a value as markup or SQL.
#: Used to prove the API returns it inert (spec section 14).
XSS_PAYLOAD = "<script>alert('XSS')</script>"

USER_ID = UUID("99999999-9999-4999-8999-999999999999")


def make_user(role: RoleCode = RoleCode.ADMIN, **overrides: Any) -> AuthenticatedUser:
    """Build an authenticated user for tests that need a session.

    Defaults to ADMIN so a test about pagination is not also a test about
    permissions. Tests that *are* about permissions pass the role explicitly.
    """
    labels = {
        RoleCode.ADMIN: "Administrator",
        RoleCode.FACTORY_MANAGER: "Factory Manager",
        RoleCode.PRODUCTION_SUPERVISOR: "Production Supervisor",
        RoleCode.QUALITY_ENGINEER: "Quality Engineer",
        RoleCode.INVENTORY_MANAGER: "Inventory Manager",
        RoleCode.VIEWER: "Viewer",
    }
    defaults: dict[str, Any] = {
        "id": USER_ID,
        "email": "tester@factory.local",
        "name": "Test User",
        "role": role,
        "role_label": labels[role],
        "avatar_url": None,
        "is_active": True,
        "last_login_at": NOW,
    }
    return AuthenticatedUser(**{**defaults, **overrides})


class FakeRevocationStore:
    """In-memory stand-in for the Redis revocation denylist."""

    def __init__(self) -> None:
        self.revoked: set[str] = set()

    async def revoke(self, token_id: str, ttl_seconds: int) -> bool:
        self.revoked.add(token_id)
        return True

    async def is_revoked(self, token_id: str) -> bool:
        return token_id in self.revoked


class FakeAuditService:
    """Records audit calls in memory so tests can assert on them."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def record(self, **kwargs: Any) -> None:
        self.events.append(kwargs)

    async def login_initiated(self, **kwargs: Any) -> None:
        self.events.append({"action": "AUTH.LOGIN_INITIATED", **kwargs})

    async def login_success(self, **kwargs: Any) -> None:
        self.events.append({"action": "AUTH.LOGIN_SUCCESS", **kwargs})

    async def login_failure(self, **kwargs: Any) -> None:
        self.events.append({"action": "AUTH.LOGIN_FAILURE", **kwargs})

    async def login_denied(self, **kwargs: Any) -> None:
        self.events.append({"action": "AUTH.LOGIN_DENIED", **kwargs})

    async def logout(self, **kwargs: Any) -> None:
        self.events.append({"action": "AUTH.LOGOUT", **kwargs})

    async def unauthorized(self, **kwargs: Any) -> None:
        self.events.append({"action": "AUTH.UNAUTHORIZED_ACCESS", **kwargs})

    async def forbidden(self, **kwargs: Any) -> None:
        self.events.append({"action": "AUTH.FORBIDDEN_ACCESS", **kwargs})

    def actions(self) -> list[str]:
        return [event.get("action", "") for event in self.events]


class FakeDatabasePool:
    """A pool that is never available.

    Used to assert that a missing database produces a clean 503 with the error
    envelope rather than a stack trace, and that readiness reports it.
    """

    def __init__(self, *, healthy: bool = False) -> None:
        self._healthy = healthy
        self.is_open = healthy

    @asynccontextmanager
    async def connection(self) -> Any:
        if not self._healthy:
            raise DatabaseNotConfiguredError("The database connection pool is not available.")
        yield None

    async def healthcheck(self) -> bool:
        return self._healthy

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


def make_production_record(**overrides: Any) -> ProductionRecord:
    defaults: dict[str, Any] = {
        "id": RECORD_ID,
        "record_date": TODAY,
        "machine_id": MACHINE_ID,
        "machine_code": "CNC-T-001",
        "machine_name": "CNC Turning Center 1",
        "component_id": COMPONENT_ID,
        "component_code": "BRK-DISC",
        "component_name": "Brake Disc",
        "line_id": LINE_ID,
        "line_code": "LINE-A",
        "line_name": "Line A - Brake Components",
        "shift_id": SHIFT_ID,
        "shift_code": "MORNING",
        "shift_name": "Morning",
        "started_at": datetime(2026, 9, 5, 6, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 9, 5, 14, 0, tzinfo=UTC),
        "planned_quantity": 600,
        "produced_quantity": 580,
        "accepted_quantity": 568,
        "rejected_quantity": 12,
        "planned_minutes": 450,
        "operating_minutes": 430,
        "downtime_minutes": 20,
        "efficiency_percentage": 96.67,
        "defect_rate_percentage": 2.07,
    }
    return ProductionRecord(**{**defaults, **overrides})


def make_production_summary(**overrides: Any) -> ProductionSummary:
    defaults: dict[str, Any] = {
        "start_date": TODAY,
        "end_date": TODAY,
        "total_planned": 10_000,
        "total_produced": 9_250,
        "total_accepted": 9_000,
        "total_rejected": 250,
        "target_quantity": 10_000,
        "achievement_percentage": 92.5,
        "efficiency_percentage": 92.5,
        "defect_rate_percentage": 2.7,
        "total_planned_minutes": 1_350,
        "total_operating_minutes": 1_280,
        "total_downtime_minutes": 70,
        "record_count": 14,
        "has_data": True,
    }
    return ProductionSummary(**{**defaults, **overrides})


def make_quality_summary(**overrides: Any) -> QualitySummary:
    defaults: dict[str, Any] = {
        "start_date": TODAY,
        "end_date": TODAY,
        "total_inspected": 9_250,
        "total_passed": 9_000,
        "total_rejected": 250,
        "total_first_pass": 8_900,
        "total_rework": 100,
        "defect_rate_percentage": 2.7,
        "first_pass_yield_percentage": 96.22,
        "quality_rate_percentage": 97.3,
        "distinct_defect_types": 6,
        "record_count": 40,
        "has_data": True,
    }
    return QualitySummary(**{**defaults, **overrides})


def make_inventory_summary(**overrides: Any) -> InventorySummary:
    defaults: dict[str, Any] = {
        "total_items": 8,
        "healthy_count": 3,
        "low_count": 2,
        "critical_count": 2,
        "overstocked_count": 1,
        "health_percentage": 37.5,
        "items_requiring_attention": 4,
        "total_stock_value": 125_000.0,
        "status_breakdown": [
            InventoryStatusCount(status=InventoryStatus.HEALTHY, status_label="Healthy", count=3),
            InventoryStatusCount(status=InventoryStatus.LOW, status_label="Low", count=2),
            InventoryStatusCount(status=InventoryStatus.CRITICAL, status_label="Critical", count=2),
            InventoryStatusCount(
                status=InventoryStatus.OVERSTOCKED, status_label="Overstocked", count=1
            ),
        ],
    }
    return InventorySummary(**{**defaults, **overrides})


def make_inventory_item(**overrides: Any) -> InventoryItem:
    defaults: dict[str, Any] = {
        "id": ITEM_ID,
        "sku": "RM-STEEL-BILLET",
        "name": "Steel Billets",
        "material_type": "Raw Material",
        "unit": "kg",
        "component_id": None,
        "component_code": None,
        "component_name": None,
        "current_quantity": 42_500.0,
        "minimum_stock": 8_000.0,
        "reorder_point": 15_000.0,
        "maximum_stock": 60_000.0,
        "status": InventoryStatus.HEALTHY,
        "status_label": "Healthy",
        "stock_utilization_percentage": 70.83,
        "supplier_name": "Nordkraft Steel AB",
        "supplier_lead_time_days": 21,
        "unit_cost": 1.85,
        "last_counted_at": NOW,
        "updated_at": NOW,
    }
    return InventoryItem(**{**defaults, **overrides})


def make_inventory_alert(**overrides: Any) -> InventoryAlert:
    defaults: dict[str, Any] = {
        "id": ITEM_ID,
        "sku": "CS-LUBRICANT",
        "name": "Lubricant",
        "unit": "litres",
        "status": InventoryStatus.CRITICAL,
        "status_label": "Critical",
        "current_quantity": 310.0,
        "minimum_stock": 400.0,
        "reorder_point": 900.0,
        "shortfall": 590.0,
        "supplier_name": "Helios Industrial Fluids",
        "supplier_lead_time_days": 14,
        "message": "Lubricant is at 310 litres, at or below the minimum of 400.",
    }
    return InventoryAlert(**{**defaults, **overrides})


def make_machine_summary(**overrides: Any) -> MachineSummary:
    defaults: dict[str, Any] = {
        "id": MACHINE_ID,
        "code": "CNC-T-001",
        "name": "CNC Turning Center 1",
        "machine_type": MachineType.CNC_TURNING_CENTER,
        "machine_type_label": "CNC Turning Center",
        "line_id": LINE_ID,
        "line_code": "LINE-A",
        "line_name": "Line A - Brake Components",
        "status": MachineStatus.RUNNING,
        "status_label": "Running",
        "current_component_id": COMPONENT_ID,
        "current_component_name": "Brake Disc",
        "utilization_percentage": 92.31,
        "total_downtime_minutes": 553,
        "commissioned_date": date(2021, 3, 15),
        "last_maintenance_date": date(2026, 8, 1),
        "next_maintenance_date": date(2026, 9, 15),
        "days_until_maintenance": 10,
        "maintenance_due": False,
    }
    return MachineSummary(**{**defaults, **overrides})


def make_fleet_summary(**overrides: Any) -> MachineFleetSummary:
    defaults: dict[str, Any] = {
        "total_machines": 14,
        "running_count": 9,
        "idle_count": 2,
        "maintenance_count": 2,
        "offline_count": 1,
        "availability_percentage": 64.29,
        "average_utilization_percentage": 88.5,
        "maintenance_due_count": 3,
        "status_breakdown": [
            MachineStatusCount(status=MachineStatus.RUNNING, status_label="Running", count=9),
            MachineStatusCount(status=MachineStatus.IDLE, status_label="Idle", count=2),
            MachineStatusCount(
                status=MachineStatus.MAINTENANCE, status_label="Under maintenance", count=2
            ),
            MachineStatusCount(status=MachineStatus.OFFLINE, status_label="Offline", count=1),
        ],
    }
    return MachineFleetSummary(**{**defaults, **overrides})


def make_maintenance_record(**overrides: Any) -> MaintenanceRecord:
    defaults: dict[str, Any] = {
        "id": RECORD_ID,
        "machine_id": MACHINE_ID,
        "machine_code": "CNC-T-001",
        "machine_name": "CNC Turning Center 1",
        "maintenance_type": MaintenanceType.PREVENTIVE,
        "maintenance_type_label": "Preventive",
        "status": MaintenanceStatus.COMPLETED,
        "status_label": "Completed",
        "scheduled_date": date(2026, 8, 1),
        "started_at": datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
        "completed_at": datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        "downtime_minutes": 240,
        "technician": "R. Persson",
        "description": "Scheduled preventive service.",
        "cost": 850.0,
        "is_overdue": False,
    }
    return MaintenanceRecord(**{**defaults, **overrides})


def make_machine_detail(**overrides: Any) -> MachineDetail:
    summary = make_machine_summary()
    defaults: dict[str, Any] = {
        **summary.model_dump(),
        "production": MachineProductionStats(
            produced_quantity=17_400,
            accepted_quantity=17_040,
            rejected_quantity=360,
            planned_quantity=18_000,
            operating_minutes=12_900,
            planned_minutes=13_500,
            downtime_minutes=600,
            run_count=30,
            availability_percentage=95.56,
            performance_percentage=88.4,
            quality_percentage=97.93,
            oee_percentage=82.72,
            defect_rate_percentage=2.07,
        ),
        "recent_maintenance": [make_maintenance_record()],
        "upcoming_maintenance": [],
    }
    return MachineDetail(**{**defaults, **overrides})


def make_alert(**overrides: Any) -> Alert:
    defaults: dict[str, Any] = {
        "id": ALERT_ID,
        "alert_type": AlertType.CRITICAL_INVENTORY,
        "alert_type_label": "Critical inventory",
        "severity": AlertSeverity.CRITICAL,
        "severity_label": "Critical",
        "status": AlertStatus.OPEN,
        "status_label": "Open",
        "title": "Critical stock: Lubricant",
        "description": "Lubricant is at 310 litres, at or below the minimum of 400.",
        "machine_id": None,
        "machine_code": None,
        "machine_name": None,
        "component_id": None,
        "component_name": None,
        "inventory_item_id": ITEM_ID,
        "inventory_item_name": "Lubricant",
        "line_id": None,
        "line_name": None,
        "triggered_at": NOW,
        "acknowledged_at": None,
        "resolved_at": None,
        "age_minutes": 540,
    }
    return Alert(**{**defaults, **overrides})


def make_alert_summary(**overrides: Any) -> AlertSummary:
    defaults: dict[str, Any] = {
        "total_open": 7,
        "critical_count": 3,
        "warning_count": 3,
        "info_count": 1,
        "acknowledged_count": 2,
        "severity_breakdown": [
            AlertSeverityCount(severity=AlertSeverity.CRITICAL, severity_label="Critical", count=3),
            AlertSeverityCount(severity=AlertSeverity.WARNING, severity_label="Warning", count=3),
            AlertSeverityCount(severity=AlertSeverity.INFO, severity_label="Info", count=1),
        ],
    }
    return AlertSummary(**{**defaults, **overrides})


def make_oee_components(**overrides: Any) -> OEEComponents:
    defaults: dict[str, Any] = {
        "availability_percentage": 94.81,
        "performance_percentage": 88.4,
        "quality_percentage": 97.3,
        "oee_percentage": 81.55,
        "performance_uncapped_percentage": 88.4,
    }
    return OEEComponents(**{**defaults, **overrides})


def make_oee_summary(**overrides: Any) -> OEESummary:
    defaults: dict[str, Any] = {
        **make_oee_components().model_dump(),
        "start_date": TODAY,
        "end_date": TODAY,
        "operating_minutes": 1_280,
        "planned_minutes": 1_350,
        "downtime_minutes": 70,
        "produced_quantity": 9_250,
        "accepted_quantity": 9_000,
        "rejected_quantity": 250,
        "ideal_output": 10_464.0,
        "record_count": 14,
        "has_data": True,
    }
    return OEESummary(**{**defaults, **overrides})


def make_efficiency_summary(**overrides: Any) -> EfficiencySummary:
    defaults: dict[str, Any] = {
        "start_date": TODAY,
        "end_date": TODAY,
        "total_planned": 10_000,
        "total_produced": 9_250,
        "total_target": 10_400,
        "efficiency_percentage": 92.5,
        "achievement_percentage": 88.94,
        "total_planned_minutes": 1_350,
        "total_operating_minutes": 1_280,
        "total_downtime_minutes": 70,
        "downtime_percentage": 5.19,
        "record_count": 14,
        "has_data": True,
    }
    return EfficiencySummary(**{**defaults, **overrides})


def make_defect_summary(**overrides: Any) -> DefectSummary:
    defaults: dict[str, Any] = {
        "defect_id": DEFECT_ID,
        "defect_code": "DIMENSIONAL_OOT",
        "defect_name": "Dimensional Out-of-Tolerance",
        "category": "Dimensional",
        "default_severity": DefectSeverity.MAJOR,
        "rejected_quantity": 8_098,
        "occurrence_count": 1_240,
        "share_percentage": 26.8,
        "cumulative_percentage": 26.8,
    }
    return DefectSummary(**{**defaults, **overrides})


def make_quality_record(**overrides: Any) -> QualityRecord:
    defaults: dict[str, Any] = {
        "id": RECORD_ID,
        "production_record_id": RECORD_ID,
        "inspected_at": NOW,
        "machine_id": MACHINE_ID,
        "machine_code": "CNC-T-001",
        "component_id": COMPONENT_ID,
        "component_code": "BRK-DISC",
        "component_name": "Brake Disc",
        "defect_id": DEFECT_ID,
        "defect_code": "DIMENSIONAL_OOT",
        "defect_name": "Dimensional Out-of-Tolerance",
        "severity": DefectSeverity.MAJOR,
        "inspected_quantity": 12,
        "passed_quantity": 0,
        "rejected_quantity": 12,
        "first_pass_quantity": 0,
        "rework_quantity": 0,
        "is_rejection": True,
    }
    return QualityRecord(**{**defaults, **overrides})


def make_dashboard_summary(**overrides: Any) -> DashboardSummary:
    defaults: dict[str, Any] = {
        "generated_at": NOW,
        "business_date": TODAY,
        "kpis": [
            DashboardKpi(
                key="production_today",
                label="Today's production",
                value=9_250.0,
                unit="units",
                context_label="9,250 of 10,000 units",
                status="warning",
                status_label="Needs attention",
                trend=KpiTrend(
                    change_percentage=4.2, direction="up", comparison_label="vs previous day"
                ),
            )
        ],
        "production": make_production_summary(),
        "quality": make_quality_summary(),
        "inventory": make_inventory_summary(),
        "machines": make_fleet_summary(),
        "oee": make_oee_components(),
        "alerts": make_alert_summary(),
        "recent_alerts": [make_alert()],
        "cache_hit": False,
    }
    return DashboardSummary(**{**defaults, **overrides})


def make_dashboard_trends(**overrides: Any) -> DashboardTrends:
    defaults: dict[str, Any] = {
        "start_date": date(2026, 8, 7),
        "end_date": TODAY,
        "production": [
            ProductionTrendPoint(
                bucket_date=TODAY,
                planned_quantity=10_000,
                produced_quantity=9_250,
                accepted_quantity=9_000,
                rejected_quantity=250,
                target_quantity=10_400,
                achievement_percentage=88.94,
            )
        ],
        "defects": [
            DefectTrendPoint(
                bucket_date=TODAY,
                inspected_quantity=9_250,
                rejected_quantity=250,
                defect_rate_percentage=2.7,
            )
        ],
        "oee": [OEETrendPoint(bucket_date=TODAY, **make_oee_components().model_dump())],
        "top_defects": [make_defect_summary()],
        "has_data": True,
    }
    return DashboardTrends(**{**defaults, **overrides})


# =============================================================================
# Fake services
#
# Each records the filters it was called with, so a test can assert that a
# query parameter actually reached the service rather than being silently
# dropped by the routing layer.
# =============================================================================


class FakeProductionService:
    def __init__(self) -> None:
        self.last_filters: Any = None
        self.records = [make_production_record()]
        self.total = 1

    async def list_records(self, filters: Any) -> tuple[list[ProductionRecord], int]:
        self.last_filters = filters
        return self.records, self.total

    async def get_summary(self, filters: Any) -> ProductionSummary:
        self.last_filters = filters
        return make_production_summary(
            start_date=filters.resolved_start, end_date=filters.resolved_end
        )

    async def get_trend(self, filters: Any) -> list[ProductionTrendPoint]:
        self.last_filters = filters
        return [
            ProductionTrendPoint(
                bucket_date=filters.resolved_end,
                planned_quantity=10_000,
                produced_quantity=9_250,
                accepted_quantity=9_000,
                rejected_quantity=250,
                target_quantity=10_400,
                achievement_percentage=88.94,
            )
        ]

    async def get_by_dimension(
        self, filters: Any, dimension: str, limit: int = 20
    ) -> list[ProductionByDimension]:
        self.last_filters = filters
        self.last_dimension = dimension
        self.last_limit = limit
        return [
            ProductionByDimension(
                key_id=MACHINE_ID,
                key_code="CNC-T-001",
                key_name="CNC Turning Center 1",
                planned_quantity=600,
                produced_quantity=580,
                accepted_quantity=568,
                rejected_quantity=12,
                efficiency_percentage=96.67,
                defect_rate_percentage=2.07,
            )
        ]


class FakeQualityService:
    def __init__(self) -> None:
        self.last_filters: Any = None
        self.records = [make_quality_record()]
        self.total = 1

    async def list_records(self, filters: Any) -> tuple[list[QualityRecord], int]:
        self.last_filters = filters
        return self.records, self.total

    async def get_summary(self, filters: Any) -> QualitySummary:
        self.last_filters = filters
        return make_quality_summary(
            start_date=filters.resolved_start, end_date=filters.resolved_end
        )

    async def get_defect_breakdown(self, filters: Any, limit: int = 20) -> list[DefectSummary]:
        self.last_filters = filters
        self.last_limit = limit
        return [make_defect_summary()]

    async def get_defect_trend(self, filters: Any) -> list[DefectTrendPoint]:
        self.last_filters = filters
        return [
            DefectTrendPoint(
                bucket_date=filters.resolved_end,
                inspected_quantity=9_250,
                rejected_quantity=250,
                defect_rate_percentage=2.7,
            )
        ]

    async def get_by_dimension(
        self, filters: Any, dimension: str, limit: int = 20
    ) -> list[QualityByDimension]:
        self.last_filters = filters
        return [
            QualityByDimension(
                key_id=MACHINE_ID,
                key_code="CNC-T-001",
                key_name="CNC Turning Center 1",
                inspected_quantity=9_250,
                rejected_quantity=250,
                defect_rate_percentage=2.7,
            )
        ]


class FakeInventoryService:
    def __init__(self) -> None:
        self.last_filters: Any = None
        self.items = [make_inventory_item()]
        self.total = 1
        self.item: InventoryItem | None = make_inventory_item()

    async def list_items(self, filters: Any) -> tuple[list[InventoryItem], int]:
        self.last_filters = filters
        return self.items, self.total

    async def get_alerts(self, limit: int = 50) -> list[InventoryAlert]:
        self.last_limit = limit
        return [make_inventory_alert()]

    async def get_summary(self) -> InventorySummary:
        return make_inventory_summary()

    async def get_item(self, item_id: UUID) -> InventoryItem | None:
        self.last_item_id = item_id
        return self.item

    async def get_transactions(
        self, *, item_id: UUID, limit: int, offset: int
    ) -> tuple[list[InventoryTransaction], int]:
        self.last_item_id = item_id
        return [
            InventoryTransaction(
                id=RECORD_ID,
                inventory_item_id=item_id,
                transaction_type="ISSUE",
                quantity_delta=-780.0,
                balance_after=42_500.0,
                reference="ISS-RM-STEEL-BILLET-2026-09-05",
                notes="Issued to production.",
                occurred_at=NOW,
            )
        ], 1

    async def get_stock_trend(self, item_id: UUID, limit: int = 90) -> list[InventoryTrendPoint]:
        self.last_item_id = item_id
        return [InventoryTrendPoint(bucket_date=NOW, balance=42_500.0)]


class FakeMachineService:
    def __init__(self) -> None:
        self.last_filters: Any = None
        self.machines = [make_machine_summary()]
        self.detail: MachineDetail | None = make_machine_detail()

    async def list_machines(self, filters: Any) -> list[MachineSummary]:
        self.last_filters = filters
        return self.machines

    async def get_fleet_summary(self) -> MachineFleetSummary:
        return make_fleet_summary()

    async def get_machine(
        self, machine_id: UUID, *, start_date: Any = None, end_date: Any = None
    ) -> MachineDetail | None:
        self.last_machine_id = machine_id
        self.last_window = (start_date, end_date)
        return self.detail


class FakeAlertService:
    def __init__(self) -> None:
        self.last_filters: Any = None
        self.alerts = [make_alert()]
        self.total = 1

    async def list_alerts(self, filters: Any) -> tuple[list[Alert], int]:
        self.last_filters = filters
        return self.alerts, self.total

    async def get_active_alerts(self, limit: int = 10) -> list[Alert]:
        self.last_limit = limit
        return self.alerts

    async def get_summary(self) -> AlertSummary:
        return make_alert_summary()


class FakeMaintenanceService:
    def __init__(self) -> None:
        self.last_filters: Any = None
        self.records = [make_maintenance_record()]
        self.total = 1

    async def list_records(self, filters: Any) -> tuple[list[MaintenanceRecord], int]:
        self.last_filters = filters
        return self.records, self.total


class FakeAnalyticsService:
    def __init__(self) -> None:
        self.last_filters: Any = None

    async def get_oee(self, filters: Any) -> OEESummary:
        self.last_filters = filters
        return make_oee_summary(start_date=filters.resolved_start, end_date=filters.resolved_end)

    async def get_oee_trend(self, filters: Any) -> list[OEETrendPoint]:
        self.last_filters = filters
        return [
            OEETrendPoint(bucket_date=filters.resolved_end, **make_oee_components().model_dump())
        ]

    async def get_oee_by_machine(self, filters: Any) -> list[OEEByMachine]:
        self.last_filters = filters
        return [
            OEEByMachine(
                machine_id=MACHINE_ID,
                machine_code="CNC-T-001",
                machine_name="CNC Turning Center 1",
                produced_quantity=17_400,
                operating_minutes=12_900,
                **make_oee_components().model_dump(),
            )
        ]

    async def get_efficiency(self, filters: Any) -> EfficiencySummary:
        self.last_filters = filters
        return make_efficiency_summary(
            start_date=filters.resolved_start, end_date=filters.resolved_end
        )

    async def get_efficiency_trend(self, filters: Any) -> list[EfficiencyTrendPoint]:
        self.last_filters = filters
        return [
            EfficiencyTrendPoint(
                bucket_date=filters.resolved_end,
                planned_quantity=10_000,
                produced_quantity=9_250,
                target_quantity=10_400,
                efficiency_percentage=92.5,
                achievement_percentage=88.94,
            )
        ]

    async def get_downtime_by_machine(self, filters: Any) -> list[DowntimeByMachine]:
        self.last_filters = filters
        return [
            DowntimeByMachine(
                machine_id=MACHINE_ID,
                machine_code="CNC-T-001",
                machine_name="CNC Turning Center 1",
                downtime_minutes=600,
                planned_minutes=13_500,
                downtime_percentage=4.44,
            )
        ]

    async def get_defect_analytics(self, filters: Any) -> DefectAnalytics:
        self.last_filters = filters
        return DefectAnalytics(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            total_inspected=9_250,
            total_rejected=250,
            defect_rate_percentage=2.7,
            by_defect=[make_defect_summary()],
            by_machine=[],
            by_component=[],
            trend=[],
            has_data=True,
        )


class FakeDashboardService:
    def __init__(self) -> None:
        self.last_filters: Any = None
        self.summary = make_dashboard_summary()

    async def get_summary(self) -> DashboardSummary:
        return self.summary

    async def get_trends(self, filters: Any) -> DashboardTrends:
        self.last_filters = filters
        return make_dashboard_trends(
            start_date=filters.resolved_start, end_date=filters.resolved_end
        )
