"""Inventory response models.

`status` is a generated column in the database (see `docs/database.md` section
4.2), so it is read here and never written. That is why there is no request
model for changing it: the stock quantity is the input, and the state follows.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InventoryStatus, InventoryTransactionType


class InventoryItem(BaseModel):
    """One stock line."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    name: str
    material_type: str
    unit: str = Field(description="Unit of measure, e.g. kg, litres, units.")

    component_id: UUID | None = Field(
        default=None, description="Set when the item maps to a manufactured component."
    )
    component_code: str | None = None
    component_name: str | None = None

    current_quantity: float = Field(ge=0)
    minimum_stock: float = Field(ge=0)
    reorder_point: float = Field(ge=0)
    maximum_stock: float = Field(gt=0)

    status: InventoryStatus = Field(
        description="Derived in the database from the quantity and thresholds."
    )
    #: Spec section 45: state must be readable as text, never colour alone.
    status_label: str = Field(description="Human-readable status for display.")
    stock_utilization_percentage: float = Field(
        ge=0, le=100, description="Current quantity against the maximum holding."
    )

    supplier_name: str
    supplier_lead_time_days: int | None = None
    unit_cost: float | None = Field(default=None, ge=0)
    last_counted_at: datetime | None = None
    updated_at: datetime


class InventoryAlert(BaseModel):
    """A stock line needing attention.

    A narrower projection than `InventoryItem`: the alerts panel needs to say
    what is wrong and how urgent it is, not carry the full stock record.
    """

    id: UUID
    sku: str
    name: str
    unit: str
    status: InventoryStatus
    status_label: str
    current_quantity: float = Field(ge=0)
    minimum_stock: float = Field(ge=0)
    reorder_point: float = Field(ge=0)
    shortfall: float = Field(
        ge=0, description="Units below the reorder point. Zero when at or above it."
    )
    supplier_name: str
    supplier_lead_time_days: int | None = None
    #: A full sentence, not a fragment, so it reads correctly on its own.
    message: str = Field(description="Human-readable description of the condition.")


class InventoryStatusCount(BaseModel):
    """How many stock lines sit in one state."""

    status: InventoryStatus
    status_label: str
    count: int = Field(ge=0)


class InventorySummary(BaseModel):
    """Aggregate inventory position."""

    total_items: int = Field(ge=0)
    healthy_count: int = Field(ge=0)
    low_count: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    overstocked_count: int = Field(ge=0)

    health_percentage: float = Field(
        ge=0, le=100, description="Share of stock lines in a healthy state."
    )
    items_requiring_attention: int = Field(ge=0, description="Lines that are CRITICAL or LOW.")
    total_stock_value: float | None = Field(
        default=None,
        ge=0,
        description="Sum of quantity x unit cost. Null when any unit cost is unset.",
    )
    status_breakdown: list[InventoryStatusCount] = Field(default_factory=list)


class InventoryTransaction(BaseModel):
    """One stock movement.

    `quantity_delta` is signed: positive adds stock, negative removes it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    inventory_item_id: UUID
    transaction_type: InventoryTransactionType
    quantity_delta: float
    balance_after: float = Field(ge=0)
    reference: str
    notes: str
    occurred_at: datetime


class InventoryTrendPoint(BaseModel):
    """One point on an item's stock-level history."""

    bucket_date: datetime = Field(description="Timestamp of the closing balance (UTC).")
    balance: float = Field(ge=0)
