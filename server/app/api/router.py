"""Aggregate API router.

Every versioned route is mounted here and the application includes this single
router, so the URL surface is visible in one file. Domain routers (production,
quality, inventory, machines, analytics, auth, dashboard) are added in Phase 3.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health

api_router = APIRouter()

api_router.include_router(health.router)
