"""Inventory business logic."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.cache.service import CacheService, CacheTier
from app.models.enums import InventoryStatus
from app.repositories.inventory import InventoryRepository
from app.schemas.filters import InventoryFilters
from app.schemas.inventory import (
    InventoryAlert,
    InventoryItem,
    InventoryStatusCount,
    InventorySummary,
    InventoryTransaction,
    InventoryTrendPoint,
)
from app.services import kpi
from app.services.labels import INVENTORY_STATUS_LABELS, label_for


class InventoryService:
    """Inventory reads, with derived figures and caching."""

    def __init__(self, repository: InventoryRepository, cache: CacheService) -> None:
        self._repository = repository
        self._cache = cache

    async def list_items(self, filters: InventoryFilters) -> tuple[list[InventoryItem], int]:
        """Return one page of stock lines."""
        rows, total = await self._repository.get_inventory(
            status=filters.status,
            component_id=filters.component_id,
            limit=filters.limit,
            offset=filters.offset,
            sort_by=filters.sort_by,
            sort_dir=filters.sort_dir,
        )
        return [self._to_item(row) for row in rows], total

    async def get_alerts(self, limit: int = 50) -> list[InventoryAlert]:
        """Return stock lines needing attention, cached.

        Cached on a fixed key with no filters: the alerts panel always asks the
        same question, so one entry serves every dashboard load.
        """
        return await self._cache.get_or_set_list(
            self._cache.keys.inventory_alerts(),
            CacheTier.REALTIME,
            InventoryAlert,
            lambda: self._build_alerts(limit),
        )

    async def _build_alerts(self, limit: int) -> list[InventoryAlert]:
        rows = await self._repository.get_inventory_alerts(limit=limit)
        return [self._to_alert(row) for row in rows]

    async def get_summary(self) -> InventorySummary:
        """Return the aggregate inventory position, cached."""
        return await self._cache.get_or_set(
            self._cache.keys.inventory_summary(),
            CacheTier.REALTIME,
            InventorySummary,
            self._build_summary,
        )

    async def _build_summary(self) -> InventorySummary:
        totals = await self._repository.get_inventory_summary()
        return self.build_summary_from_totals(totals)

    @staticmethod
    def build_summary_from_totals(totals: dict[str, Any]) -> InventorySummary:
        """Assemble the summary from repository counts.

        Shared with the dashboard service so both report the same health figure.
        """
        total = int(totals.get("total_items") or 0)
        healthy = int(totals.get("healthy_count") or 0)
        low = int(totals.get("low_count") or 0)
        critical = int(totals.get("critical_count") or 0)
        overstocked = int(totals.get("overstocked_count") or 0)

        stock_value = totals.get("total_stock_value")

        return InventorySummary(
            total_items=total,
            healthy_count=healthy,
            low_count=low,
            critical_count=critical,
            overstocked_count=overstocked,
            health_percentage=kpi.inventory_health(healthy, total),
            items_requiring_attention=critical + low,
            # Passed through as None when any unit cost is unset: a partial sum
            # presented as a total would be worse than no number at all.
            total_stock_value=float(stock_value) if stock_value is not None else None,
            status_breakdown=[
                InventoryStatusCount(
                    status=status,
                    status_label=label_for(status, INVENTORY_STATUS_LABELS),
                    count=count,
                )
                for status, count in (
                    (InventoryStatus.HEALTHY, healthy),
                    (InventoryStatus.LOW, low),
                    (InventoryStatus.CRITICAL, critical),
                    (InventoryStatus.OVERSTOCKED, overstocked),
                )
            ],
        )

    async def get_item(self, item_id: UUID) -> InventoryItem | None:
        """Return one stock line, or None."""
        row = await self._repository.get_item(item_id)
        return self._to_item(row) if row else None

    async def get_transactions(
        self, *, item_id: UUID, limit: int, offset: int
    ) -> tuple[list[InventoryTransaction], int]:
        """Return one page of an item's stock movements."""
        rows, total = await self._repository.get_transactions(
            item_id=item_id, limit=limit, offset=offset
        )
        return [
            InventoryTransaction(
                id=row["id"],
                inventory_item_id=row["inventory_item_id"],
                transaction_type=row["transaction_type"],
                quantity_delta=float(row["quantity_delta"]),
                balance_after=float(row["balance_after"]),
                reference=row["reference"],
                notes=row["notes"],
                occurred_at=row["occurred_at"],
            )
            for row in rows
        ], total

    async def get_stock_trend(self, item_id: UUID, limit: int = 90) -> list[InventoryTrendPoint]:
        """Return an item's closing balance per day."""
        rows = await self._repository.get_stock_trend(item_id=item_id, limit=limit)
        return [
            InventoryTrendPoint(bucket_date=row["bucket_date"], balance=float(row["balance"]))
            for row in rows
        ]

    # -- mapping --------------------------------------------------------------

    @staticmethod
    def _to_item(row: dict[str, Any]) -> InventoryItem:
        status = InventoryStatus(row["status"])
        return InventoryItem(
            id=row["id"],
            sku=row["sku"],
            name=row["name"],
            material_type=row["material_type"],
            unit=row["unit"],
            component_id=row["component_id"],
            component_code=row["component_code"],
            component_name=row["component_name"],
            current_quantity=float(row["current_quantity"]),
            minimum_stock=float(row["minimum_stock"]),
            reorder_point=float(row["reorder_point"]),
            maximum_stock=float(row["maximum_stock"]),
            status=status,
            status_label=label_for(status, INVENTORY_STATUS_LABELS),
            stock_utilization_percentage=kpi.stock_utilization(
                row["current_quantity"], row["maximum_stock"]
            ),
            supplier_name=row["supplier_name"],
            supplier_lead_time_days=row["supplier_lead_time_days"],
            unit_cost=float(row["unit_cost"]) if row["unit_cost"] is not None else None,
            last_counted_at=row["last_counted_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _to_alert(row: dict[str, Any]) -> InventoryAlert:
        status = InventoryStatus(row["status"])
        current = float(row["current_quantity"])
        reorder = float(row["reorder_point"])
        minimum = float(row["minimum_stock"])
        label = label_for(status, INVENTORY_STATUS_LABELS)

        # Spec section 45: the message must carry the meaning on its own, so a
        # screen reader or a greyscale display loses nothing.
        lead_time = row["supplier_lead_time_days"]
        lead_clause = f" Supplier lead time is {lead_time} days." if lead_time is not None else ""
        if status is InventoryStatus.CRITICAL:
            message = (
                f"{row['name']} is at {current:,.0f} {row['unit']}, at or below the "
                f"minimum of {minimum:,.0f}.{lead_clause}"
            )
        else:
            message = (
                f"{row['name']} has fallen to {current:,.0f} {row['unit']}, below the "
                f"reorder point of {reorder:,.0f}.{lead_clause}"
            )

        return InventoryAlert(
            id=row["id"],
            sku=row["sku"],
            name=row["name"],
            unit=row["unit"],
            status=status,
            status_label=label,
            current_quantity=current,
            minimum_stock=minimum,
            reorder_point=reorder,
            shortfall=max(0.0, round(reorder - current, 3)),
            supplier_name=row["supplier_name"],
            supplier_lead_time_days=lead_time,
            message=message,
        )
