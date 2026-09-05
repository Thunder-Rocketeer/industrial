"""Tests for the KPI formulas (spec section 43).

Pure functions with no I/O, so these are the cheapest and most valuable tests in
the suite: every percentage the dashboard reports is computed by one of them.

The zero-denominator cases get as much attention as the happy paths. A factory
dashboard spends a lot of its time looking at periods where something did not
happen -- a machine that ran nothing, a day with no inspections -- and a division
error there would break the whole page rather than one number.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services import kpi

# =============================================================================
# safe_ratio and as_percentage
# =============================================================================


def test_safe_ratio_divides() -> None:
    assert kpi.safe_ratio(1, 4) == 0.25


@pytest.mark.parametrize("denominator", [0, 0.0, None, Decimal("0")])
def test_safe_ratio_returns_zero_for_a_zero_denominator(denominator: object) -> None:
    """No data is a normal state, not an error."""
    assert kpi.safe_ratio(10, denominator) == 0.0


def test_safe_ratio_treats_a_null_numerator_as_zero() -> None:
    """A SQL aggregate over no rows returns NULL, not 0."""
    assert kpi.safe_ratio(None, 10) == 0.0


def test_safe_ratio_accepts_decimals() -> None:
    """psycopg returns NUMERIC columns as Decimal."""
    assert kpi.safe_ratio(Decimal("3"), Decimal("4")) == 0.75


def test_as_percentage_rounds_to_two_places() -> None:
    assert kpi.as_percentage(1, 3) == 33.33


def test_as_percentage_applies_the_cap() -> None:
    assert kpi.as_percentage(150, 100, cap=100.0) == 100.0


def test_as_percentage_is_uncapped_by_default() -> None:
    assert kpi.as_percentage(150, 100) == 150.0


# =============================================================================
# Production
# =============================================================================


def test_production_achievement() -> None:
    """actual / planned * 100."""
    assert kpi.production_achievement(9_250, 10_000) == 92.5


def test_production_achievement_is_uncapped() -> None:
    """Beating the target is real information, not a data error.

    Unlike an OEE term above 100%, exceeding a management target is a fact a
    manager wants to see.
    """
    assert kpi.production_achievement(11_000, 10_000) == 110.0


def test_production_achievement_with_no_target() -> None:
    assert kpi.production_achievement(500, 0) == 0.0


def test_production_efficiency() -> None:
    assert kpi.production_efficiency(450, 500) == 90.0


# =============================================================================
# Quality
# =============================================================================


def test_defect_rate() -> None:
    """rejected / inspected * 100."""
    assert kpi.defect_rate(25, 1_000) == 2.5


def test_defect_rate_with_nothing_inspected() -> None:
    assert kpi.defect_rate(0, 0) == 0.0


def test_first_pass_yield() -> None:
    """Units passing without rework, over all units."""
    assert kpi.first_pass_yield(940, 1_000) == 94.0


def test_first_pass_yield_is_at_or_below_the_quality_rate() -> None:
    """FPY counts only units right first time, so rework pulls it below quality.

    1000 units: 950 passed, 50 rejected, and 30 of the passes needed rework.
    Quality is 95%, but only 920 were right first time, so FPY is 92%.
    """
    inspected, passed, first_pass = 1_000, 950, 920

    quality = kpi.quality_rate(passed, inspected)
    fpy = kpi.first_pass_yield(first_pass, inspected)

    assert quality == 95.0
    assert fpy == 92.0
    assert fpy < quality


def test_quality_rate_is_capped() -> None:
    assert kpi.quality_rate(120, 100) == 100.0


# =============================================================================
# OEE
# =============================================================================


def test_availability() -> None:
    """operating time / planned production time * 100."""
    assert kpi.availability(408, 480) == 85.0


def test_availability_is_capped() -> None:
    """A machine cannot operate longer than it was scheduled to."""
    assert kpi.availability(500, 480) == 100.0


def test_availability_with_no_planned_time() -> None:
    assert kpi.availability(0, 0) == 0.0


def test_ideal_output_converts_cycle_time_to_units() -> None:
    """60 minutes at a 30-second cycle is 120 units."""
    assert kpi.ideal_output(30.0, 60) == 120.0


def test_ideal_output_is_zero_without_a_cycle_time() -> None:
    """Missing reference data must not raise; it yields 0% performance."""
    assert kpi.ideal_output(0, 60) == 0.0
    assert kpi.ideal_output(None, 60) == 0.0


def test_performance() -> None:
    """100 units against an ideal of 120 is 83.33%."""
    assert kpi.performance(100, 30.0, 60) == 83.33


def test_performance_is_capped_at_100() -> None:
    """Beating the ideal cycle time means the cycle time is wrong.

    Letting it through would push OEE above 100% and make the metric
    meaningless, so the term is capped.
    """
    assert kpi.performance(150, 30.0, 60) == 100.0


def test_performance_uncapped_exposes_bad_reference_data() -> None:
    """The uncapped value keeps a cycle-time problem visible rather than hidden."""
    assert kpi.performance_uncapped(150, 30.0, 60) == 125.0


def test_oee_multiplies_its_three_terms() -> None:
    """OEE = Availability x Performance x Quality.

    0.90 x 0.95 x 0.99 is 84.645, which rounds to 84.64 rather than 84.65:
    the nearest float to 84.645 sits fractionally below the midpoint. Asserted
    exactly so that a change to the rounding strategy shows up as a failure
    here rather than as a drifting number on the dashboard.
    """
    assert kpi.oee(90.0, 95.0, 99.0) == 84.64


def test_oee_is_zero_when_any_term_is_zero() -> None:
    """A machine that never ran has no effectiveness, whatever its quality."""
    assert kpi.oee(0.0, 95.0, 99.0) == 0.0


def test_oee_of_a_perfect_period_is_100() -> None:
    assert kpi.oee(100.0, 100.0, 100.0) == 100.0


def test_oee_end_to_end_from_raw_inputs() -> None:
    """The full chain from production figures to an OEE percentage.

    A shift of 480 planned minutes, 60 lost to breakdown, producing 700 units of
    a part with a 30-second ideal cycle, of which 690 were good.
    """
    planned_minutes, operating_minutes = 480, 420
    produced, accepted = 700, 690
    cycle_seconds = 30.0

    availability = kpi.availability(operating_minutes, planned_minutes)
    performance = kpi.performance(produced, cycle_seconds, operating_minutes)
    quality = kpi.quality_rate(accepted, produced)
    result = kpi.oee(availability, performance, quality)

    assert availability == 87.5  # 420 / 480
    assert performance == 83.33  # 700 / 840 ideal units
    assert quality == pytest.approx(98.57, abs=0.01)
    assert result == pytest.approx(71.87, abs=0.05)


# =============================================================================
# Inventory
# =============================================================================


def test_stock_utilization() -> None:
    assert kpi.stock_utilization(250, 1_000) == 25.0


def test_stock_utilization_is_capped() -> None:
    """An overstocked line exceeds its maximum; a bar past 100% reads as a bug."""
    assert kpi.stock_utilization(1_500, 1_000) == 100.0


def test_inventory_health() -> None:
    assert kpi.inventory_health(6, 8) == 75.0


def test_inventory_health_with_no_items() -> None:
    assert kpi.inventory_health(0, 0) == 0.0


# =============================================================================
# Trend comparison
# =============================================================================


def test_percentage_change() -> None:
    assert kpi.percentage_change(110, 100) == 10.0


def test_percentage_change_can_be_negative() -> None:
    assert kpi.percentage_change(90, 100) == -10.0


def test_percentage_change_returns_none_without_a_previous_value() -> None:
    """ "No comparison available" and "no change" are different statements.

    This is the one KPI that returns None rather than 0.0: a card reading
    "0.0% vs yesterday" when yesterday has no data is factually wrong, and the
    frontend needs to be able to omit the comparison entirely.
    """
    assert kpi.percentage_change(100, 0) is None
    assert kpi.percentage_change(100, None) is None


def test_percentage_change_of_a_flat_period_is_zero() -> None:
    assert kpi.percentage_change(100, 100) == 0.0
