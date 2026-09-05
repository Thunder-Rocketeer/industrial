"""Quality business logic."""

from __future__ import annotations

from typing import Any

from app.cache.service import CacheService, CacheTier
from app.repositories.quality import QualityRepository
from app.schemas.filters import QualityFilters, QualityListFilters
from app.schemas.quality import (
    DefectSummary,
    DefectTrendPoint,
    QualityByDimension,
    QualityRecord,
    QualitySummary,
)
from app.services import kpi


class QualityService:
    """Quality reads, with KPI derivation and caching."""

    def __init__(self, repository: QualityRepository, cache: CacheService) -> None:
        self._repository = repository
        self._cache = cache

    async def list_records(self, filters: QualityListFilters) -> tuple[list[QualityRecord], int]:
        """Return one page of inspection lines. Uncached, like every list."""
        rows, total = await self._repository.get_quality_records(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
            defect_id=filters.defect_id,
            rejections_only=filters.rejections_only,
            limit=filters.limit,
            offset=filters.offset,
            sort_by=filters.sort_by,
            sort_dir=filters.sort_dir,
        )
        return [self._to_record(row) for row in rows], total

    async def get_summary(self, filters: QualityFilters) -> QualitySummary:
        """Return aggregate quality for the filtered period, cached."""
        key = self._cache.keys.quality_summary(
            filters.resolved_start, filters.resolved_end, filters.cache_filters()
        )
        return await self._cache.get_or_set(
            key, CacheTier.TREND, QualitySummary, lambda: self._build_summary(filters)
        )

    async def _build_summary(self, filters: QualityFilters) -> QualitySummary:
        totals = await self._repository.get_quality_summary(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
            defect_id=filters.defect_id,
        )
        return self.build_summary_from_totals(totals, filters.resolved_start, filters.resolved_end)

    @staticmethod
    def build_summary_from_totals(totals: dict[str, Any], start, end) -> QualitySummary:
        """Assemble a summary from repository totals.

        Shared with the dashboard service, which fetches a single day's totals
        through a different query but needs the identical derivation. Two copies
        of this arithmetic would be two chances for the dashboard and the
        quality page to report different defect rates for the same day.
        """
        inspected = int(totals.get("total_inspected") or 0)
        rejected = int(totals.get("total_rejected") or 0)
        passed = int(totals.get("total_passed") or 0)
        first_pass = int(totals.get("total_first_pass") or 0)
        record_count = int(totals.get("record_count") or 0)

        return QualitySummary(
            start_date=start,
            end_date=end,
            total_inspected=inspected,
            total_passed=passed,
            total_rejected=rejected,
            total_first_pass=first_pass,
            total_rework=int(totals.get("total_rework") or 0),
            defect_rate_percentage=kpi.defect_rate(rejected, inspected),
            first_pass_yield_percentage=kpi.first_pass_yield(first_pass, inspected),
            quality_rate_percentage=kpi.quality_rate(passed, inspected),
            distinct_defect_types=int(totals.get("distinct_defect_types") or 0),
            record_count=record_count,
            has_data=record_count > 0,
        )

    async def get_defect_breakdown(
        self, filters: QualityFilters, limit: int = 20
    ) -> list[DefectSummary]:
        """Return the Pareto-ordered defect breakdown, cached."""
        key = self._cache.keys.defect_breakdown(
            filters.resolved_start, filters.resolved_end, filters.cache_filters()
        )
        return await self._cache.get_or_set_list(
            key,
            CacheTier.TREND,
            DefectSummary,
            lambda: self._build_defect_breakdown(filters, limit),
        )

    async def _build_defect_breakdown(
        self, filters: QualityFilters, limit: int
    ) -> list[DefectSummary]:
        rows = await self._repository.get_defect_breakdown(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
            limit=limit,
        )
        return self.build_pareto(rows)

    @staticmethod
    def build_pareto(rows: list[dict[str, Any]]) -> list[DefectSummary]:
        """Turn defect totals into a Pareto series.

        The cumulative percentage is computed here, once, over the descending
        order the query returned. Leaving it to the chart would mean every
        component that renders this data re-deriving it -- and getting a
        different answer if it sorted differently or received a truncated list.
        """
        total_rejected = sum(int(row["rejected_quantity"] or 0) for row in rows)

        summaries: list[DefectSummary] = []
        cumulative = 0.0
        for row in rows:
            rejected = int(row["rejected_quantity"] or 0)
            share = kpi.as_percentage(rejected, total_rejected)
            cumulative = min(100.0, round(cumulative + share, kpi.PERCENTAGE_PRECISION))
            summaries.append(
                DefectSummary(
                    defect_id=row["defect_id"],
                    defect_code=row["defect_code"],
                    defect_name=row["defect_name"],
                    category=row["category"],
                    default_severity=row["default_severity"],
                    rejected_quantity=rejected,
                    occurrence_count=int(row["occurrence_count"] or 0),
                    share_percentage=share,
                    cumulative_percentage=cumulative,
                )
            )
        return summaries

    async def get_defect_trend(self, filters: QualityFilters) -> list[DefectTrendPoint]:
        """Return the daily defect rate, cached."""
        key = self._cache.keys.analytics_defects(
            filters.resolved_start, filters.resolved_end, filters.cache_filters()
        )
        return await self._cache.get_or_set_list(
            key,
            CacheTier.TREND,
            DefectTrendPoint,
            lambda: self._build_defect_trend(filters),
        )

    async def _build_defect_trend(self, filters: QualityFilters) -> list[DefectTrendPoint]:
        rows = await self._repository.get_defect_trend(
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            machine_id=filters.machine_id,
            component_id=filters.component_id,
            defect_id=filters.defect_id,
        )
        return [
            DefectTrendPoint(
                bucket_date=row["bucket_date"],
                inspected_quantity=int(row["inspected_quantity"] or 0),
                rejected_quantity=int(row["rejected_quantity"] or 0),
                defect_rate_percentage=kpi.defect_rate(
                    row["rejected_quantity"], row["inspected_quantity"]
                ),
            )
            for row in rows
        ]

    async def get_by_dimension(
        self, filters: QualityFilters, dimension: str, limit: int = 20
    ) -> list[QualityByDimension]:
        """Return rejection rates grouped by machine or component."""
        rows = await self._repository.get_quality_by_dimension(
            dimension=dimension,
            start_date=filters.resolved_start,
            end_date=filters.resolved_end,
            limit=limit,
        )
        return [
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
            for row in rows
        ]

    @staticmethod
    def _to_record(row: dict[str, Any]) -> QualityRecord:
        return QualityRecord(
            id=row["id"],
            production_record_id=row["production_record_id"],
            inspected_at=row["inspected_at"],
            machine_id=row["machine_id"],
            machine_code=row["machine_code"],
            component_id=row["component_id"],
            component_code=row["component_code"],
            component_name=row["component_name"],
            defect_id=row["defect_id"],
            defect_code=row["defect_code"],
            defect_name=row["defect_name"],
            severity=row["severity"],
            inspected_quantity=int(row["inspected_quantity"]),
            passed_quantity=int(row["passed_quantity"]),
            rejected_quantity=int(row["rejected_quantity"]),
            first_pass_quantity=int(row["first_pass_quantity"]),
            rework_quantity=int(row["rework_quantity"]),
            # Derived rather than stored: the schema's two row shapes make
            # "is this a rejection line" a property of defect_id, and computing
            # it here keeps that rule out of the frontend.
            is_rejection=row["defect_id"] is not None,
        )
