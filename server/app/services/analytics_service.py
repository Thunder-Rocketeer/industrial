"""Analytics business logic: OEE, efficiency and defect analysis.

OEE is assembled here rather than in the repository because it is a composition
of three ratios over the same rows, and the repository's job is to return those
rows' sums (spec section 8).
"""

from __future__ import annotations

from typing import Any

from app.cache.service import CacheService, CacheTier
from app.repositories.machines import MachineRepository
from app.repositories.production import ProductionRepository
from app.repositories.quality import QualityRepository
from app.schemas.analytics import (
    DefectAnalytics,
    DowntimeByMachine,
    EfficiencySummary,
    EfficiencyTrendPoint,
    OEEByMachine,
    OEEComponents,
    OEESummary,
    OEETrendPoint,
)
from app.schemas.filters import AnalyticsFilters
from app.services import kpi
from app.services.quality_service import QualityService


def compute_oee_components(row: dict[str, Any]) -> dict[str, float]:
    """Derive the three OEE terms and their product from one aggregate row.

    Expects the keys `operating_minutes`, `planned_minutes`, `produced_quantity`,
    `accepted_quantity` and `ideal_output_units`.

    Shared by the summary, the trend and the per-machine breakdown so all three
    are guaranteed to compute OEE identically -- the single most likely place
    for three endpoints to quietly disagree.
    """
    availability = kpi.availability(row.get("operating_minutes"), row.get("planned_minutes"))
    performance = kpi.as_percentage(
        row.get("produced_quantity"), row.get("ideal_output_units"), cap=kpi.MAX_PERCENTAGE
    )
    performance_raw = kpi.as_percentage(row.get("produced_quantity"), row.get("ideal_output_units"))
    quality = kpi.quality_rate(row.get("accepted_quantity"), row.get("produced_quantity"))

    return {
        "availability_percentage": availability,
        "performance_percentage": performance,
        "quality_percentage": quality,
        "oee_percentage": kpi.oee(availability, performance, quality),
        "performance_uncapped_percentage": performance_raw,
    }


