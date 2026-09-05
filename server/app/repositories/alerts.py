"""Alert data access."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import sql

from app.repositories.base import BaseRepository, WhereBuilder

_LIST_FROM = sql.SQL("""
    public.alerts a
    left join public.machines        m on m.id = a.machine_id
    left join public.components      c on c.id = a.component_id
    left join public.inventory_items i on i.id = a.inventory_item_id
    left join public.factory_lines   l on l.id = a.line_id
""")

_ALERT_COLUMNS = sql.SQL("""
    a.id, a.alert_type, a.severity, a.status,
    a.title, a.description,
    a.machine_id, m.code as machine_code, m.name as machine_name,
    a.component_id, c.name as component_name,
    a.inventory_item_id, i.name as inventory_item_name,
    a.line_id, l.name as line_name,
    a.triggered_at, a.acknowledged_at, a.resolved_at
""")

#: Severity ordering for "most urgent first". The enum's declaration order runs
#: INFO -> WARNING -> CRITICAL, so a plain `order by severity desc` already puts
#: CRITICAL first; this expression states it explicitly rather than depending on
#: the enum's physical order, which a future migration could change.
_SEVERITY_RANK = sql.SQL("""
    case a.severity
        when 'CRITICAL'::public.alert_severity then 0
        when 'WARNING'::public.alert_severity  then 1
        when 'INFO'::public.alert_severity     then 2
        else 3
    end
""")


class AlertRepository(BaseRepository):
    """Reads operational alerts."""

    @staticmethod
    def _filters(
        *,
        status: Any = None,
        severity: Any = None,
        machine_id: UUID | None = None,
    ) -> WhereBuilder:
        where = WhereBuilder()
        if status is not None:
            where.add("a.status = %s::public.alert_status", getattr(status, "value", status))
        if severity is not None:
            where.add(
                "a.severity = %s::public.alert_severity", getattr(severity, "value", severity)
            )
        where.add_if(machine_id, "a.machine_id = %s", machine_id)
        return where

    async def get_alerts(
        self,
        *,
        status: Any = None,
        severity: Any = None,
        machine_id: UUID | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of alerts, most severe and most recent first."""
        where = self._filters(status=status, severity=severity, machine_id=machine_id)

        statement = sql.SQL("""
            select {columns}
            from {source}
            {where}
            order by {severity_rank}, a.triggered_at desc, a.id
            limit %s offset %s
        """).format(
            columns=_ALERT_COLUMNS,
            source=_LIST_FROM,
            where=where.clause(),
            severity_rank=_SEVERITY_RANK,
        )

        rows = await self.fetch_all(statement, [*where.params, limit, offset])
        total = await self.count(_LIST_FROM, where)
        return rows, total

    async def get_active_alerts(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most urgent open alerts, for the dashboard panel.

        Restricted to OPEN, which the partial index `alerts_open_triggered_idx`
        covers, so the query cost does not grow with alert history.
        """
        statement = sql.SQL("""
            select {columns}
            from {source}
            where a.status = 'OPEN'::public.alert_status
            order by {severity_rank}, a.triggered_at desc
            limit %s
        """).format(columns=_ALERT_COLUMNS, source=_LIST_FROM, severity_rank=_SEVERITY_RANK)
        return await self.fetch_all(statement, [limit])

    async def get_alert_summary(self) -> dict[str, Any]:
        """Return open-alert counts per severity, for the dashboard."""
        statement = sql.SQL("""
            select
                count(*) filter (
                    where a.status = 'OPEN'::public.alert_status
                ) as total_open,
                count(*) filter (
                    where a.status = 'OPEN'::public.alert_status
                      and a.severity = 'CRITICAL'::public.alert_severity
                ) as critical_count,
                count(*) filter (
                    where a.status = 'OPEN'::public.alert_status
                      and a.severity = 'WARNING'::public.alert_severity
                ) as warning_count,
                count(*) filter (
                    where a.status = 'OPEN'::public.alert_status
                      and a.severity = 'INFO'::public.alert_severity
                ) as info_count,
                count(*) filter (
                    where a.status = 'ACKNOWLEDGED'::public.alert_status
                ) as acknowledged_count
            from public.alerts a
        """)
        return await self.fetch_one(statement) or {}

    async def get_alert(self, alert_id: UUID) -> dict[str, Any] | None:
        """Return one alert, or None."""
        statement = sql.SQL("""
            select {columns}
            from {source}
            where a.id = %s
        """).format(columns=_ALERT_COLUMNS, source=_LIST_FROM)
        return await self.fetch_one(statement, [alert_id])
