"""Production data access.

Database access only. No KPI arithmetic: percentages are the service layer's
job (spec section 8), so this module returns the raw sums a rate is computed
from and nothing else.

Every aggregate is computed by PostgreSQL rather than by loading rows into
Python (spec sections 11 and 19). A 90-day summary touches roughly 3,000 rows in
the database and returns one.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from psycopg import sql

from app.repositories.base import BaseRepository, SortSpec, WhereBuilder

#: Sort keys the API exposes, mapped to real columns.
#:
#: This mapping *is* the sort allow-list (spec section 57). A client sends a key
#: from the left column; anything else is rejected before SQL is built. Column
#: names never come from the request.
PRODUCTION_SORTS = SortSpec(
    mapping={
        "date": ("p", "record_date"),
        "produced": ("p", "produced_quantity"),
        "planned": ("p", "planned_quantity"),
        "accepted": ("p", "accepted_quantity"),
        "rejected": ("p", "rejected_quantity"),
        "downtime": ("p", "downtime_minutes"),
        "machine": ("m", "code"),
        "component": ("c", "code"),
    },
    default="date",
)

#: Joined source for the detail list. Every join is on an indexed key, and each
#: reference table contributes at most one row, so this cannot fan out.
_LIST_FROM = sql.SQL("""
    public.production_records p
    join public.machines       m on m.id = p.machine_id
    join public.components     c on c.id = p.component_id
    join public.factory_lines  l on l.id = p.line_id
    join public.shifts         s on s.id = p.shift_id
