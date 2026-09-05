"""Maintenance data access."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import sql

from app.repositories.base import BaseRepository, WhereBuilder

_LIST_FROM = sql.SQL("""
    public.maintenance_records r
    join public.machines m on m.id = r.machine_id
""")

_COLUMNS = sql.SQL("""
    r.id, r.machine_id, m.code as machine_code, m.name as machine_name,
    r.maintenance_type, r.status, r.scheduled_date,
    r.started_at, r.completed_at, r.downtime_minutes,
    r.technician, r.description, r.cost
""")


class MaintenanceRepository(BaseRepository):
    """Reads maintenance jobs."""

    @staticmethod
    def _filters(
        *,
        status: Any = None,
        machine_id: UUID | None = None,
        upcoming_only: bool = False,
    ) -> WhereBuilder:
        where = WhereBuilder()
        if status is not None:
            where.add("r.status = %s::public.maintenance_status", getattr(status, "value", status))
        where.add_if(machine_id, "r.machine_id = %s", machine_id)
        if upcoming_only:
            where.add(
                "r.scheduled_date >= current_date "
                "and r.status in ('SCHEDULED'::public.maintenance_status, "
                "'IN_PROGRESS'::public.maintenance_status)"
            )
        return where

    async def get_maintenance_records(
        self,
        *,
        status: Any = None,
        machine_id: UUID | None = None,
        upcoming_only: bool = False,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of maintenance jobs.

        Upcoming work is ordered soonest-first; history newest-first. Ordering
        both the same way would bury the next job at the bottom of the list.
        """
        where = self._filters(status=status, machine_id=machine_id, upcoming_only=upcoming_only)
        order = (
            sql.SQL("order by r.scheduled_date asc, r.id")
            if upcoming_only
            else sql.SQL("order by r.scheduled_date desc, r.id")
        )

        statement = sql.SQL("""
            select {columns}
            from {source}
            {where}
            {order}
            limit %s offset %s
        """).format(columns=_COLUMNS, source=_LIST_FROM, where=where.clause(), order=order)

        rows = await self.fetch_all(statement, [*where.params, limit, offset])
        total = await self.count(_LIST_FROM, where)
        return rows, total

    async def get_recent_for_machine(
        self, *, machine_id: UUID, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Return a machine's most recent completed jobs."""
        statement = sql.SQL("""
            select {columns}
            from {source}
            where r.machine_id = %s
              and r.status = 'COMPLETED'::public.maintenance_status
            order by r.scheduled_date desc
            limit %s
        """).format(columns=_COLUMNS, source=_LIST_FROM)
        return await self.fetch_all(statement, [machine_id, limit])

    async def get_upcoming_for_machine(
        self, *, machine_id: UUID, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Return a machine's scheduled and in-progress jobs, soonest first."""
        statement = sql.SQL("""
            select {columns}
            from {source}
            where r.machine_id = %s
              and r.status in ('SCHEDULED'::public.maintenance_status,
                               'IN_PROGRESS'::public.maintenance_status)
            order by r.scheduled_date asc
            limit %s
        """).format(columns=_COLUMNS, source=_LIST_FROM)
        return await self.fetch_all(statement, [machine_id, limit])

    async def get_recent_for_machines(
        self, *, machine_ids: list[UUID], limit_per_machine: int = 3
    ) -> dict[UUID, list[dict[str, Any]]]:
        """Return recent jobs for several machines in one query.

        Avoids the N+1 that a loop over `get_recent_for_machine` would produce
        (spec section 19). A lateral join gives PostgreSQL the per-machine limit
        without transferring every job for every machine.
        """
        if not machine_ids:
            return {}

        statement = sql.SQL("""
            select {columns}
            from public.machines m
            join lateral (
                select *
                from public.maintenance_records inner_r
                where inner_r.machine_id = m.id
                order by inner_r.scheduled_date desc
                limit %s
            ) r on true
            where m.id = any(%s)
            order by m.code, r.scheduled_date desc
        """).format(columns=_COLUMNS)

        rows = await self.fetch_all(statement, [limit_per_machine, machine_ids])

        grouped: dict[UUID, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["machine_id"], []).append(row)
        return grouped
