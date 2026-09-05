"""Inventory data access.

`inventory_items.status` is a generated column, so it is filtered and read but
never written. Filtering on it uses the partial index
`inventory_items_needs_attention_idx` for the CRITICAL/LOW case, which is the
query the alerts panel runs on every dashboard load.

Enum comparisons are cast explicitly (`%s::public.inventory_status`). psycopg
sends a Python `str` as `text`, and PostgreSQL will not implicitly compare
`text` to an enum -- the cast is what makes a parameterised enum filter work at
all, and it keeps the value a bound parameter rather than inline SQL.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import sql

from app.repositories.base import BaseRepository, SortSpec, WhereBuilder

INVENTORY_SORTS = SortSpec(
    mapping={
        "name": ("i", "name"),
        "sku": ("i", "sku"),
        "status": ("i", "status"),
        "quantity": ("i", "current_quantity"),
        "updated": ("i", "updated_at"),
    },
    default="name",
)

_LIST_FROM = sql.SQL("""
    public.inventory_items i
    left join public.components c on c.id = i.component_id
""")


class InventoryRepository(BaseRepository):
    """Reads stock lines, their movements and their aggregates."""

    @staticmethod
    def _filters(
        *,
        status: Any = None,
        component_id: UUID | None = None,
    ) -> WhereBuilder:
        where = WhereBuilder()
        if status is not None:
            status_value = getattr(status, "value", status)
            where.add("i.status = %s::public.inventory_status", status_value)
        where.add_if(component_id, "i.component_id = %s", component_id)
        return where

    async def get_inventory(
        self,
        *,
        status: Any = None,
        component_id: UUID | None = None,
        limit: int,
        offset: int,
        sort_by: str | None = None,
        sort_dir: Any = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of stock lines and the total match count."""
        where = self._filters(status=status, component_id=component_id)
        order_by = INVENTORY_SORTS.resolve(sort_by, sort_dir)

        statement = sql.SQL("""
            select
                i.id, i.sku, i.name, i.material_type, i.unit,
                i.component_id, c.code as component_code, c.name as component_name,
                i.current_quantity, i.minimum_stock, i.reorder_point, i.maximum_stock,
                i.status,
                i.supplier_name, i.supplier_lead_time_days, i.unit_cost,
                i.last_counted_at, i.updated_at
            from {source}
            {where}
            {order_by}, i.id
            limit %s offset %s
        """).format(source=_LIST_FROM, where=where.clause(), order_by=order_by)

        rows = await self.fetch_all(statement, [*where.params, limit, offset])
        total = await self.count(_LIST_FROM, where)
        return rows, total

    async def get_inventory_alerts(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return stock lines that are CRITICAL or LOW, most urgent first.

        Ordered by status then by how far below the reorder point the line sits,
        so the item closest to stopping production appears first rather than the
        one that happens to sort earliest alphabetically.
        """
        statement = sql.SQL("""
            select
                i.id, i.sku, i.name, i.unit, i.status,
                i.current_quantity, i.minimum_stock, i.reorder_point,
                i.supplier_name, i.supplier_lead_time_days
            from public.inventory_items i
            where i.status in ('CRITICAL'::public.inventory_status,
                               'LOW'::public.inventory_status)
            order by
                case i.status
                    when 'CRITICAL'::public.inventory_status then 0
                    when 'LOW'::public.inventory_status      then 1
                    else 2
                end,
                case
                    when i.reorder_point > 0
                        then i.current_quantity / i.reorder_point
                    else 0
                end,
                i.name
            limit %s
        """)
        return await self.fetch_all(statement, [limit])

    async def get_inventory_summary(self) -> dict[str, Any]:
        """Return counts per stock state and the total stock value.

        `total_stock_value` is NULL when any line has no unit cost: summing only
        the priced lines would present a partial figure as a complete one. The
        service passes the NULL through rather than substituting zero.
        """
        statement = sql.SQL("""
            select
                count(*) as total_items,
                count(*) filter (
                    where i.status = 'HEALTHY'::public.inventory_status
                ) as healthy_count,
                count(*) filter (
                    where i.status = 'LOW'::public.inventory_status
                ) as low_count,
                count(*) filter (
                    where i.status = 'CRITICAL'::public.inventory_status
                ) as critical_count,
                count(*) filter (
                    where i.status = 'OVERSTOCKED'::public.inventory_status
                ) as overstocked_count,
                case
                    when count(*) filter (where i.unit_cost is null) = 0
                        then coalesce(sum(i.current_quantity * i.unit_cost), 0)
                    else null
                end as total_stock_value
            from public.inventory_items i
        """)
        return await self.fetch_one(statement) or {}

    async def get_item(self, item_id: UUID) -> dict[str, Any] | None:
        """Return one stock line, or None."""
        statement = sql.SQL("""
            select
                i.id, i.sku, i.name, i.material_type, i.unit,
                i.component_id, c.code as component_code, c.name as component_name,
                i.current_quantity, i.minimum_stock, i.reorder_point, i.maximum_stock,
                i.status,
                i.supplier_name, i.supplier_lead_time_days, i.unit_cost,
                i.last_counted_at, i.updated_at
            from {source}
            where i.id = %s
        """).format(source=_LIST_FROM)
        return await self.fetch_one(statement, [item_id])

    async def get_transactions(
        self,
        *,
        item_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of stock movements for an item, newest first."""
        where = WhereBuilder()
        where.add("t.inventory_item_id = %s", item_id)

        statement = sql.SQL("""
            select
                t.id, t.inventory_item_id, t.transaction_type,
                t.quantity_delta, t.balance_after,
                t.reference, t.notes, t.occurred_at
            from public.inventory_transactions t
            {where}
            order by t.occurred_at desc, t.id
            limit %s offset %s
        """).format(where=where.clause())

        rows = await self.fetch_all(statement, [*where.params, limit, offset])
        total = await self.count(sql.SQL("public.inventory_transactions t"), where)
        return rows, total

    async def get_stock_trend(self, *, item_id: UUID, limit: int = 90) -> list[dict[str, Any]]:
        """Return an item's closing balance per day.

        `distinct on` takes the last movement of each day, which is that day's
        closing balance. The alternative -- summing deltas in Python -- would
        re-derive a number the ledger already carries in `balance_after`.
        """
        statement = sql.SQL("""
            select bucket_date, balance
            from (
                select distinct on ((t.occurred_at at time zone 'UTC')::date)
                    t.occurred_at   as bucket_date,
                    t.balance_after as balance
                from public.inventory_transactions t
                where t.inventory_item_id = %s
                order by (t.occurred_at at time zone 'UTC')::date desc, t.occurred_at desc
            ) as daily
            order by bucket_date
            limit %s
        """)
        return await self.fetch_all(statement, [item_id, limit])