class AnalyticsService:
    """OEE, efficiency and defect analytics."""

    def __init__(
        self,
        machine_repository: MachineRepository,
        production_repository: ProductionRepository,
        quality_repository: QualityRepository,
        cache: CacheService,
    ) -> None:
        self._machines = machine_repository
        self._production = production_repository
        self._quality = quality_repository
        self._cache = cache

    # -- OEE ------------------------------------------------------------------

    async def get_oee(self, filters: AnalyticsFilters) -> OEESummary:
        """Return OEE and its three terms for the filtered period, cached."""
        key = self._cache.keys.analytics_oee(
            filters.resolved_start, filters.resolved_end, filters.cache_filters()
        )
        return await self._cache.get_or_set(
            key, CacheTier.ANALYTICS, OEESummary, lambda: self._build_oee(filters)
        )

    async def _build_oee(self, filters: AnalyticsFilters) -> OEESummary:
        row = await self._machines.get_fleet_oee_inputs(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
            line_id=filters.line_id,
        )
        components = compute_oee_components(row)
        record_count = int(row.get("record_count") or 0)

        return OEESummary(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            operating_minutes=int(row.get("operating_minutes") or 0),
            planned_minutes=int(row.get("planned_minutes") or 0),
            downtime_minutes=int(row.get("downtime_minutes") or 0),
            produced_quantity=int(row.get("produced_quantity") or 0),
            accepted_quantity=int(row.get("accepted_quantity") or 0),
            rejected_quantity=int(row.get("rejected_quantity") or 0),
            ideal_output=round(float(row.get("ideal_output_units") or 0.0), 2),
            record_count=record_count,
            has_data=record_count > 0,
            **components,
        )

    async def get_oee_trend(self, filters: AnalyticsFilters) -> list[OEETrendPoint]:
        """Return daily OEE for the trend chart, cached."""
        base = self._cache.keys.analytics_oee(
            filters.resolved_start, filters.resolved_end, filters.cache_filters()
        )
        key = f"{base}:trend"
        return await self._cache.get_or_set_list(
            key, CacheTier.ANALYTICS, OEETrendPoint, lambda: self._build_oee_trend(filters)
        )

    async def _build_oee_trend(self, filters: AnalyticsFilters) -> list[OEETrendPoint]:
        rows = await self._machines.get_oee_trend_inputs(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
            line_id=filters.line_id,
        )
        return [
            OEETrendPoint(bucket_date=row["bucket_date"], **compute_oee_components(row))
            for row in rows
        ]

    async def get_oee_by_machine(self, filters: AnalyticsFilters) -> list[OEEByMachine]:
        """Return OEE per machine, worst first, so problems surface at the top."""
        rows = await self._machines.get_oee_by_machine(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            line_id=filters.line_id,
        )
        machines = [
            OEEByMachine(
                machine_id=row["machine_id"],
                machine_code=row["machine_code"],
                machine_name=row["machine_name"],
                produced_quantity=int(row["produced_quantity"] or 0),
                operating_minutes=int(row["operating_minutes"] or 0),
                **compute_oee_components(row),
            )
            for row in rows
        ]
        return sorted(machines, key=lambda m: m.oee_percentage)

    # -- efficiency -----------------------------------------------------------

    async def get_efficiency(self, filters: AnalyticsFilters) -> EfficiencySummary:
        """Return production efficiency against plan and target, cached."""
        key = self._cache.keys.analytics_efficiency(
            filters.resolved_start, filters.resolved_end, filters.cache_filters()
        )
        return await self._cache.get_or_set(
            key,
            CacheTier.ANALYTICS,
            EfficiencySummary,
            lambda: self._build_efficiency(filters),
        )

    async def _build_efficiency(self, filters: AnalyticsFilters) -> EfficiencySummary:
        totals = await self._production.get_production_summary(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
            line_id=filters.line_id,
        )
        # As in the production service: targets have no machine dimension, so
        # achievement is only reported when the comparison is sound.
        target = (
            await self._production.get_target_quantity(
                start_date=filters.resolved_start,
                end_date=filters.resolved_end,
                component_id=filters.component_id,
                line_id=filters.line_id,
            )
            if filters.machine_id is None
            else 0
        )

        produced = int(totals.get("total_produced") or 0)
        planned = int(totals.get("total_planned") or 0)
        planned_minutes = int(totals.get("total_planned_minutes") or 0)
        downtime = int(totals.get("total_downtime_minutes") or 0)
        record_count = int(totals.get("record_count") or 0)

        return EfficiencySummary(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            total_planned=planned,
            total_produced=produced,
            total_target=target,
            efficiency_percentage=kpi.production_efficiency(produced, planned),
            achievement_percentage=kpi.production_achievement(produced, target),
            total_planned_minutes=planned_minutes,
            total_operating_minutes=int(totals.get("total_operating_minutes") or 0),
            total_downtime_minutes=downtime,
            downtime_percentage=kpi.as_percentage(
                downtime, planned_minutes, cap=kpi.MAX_PERCENTAGE
            ),
            record_count=record_count,
            has_data=record_count > 0,
        )

    async def get_efficiency_trend(self, filters: AnalyticsFilters) -> list[EfficiencyTrendPoint]:
        """Return the daily efficiency and achievement trend."""
        rows = await self._production.get_production_trend(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
            line_id=filters.line_id,
        )
        return [
            EfficiencyTrendPoint(
                bucket_date=row["bucket_date"],
                planned_quantity=int(row["planned_quantity"] or 0),
                produced_quantity=int(row["produced_quantity"] or 0),
                target_quantity=int(row["target_quantity"] or 0),
                efficiency_percentage=kpi.production_efficiency(
                    row["produced_quantity"], row["planned_quantity"]
                ),
                achievement_percentage=kpi.production_achievement(
                    row["produced_quantity"], row["target_quantity"]
                ),
            )
            for row in rows
        ]

    async def get_downtime_by_machine(self, filters: AnalyticsFilters) -> list[DowntimeByMachine]:
        """Return downtime per machine, worst first."""
        rows = await self._machines.get_downtime_by_machine(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            line_id=filters.line_id,
        )
        return [
            DowntimeByMachine(
                machine_id=row["machine_id"],
                machine_code=row["machine_code"],
                machine_name=row["machine_name"],
                downtime_minutes=int(row["downtime_minutes"] or 0),
                planned_minutes=int(row["planned_minutes"] or 0),
                downtime_percentage=kpi.as_percentage(
                    row["downtime_minutes"], row["planned_minutes"], cap=kpi.MAX_PERCENTAGE
                ),
            )
            for row in rows
        ]

    # -- defects --------------------------------------------------------------

    async def get_defect_analytics(self, filters: AnalyticsFilters) -> DefectAnalytics:
        """Return the full defect analysis: Pareto, by machine, by component, trend."""
        base = self._cache.keys.analytics_defects(
            filters.resolved_start, filters.resolved_end, filters.cache_filters()
        )
        key = f"{base}:full"
        return await self._cache.get_or_set(
            key, CacheTier.ANALYTICS, DefectAnalytics, lambda: self._build_defects(filters)
        )

    async def _build_defects(self, filters: AnalyticsFilters) -> DefectAnalytics:
        totals = await self._quality.get_quality_summary(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
        )
        breakdown = await self._quality.get_defect_breakdown(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
        )
        by_machine = await self._quality.get_quality_by_dimension(
            dimension="machine",
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
        )
        by_component = await self._quality.get_quality_by_dimension(
            dimension="component",
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
        )
        trend_rows = await self._quality.get_defect_trend(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
        )

        from app.schemas.quality import DefectTrendPoint, QualityByDimension

        inspected = int(totals.get("total_inspected") or 0)
        rejected = int(totals.get("total_rejected") or 0)

        return DefectAnalytics(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            total_inspected=inspected,
            total_rejected=rejected,
            defect_rate_percentage=kpi.defect_rate(rejected, inspected),
            by_defect=QualityService.build_pareto(breakdown),
            by_machine=[
                QualityByDimension(
                    key_id=row["key_id"],
                    key_code=row["key_code"],
                    key_name=row["key_name"],
                    inspected_quantity=int(row["inspected_quantity"] or 0),
                    rejected_quantity=int(row["rejected_quantity"] or 0),
                    defect_rate_percentage=kpi.defect_rate(
                        row["rejected_quantity"], row["inspected_quantity"]
                    ),
                )
                for row in by_machine
            ],
            by_component=[
                QualityByDimension(
                    key_id=row["key_id"],
                    key_code=row["key_code"],
                    key_name=row["key_name"],
                    inspected_quantity=int(row["inspected_quantity"] or 0),
                    rejected_quantity=int(row["rejected_quantity"] or 0),
                    defect_rate_percentage=kpi.defect_rate(
                        row["rejected_quantity"], row["inspected_quantity"]
                    ),
                )
                for row in by_component
            ],
            trend=[
                DefectTrendPoint(
                    bucket_date=row["bucket_date"],
                    inspected_quantity=int(row["inspected_quantity"] or 0),
                    rejected_quantity=int(row["rejected_quantity"] or 0),
                    defect_rate_percentage=kpi.defect_rate(
                        row["rejected_quantity"], row["inspected_quantity"]
                    ),
                )
                for row in trend_rows
            ],
            has_data=int(totals.get("record_count") or 0) > 0,
        )

    @staticmethod
    def components_from_row(row: dict[str, Any]) -> OEEComponents:
        """Build an `OEEComponents` from an aggregate row. Used by the dashboard."""
        return OEEComponents(**compute_oee_components(row))
