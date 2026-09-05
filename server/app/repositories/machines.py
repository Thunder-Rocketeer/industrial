"""Machine data access."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from psycopg import sql

from app.repositories.base import BaseRepository, WhereBuilder

_LIST_FROM = sql.SQL("""
    public.machines m
    join public.factory_lines l on l.id = m.line_id
    left join public.components c on c.id = m.current_component_id
""")

_MACHINE_COLUMNS = sql.SQL("""
    m.id, m.code, m.name, m.machine_type,
    m.line_id, l.code as line_code, l.name as line_name,
    m.status,
    m.current_component_id, c.name as current_component_name,
    m.utilization_percentage, m.total_downtime_minutes,
    m.commissioned_date, m.last_maintenance_date, m.next_maintenance_date
""")


class MachineRepository(BaseRepository):
    """Reads machines, their production statistics and fleet aggregates."""

    async def get_machines(
        self,
        *,
        status: Any = None,
        line_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Return machines matching the filter.

        Unpaginated by design: the fleet is a dozen or so machines, and the
        machines board shows all of them at once. Paginating would add a
        round trip and a control the user would never use.
        """
        where = WhereBuilder()
        if status is not None:
            where.add("m.status = %s::public.machine_status", getattr(status, "value", status))
        where.add_if(line_id, "m.line_id = %s", line_id)

        statement = sql.SQL("""
            select {columns}
            from {source}
            {where}
            order by l.code, m.code
        """).format(columns=_MACHINE_COLUMNS, source=_LIST_FROM, where=where.clause())

        return await self.fetch_all(statement, where.params)

    async def get_machine(self, machine_id: UUID) -> dict[str, Any] | None:
        """Return one machine, or None when it does not exist."""
        statement = sql.SQL("""
            select {columns}
            from {source}
            where m.id = %s
        """).format(columns=_MACHINE_COLUMNS, source=_LIST_FROM)
        return await self.fetch_one(statement, [machine_id])

    async def get_machine_summary(self) -> dict[str, Any]:
        """Return fleet-level counts and average utilisation."""
        statement = sql.SQL("""
            select
                count(*) as total_machines,
                count(*) filter (
                    where m.status = 'RUNNING'::public.machine_status
                ) as running_count,
                count(*) filter (
                    where m.status = 'IDLE'::public.machine_status
                ) as idle_count,
                count(*) filter (
                    where m.status = 'MAINTENANCE'::public.machine_status
                ) as maintenance_count,
                count(*) filter (
                    where m.status = 'OFFLINE'::public.machine_status
                ) as offline_count,
                coalesce(avg(m.utilization_percentage), 0) as average_utilization,
                count(*) filter (
                    where m.next_maintenance_date is not null
                      and m.next_maintenance_date <= current_date + %s
                ) as maintenance_due_count
            from public.machines m
        """)
        # The attention window is passed as a parameter rather than inlined so
        # the service owns the policy and the SQL stays constant.
        return await self.fetch_one(statement, [7]) or {}

    async def get_machine_production_stats(
        self,
        *,
        machine_id: UUID,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """Return one machine's production aggregates for a window.

        `ideal_output_units` is computed in SQL because the ideal cycle time
        varies by component: a machine that ran three different parts has three
        different ideal rates, so summing per row is the only correct way to get
        the denominator of the Performance term. Doing it in Python would need
        every row transferred.
        """
        statement = sql.SQL("""
            select
                coalesce(sum(p.produced_quantity), 0) as produced_quantity,
                coalesce(sum(p.accepted_quantity), 0) as accepted_quantity,
                coalesce(sum(p.rejected_quantity), 0) as rejected_quantity,
                coalesce(sum(p.planned_quantity), 0)  as planned_quantity,
                coalesce(sum(p.operating_minutes), 0) as operating_minutes,
                coalesce(sum(p.planned_minutes), 0)   as planned_minutes,
                coalesce(sum(p.downtime_minutes), 0)  as downtime_minutes,
                coalesce(sum(
                    case
                        when c.ideal_cycle_time_seconds > 0
                            then (p.operating_minutes * 60.0) / c.ideal_cycle_time_seconds
                        else 0
                    end
                ), 0) as ideal_output_units,
                count(*) as run_count
            from public.production_records p
            join public.components c on c.id = p.component_id
            where p.machine_id = %s
              and p.record_date between %s and %s
        """)
        return await self.fetch_one(statement, [machine_id, start_date, end_date]) or {}

    async def get_fleet_oee_inputs(
        self,
        *,
        start_date: date,
        end_date: date,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        line_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Return the raw inputs for a fleet-wide OEE calculation.

        One query returns every term's numerator and denominator, so the three
        OEE components are guaranteed to describe the same set of rows. Three
        separate queries could each see a slightly different set.
        """
        where = WhereBuilder()
        where.add("p.record_date between %s and %s", start_date, end_date)
        where.add_if(machine_id, "p.machine_id = %s", machine_id)
        where.add_if(component_id, "p.component_id = %s", component_id)
        where.add_if(line_id, "p.line_id = %s", line_id)

        statement = sql.SQL("""
            select
                coalesce(sum(p.operating_minutes), 0) as operating_minutes,
                coalesce(sum(p.planned_minutes), 0)   as planned_minutes,
                coalesce(sum(p.downtime_minutes), 0)  as downtime_minutes,
                coalesce(sum(p.produced_quantity), 0) as produced_quantity,
                coalesce(sum(p.accepted_quantity), 0) as accepted_quantity,
                coalesce(sum(p.rejected_quantity), 0) as rejected_quantity,
                coalesce(sum(
                    case
                        when c.ideal_cycle_time_seconds > 0
                            then (p.operating_minutes * 60.0) / c.ideal_cycle_time_seconds
                        else 0
                    end
                ), 0) as ideal_output_units,
                count(*) as record_count
            from public.production_records p
            join public.components c on c.id = p.component_id
            {where}
        """).format(where=where.clause())

        return await self.fetch_one(statement, where.params) or {}

    async def get_oee_trend_inputs(
        self,
        *,
        start_date: date,
        end_date: date,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        line_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Return per-day OEE inputs for the trend chart."""
        where = WhereBuilder()
        where.add("p.record_date between %s and %s", start_date, end_date)
        where.add_if(machine_id, "p.machine_id = %s", machine_id)
        where.add_if(component_id, "p.component_id = %s", component_id)
        where.add_if(line_id, "p.line_id = %s", line_id)

        statement = sql.SQL("""
            select
                p.record_date as bucket_date,
                coalesce(sum(p.operating_minutes), 0) as operating_minutes,
                coalesce(sum(p.planned_minutes), 0)   as planned_minutes,
                coalesce(sum(p.produced_quantity), 0) as produced_quantity,
                coalesce(sum(p.accepted_quantity), 0) as accepted_quantity,
                coalesce(sum(
                    case
                        when c.ideal_cycle_time_seconds > 0
                            then (p.operating_minutes * 60.0) / c.ideal_cycle_time_seconds
                        else 0
                    end
                ), 0) as ideal_output_units
            from public.production_records p
            join public.components c on c.id = p.component_id
            {where}
            group by p.record_date
            order by p.record_date
        """).format(where=where.clause())

        return await self.fetch_all(statement, where.params)

    async def get_oee_by_machine(
        self,
        *,
        start_date: date,
        end_date: date,
        line_id: UUID | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Return per-machine OEE inputs, for fleet comparison."""
        where = WhereBuilder()
        where.add("p.record_date between %s and %s", start_date, end_date)
        where.add_if(line_id, "p.line_id = %s", line_id)

        statement = sql.SQL("""
            select
                m.id   as machine_id,
                m.code as machine_code,
                m.name as machine_name,
                coalesce(sum(p.operating_minutes), 0) as operating_minutes,
                coalesce(sum(p.planned_minutes), 0)   as planned_minutes,
                coalesce(sum(p.produced_quantity), 0) as produced_quantity,
                coalesce(sum(p.accepted_quantity), 0) as accepted_quantity,
                coalesce(sum(
                    case
                        when c.ideal_cycle_time_seconds > 0
                            then (p.operating_minutes * 60.0) / c.ideal_cycle_time_seconds
                        else 0
                    end
                ), 0) as ideal_output_units
            from public.production_records p
            join public.machines m   on m.id = p.machine_id
            join public.components c on c.id = p.component_id
            {where}
            group by m.id, m.code, m.name
            order by m.code
            limit %s
        """).format(where=where.clause())

        return await self.fetch_all(statement, [*where.params, limit])

    async def get_downtime_by_machine(
        self,
        *,
        start_date: date,
        end_date: date,
        line_id: UUID | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Return downtime per machine, worst first."""
        where = WhereBuilder()
        where.add("p.record_date between %s and %s", start_date, end_date)
        where.add_if(line_id, "p.line_id = %s", line_id)

        statement = sql.SQL("""
            select
                m.id   as machine_id,
                m.code as machine_code,
                m.name as machine_name,
                coalesce(sum(p.downtime_minutes), 0) as downtime_minutes,
                coalesce(sum(p.planned_minutes), 0)  as planned_minutes
            from public.production_records p
            join public.machines m on m.id = p.machine_id
            {where}
            group by m.id, m.code, m.name
            order by downtime_minutes desc
            limit %s
        """).format(where=where.clause())

        return await self.fetch_all(statement, [*where.params, limit])
