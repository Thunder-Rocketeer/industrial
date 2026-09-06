"""Aggregate API router.

Every versioned route is mounted here and the application includes this single
router, so the whole URL surface is visible in one file.

Router order matters for `/inventory`. FastAPI matches routes in declaration
order, so `/inventory/alerts` and `/inventory/summary` must be declared before
`/inventory/{item_id}` -- otherwise "alerts" is matched as an item id and the
request fails UUID validation instead of reaching the handler. They are ordered
correctly within that module; this note exists so a future reordering does not
quietly break them.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    alerts,
    analytics,
    auth,
    dashboard,
    health,
    inventory,
    machines,
    production,
    quality,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(production.router)
api_router.include_router(quality.router)
api_router.include_router(inventory.router)
api_router.include_router(machines.router)
api_router.include_router(analytics.router)
api_router.include_router(alerts.alerts_router)
api_router.include_router(alerts.maintenance_router)