""")


class ProductionRepository(BaseRepository):
    """Reads production records and their aggregates."""

    @staticmethod
    def _filters(
        *,
        start_date: date,
        end_date: date,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        shift_id: UUID | None = None,
        line_id: UUID | None = None,
        alias: str = "p",
    ) -> WhereBuilder:
        """Build the shared WHERE clause.

        One place for the filter logic, so the list, the summary and the trend
        can never disagree about what a filter means.
        """
        where = WhereBuilder()
        where.add(f"{alias}.record_date between %s and %s", start_date, end_date)
        where.add_if(machine_id, f"{alias}.machine_id = %s", machine_id)
        where.add_if(component_id, f"{alias}.component_id = %s", component_id)
        where.add_if(shift_id, f"{alias}.shift_id = %s", shift_id)
        where.add_if(line_id, f"{alias}.line_id = %s", line_id)
        return where

    async def get_production_records(
        self,
        *,
        start_date: date,
        end_date: date,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        shift_id: UUID | None = None,
        line_id: UUID | None = None,
        limit: int,
        offset: int,
        sort_by: str | None = None,
        sort_dir: Any = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of production records and the total match count.

        Raises:
            UnknownSortFieldError: If `sort_by` is not an allow-listed key.
        """
        where = self._filters(
            start_date=start_date,
            end_date=end_date,
            machine_id=machine_id,
            component_id=component_id,
            shift_id=shift_id,
            line_id=line_id,
        )
        order_by = PRODUCTION_SORTS.resolve(sort_by, sort_dir)

        statement = sql.SQL("""
            select
                p.id, p.record_date,
                p.machine_id, m.code as machine_code, m.name as machine_name,
                p.component_id, c.code as component_code, c.name as component_name,
                p.line_id, l.code as line_code, l.name as line_name,
                p.shift_id, s.code as shift_code, s.name as shift_name,
                p.started_at, p.ended_at,
                p.planned_quantity, p.produced_quantity,
                p.accepted_quantity, p.rejected_quantity,
                p.planned_minutes, p.operating_minutes, p.downtime_minutes
            from {source}
            {where}
            {order_by}, p.id
            limit %s offset %s
        """).format(source=_LIST_FROM, where=where.clause(), order_by=order_by)

        rows = await self.fetch_all(statement, [*where.params, limit, offset])
        total = await self.count(_LIST_FROM, where)
        return rows, total

    async def get_production_summary(
        self,
        *,
        start_date: date,
        end_date: date,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        shift_id: UUID | None = None,
        line_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Return summed production quantities and minutes for the filter.

        Always returns a row: `coalesce` turns an empty match into zeros, and
        `record_count` tells the service whether that zero means "nothing
        happened" or "nothing matched".
        """
        where = self._filters(
            start_date=start_date,
            end_date=end_date,
            machine_id=machine_id,
            component_id=component_id,
            shift_id=shift_id,
            line_id=line_id,
        )

        statement = sql.SQL("""
            select
                coalesce(sum(p.planned_quantity), 0)  as total_planned,
                coalesce(sum(p.produced_quantity), 0) as total_produced,
                coalesce(sum(p.accepted_quantity), 0) as total_accepted,
                coalesce(sum(p.rejected_quantity), 0) as total_rejected,
                coalesce(sum(p.planned_minutes), 0)   as total_planned_minutes,
                coalesce(sum(p.operating_minutes), 0) as total_operating_minutes,
                coalesce(sum(p.downtime_minutes), 0)  as total_downtime_minutes,
                count(*)                              as record_count
            from public.production_records p
            {where}
        """).format(where=where.clause())

        row = await self.fetch_one(statement, where.params)
        return row or {}

    async def get_target_quantity(
        self,
        *,
        start_date: date,
        end_date: date,
        component_id: UUID | None = None,
        line_id: UUID | None = None,
    ) -> int:
        """Sum the daily targets for the period.

        Targets live at (date, line, component) grain and have no machine or
        shift dimension, so those filters cannot be applied here. Filtering
        production by machine while comparing against a whole line's target
        would understate achievement, which is why the service only reports
        achievement when the filters are compatible.
        """
        where = WhereBuilder()
        where.add("t.target_date between %s and %s", start_date, end_date)
        where.add_if(component_id, "t.component_id = %s", component_id)
        where.add_if(line_id, "t.line_id = %s", line_id)

        statement = sql.SQL("""
            select coalesce(sum(t.target_quantity), 0) as target_quantity
            from public.daily_targets t
            {where}
        """).format(where=where.clause())

        return int(await self.fetch_value(statement, where.params, default=0) or 0)

    async def get_production_trend(
        self,
        *,
        start_date: date,
        end_date: date,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        shift_id: UUID | None = None,
        line_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Return daily production totals with the matching daily target.

        Production and targets are aggregated separately and joined on the date.
        Joining first would multiply production rows by the number of target
        rows for that day -- the classic fan-out that silently inflates a sum.
        """
        production_where = self._filters(
            start_date=start_date,
            end_date=end_date,
            machine_id=machine_id,
            component_id=component_id,
            shift_id=shift_id,
            line_id=line_id,
        )
        target_where = WhereBuilder()
        target_where.add("t.target_date between %s and %s", start_date, end_date)
        target_where.add_if(component_id, "t.component_id = %s", component_id)
        target_where.add_if(line_id, "t.line_id = %s", line_id)

        statement = sql.SQL("""
            with production as (
                select
                    p.record_date,
                    sum(p.planned_quantity)  as planned_quantity,
                    sum(p.produced_quantity) as produced_quantity,
                    sum(p.accepted_quantity) as accepted_quantity,
                    sum(p.rejected_quantity) as rejected_quantity
                from public.production_records p
                {production_where}
                group by p.record_date
            ),
            targets as (
                select t.target_date, sum(t.target_quantity) as target_quantity
                from public.daily_targets t
                {target_where}
                group by t.target_date
            )
            select
                production.record_date                    as bucket_date,
                production.planned_quantity,
                production.produced_quantity,
                production.accepted_quantity,
                production.rejected_quantity,
                coalesce(targets.target_quantity, 0)      as target_quantity
            from production
            left join targets on targets.target_date = production.record_date
            order by production.record_date
        """).format(
            production_where=production_where.clause(),
            target_where=target_where.clause(),
        )

        return await self.fetch_all(statement, [*production_where.params, *target_where.params])

    async def get_production_by_dimension(
        self,
        *,
        dimension: str,
        start_date: date,
        end_date: date,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        shift_id: UUID | None = None,
        line_id: UUID | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Group production by machine, component, line or shift.

        Args:
            dimension: One of `machine`, `component`, `line`, `shift`. Validated
                against the mapping below, so it cannot introduce SQL.

        Raises:
            ValueError: If `dimension` is not one of the four supported values.
        """
        # The allow-list. `dimension` is an internal argument, but it is
        # validated all the same: a future endpoint that forwards a query
        # parameter here must not become an injection point.
        joins = {
            "machine": ("public.machines", "machine_id"),
            "component": ("public.components", "component_id"),
            "line": ("public.factory_lines", "line_id"),
            "shift": ("public.shifts", "shift_id"),
        }
        if dimension not in joins:
            raise ValueError(f"Unknown dimension {dimension!r}. Expected one of {sorted(joins)}.")
        table_name, fk_column = joins[dimension]
        schema, table = table_name.split(".")

        where = self._filters(
            start_date=start_date,
            end_date=end_date,
            machine_id=machine_id,
            component_id=component_id,
            shift_id=shift_id,
            line_id=line_id,
        )

        statement = sql.SQL("""
            select
                d.id   as key_id,
                d.code as key_code,
                d.name as key_name,
                coalesce(sum(p.planned_quantity), 0)  as planned_quantity,
                coalesce(sum(p.produced_quantity), 0) as produced_quantity,
                coalesce(sum(p.accepted_quantity), 0) as accepted_quantity,
                coalesce(sum(p.rejected_quantity), 0) as rejected_quantity
            from public.production_records p
            join {dimension_table} d on d.id = p.{fk_column}
            {where}
            group by d.id, d.code, d.name
            order by produced_quantity desc
            limit %s
        """).format(
            dimension_table=sql.Identifier(schema, table),
            fk_column=sql.Identifier(fk_column),
            where=where.clause(),
        )

        return await self.fetch_all(statement, [*where.params, limit])

    async def get_daily_totals_for(self, on_date: date) -> dict[str, Any]:
        """Return one day's production totals, for the dashboard KPI cards."""
        statement = sql.SQL("""
            select
                coalesce(sum(p.planned_quantity), 0)  as total_planned,
                coalesce(sum(p.produced_quantity), 0) as total_produced,
                coalesce(sum(p.accepted_quantity), 0) as total_accepted,
                coalesce(sum(p.rejected_quantity), 0) as total_rejected,
                coalesce(sum(p.planned_minutes), 0)   as total_planned_minutes,
                coalesce(sum(p.operating_minutes), 0) as total_operating_minutes,
                coalesce(sum(p.downtime_minutes), 0)  as total_downtime_minutes,
                count(*)                              as record_count
            from public.production_records p
            where p.record_date = %s
        """)
        return await self.fetch_one(statement, [on_date]) or {}

    async def get_latest_production_date(self) -> date | None:
        """Return the most recent date with production.

        The dashboard anchors "today" to this rather than the wall clock. Demo
        data is seeded up to the day it was generated, so on any later day a
        literal `current_date` would show an empty dashboard -- which looks like
        a broken application rather than a quiet factory.
        """
        return await self.fetch_value(
            "select max(record_date) as latest from public.production_records"
        )
