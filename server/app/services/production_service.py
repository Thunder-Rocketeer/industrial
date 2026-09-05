"""Production business logic.

Calls the repository, applies the KPI formulas from `app.services.kpi`, and
returns typed models. No SQL here, and no formulas anywhere else (spec sections
8 and 42).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.cache.service import CacheService, CacheTier
from app.repositories.production import ProductionRepository
from app.schemas.filters import ProductionFilters, ProductionListFilters
from app.schemas.production import (
    ProductionByDimension,
    ProductionRecord,
    ProductionSummary,
    ProductionTrendPoint,
)
from app.services import kpi


class ProductionService:
    """Production reads, with KPI derivation and caching."""

    def __init__(self, repository: ProductionRepository, cache: CacheService) -> None:
        self._repository = repository
        self._cache = cache

    async def list_records(
        self, filters: ProductionListFilters
    ) -> tuple[list[ProductionRecord], int]:
        """Return one page of production records.

        Deliberately uncached: a filtered, paginated, sorted list has very high
        key cardinality and low reuse, so caching it would fill Redis with
        entries nobody reads twice. The aggregates below are the opposite --
        few keys, read constantly -- which is what makes them worth caching.
        """
        rows, total = await self._repository.get_production_records(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
            shift_id=filters.shift_id,
            line_id=filters.line_id,
            limit=filters.limit,
            offset=filters.offset,
            sort_by=filters.sort_by,
            sort_dir=filters.sort_dir,
        )
        return [self._to_record(row) for row in rows], total

    async def get_summary(self, filters: ProductionFilters) -> ProductionSummary:
        """Return aggregate production for the filtered period, cached."""
        key = self._cache.keys.production_summary(
            filters.resolved_start, filters.resolved_end, filters.cache_filters()
        )
        return await self._cache.get_or_set(
            key,
            CacheTier.TREND,
            ProductionSummary,
            lambda: self._build_summary(filters),
        )

    async def _build_summary(self, filters: ProductionFilters) -> ProductionSummary:
        totals = await self._repository.get_production_summary(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
            shift_id=filters.shift_id,
            line_id=filters.line_id,
        )

        # Targets exist at (date, line, component) grain only. Filtering
        # production by machine or shift while comparing against a whole line's
        # target would understate achievement, so the target is fetched with
        # only the filters that apply to it, and achievement is reported as 0
        # when the comparison would be misleading.
        comparable = filters.machine_id is None and filters.shift_id is None
        target = (
            await self._repository.get_target_quantity(
                start_date=filters.resolved_start,
                end_date=filters.resolved_end,
                component_id=filters.component_id,
                line_id=filters.line_id,
            )
            if comparable
            else 0
        )

        return self.build_summary_from_totals(
            totals, target, filters.resolved_start, filters.resolved_end
        )

    @staticmethod
    def build_summary_from_totals(
        totals: dict[str, Any],
        target: int,
        start: date,
        end: date,
    ) -> ProductionSummary:
        """Assemble a summary from repository totals.

        Shared with the dashboard service, which fetches a single day through a
        different query but needs the identical derivation. Two copies of this
        arithmetic would be two chances for the dashboard and the production
        page to disagree about the same day's efficiency.
        """
        produced = int(totals.get("total_produced") or 0)
        planned = int(totals.get("total_planned") or 0)
        rejected = int(totals.get("total_rejected") or 0)
        record_count = int(totals.get("record_count") or 0)

        return ProductionSummary(
            start_date=start,
            end_date=end,
            total_planned=planned,
            total_produced=produced,
            total_accepted=int(totals.get("total_accepted") or 0),
            total_rejected=rejected,
            target_quantity=target,
            achievement_percentage=kpi.production_achievement(produced, target),
            efficiency_percentage=kpi.production_efficiency(produced, planned),
            defect_rate_percentage=kpi.defect_rate(rejected, produced),
            total_planned_minutes=int(totals.get("total_planned_minutes") or 0),
            total_operating_minutes=int(totals.get("total_operating_minutes") or 0),
            total_downtime_minutes=int(totals.get("total_downtime_minutes") or 0),
            record_count=record_count,
            has_data=record_count > 0,
        )

    async def get_trend(self, filters: ProductionFilters) -> list[ProductionTrendPoint]:
        """Return the daily production trend, cached."""
        key = self._cache.keys.production_trend(
            filters.resolved_start, filters.resolved_end, filters.cache_filters()
        )
        return await self._cache.get_or_set_list(
            key,
            CacheTier.TREND,
            ProductionTrendPoint,
            lambda: self._build_trend(filters),
        )

    async def _build_trend(self, filters: ProductionFilters) -> list[ProductionTrendPoint]:
        rows = await self._repository.get_production_trend(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
            shift_id=filters.shift_id,
            line_id=filters.line_id,
        )
        return [
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
            for row in rows
        ]

    async def get_by_dimension(
        self, filters: ProductionFilters, dimension: str, limit: int = 20
    ) -> list[ProductionByDimension]:
        """Return production grouped by machine, component, line or shift."""
        rows = await self._repository.get_production_by_dimension(
            dimension=dimension,
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
            shift_id=filters.shift_id,
            line_id=filters.line_id,
            limit=limit,
        )
        return [
            ProductionByDimension(
                key_id=row["key_id"],
                key_code=row["key_code"],
                key_name=row["key_name"],
                planned_quantity=int(row["planned_quantity"] or 0),
                produced_quantity=int(row["produced_quantity"] or 0),
                accepted_quantity=int(row["accepted_quantity"] or 0),
                rejected_quantity=int(row["rejected_quantity"] or 0),
                efficiency_percentage=kpi.production_efficiency(
                    row["produced_quantity"], row["planned_quantity"]
                ),
                defect_rate_percentage=kpi.defect_rate(
                    row["rejected_quantity"], row["produced_quantity"]
                ),
            )
            for row in rows
        ]

    @staticmethod
    def _to_record(row: dict[str, Any]) -> ProductionRecord:
        """Map a repository row to the response model.

        Explicit rather than `model_validate(row)`: an added column should not
        silently become part of the API surface.
        """
        return ProductionRecord(
            id=row["id"],
            record_date=row["record_date"],
            machine_id=row["machine_id"],
            machine_code=row["machine_code"],
            machine_name=row["machine_name"],
            component_id=row["component_id"],
            component_code=row["component_code"],
            component_name=row["component_name"],
            line_id=row["line_id"],
            line_code=row["line_code"],
            line_name=row["line_name"],
            shift_id=row["shift_id"],
            shift_code=row["shift_code"],
            shift_name=row["shift_name"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            planned_quantity=int(row["planned_quantity"]),
            produced_quantity=int(row["produced_quantity"]),
            accepted_quantity=int(row["accepted_quantity"]),
            rejected_quantity=int(row["rejected_quantity"]),
            planned_minutes=int(row["planned_minutes"]),
            operating_minutes=int(row["operating_minutes"]),
            downtime_minutes=int(row["downtime_minutes"]),
            efficiency_percentage=kpi.production_efficiency(
                row["produced_quantity"], row["planned_quantity"]
            ),
            defect_rate_percentage=kpi.defect_rate(
                row["rejected_quantity"], row["produced_quantity"]
            ),
        )
