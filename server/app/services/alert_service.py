"""Alert business logic."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.cache.service import CacheService, CacheTier
from app.models.enums import AlertSeverity, AlertStatus, AlertType
from app.repositories.alerts import AlertRepository
from app.schemas.alerts import Alert, AlertSeverityCount, AlertSummary
from app.schemas.filters import AlertFilters
from app.services.labels import (
    ALERT_SEVERITY_LABELS,
    ALERT_STATUS_LABELS,
    ALERT_TYPE_LABELS,
    label_for,
)


class AlertService:
    """Alert reads, with derived age and caching."""

    def __init__(self, repository: AlertRepository, cache: CacheService) -> None:
        self._repository = repository
        self._cache = cache

    async def list_alerts(self, filters: AlertFilters) -> tuple[list[Alert], int]:
        """Return one page of alerts."""
        rows, total = await self._repository.get_alerts(
            status=filters.status,
            severity=filters.severity,
            machine_id=filters.machine_id,
            limit=filters.limit,
            offset=filters.offset,
        )
        now = datetime.now(tz=timezone.utc)
        return [self.build_alert(row, now) for row in rows], total

    async def get_active_alerts(self, limit: int = 10) -> list[Alert]:
        """Return the most urgent open alerts, cached.

        Not cached on the fixed dashboard key: `limit` varies by caller, and two
        callers asking for different counts must not overwrite each other's
        entry. The key carries the limit.
        """
        key = f"{self._cache.keys.dashboard_alerts()}:{limit}"
        return await self._cache.get_or_set_list(
            key, CacheTier.REALTIME, Alert, lambda: self._build_active(limit)
        )

    async def _build_active(self, limit: int) -> list[Alert]:
        rows = await self._repository.get_active_alerts(limit=limit)
        now = datetime.now(tz=timezone.utc)
        return [self.build_alert(row, now) for row in rows]

    async def get_summary(self) -> AlertSummary:
        """Return open-alert counts by severity."""
        totals = await self._repository.get_alert_summary()
        return self.build_summary_from_totals(totals)

    @staticmethod
    def build_summary_from_totals(totals: dict[str, Any]) -> AlertSummary:
        """Assemble the alert summary from repository counts."""
        critical = int(totals.get("critical_count") or 0)
        warning = int(totals.get("warning_count") or 0)
        info = int(totals.get("info_count") or 0)

        return AlertSummary(
            total_open=int(totals.get("total_open") or 0),
            critical_count=critical,
            warning_count=warning,
            info_count=info,
            acknowledged_count=int(totals.get("acknowledged_count") or 0),
            severity_breakdown=[
                AlertSeverityCount(
                    severity=severity,
                    severity_label=label_for(severity, ALERT_SEVERITY_LABELS),
                    count=count,
                )
                for severity, count in (
                    (AlertSeverity.CRITICAL, critical),
                    (AlertSeverity.WARNING, warning),
                    (AlertSeverity.INFO, info),
                )
            ],
        )

    @staticmethod
    def build_alert(row: dict[str, Any], now: datetime) -> Alert:
        severity = AlertSeverity(row["severity"])
        status = AlertStatus(row["status"])
        alert_type = AlertType(row["alert_type"])

        triggered = row["triggered_at"]
        # The database stores timestamptz, so this is already UTC-aware. The
        # guard covers a driver returning a naive value rather than assuming.
        if triggered.tzinfo is None:
            triggered = triggered.replace(tzinfo=timezone.utc)
        age_minutes = max(0, int((now - triggered).total_seconds() // 60))

        return Alert(
            id=row["id"],
            alert_type=alert_type,
            alert_type_label=label_for(alert_type, ALERT_TYPE_LABELS),
            severity=severity,
            severity_label=label_for(severity, ALERT_SEVERITY_LABELS),
            status=status,
            status_label=label_for(status, ALERT_STATUS_LABELS),
            title=row["title"],
            description=row["description"],
            machine_id=row["machine_id"],
            machine_code=row["machine_code"],
            machine_name=row["machine_name"],
            component_id=row["component_id"],
            component_name=row["component_name"],
            inventory_item_id=row["inventory_item_id"],
            inventory_item_name=row["inventory_item_name"],
            line_id=row["line_id"],
            line_name=row["line_name"],
            triggered_at=triggered,
            acknowledged_at=row["acknowledged_at"],
            resolved_at=row["resolved_at"],
            age_minutes=age_minutes,
        )
