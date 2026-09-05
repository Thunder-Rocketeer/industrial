"""KPI formulas (spec section 43).

Every percentage the application reports is computed here and nowhere else.
Spec section 42 requires that KPI formulas are not duplicated across endpoints;
concentrating them in pure functions also makes them the easiest part of the
system to test, since none of them touch a database or a cache.

THE ZERO-DENOMINATOR DECISION

Every one of these is a ratio, and every ratio has a denominator that can be
zero: a machine that produced nothing, a period with no inspections, a line with
no target set. Three options were available -- raise, return `None`, or return
`0.0`.

Raising is wrong: no data is a normal state for a factory dashboard, not an
error. `None` is the most honest, but it forces every consumer to handle a
nullable number, and a chart cannot plot it.

These functions return `0.0`, **and every summary schema that reports a rate
also reports the counts it was computed from**. That is what lets a caller
distinguish "0% because nothing was produced" from "0% because everything
failed" -- the rate alone cannot express the difference, so the counts travel
with it rather than the rate being made nullable.

ROUNDING

Rounded to two decimal places at the point of calculation. A dashboard showing
92.5% has no use for further precision, and rounding once here means two
endpoints reporting the same KPI cannot disagree in the last digit.
"""

from __future__ import annotations

from decimal import Decimal

#: Percentages are reported to this many decimal places.
PERCENTAGE_PRECISION = 2

#: OEE terms are capped at 100%.
#:
#: Performance is the term that can genuinely exceed it: if a machine produces
#: more units than its ideal cycle time says are possible, the cycle time is
#: wrong, not the machine. Letting that propagate would inflate OEE above 100%
#: and make the metric meaningless. Capping keeps OEE interpretable; the
#: uncapped value is exposed separately so bad reference data stays visible
#: rather than being silently hidden.
MAX_PERCENTAGE = 100.0

Number = int | float | Decimal


