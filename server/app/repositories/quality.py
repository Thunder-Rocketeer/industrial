"""Quality data access.

The two row shapes in `quality_records` drive every query here (see
`docs/database.md` section 5):

  * the pass line has `defect_id IS NULL` and carries accepted units
  * each rejection line names one defect and carries its rejected units

So a summary aggregates across **all** rows, while anything about defects
filters to `defect_id IS NOT NULL`. Getting that backwards would either double
count or silently drop every pass.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from psycopg import sql

from app.repositories.base import BaseRepository, SortSpec, WhereBuilder

QUALITY_SORTS = SortSpec(
    mapping={
        "inspected_at": ("q", "inspected_at"),
        "inspected": ("q", "inspected_quantity"),
        "rejected": ("q", "rejected_quantity"),
        "passed": ("q", "passed_quantity"),
        "machine": ("m", "code"),
        "component": ("c", "code"),
    },
    default="inspected_at",
)

_LIST_FROM = sql.SQL("""
    public.quality_records q
    join public.production_records pr on pr.id = q.production_record_id
    join public.machines   m on m.id = q.machine_id
    join public.components c on c.id = q.component_id
    left join public.defects d on d.id = q.defect_id
""")


class QualityRepository(BaseRepository):
    """Reads inspection records and their aggregates."""

    @staticmethod
    def _filters(
        *,
        start_date: date,
        end_date: date,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        defect_id: UUID | None = None,
        rejections_only: bool = False,
    ) -> WhereBuilder:
        """Build the shared WHERE clause.

        The date filter is on the parent production record's `record_date`, not
        on `inspected_at`, and that distinction is load-bearing.

        A production run belongs to a business date -- the (date, shift,
        machine, component) grain the schema is built on. Its inspections are
        timestamped when they physically happened, which for a night shift is
        often after midnight. Windowing quality by `inspected_at` therefore
        selects a slightly different set of runs than the identical window over
        production, and the two do not reconcile: measured against the live
        seed, 398,369 units inspected against 395,315 produced over the same
        thirty days.

        That is not a rounding difference, it is two different questions. And
        because the dashboard prints a production defect rate beside a quality
        defect rate, the answer has to be the same one -- otherwise two panels
        on one screen disagree and neither is wrong. Joining to the production
        record makes the totals identical by construction.

        The join is on a primary key covered by
        `quality_records_production_record_idx`, so it is cheap; the Pareto
        query already did exactly this.
        """
        where = WhereBuilder()
        where.add(
            "pr.record_date >= %s and pr.record_date <= %s",
            start_date,
            end_date,
        )
        where.add_if(machine_id, "q.machine_id = %s", machine_id)
        where.add_if(component_id, "q.component_id = %s", component_id)
        where.add_if(defect_id, "q.defect_id = %s", defect_id)
        if rejections_only:
            where.add("q.defect_id is not null")
        return where

    async def get_quality_records(
        self,
        *,
        start_date: date,
        end_date: date,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        defect_id: UUID | None = None,
        rejections_only: bool = False,
        limit: int,
        offset: int,
        sort_by: str | None = None,
        sort_dir: Any = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of inspection lines and the total match count."""
        where = self._filters(
            start_date=start_date,
            end_date=end_date,
            machine_id=machine_id,
            component_id=component_id,
            defect_id=defect_id,
            rejections_only=rejections_only,
        )
        order_by = QUALITY_SORTS.resolve(sort_by, sort_dir)

        statement = sql.SQL("""
            select
                q.id, q.production_record_id, q.inspected_at,
                q.machine_id, m.code as machine_code,
                q.component_id, c.code as component_code, c.name as component_name,
                q.defect_id, d.code as defect_code, d.name as defect_name,
                q.severity,
                q.inspected_quantity, q.passed_quantity, q.rejected_quantity,
                q.first_pass_quantity, q.rework_quantity
            from {source}
            {where}
            {order_by}, q.id
            limit %s offset %s
        """).format(source=_LIST_FROM, where=where.clause(), order_by=order_by)

        rows = await self.fetch_all(statement, [*where.params, limit, offset])
        total = await self.count(_LIST_FROM, where)
        return rows, total

    async def get_quality_summary(
        self,
        *,
        start_date: date,
        end_date: date,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        defect_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Return summed inspection quantities for the filter.

        Aggregates across both row shapes, so `total_inspected` equals the units
        produced in the period and the defect rate is a true ratio.
        """
        where = self._filters(
            start_date=start_date,
            end_date=end_date,
            machine_id=machine_id,
            component_id=component_id,
            defect_id=defect_id,
        )

        statement = sql.SQL("""
            select
                coalesce(sum(q.inspected_quantity), 0)  as total_inspected,
                coalesce(sum(q.passed_quantity), 0)     as total_passed,
                coalesce(sum(q.rejected_quantity), 0)   as total_rejected,
                coalesce(sum(q.first_pass_quantity), 0) as total_first_pass,
                coalesce(sum(q.rework_quantity), 0)     as total_rework,
                count(distinct q.defect_id)             as distinct_defect_types,
                count(*)                                as record_count
            from public.quality_records q
            join public.production_records pr on pr.id = q.production_record_id
            {where}
        """).format(where=where.clause())

        return await self.fetch_one(statement, where.params) or {}

    async def get_defect_breakdown(
        self,
        *,
        start_date: date,
        end_date: date,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return rejections grouped by defect type, most frequent first.

        The Pareto query. Restricted to rejection lines, which is what the
        partial index `quality_records_defect_inspected_idx` covers.
        """
        where = self._filters(
            start_date=start_date,
            end_date=end_date,
            machine_id=machine_id,
            component_id=component_id,
            rejections_only=True,
        )

        statement = sql.SQL("""
            select
                d.id   as defect_id,
                d.code as defect_code,
                d.name as defect_name,
                d.category,
                d.default_severity,
                coalesce(sum(q.rejected_quantity), 0) as rejected_quantity,
                count(*)                              as occurrence_count
            from public.quality_records q
            join public.production_records pr on pr.id = q.production_record_id
            join public.defects d on d.id = q.defect_id
            {where}
            group by d.id, d.code, d.name, d.category, d.default_severity
            order by rejected_quantity desc, d.name
            limit %s
        """).format(where=where.clause())

        return await self.fetch_all(statement, [*where.params, limit])

    async def get_defect_trend(
        self,
        *,
        start_date: date,
        end_date: date,
        machine_id: UUID | None = None,
        component_id: UUID | None = None,
        defect_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Return the daily inspected and rejected totals.

        Both come from one pass over the table. Two queries -- one for the
        denominator and one for the numerator -- would double the work and could
        disagree if a row were written between them.
        """
        where = self._filters(
            start_date=start_date,
            end_date=end_date,
            machine_id=machine_id,
            component_id=component_id,
            defect_id=defect_id,
        )

        statement = sql.SQL("""
            select
                pr.record_date as bucket_date,
                coalesce(sum(q.inspected_quantity), 0)    as inspected_quantity,
                coalesce(sum(q.rejected_quantity), 0)     as rejected_quantity
            from public.quality_records q
            join public.production_records pr on pr.id = q.production_record_id
            {where}
            group by bucket_date
            order by bucket_date
        """).format(where=where.clause())

        return await self.fetch_all(statement, where.params)

    async def get_quality_by_dimension(
        self,
        *,
        dimension: str,
        start_date: date,
        end_date: date,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Group inspection totals by machine or component.

        Raises:
            ValueError: If `dimension` is not `machine` or `component`.
        """
        joins = {
            "machine": ("public.machines", "machine_id"),
            "component": ("public.components", "component_id"),
        }
        if dimension not in joins:
            raise ValueError(f"Unknown dimension {dimension!r}. Expected one of {sorted(joins)}.")
        table_name, fk_column = joins[dimension]
        schema, table = table_name.split(".")

        where = self._filters(start_date=start_date, end_date=end_date)

        statement = sql.SQL("""
            select
                d.id   as key_id,
                d.code as key_code,
                d.name as key_name,
                coalesce(sum(q.inspected_quantity), 0) as inspected_quantity,
                coalesce(sum(q.rejected_quantity), 0)  as rejected_quantity
            from public.quality_records q
            join public.production_records pr on pr.id = q.production_record_id
            join {dimension_table} d on d.id = q.{fk_column}
            {where}
            group by d.id, d.code, d.name
            having sum(q.inspected_quantity) > 0
            order by rejected_quantity desc
            limit %s
        """).format(
            dimension_table=sql.Identifier(schema, table),
            fk_column=sql.Identifier(fk_column),
            where=where.clause(),
        )

        return await self.fetch_all(statement, [*where.params, limit])

    async def get_daily_totals_for(self, on_date: date) -> dict[str, Any]:
        """Return one day's inspection totals, for the dashboard KPI cards."""
        statement = sql.SQL("""
            select
                coalesce(sum(q.inspected_quantity), 0)  as total_inspected,
                coalesce(sum(q.passed_quantity), 0)     as total_passed,
                coalesce(sum(q.rejected_quantity), 0)   as total_rejected,
                coalesce(sum(q.first_pass_quantity), 0) as total_first_pass,
                coalesce(sum(q.rework_quantity), 0)     as total_rework,
                count(distinct q.defect_id)             as distinct_defect_types,
                count(*)                                as record_count
            from public.quality_records q
            join public.production_records pr on pr.id = q.production_record_id
            where pr.record_date = %s
        """)
        return await self.fetch_one(statement, [on_date]) or {}
