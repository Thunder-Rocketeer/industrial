"""Dashboard composition (spec sections 9 and 10).

The summary endpoint answers the ten questions in spec section 3 in one
response. Assembling it needs six independent aggregates, and this module's job
is to get all six without the request taking six times as long.

CONCURRENCY

The aggregates do not depend on each other, so they run concurrently with
`asyncio.gather`, each on its own pooled connection. Spec section 19 asks for
exactly this -- "where multiple independent aggregate queries can safely run
concurrently, consider async/concurrent execution" -- and then adds the
constraint that matters: "without sacrificing database stability".

That constraint is why a semaphore bounds the fan-out to
`DB_MAX_CONCURRENT_QUERIES`. Without it, every concurrent dashboard request
would try to take six connections at once, and a handful of simultaneous page
loads would exhaust a pool sized for ten. With it, the fan-out is capped and
sized independently of the pool.

One consequence worth stating: because each query takes its own connection, the
six aggregates are read in six separate transactions and therefore six slightly
different snapshots. For a dashboard refreshed every thirty seconds that is
immaterial. If exact cross-aggregate consistency were ever required, they would
have to share one connection and run sequentially -- trading latency for it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from typing import TypeVar

from app.cache.service import CacheService, CacheTier
from app.repositories.alerts import AlertRepository
from app.repositories.inventory import InventoryRepository
from app.repositories.machines import MachineRepository
from app.repositories.production import ProductionRepository
from app.repositories.quality import QualityRepository
from app.schemas.dashboard import (
    DashboardKpi,
    DashboardSummary,
    DashboardTrends,
    KpiTrend,
)
from app.schemas.filters import TrendFilters
from app.services import kpi
from app.services.alert_service import AlertService
from app.services.analytics_service import AnalyticsService, compute_oee_components
from app.services.inventory_service import InventoryService
from app.services.labels import (
    ACHIEVEMENT_GOOD,
    ACHIEVEMENT_WARNING,
    AVAILABILITY_GOOD,
    AVAILABILITY_WARNING,
    DEFECT_RATE_GOOD,
    DEFECT_RATE_WARNING,
    INVENTORY_HEALTH_GOOD,
    INVENTORY_HEALTH_WARNING,
    OEE_GOOD,
    OEE_WARNING,
    STATUS_LABELS,
    status_for,
    trend_direction,
)
from app.services.machine_service import MachineService
from app.services.production_service import ProductionService
from app.services.quality_service import QualityService
from app.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

#: Open alerts shown in the dashboard panel.
DASHBOARD_ALERT_LIMIT = 8

#: Defect categories in the trends response, enough for a readable Pareto.
DASHBOARD_TOP_DEFECTS = 8


class DashboardService:
    """Assembles the executive dashboard.

    Takes repository *factories* rather than repositories: each concurrent query
    needs its own connection, so the repository must be constructed inside the
    task that borrows one. A shared repository would mean a shared connection,
    and psycopg connections are not safe to use from two coroutines at once.
    """

    def __init__(
        self,
        *,
        connection_factory: Callable[[], object],
        cache: CacheService,
        max_concurrency: int = 5,
    ) -> None:
        self._connection_factory = connection_factory
        self._cache = cache
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _run(self, work: Callable[..., Awaitable[T]]) -> T:
        """Run one query on its own pooled connection, bounded by the semaphore."""
        async with self._semaphore, self._connection_factory() as connection:
            return await work(connection)

    # -- summary --------------------------------------------------------------

    async def get_summary(self) -> DashboardSummary:
        """Return the complete dashboard summary, cached for the realtime tier."""
        business_date = await self._resolve_business_date()
        key = self._cache.keys.dashboard_summary(business_date)

        cached = await self._cache.client.get(key)
        if cached is not None:
            from app.cache.serializer import CacheSerializationError, load_model

            try:
                summary = load_model(cached, DashboardSummary)
                # Marked so a stale dashboard can be diagnosed without guessing.
                return summary.model_copy(update={"cache_hit": True})
            except CacheSerializationError:
                logger.info("cache.entry_rejected", extra={"cache_key": key})

        summary = await self._build_summary(business_date)
        await self._cache.set(key, summary, CacheTier.REALTIME)
        return summary

    async def _resolve_business_date(self) -> date:
        """Return the date the dashboard's "today" figures cover.

        Anchored to the latest date with production rather than the wall clock.
        The demo database is seeded up to the day it was generated, so on any
        later day `current_date` would produce an entirely empty dashboard --
        indistinguishable from a broken deployment. Falling back to today keeps
        a genuinely empty database behaving sensibly.
        """

        async def work(connection: object) -> date | None:
            return await ProductionRepository(connection).get_latest_production_date()

        latest = await self._run(work)
        return latest or datetime.now(tz=timezone.utc).date()

    async def _build_summary(self, business_date: date) -> DashboardSummary:
        previous_date = business_date - timedelta(days=1)

        async def production_today(connection: object) -> dict:
            return await ProductionRepository(connection).get_daily_totals_for(business_date)

        async def production_previous(connection: object) -> dict:
            return await ProductionRepository(connection).get_daily_totals_for(previous_date)

        async def production_target(connection: object) -> int:
            return await ProductionRepository(connection).get_target_quantity(
                start_date=business_date, end_date=business_date
            )

        async def quality_today(connection: object) -> dict:
            return await QualityRepository(connection).get_daily_totals_for(business_date)

        async def inventory_totals(connection: object) -> dict:
            return await InventoryRepository(connection).get_inventory_summary()

        async def machine_totals(connection: object) -> dict:
            return await MachineRepository(connection).get_machine_summary()

        async def oee_inputs(connection: object) -> dict:
            return await MachineRepository(connection).get_fleet_oee_inputs(
                start_date=business_date, end_date=business_date
            )

        async def alert_totals(connection: object) -> dict:
            return await AlertRepository(connection).get_alert_summary()

        async def recent_alerts(connection: object) -> list[dict]:
            return await AlertRepository(connection).get_active_alerts(limit=DASHBOARD_ALERT_LIMIT)

        (
            production_row,
            previous_row,
            target,
            quality_row,
            inventory_row,
            machine_row,
            oee_row,
            alerts_row,
            alert_rows,
        ) = await asyncio.gather(
            self._run(production_today),
            self._run(production_previous),
            self._run(production_target),
            self._run(quality_today),
            self._run(inventory_totals),
            self._run(machine_totals),
            self._run(oee_inputs),
            self._run(alert_totals),
            self._run(recent_alerts),
        )

        # Reuse the domain services' assembly so the dashboard and the detail
        # pages cannot report different numbers for the same day.
        production = ProductionService.build_summary_from_totals(
            production_row, target, business_date, business_date
        )
        quality = QualityService.build_summary_from_totals(
            quality_row, business_date, business_date
        )
        inventory = InventoryService.build_summary_from_totals(inventory_row)
        machines = MachineService.build_fleet_summary_from_totals(machine_row)
        oee = AnalyticsService.components_from_row(oee_row)
        alerts = AlertService.build_summary_from_totals(alerts_row)

        now = datetime.now(tz=timezone.utc)
        recent = [AlertService.build_alert(row, now) for row in alert_rows]

        return DashboardSummary(
            generated_at=now,
            business_date=business_date,
            kpis=self._build_kpis(
                production=production,
                quality=quality,
                inventory=inventory,
                machines=machines,
                oee=oee,
                previous_production=previous_row,
            ),
            production=production,
            quality=quality,
            inventory=inventory,
            machines=machines,
            oee=oee,
            alerts=alerts,
            recent_alerts=recent,
            cache_hit=False,
        )

    @staticmethod
    def _build_kpis(
        *,
        production,
        quality,
        inventory,
        machines,
        oee,
        previous_production: dict,
    ) -> list[DashboardKpi]:
        """Build the KPI cards for spec section 5.1.

        Every card carries its value, unit, a context sentence, a textual status
        and a trend, so the frontend formats rather than calculates
        (spec section 42).
        """
        previous_produced = int(previous_production.get("total_produced") or 0)
        production_change = kpi.percentage_change(production.total_produced, previous_produced)

        def card(
            key: str,
            label: str,
            value: float,
            unit: str,
            context: str,
            status: str,
            trend: KpiTrend | None = None,
        ) -> DashboardKpi:
            return DashboardKpi(
                key=key,
                label=label,
                value=value,
                unit=unit,
                context_label=context,
                status=status,
                status_label=STATUS_LABELS.get(status, ""),
                trend=trend or KpiTrend(),
            )

        return [
            card(
                "production_today",
                "Today's production",
                float(production.total_produced),
                "units",
                (
                    f"{production.total_produced:,} of {production.target_quantity:,} units"
                    if production.target_quantity
                    else f"{production.total_produced:,} units"
                ),
                status_for(production.achievement_percentage, ACHIEVEMENT_GOOD, ACHIEVEMENT_WARNING)
                if production.target_quantity
                else "neutral",
                KpiTrend(
                    change_percentage=production_change,
                    direction=trend_direction(production_change),
                    comparison_label="vs previous day",
                ),
            ),
            card(
                "production_target",
                "Production target",
                float(production.target_quantity),
                "units",
                f"{production.achievement_percentage:.1f}% achieved",
                status_for(production.achievement_percentage, ACHIEVEMENT_GOOD, ACHIEVEMENT_WARNING)
                if production.target_quantity
                else "neutral",
            ),
            card(
                "production_efficiency",
                "Production efficiency",
                production.efficiency_percentage,
                "%",
                f"{production.total_produced:,} of {production.total_planned:,} planned",
                status_for(production.efficiency_percentage, ACHIEVEMENT_GOOD, ACHIEVEMENT_WARNING)
                if production.has_data
                else "neutral",
            ),
            card(
                "defect_rate",
                "Defect rate",
                quality.defect_rate_percentage,
                "%",
                f"{quality.total_rejected:,} of {quality.total_inspected:,} units rejected",
                status_for(
                    quality.defect_rate_percentage,
                    DEFECT_RATE_GOOD,
                    DEFECT_RATE_WARNING,
                    higher_is_better=False,
                )
                if quality.has_data
                else "neutral",
            ),
            card(
                "first_pass_yield",
                "First pass yield",
                quality.first_pass_yield_percentage,
                "%",
                f"{quality.total_first_pass:,} units right first time",
                status_for(quality.first_pass_yield_percentage, 95.0, 90.0)
                if quality.has_data
                else "neutral",
            ),
            card(
                "machine_availability",
                "Machine availability",
                machines.availability_percentage,
                "%",
                f"{machines.running_count} of {machines.total_machines} machines running",
                status_for(
                    machines.availability_percentage, AVAILABILITY_GOOD, AVAILABILITY_WARNING
                ),
            ),
            card(
                "oee",
                "OEE",
                oee.oee_percentage,
                "%",
                (
                    f"A {oee.availability_percentage:.0f}% "
                    f"P {oee.performance_percentage:.0f}% "
                    f"Q {oee.quality_percentage:.0f}%"
                ),
                status_for(oee.oee_percentage, OEE_GOOD, OEE_WARNING)
                if production.has_data
                else "neutral",
            ),
            card(
                "inventory_health",
                "Inventory health",
                inventory.health_percentage,
                "%",
                (
                    f"{inventory.items_requiring_attention} of "
                    f"{inventory.total_items} lines need attention"
                ),
                status_for(
                    inventory.health_percentage,
                    INVENTORY_HEALTH_GOOD,
                    INVENTORY_HEALTH_WARNING,
                ),
            ),
        ]

    # -- trends ---------------------------------------------------------------

    async def get_trends(self, filters: TrendFilters) -> DashboardTrends:
        """Return the dashboard chart series, cached."""
        key = self._cache.keys.dashboard_trends(
            filters.resolved_start, filters.resolved_end, filters.cache_filters()
        )
        return await self._cache.get_or_set(
            key, CacheTier.TREND, DashboardTrends, lambda: self._build_trends(filters)
        )

    async def _build_trends(self, filters: TrendFilters) -> DashboardTrends:
        async def production_trend(connection: object) -> list[dict]:
            return await ProductionRepository(connection).get_production_trend(
                start_date=filters.resolved_start,
                end_date=filters.resolved_end,
                line_id=filters.line_id,
            )

        async def defect_trend(connection: object) -> list[dict]:
            return await QualityRepository(connection).get_defect_trend(
                start_date=filters.resolved_start, end_date=filters.resolved_end
            )

        async def oee_trend(connection: object) -> list[dict]:
            return await MachineRepository(connection).get_oee_trend_inputs(
                start_date=filters.resolved_start,
                end_date=filters.resolved_end,
                line_id=filters.line_id,
            )

        async def top_defects(connection: object) -> list[dict]:
            return await QualityRepository(connection).get_defect_breakdown(
                start_date=filters.resolved_start,
                end_date=filters.resolved_end,
                limit=DASHBOARD_TOP_DEFECTS,
            )

        production_rows, defect_rows, oee_rows, defect_breakdown = await asyncio.gather(
            self._run(production_trend),
            self._run(defect_trend),
            self._run(oee_trend),
            self._run(top_defects),
        )

        from app.schemas.analytics import OEETrendPoint
        from app.schemas.production import ProductionTrendPoint
        from app.schemas.quality import DefectTrendPoint

        return DashboardTrends(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            production=[
                ProductionTrendPoint(
                    bucket_date=row["bucket_date"],
                    planned_quantity=int(row["planned_quantity"] or 0),
                    produced_quantity=int(row["produced_quantity"] or 0),
                    accepted_quantity=int(row["accepted_quantity"] or 0),
                    rejected_quantity=int(row["rejected_quantity"] or 0),
                    target_quantity=int(row["target_quantity"] or 0),
                    achievement_percentage=kpi.production_achievement(
                        row["produced_quantity"], row["target_quantity"]
                    ),
                )
                for row in production_rows
            ],
            defects=[
                DefectTrendPoint(
                    bucket_date=row["bucket_date"],
                    inspected_quantity=int(row["inspected_quantity"] or 0),
                    rejected_quantity=int(row["rejected_quantity"] or 0),
                    defect_rate_percentage=kpi.defect_rate(
                        row["rejected_quantity"], row["inspected_quantity"]
                    ),
                )
                for row in defect_rows
            ],
            oee=[
                OEETrendPoint(bucket_date=row["bucket_date"], **compute_oee_components(row))
                for row in oee_rows
            ],
            top_defects=QualityService.build_pareto(defect_breakdown),
            has_data=bool(production_rows or defect_rows),
        )
