"""Shared FastAPI dependencies.

Wires the layers together in one place, so a route declares the service it needs
and receives it fully constructed. A route that built its own repository would
also be choosing its own connection, which is how connection leaks and
accidental N+1 patterns start.

Request-scoped resources -- a pooled connection, and the repositories over it --
are yielded by dependencies so FastAPI returns them when the response is done,
whether or not the handler raised.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from psycopg import AsyncConnection

from app.cache.service import CacheService
from app.config import Settings, get_settings
from app.db.pool import DatabasePool
from app.repositories.alerts import AlertRepository
from app.repositories.inventory import InventoryRepository
from app.repositories.machines import MachineRepository
from app.repositories.maintenance import MaintenanceRepository
from app.repositories.production import ProductionRepository
from app.repositories.quality import QualityRepository
from app.services.alert_service import AlertService
from app.services.analytics_service import AnalyticsService
from app.services.dashboard_service import DashboardService
from app.services.inventory_service import InventoryService
from app.services.machine_service import MachineService
from app.services.maintenance_service import MaintenanceService
from app.services.production_service import ProductionService
from app.services.quality_service import QualityService

SettingsDep = Annotated[Settings, Depends(get_settings)]
"""Injects the cached application settings."""


# =============================================================================
# Infrastructure
# =============================================================================


def get_pool(request: Request) -> DatabasePool:
    """Return the pool created during startup.

    Held on `app.state` rather than in a module global so tests can build an
    application with a different pool without monkeypatching.
    """
    return request.app.state.db_pool


def get_cache(request: Request) -> CacheService:
    """Return the cache service created during startup."""
    return request.app.state.cache


PoolDep = Annotated[DatabasePool, Depends(get_pool)]
CacheDep = Annotated[CacheService, Depends(get_cache)]


async def get_connection(pool: PoolDep) -> AsyncIterator[AsyncConnection]:
    """Borrow a pooled connection for the lifetime of one request.

    Yielded, so the connection is returned to the pool even when the handler
    raises. One connection per request means every repository a handler uses
    reads from the same transaction and therefore the same snapshot.
    """
    async with pool.connection() as connection:
        yield connection


ConnectionDep = Annotated[AsyncConnection, Depends(get_connection)]


# =============================================================================
# Repositories
# =============================================================================


def get_production_repository(connection: ConnectionDep) -> ProductionRepository:
    return ProductionRepository(connection)


def get_quality_repository(connection: ConnectionDep) -> QualityRepository:
    return QualityRepository(connection)


def get_inventory_repository(connection: ConnectionDep) -> InventoryRepository:
    return InventoryRepository(connection)


def get_machine_repository(connection: ConnectionDep) -> MachineRepository:
    return MachineRepository(connection)


def get_maintenance_repository(connection: ConnectionDep) -> MaintenanceRepository:
    return MaintenanceRepository(connection)


def get_alert_repository(connection: ConnectionDep) -> AlertRepository:
    return AlertRepository(connection)


# =============================================================================
# Services
# =============================================================================


def get_production_service(
    repository: Annotated[ProductionRepository, Depends(get_production_repository)],
    cache: CacheDep,
) -> ProductionService:
    return ProductionService(repository, cache)


def get_quality_service(
    repository: Annotated[QualityRepository, Depends(get_quality_repository)],
    cache: CacheDep,
) -> QualityService:
    return QualityService(repository, cache)


def get_inventory_service(
    repository: Annotated[InventoryRepository, Depends(get_inventory_repository)],
    cache: CacheDep,
) -> InventoryService:
    return InventoryService(repository, cache)


def get_machine_service(
    repository: Annotated[MachineRepository, Depends(get_machine_repository)],
    maintenance: Annotated[MaintenanceRepository, Depends(get_maintenance_repository)],
    cache: CacheDep,
) -> MachineService:
    return MachineService(repository, maintenance, cache)


def get_alert_service(
    repository: Annotated[AlertRepository, Depends(get_alert_repository)],
    cache: CacheDep,
) -> AlertService:
    return AlertService(repository, cache)


def get_maintenance_service(
    repository: Annotated[MaintenanceRepository, Depends(get_maintenance_repository)],
) -> MaintenanceService:
    return MaintenanceService(repository)


def get_analytics_service(
    machines: Annotated[MachineRepository, Depends(get_machine_repository)],
    production: Annotated[ProductionRepository, Depends(get_production_repository)],
    quality: Annotated[QualityRepository, Depends(get_quality_repository)],
    cache: CacheDep,
) -> AnalyticsService:
    return AnalyticsService(machines, production, quality, cache)


def get_dashboard_service(
    pool: PoolDep,
    cache: CacheDep,
    settings: SettingsDep,
) -> DashboardService:
    """Build the dashboard service.

    Takes the pool rather than a connection: the dashboard runs its aggregates
    concurrently and each needs its own connection, so it is given the factory
    and borrows several for the duration of one request.
    """
    return DashboardService(
        connection_factory=pool.connection,
        cache=cache,
        max_concurrency=settings.db_max_concurrent_queries,
    )


ProductionServiceDep = Annotated[ProductionService, Depends(get_production_service)]
QualityServiceDep = Annotated[QualityService, Depends(get_quality_service)]
InventoryServiceDep = Annotated[InventoryService, Depends(get_inventory_service)]
MachineServiceDep = Annotated[MachineService, Depends(get_machine_service)]
AlertServiceDep = Annotated[AlertService, Depends(get_alert_service)]
AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]
DashboardServiceDep = Annotated[DashboardService, Depends(get_dashboard_service)]
MaintenanceServiceDep = Annotated[MaintenanceService, Depends(get_maintenance_service)]