def _to_float(value: Number | None) -> float:
    """Coerce a database numeric to float, treating NULL as zero."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def safe_ratio(numerator: Number | None, denominator: Number | None) -> float:
    """Return `numerator / denominator`, or 0.0 when the denominator is zero.

    The single guard every KPI below routes through, so the zero-denominator
    decision is made once rather than re-litigated in each formula.
    """
    denominator_value = _to_float(denominator)
    if denominator_value == 0.0:
        return 0.0
    return _to_float(numerator) / denominator_value


def as_percentage(
    numerator: Number | None,
    denominator: Number | None,
    *,
    cap: float | None = None,
) -> float:
    """Return the ratio as a rounded percentage.

    Args:
        cap: Upper bound, or `None` for uncapped. Used by the OEE terms.
    """
    value = safe_ratio(numerator, denominator) * 100.0
    if cap is not None:
        value = min(value, cap)
    return round(value, PERCENTAGE_PRECISION)


# =============================================================================
# Production
# =============================================================================


def production_achievement(actual: Number | None, planned: Number | None) -> float:
    """Actual production as a percentage of planned.

        actual / planned * 100

    Deliberately uncapped: exceeding target is real information a manager wants
    to see, unlike an OEE term above 100% which only ever indicates bad data.
    """
    return as_percentage(actual, planned)


def production_efficiency(produced: Number | None, planned: Number | None) -> float:
    """Alias of achievement at the run level, kept for naming clarity.

    "Achievement" is used against a management target, "efficiency" against the
    planned quantity for a run. The arithmetic is identical; the two names read
    correctly in their own contexts.
    """
    return as_percentage(produced, planned)


# =============================================================================
# Quality
# =============================================================================


def defect_rate(rejected: Number | None, inspected: Number | None) -> float:
    """Rejected units as a percentage of units inspected.

    rejected / inspected * 100

    Capped at 100%. The database constraint `accepted + rejected = produced`
    means real data cannot exceed it, so the cap only ever fires on data that is
    already inconsistent. It is here because the response schemas declare
    `le=100`: without the cap, an anomaly would fail serialization and return a
    500 instead of a visible -- if surprising -- number, which is a worse way to
    learn that the data is wrong.
    """
    return as_percentage(rejected, inspected, cap=MAX_PERCENTAGE)


def first_pass_yield(first_pass: Number | None, total: Number | None) -> float:
    """Units passing inspection without rework, as a percentage of the total.

        units passing without rework / total units * 100

    Note the denominator is *all* units produced, not units that passed. A part
    that was reworked into an acceptable state did not pass first time, and
    neither did a part that was rejected -- FPY measures how much came out right
    the first time, which is why it is always at or below the pass rate.

    Schema note: `quality_records.first_pass_quantity` is non-zero only on the
    pass line, since a rejected unit never had a first pass to succeed at.
    """
    return as_percentage(first_pass, total)


def quality_rate(good: Number | None, total: Number | None) -> float:
    """Good units as a percentage of total units -- the OEE Quality term.

    good units / total units * 100
    """
    return as_percentage(good, total, cap=MAX_PERCENTAGE)


# =============================================================================
# OEE (spec section 43)
# =============================================================================


def availability(operating_minutes: Number | None, planned_minutes: Number | None) -> float:
    """Operating time as a percentage of planned production time.

        operating time / planned production time * 100

    `planned_minutes` excludes scheduled breaks, so this measures unplanned loss
    -- breakdowns and changeovers -- rather than penalising the plant for not
    running during a scheduled break.
    """
    return as_percentage(operating_minutes, planned_minutes, cap=MAX_PERCENTAGE)


def ideal_output(
    ideal_cycle_time_seconds: Number | None,
    operating_minutes: Number | None,
) -> float:
    """Units the machine could have made in its operating time at rated speed.

    The denominator of the Performance term. Zero when the cycle time is missing
    or zero, which `safe_ratio` then turns into 0% performance rather than a
    division error.
    """
    cycle_time = _to_float(ideal_cycle_time_seconds)
    if cycle_time <= 0:
        return 0.0
    return _to_float(operating_minutes) * 60.0 / cycle_time


def performance(
    produced: Number | None,
    ideal_cycle_time_seconds: Number | None,
    operating_minutes: Number | None,
) -> float:
    """Actual output against ideal output for the operating time.

        produced / (operating_seconds / ideal_cycle_time) * 100

    Capped at 100%. A value above it means the recorded cycle time is shorter
    than reality allows -- a reference-data problem, not a machine outperforming
    physics. `performance_uncapped` exposes the raw figure so the problem stays
    visible.
    """
    return as_percentage(
        produced,
        ideal_output(ideal_cycle_time_seconds, operating_minutes),
        cap=MAX_PERCENTAGE,
    )


def performance_uncapped(
    produced: Number | None,
    ideal_cycle_time_seconds: Number | None,
    operating_minutes: Number | None,
) -> float:
    """Performance without the 100% cap, for detecting bad cycle-time data."""
    return as_percentage(produced, ideal_output(ideal_cycle_time_seconds, operating_minutes))


def oee(availability_pct: float, performance_pct: float, quality_pct: float) -> float:
    """Overall Equipment Effectiveness.

        OEE = Availability x Performance x Quality

    Takes percentages and returns a percentage, so the three terms and the
    result are all in the same units on the dashboard. Each term is expected to
    already be capped; spec section 5.6 requires displaying them separately so a
    user can see *why* OEE moved.
    """
    product = (availability_pct / 100.0) * (performance_pct / 100.0) * (quality_pct / 100.0)
    return round(product * 100.0, PERCENTAGE_PRECISION)


# =============================================================================
# Inventory
# =============================================================================


def stock_utilization(current: Number | None, maximum: Number | None) -> float:
    """Current stock as a percentage of the maximum holding.

    Capped: an overstocked item legitimately exceeds its maximum, but a progress
    bar past 100% reads as a rendering bug rather than as information. The
    OVERSTOCKED status is what communicates the excess.
    """
    return as_percentage(current, maximum, cap=MAX_PERCENTAGE)


def inventory_health(healthy_count: int, total_count: int) -> float:
    """Share of stock lines in a healthy state.

    The dashboard's single "inventory health" KPI. Counts lines rather than
    weighting by value or criticality: one line of a cheap consumable stopping
    production is as damaging as an expensive one, and the alerts panel carries
    the per-item detail.
    """
    return as_percentage(healthy_count, total_count, cap=MAX_PERCENTAGE)


# =============================================================================
# Trends
# =============================================================================


def percentage_change(current: Number | None, previous: Number | None) -> float | None:
    """Change from `previous` to `current`, as a percentage of `previous`.

    Returns `None` -- not 0.0 -- when there is no previous value to compare
    against. This is the one place where the null is worth the inconvenience:
    "no comparison available" and "no change" are different statements, and a
    KPI card showing "0.0% vs yesterday" when yesterday does not exist is a
    factual error rather than a formatting choice.
    """
    previous_value = _to_float(previous)
    if previous_value == 0.0:
        return None
    return round(
        ((_to_float(current) - previous_value) / previous_value) * 100.0, PERCENTAGE_PRECISION
    )
