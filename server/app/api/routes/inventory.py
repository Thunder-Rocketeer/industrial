"""Inventory endpoints (spec section 9)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.routes.production import COMMON_ERRORS
from app.dependencies import InventoryServiceDep
from app.schemas.common import Envelope, PaginatedResponse, PaginationMeta
from app.schemas.filters import InventoryFilters, PageParams
from app.schemas.inventory import (
    InventoryAlert,
    InventoryItem,
    InventorySummary,
    InventoryTransaction,
    InventoryTrendPoint,
)
from app.security.dependencies import require_permission
from app.security.policy import Permission

#: Every endpoint on this router requires INVENTORY_READ. Declared once at
#: the router rather than per route, so an endpoint added later inherits
#: the protection instead of being unguarded until someone notices.
router = APIRouter(
    prefix="/inventory",
    tags=["Inventory"],
    dependencies=[Depends(require_permission(Permission.INVENTORY_READ))],
)

_NOT_FOUND = {404: {"description": "The requested inventory item does not exist."}}


@router.get(
    "",
    response_model=PaginatedResponse[InventoryItem],
    summary="List inventory items",
    description=(
        "Returns stock lines with their derived status and utilisation.\n\n"
        "`status` is computed by the database from the quantity and its "
        "thresholds -- CRITICAL at or below minimum, LOW at or below the "
        "reorder point, OVERSTOCKED at or above maximum, otherwise HEALTHY -- so "
        "the label and the number can never disagree.\n\n"
        "Sorting accepts: `name`, `sku`, `status`, `quantity`, `updated`."
    ),
    responses=COMMON_ERRORS,
)
async def list_inventory(
    service: InventoryServiceDep,
    filters: Annotated[InventoryFilters, Query()],
) -> PaginatedResponse[InventoryItem]:
    items, total = await service.list_items(filters)
    return PaginatedResponse(
        data=items,
        pagination=PaginationMeta(page=filters.page, page_size=filters.page_size, total=total),
    )


@router.get(
    "/alerts",
    response_model=Envelope[list[InventoryAlert]],
    summary="Inventory items requiring attention",
    description=(
        "Stock lines that are CRITICAL or LOW, most urgent first. Each carries a "
        "full-sentence `message` describing the condition, so the alert is "
        "readable without colour or an icon."
    ),
    responses=COMMON_ERRORS,
)
async def inventory_alerts(
    service: InventoryServiceDep,
    limit: Annotated[int, Query(ge=1, le=100, description="Maximum alerts.")] = 50,
) -> Envelope[list[InventoryAlert]]:
    return Envelope(data=await service.get_alerts(limit))


@router.get(
    "/summary",
    response_model=Envelope[InventorySummary],
    summary="Inventory summary",
    description=(
        "Counts per stock state and the overall health percentage.\n\n"
        "`total_stock_value` is null when any item has no unit cost, rather than "
        "presenting a partial sum as a complete one."
    ),
    responses=COMMON_ERRORS,
)
async def inventory_summary(service: InventoryServiceDep) -> Envelope[InventorySummary]:
    return Envelope(data=await service.get_summary())


@router.get(
    "/{item_id}",
    response_model=Envelope[InventoryItem],
    summary="Get one inventory item",
    description="Returns a single stock line by its identifier.",
    responses={**COMMON_ERRORS, **_NOT_FOUND},
)
async def get_inventory_item(
    item_id: UUID,
    service: InventoryServiceDep,
) -> Envelope[InventoryItem]:
    item = await service.get_item(item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inventory item not found.",
        )
    return Envelope(data=item)


@router.get(
    "/{item_id}/transactions",
    response_model=PaginatedResponse[InventoryTransaction],
    summary="List stock movements for an item",
    description=(
        "Stock movements for one item, newest first. `quantity_delta` is signed: "
        "positive adds stock, negative removes it."
    ),
    responses={**COMMON_ERRORS, **_NOT_FOUND},
)
async def inventory_transactions(
    item_id: UUID,
    service: InventoryServiceDep,
    page: Annotated[PageParams, Query()],
) -> PaginatedResponse[InventoryTransaction]:
    transactions, total = await service.get_transactions(
        item_id=item_id, limit=page.limit, offset=page.offset
    )
    return PaginatedResponse(
        data=transactions,
        pagination=PaginationMeta(page=page.page, page_size=page.page_size, total=total),
    )


@router.get(
    "/{item_id}/trend",
    response_model=Envelope[list[InventoryTrendPoint]],
    summary="Stock level history for an item",
    description="Closing balance per day, oldest first, for the inventory trend chart.",
    responses={**COMMON_ERRORS, **_NOT_FOUND},
)
async def inventory_trend(
    item_id: UUID,
    service: InventoryServiceDep,
    limit: Annotated[int, Query(ge=1, le=365, description="Maximum days.")] = 90,
) -> Envelope[list[InventoryTrendPoint]]:
    return Envelope(data=await service.get_stock_trend(item_id, limit))
