"""Repository tests against a live database.

Skipped unless `DATABASE_URL` points at a migrated and seeded database, so a
normal `pytest` run needs no external service (spec section 22). To run them:

    cd server
    # 1. apply supabase/schema.sql to your Supabase project
    python -m app.db.seed
    python -m app.db.verify
    pytest -m integration

These are the tests the unit suite cannot replace. Everything else in the suite
proves the SQL is valid PostgreSQL and that the Python around it behaves; only
these prove the queries return what the schema actually holds -- that a column
exists, that a join does not fan out, and that an aggregate reconciles with the
rows underneath it.

They are read-only. Nothing here writes, so they can be run against a seeded
development database repeatedly without changing it.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
import pytest_asyncio

from app.config import Settings
from app.db.pool import DatabasePool
from app.repositories.alerts import AlertRepository
from app.repositories.base import SortDirection, UnknownSortFieldError
from app.repositories.inventory import InventoryRepository
from app.repositories.machines import MachineRepository
from app.repositories.maintenance import MaintenanceRepository
from app.repositories.production import ProductionRepository
from app.repositories.quality import QualityRepository

pytestmark = [
    pytest.mark.integration,
    # Every async test in this module runs on the module-scoped loop that the
    # `pool` fixture lives on. Without this they each get a fresh loop and the
    # module-scoped pool is a ScopeMismatch.
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL", "").strip(),
        reason="DATABASE_URL is not set; see this module's docstring to run these.",
    ),
]

#: Payloads fed through the real query path, to prove they stay values.
INJECTION_PAYLOADS = ["' OR '1'='1", "'; DROP TABLE production_records; --"]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def pool():
    """Open a pool against the configured database for the module.

    `loop_scope="module"` is not optional. pytest-asyncio runs each test on a
    function-scoped event loop by default, and a module-scoped async fixture
    asking for that loop is a `ScopeMismatch` -- every test in the module errors
    at setup. The pool has to be module-scoped (opening one per test would mean
    a fresh connection to Supabase for each) so the loop must be widened to
    match it rather than the other way round.

    This surfaced the first time the module actually ran, in Phase 7. Until a
    real `DATABASE_URL` was reachable every test here skipped, and a skipped
    test cannot report a broken fixture.
    """
    settings = Settings()
    database_pool = DatabasePool(settings)
    await database_pool.open()
    yield database_pool
    await database_pool.close()


@pytest_asyncio.fixture(loop_scope="module")
async def connection(pool):
    async with pool.connection() as conn:
        yield conn


@pytest_asyncio.fixture(loop_scope="module")
async def window(connection) -> tuple[date, date]:
    """A date range that actually contains data.

    Anchored to the latest seeded production date rather than to today, so the
    tests keep working however long after seeding they are run.
    """
    latest = await ProductionRepository(connection).get_latest_production_date()
    if latest is None:
        pytest.skip("The database has no production records; run `python -m app.db.seed`.")
    return latest - timedelta(days=29), latest


# =============================================================================
# Production
# =============================================================================


async def test_production_records_are_returned(connection, window) -> None:
    start, end = window
    rows, total = await ProductionRepository(connection).get_production_records(
        start_date=start, end_date=end, limit=10, offset=0
    )

    assert rows, "The seeded database should contain production in the last 30 days."
    assert total >= len(rows)

    row = rows[0]
    # Every column the response model needs must be present. A missing key here
    # is the failure mode the unit tests cannot detect.
    for column in (
        "id",
        "record_date",
        "machine_id",
        "machine_code",
        "machine_name",
        "component_id",
        "component_code",
        "component_name",
        "line_id",
        "line_code",
        "line_name",
        "shift_id",
        "shift_code",
        "shift_name",
        "started_at",
        "ended_at",
        "planned_quantity",
        "produced_quantity",
        "accepted_quantity",
        "rejected_quantity",
        "planned_minutes",
        "operating_minutes",
        "downtime_minutes",
    ):
        assert column in row, f"The production query does not select {column}."


async def test_production_quantities_balance(connection, window) -> None:
    """The database CHECK constraint, observed through the query."""
    start, end = window
    rows, _ = await ProductionRepository(connection).get_production_records(
        start_date=start, end_date=end, limit=100, offset=0
    )

    for row in rows:
        assert row["accepted_quantity"] + row["rejected_quantity"] == row["produced_quantity"]


async def test_the_production_summary_matches_the_rows(connection, window) -> None:
    """An aggregate must equal the sum of what the detail query returns.

    This is the assertion that catches a join fanning out: a duplicated row
    inflates the aggregate while the detail list still looks correct.
    """
    start, end = window
    repository = ProductionRepository(connection)

    summary = await repository.get_production_summary(start_date=start, end_date=end)
    rows, total = await repository.get_production_records(
        start_date=start, end_date=end, limit=10_000, offset=0
    )

    assert summary["record_count"] == total
    assert summary["total_produced"] == sum(r["produced_quantity"] for r in rows)


async def test_pagination_returns_distinct_pages(connection, window) -> None:
    start, end = window
    repository = ProductionRepository(connection)

    first, _ = await repository.get_production_records(
        start_date=start, end_date=end, limit=5, offset=0
    )
    second, _ = await repository.get_production_records(
        start_date=start, end_date=end, limit=5, offset=5
    )

    assert {r["id"] for r in first}.isdisjoint({r["id"] for r in second})


async def test_every_allow_listed_sort_works(connection, window) -> None:
    """A mapping entry pointing at a non-existent column would fail here."""
    from app.repositories.production import PRODUCTION_SORTS

    start, end = window
    repository = ProductionRepository(connection)

    for field in PRODUCTION_SORTS.allowed:
        rows, _ = await repository.get_production_records(
            start_date=start,
            end_date=end,
            limit=1,
            offset=0,
            sort_by=field,
            sort_dir=SortDirection.ASC,
        )
        assert isinstance(rows, list), f"Sorting by {field} failed."


async def test_the_denormalised_line_matches_the_machine(connection, window) -> None:
    """The composite foreign key should make drift impossible."""
    start, end = window
    repository = ProductionRepository(connection)

    drift = await repository.fetch_value(
        """
        select count(*)
        from public.production_records p
        join public.machines m on m.id = p.machine_id
        where p.line_id <> m.line_id
          and p.record_date between %s and %s
        """,
        [start, end],
    )

    assert drift == 0


async def test_the_trend_returns_one_row_per_day(connection, window) -> None:
    start, end = window
    rows = await ProductionRepository(connection).get_production_trend(
        start_date=start, end_date=end
    )

    dates = [r["bucket_date"] for r in rows]
    assert dates == sorted(dates), "The trend must be ordered by date."
    assert len(dates) == len(set(dates)), "One row per day; more means a fan-out."


async def test_grouping_by_each_dimension_works(connection, window) -> None:
    start, end = window
    repository = ProductionRepository(connection)

    for dimension in ("machine", "component", "line", "shift"):
        rows = await repository.get_production_by_dimension(
            dimension=dimension, start_date=start, end_date=end
        )
        assert rows, f"No production grouped by {dimension}."
        assert {"key_id", "key_code", "key_name"} <= set(rows[0])


async def test_an_unknown_dimension_is_rejected(connection) -> None:
    with pytest.raises(ValueError, match="Unknown dimension"):
        await ProductionRepository(connection).get_production_by_dimension(
            dimension="machines; drop table x --",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )


# =============================================================================
# Quality
# =============================================================================


async def test_inspections_reconcile_with_production(connection, window) -> None:
    """The schema's two row shapes, verified against real data.

    Inspected quantities must sum to what was produced. If the summary query
    aggregated only rejection lines, or double counted the pass line, this is
    where it would show.
    """
    start, end = window
    production = await ProductionRepository(connection).get_production_summary(
        start_date=start, end_date=end
    )
    quality = await QualityRepository(connection).get_quality_summary(
        start_date=start, end_date=end
    )

    assert quality["total_inspected"] == production["total_produced"]
    assert quality["total_rejected"] == production["total_rejected"]
    assert quality["total_passed"] == production["total_accepted"]


async def test_the_defect_breakdown_is_pareto_ordered(connection, window) -> None:
    start, end = window
    rows = await QualityRepository(connection).get_defect_breakdown(start_date=start, end_date=end)

    assert rows, "The seeded database should contain defects."
    quantities = [int(r["rejected_quantity"]) for r in rows]
    assert quantities == sorted(quantities, reverse=True)


async def test_the_defect_breakdown_excludes_pass_lines(connection, window) -> None:
    """A pass line has no defect and must never appear in the Pareto."""
    start, end = window
    rows = await QualityRepository(connection).get_defect_breakdown(start_date=start, end_date=end)

    for row in rows:
        assert row["defect_id"] is not None
        assert int(row["rejected_quantity"]) > 0


async def test_the_defect_trend_covers_the_period(connection, window) -> None:
    start, end = window
    rows = await QualityRepository(connection).get_defect_trend(start_date=start, end_date=end)

    assert rows
    for row in rows:
        assert row["rejected_quantity"] <= row["inspected_quantity"]


# =============================================================================
# Inventory, machines, alerts, maintenance
# =============================================================================


async def test_inventory_status_is_readable_and_filterable(connection) -> None:
    """`status` is a generated column; reading and filtering it must work."""
    repository = InventoryRepository(connection)

    rows, total = await repository.get_inventory(limit=50, offset=0)
    assert rows, "The seeded database should contain inventory."
    assert total >= len(rows)

    critical, _ = await repository.get_inventory(status="CRITICAL", limit=50, offset=0)
    for row in critical:
        assert row["status"] == "CRITICAL"
        assert row["current_quantity"] <= row["minimum_stock"]


async def test_inventory_alerts_are_ordered_by_urgency(connection) -> None:
    rows = await InventoryRepository(connection).get_inventory_alerts()

    assert rows, "The seed should leave items in CRITICAL or LOW."
    statuses = [r["status"] for r in rows]
    assert statuses.index("CRITICAL") == 0 if "CRITICAL" in statuses else True


async def test_the_inventory_summary_counts_add_up(connection) -> None:
    totals = await InventoryRepository(connection).get_inventory_summary()

    assert (
        totals["healthy_count"]
        + totals["low_count"]
        + totals["critical_count"]
        + totals["overstocked_count"]
        == totals["total_items"]
    )


async def test_machines_are_returned_with_their_line(connection) -> None:
    rows = await MachineRepository(connection).get_machines()

    assert len(rows) >= 12, "Spec section 7 requires at least twelve machines."
    for column in ("id", "code", "name", "machine_type", "status", "line_code", "line_name"):
        assert column in rows[0]


async def test_the_fleet_summary_counts_add_up(connection) -> None:
    totals = await MachineRepository(connection).get_machine_summary()

    assert (
        totals["running_count"]
        + totals["idle_count"]
        + totals["maintenance_count"]
        + totals["offline_count"]
        == totals["total_machines"]
    )


async def test_oee_inputs_are_complete(connection, window) -> None:
    """`ideal_output_units` is summed per row because cycle time varies by part."""
    start, end = window
    row = await MachineRepository(connection).get_fleet_oee_inputs(start_date=start, end_date=end)

    for column in (
        "operating_minutes",
        "planned_minutes",
        "produced_quantity",
        "accepted_quantity",
        "ideal_output_units",
        "record_count",
    ):
        assert column in row
    assert float(row["ideal_output_units"]) > 0


async def test_alerts_are_returned_with_their_subject(connection) -> None:
    rows, total = await AlertRepository(connection).get_alerts(limit=50, offset=0)

    assert rows, "The seeded database should contain alerts."
    assert total >= len(rows)
    for row in rows:
        assert row["title"] and row["description"]
        assert any(
            row[column] is not None
            for column in ("machine_id", "component_id", "inventory_item_id", "line_id")
        ), "Every alert must name a subject."


async def test_maintenance_avoids_the_n_plus_one(connection) -> None:
    """The lateral join fetches several machines' history in one query."""
    machines = await MachineRepository(connection).get_machines()
    machine_ids = [m["id"] for m in machines[:5]]

    grouped = await MaintenanceRepository(connection).get_recent_for_machines(
        machine_ids=machine_ids, limit_per_machine=3
    )

    assert set(grouped) <= set(machine_ids)
    for records in grouped.values():
        assert len(records) <= 3


# =============================================================================
# Injection, against the real query path
# =============================================================================


@pytest.mark.security
@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
async def test_an_injected_sort_is_rejected_before_reaching_the_database(
    connection, window, payload: str
) -> None:
    start, end = window

    with pytest.raises(UnknownSortFieldError):
        await ProductionRepository(connection).get_production_records(
            start_date=start, end_date=end, limit=1, offset=0, sort_by=payload
        )


@pytest.mark.security
@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
async def test_an_injected_filter_value_is_bound_as_a_parameter(connection, payload: str) -> None:
    """The payload reaches PostgreSQL as a value and changes nothing.

    A UUID column rejects it as a malformed input rather than executing it,
    which is exactly the intended outcome: the statement's shape is fixed before
    the value is ever seen.
    """
    import psycopg

    repository = ProductionRepository(connection)

    with pytest.raises(psycopg.Error):
        await repository.get_production_records(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            machine_id=payload,  # type: ignore[arg-type]
            limit=1,
            offset=0,
        )

    # The transaction is aborted by the failed statement; roll it back so the
    # connection can be reused, and confirm the table is still there.
    await connection.rollback()
    remaining = await repository.fetch_value("select count(*) from public.production_records")
    assert remaining > 0, "The production table must still exist and hold rows."
