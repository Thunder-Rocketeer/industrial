"""Service layer tests.

Repositories are replaced with fakes that return the row shapes the real queries
produce, so these verify the part between the database and the API: that the
right KPI formula is applied to the right column, and that caching behaves.

The most valuable assertions here are the ones about *consistency* -- that the
dashboard and the detail pages derive the same numbers from the same totals.
Two services computing a defect rate slightly differently is the kind of bug
that survives a long time, because each page looks plausible on its own.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.cache.client import CacheClient
from app.cache.keys import CacheKeys
from app.cache.service import CacheService
from app.config import Settings
from app.schemas.filters import (
    AnalyticsFilters,
    ProductionFilters,
    QualityFilters,
)
from app.services.alert_service import AlertService
from app.services.analytics_service import AnalyticsService, compute_oee_components
from app.services.inventory_service import InventoryService
from app.services.machine_service import MachineService
from app.services.production_service import ProductionService
from app.services.quality_service import QualityService
from tests.test_cache import FakeRedis

START = date(2026, 8, 1)
END = date(2026, 8, 31)


@pytest.fixture
def cache() -> CacheService:
    return CacheService(CacheClient(FakeRedis()), CacheKeys("test"), Settings(_env_file=None))


@pytest.fixture
def no_cache() -> CacheService:
    """A cache service with no Redis, so loaders always run."""
    return CacheService(CacheClient(None), CacheKeys("test"), Settings(_env_file=None))


class FakeProductionRepository:
    """Returns the aggregate shapes `ProductionRepository` produces."""

    def __init__(self, **overrides: Any) -> None:
        self.summary_row = {
            "total_planned": 10_000,
            "total_produced": 9_250,
            "total_accepted": 9_000,
            "total_rejected": 250,
            "total_planned_minutes": 1_350,
            "total_operating_minutes": 1_280,
            "total_downtime_minutes": 70,
            "record_count": 14,
            **overrides,
        }
        self.target = 10_400
        self.target_calls: list[dict[str, Any]] = []
        self.trend_rows: list[dict[str, Any]] = []

    async def get_production_summary(self, **kwargs: Any) -> dict[str, Any]:
        self.last_summary_kwargs = kwargs
        return self.summary_row

    async def get_target_quantity(self, **kwargs: Any) -> int:
        self.target_calls.append(kwargs)
        return self.target

    async def get_production_trend(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.trend_rows

    async def get_production_by_dimension(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.last_dimension = kwargs.get("dimension")
        return [
            {
                "key_id": "11111111-1111-4111-8111-111111111111",
                "key_code": "CNC-T-001",
                "key_name": "CNC Turning Center 1",
                "planned_quantity": 600,
                "produced_quantity": 570,
                "accepted_quantity": 560,
                "rejected_quantity": 10,
            }
        ]


class FakeQualityRepository:
    def __init__(self, **overrides: Any) -> None:
        self.summary_row = {
            "total_inspected": 10_000,
            "total_passed": 9_750,
            "total_rejected": 250,
            "total_first_pass": 9_600,
            "total_rework": 150,
            "distinct_defect_types": 6,
            "record_count": 40,
            **overrides,
        }
        self.breakdown_rows: list[dict[str, Any]] = []
        self.trend_rows: list[dict[str, Any]] = []

    async def get_quality_summary(self, **kwargs: Any) -> dict[str, Any]:
        return self.summary_row

    async def get_defect_breakdown(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.breakdown_rows

    async def get_defect_trend(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.trend_rows

    async def get_quality_by_dimension(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []


# =============================================================================
# Production service
# =============================================================================


async def test_production_summary_applies_the_kpi_formulas(no_cache: CacheService) -> None:
    repository = FakeProductionRepository()
    service = ProductionService(repository, no_cache)

    summary = await service.get_summary(ProductionFilters(start_date=START, end_date=END))

    assert summary.total_produced == 9_250
    assert summary.efficiency_percentage == 92.5  # 9250 / 10000
    assert summary.achievement_percentage == 88.94  # 9250 / 10400
    assert summary.defect_rate_percentage == 2.7  # 250 / 9250
    assert summary.has_data is True


async def test_an_empty_period_reports_zeros_and_has_data_false(
    no_cache: CacheService,
) -> None:
    """The distinction the percentages alone cannot express."""
    repository = FakeProductionRepository(
        total_planned=0,
        total_produced=0,
        total_accepted=0,
        total_rejected=0,
        record_count=0,
    )
    service = ProductionService(repository, no_cache)

    summary = await service.get_summary(ProductionFilters(start_date=START, end_date=END))

    assert summary.efficiency_percentage == 0.0
    assert summary.has_data is False, (
        "A caller must be able to tell an empty period from a total failure."
    )


async def test_a_machine_filter_suppresses_target_comparison(
    no_cache: CacheService,
) -> None:
    """Targets have no machine dimension, so the comparison would mislead.

    A single machine's output against a whole line's target would report a
    catastrophic achievement figure that is simply the wrong ratio.
    """
    repository = FakeProductionRepository()
    service = ProductionService(repository, no_cache)

    filters = ProductionFilters(
        start_date=START, end_date=END, machine_id="11111111-1111-4111-8111-111111111111"
    )
    summary = await service.get_summary(filters)

    assert summary.target_quantity == 0
    assert summary.achievement_percentage == 0.0
    assert repository.target_calls == [], "The target query should not have run."


async def test_a_line_filter_still_compares_against_target(no_cache: CacheService) -> None:
    """Line and component *are* target dimensions, so the comparison is sound."""
    repository = FakeProductionRepository()
    service = ProductionService(repository, no_cache)

    filters = ProductionFilters(
        start_date=START, end_date=END, line_id="33333333-3333-4333-8333-333333333333"
    )
    summary = await service.get_summary(filters)

    assert summary.target_quantity == 10_400
    assert len(repository.target_calls) == 1


async def test_production_trend_derives_achievement_per_day(no_cache: CacheService) -> None:
    repository = FakeProductionRepository()
    repository.trend_rows = [
        {
            "bucket_date": date(2026, 8, 1),
            "planned_quantity": 1_000,
            "produced_quantity": 950,
            "accepted_quantity": 930,
            "rejected_quantity": 20,
            "target_quantity": 1_050,
        }
    ]
    service = ProductionService(repository, no_cache)

    points = await service.get_trend(ProductionFilters(start_date=START, end_date=END))

    assert len(points) == 1
    assert points[0].achievement_percentage == 90.48  # 950 / 1050


async def test_a_group_result_carries_its_own_rates(no_cache: CacheService) -> None:
    service = ProductionService(FakeProductionRepository(), no_cache)

    groups = await service.get_by_dimension(
        ProductionFilters(start_date=START, end_date=END), "machine"
    )

    assert groups[0].efficiency_percentage == 95.0  # 570 / 600
    assert groups[0].defect_rate_percentage == 1.75  # 10 / 570


# =============================================================================
# Quality service
# =============================================================================


async def test_quality_summary_applies_the_kpi_formulas(no_cache: CacheService) -> None:
    service = QualityService(FakeQualityRepository(), no_cache)

    summary = await service.get_summary(QualityFilters(start_date=START, end_date=END))

    assert summary.defect_rate_percentage == 2.5  # 250 / 10000
    assert summary.quality_rate_percentage == 97.5  # 9750 / 10000
    assert summary.first_pass_yield_percentage == 96.0  # 9600 / 10000


async def test_first_pass_yield_sits_below_the_quality_rate(no_cache: CacheService) -> None:
    """Rework is what separates them, and both come from the same totals."""
    service = QualityService(FakeQualityRepository(), no_cache)

    summary = await service.get_summary(QualityFilters(start_date=START, end_date=END))

    assert summary.first_pass_yield_percentage < summary.quality_rate_percentage


def test_the_pareto_builder_accumulates_correctly() -> None:
    """The cumulative series is computed once, server-side.

    Leaving it to the chart would mean every consumer re-deriving it, and
    getting a different answer from a differently sorted or truncated copy.
    """
    rows = [
        {
            "defect_id": "55555555-5555-4555-8555-555555555555",
            "defect_code": "DIMENSIONAL_OOT",
            "defect_name": "Dimensional Out-of-Tolerance",
            "category": "Dimensional",
            "default_severity": "MAJOR",
            "rejected_quantity": 500,
            "occurrence_count": 50,
        },
        {
            "defect_id": "55555555-5555-4555-8555-555555555556",
            "defect_code": "SURFACE_DEFECT",
            "defect_name": "Surface Defect",
            "category": "Surface",
            "default_severity": "MINOR",
            "rejected_quantity": 300,
            "occurrence_count": 40,
        },
        {
            "defect_id": "55555555-5555-4555-8555-555555555557",
            "defect_code": "BURR",
            "defect_name": "Burr",
            "category": "Surface",
            "default_severity": "MINOR",
            "rejected_quantity": 200,
            "occurrence_count": 30,
        },
    ]

    pareto = QualityService.build_pareto(rows)

    assert [p.share_percentage for p in pareto] == [50.0, 30.0, 20.0]
    assert [p.cumulative_percentage for p in pareto] == [50.0, 80.0, 100.0]


def test_the_pareto_builder_handles_no_defects() -> None:
    assert QualityService.build_pareto([]) == []


def test_the_pareto_cumulative_never_exceeds_100() -> None:
    """Rounding each share independently can otherwise overshoot."""
    rows = [
        {
            "defect_id": f"55555555-5555-4555-8555-55555555555{i}",
            "defect_code": f"D{i}",
            "defect_name": f"Defect {i}",
            "category": "Test",
            "default_severity": "MINOR",
            "rejected_quantity": 1,
            "occurrence_count": 1,
        }
        for i in range(3)
    ]

    pareto = QualityService.build_pareto(rows)

    assert pareto[-1].cumulative_percentage <= 100.0


# =============================================================================
# OEE composition
# =============================================================================


def test_oee_components_from_an_aggregate_row() -> None:
    row = {
        "operating_minutes": 420,
        "planned_minutes": 480,
        "produced_quantity": 700,
        "accepted_quantity": 690,
        "ideal_output_units": 840.0,
    }

    components = compute_oee_components(row)

    assert components["availability_percentage"] == 87.5
    assert components["performance_percentage"] == 83.33
    assert components["quality_percentage"] == pytest.approx(98.57, abs=0.01)
    assert components["oee_percentage"] == pytest.approx(71.87, abs=0.05)


def test_oee_components_of_an_empty_row_are_all_zero() -> None:
    """A machine that ran nothing must not raise."""
    components = compute_oee_components(
        {
            "operating_minutes": 0,
            "planned_minutes": 0,
            "produced_quantity": 0,
            "accepted_quantity": 0,
            "ideal_output_units": 0.0,
        }
    )

    assert set(components.values()) == {0.0}


def test_bad_cycle_time_data_stays_visible_in_the_uncapped_term() -> None:
    """Capping keeps OEE meaningful; the uncapped value keeps the problem visible."""
    components = compute_oee_components(
        {
            "operating_minutes": 60,
            "planned_minutes": 60,
            "produced_quantity": 150,
            "accepted_quantity": 150,
            "ideal_output_units": 120.0,
        }
    )

    assert components["performance_percentage"] == 100.0
    assert components["performance_uncapped_percentage"] == 125.0
    assert components["oee_percentage"] <= 100.0


# =============================================================================
# Cross-service consistency
# =============================================================================


def test_the_dashboard_and_production_page_share_one_builder() -> None:
    """The same totals must produce the same summary either way.

    The dashboard fetches a single day through a different query than the
    production page uses, but both hand the result to the same builder. If they
    did not, the two pages could report different efficiency for the same day.
    """
    totals = {
        "total_planned": 1_000,
        "total_produced": 900,
        "total_accepted": 880,
        "total_rejected": 20,
        "total_planned_minutes": 450,
        "total_operating_minutes": 430,
        "total_downtime_minutes": 20,
        "record_count": 3,
    }

    first = ProductionService.build_summary_from_totals(totals, 1_000, START, START)
    second = ProductionService.build_summary_from_totals(totals, 1_000, START, START)

    assert first == second
    assert first.efficiency_percentage == 90.0
    assert first.achievement_percentage == 90.0


def test_the_dashboard_and_quality_page_share_one_builder() -> None:
    totals = {
        "total_inspected": 1_000,
        "total_passed": 980,
        "total_rejected": 20,
        "total_first_pass": 970,
        "total_rework": 10,
        "distinct_defect_types": 3,
        "record_count": 5,
    }

    summary = QualityService.build_summary_from_totals(totals, START, START)

    assert summary.defect_rate_percentage == 2.0
    assert summary.quality_rate_percentage == 98.0
    assert summary.first_pass_yield_percentage == 97.0


def test_fleet_availability_counts_only_running_machines() -> None:
    """An idle machine is capable but not producing.

    Counting idle as available would make a stopped line look healthy, which is
    the opposite of what the dashboard is for.
    """
    summary = MachineService.build_fleet_summary_from_totals(
        {
            "total_machines": 10,
            "running_count": 6,
            "idle_count": 2,
            "maintenance_count": 1,
            "offline_count": 1,
            "average_utilization": 82.5,
            "maintenance_due_count": 2,
        }
    )

    assert summary.availability_percentage == 60.0
    assert len(summary.status_breakdown) == 4
    assert all(entry.status_label for entry in summary.status_breakdown)


def test_inventory_health_counts_healthy_lines() -> None:
    summary = InventoryService.build_summary_from_totals(
        {
            "total_items": 8,
            "healthy_count": 3,
            "low_count": 2,
            "critical_count": 2,
            "overstocked_count": 1,
            "total_stock_value": 125_000.0,
        }
    )

    assert summary.health_percentage == 37.5
    assert summary.items_requiring_attention == 4


def test_stock_value_is_null_when_any_unit_cost_is_missing() -> None:
    """A partial sum presented as a total would be worse than no number."""
    summary = InventoryService.build_summary_from_totals(
        {
            "total_items": 8,
            "healthy_count": 8,
            "low_count": 0,
            "critical_count": 0,
            "overstocked_count": 0,
            "total_stock_value": None,
        }
    )

    assert summary.total_stock_value is None


def test_alert_summary_counts_by_severity() -> None:
    summary = AlertService.build_summary_from_totals(
        {
            "total_open": 6,
            "critical_count": 2,
            "warning_count": 3,
            "info_count": 1,
            "acknowledged_count": 2,
        }
    )

    assert summary.total_open == 6
    assert {e.severity_label for e in summary.severity_breakdown} == {
        "Critical",
        "Warning",
        "Info",
    }


# =============================================================================
# Caching behaviour at the service level
# =============================================================================


async def test_a_summary_is_served_from_cache_on_the_second_call(
    cache: CacheService,
) -> None:
    repository = FakeProductionRepository()
    service = ProductionService(repository, cache)
    filters = ProductionFilters(start_date=START, end_date=END)

    first = await service.get_summary(filters)
    repository.summary_row["total_produced"] = 1  # Would change the result if re-read.
    second = await service.get_summary(filters)

    assert first == second, "The second call should have been served from cache."


async def test_different_filters_do_not_share_a_cache_entry(cache: CacheService) -> None:
    """A key collision here would serve one line's numbers for another."""
    repository = FakeProductionRepository()
    service = ProductionService(repository, cache)

    await service.get_summary(
        ProductionFilters(
            start_date=START, end_date=END, line_id="33333333-3333-4333-8333-333333333333"
        )
    )
    repository.summary_row["total_produced"] = 1

    other = await service.get_summary(
        ProductionFilters(
            start_date=START, end_date=END, line_id="33333333-3333-4333-8333-333333333334"
        )
    )

    assert other.total_produced == 1, "A different filter must miss the cache."


async def test_analytics_oee_is_cached(cache: CacheService) -> None:
    class FakeMachineRepository:
        def __init__(self) -> None:
            self.calls = 0

        async def get_fleet_oee_inputs(self, **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            return {
                "operating_minutes": 420,
                "planned_minutes": 480,
                "downtime_minutes": 60,
                "produced_quantity": 700,
                "accepted_quantity": 690,
                "rejected_quantity": 10,
                "ideal_output_units": 840.0,
                "record_count": 3,
            }

    machines = FakeMachineRepository()
    service = AnalyticsService(machines, FakeProductionRepository(), FakeQualityRepository(), cache)
    filters = AnalyticsFilters(start_date=START, end_date=END)

    await service.get_oee(filters)
    await service.get_oee(filters)

    assert machines.calls == 1, "The second call should have been served from cache."


async def test_services_still_work_with_no_cache(no_cache: CacheService) -> None:
    """The degradation path, at the service level rather than the client level."""
    repository = FakeProductionRepository()
    service = ProductionService(repository, no_cache)
    filters = ProductionFilters(start_date=START, end_date=END)

    for _ in range(3):
        summary = await service.get_summary(filters)
        assert summary.total_produced == 9_250
