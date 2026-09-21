"""The CSV-backed data source (`app.db.csv_store`).

These load the real export folder in `server/supabase_csv_exports`, so they also prove
the checked-in CSVs still match the schema the repositories expect. They run in
well under a second: the largest file is 2.4 MB.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from app.config import BASE_DIR, get_settings
from app.db.connection import DatabaseNotConfiguredError
from app.db.csv_store import (
    TABLE_SCHEMAS,
    CsvDatabasePool,
    CsvDataDirectoryError,
    _adapt_param,
    _translate,
    load_csv_database,
)
from app.models.enums import MachineStatus
from app.repositories.audit import AuditRepository
from app.repositories.machines import MachineRepository
from app.repositories.production import ProductionRepository
from app.repositories.users import UserRepository

EXPORT_DIR = BASE_DIR / "supabase_csv_exports"

pytestmark = pytest.mark.skipif(
    not EXPORT_DIR.is_dir(), reason="supabase_csv_exports/ is not present"
)


# -----------------------------------------------------------------------------
# Statement translation
# -----------------------------------------------------------------------------


def test_placeholders_and_enum_casts_are_translated() -> None:
    statement = sql.SQL(
        "select {col} from public.machines m "
        "where m.status = %s::public.machine_status and m.code like '%%-001' "
        "order by {col}"
    ).format(col=sql.Identifier("m", "code"))

    assert _translate(statement) == (
        'select "m"."code" from public.machines m '
        "where m.status = ? and m.code like '%-001' "
        'order by "m"."code"'
    )


def test_jsonb_and_enum_parameters_are_adapted() -> None:
    assert _adapt_param(Jsonb({"a": 1})) == '{"a": 1}'
    assert _adapt_param(MachineStatus.RUNNING) == "RUNNING"
    machine_id = uuid.uuid4()
    assert _adapt_param([machine_id, MachineStatus.IDLE]) == [machine_id, "IDLE"]


# -----------------------------------------------------------------------------
# Loading
# -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db():
    connection = load_csv_database(EXPORT_DIR)
    yield connection
    connection.close()


def test_every_table_loads_with_rows(db) -> None:
    for table in TABLE_SCHEMAS:
        count = db.execute(f'select count(*) from public."{table}"').fetchone()[0]  # noqa: S608
        assert count > 0, table


def test_column_types_match_the_postgres_schema(db) -> None:
    row = db.execute(
        "select id, record_date, started_at, planned_quantity "
        "from public.production_records limit 1"
    ).fetchone()
    assert isinstance(row[0], uuid.UUID)
    assert isinstance(row[1], dt.date)
    assert isinstance(row[2], dt.datetime)
    assert row[2].utcoffset() == dt.timedelta(0), "timestamps are reported in UTC"
    assert isinstance(row[3], int)

    cost = db.execute("select unit_cost from public.inventory_items limit 1").fetchone()[0]
    assert isinstance(cost, Decimal)


def test_audit_metadata_is_real_json(db) -> None:
    """The export wrote jsonb as a Python dict literal; it must load as JSON."""
    raw = db.execute(
        "select metadata::varchar from public.audit_logs order by id limit 1"
    ).fetchone()[0]
    assert raw.startswith('{"')
    provider = db.execute(
        "select metadata->>'provider' from public.audit_logs order by id limit 1"
    ).fetchone()[0]
    assert provider == "google"


def test_not_null_text_columns_are_empty_strings_not_null(db) -> None:
    nulls = db.execute(
        "select count(*) from public.maintenance_records where technician is null"
    ).fetchone()[0]
    assert nulls == 0


def test_missing_folder_is_reported(tmp_path: Path) -> None:
    with pytest.raises(CsvDataDirectoryError):
        load_csv_database(tmp_path / "nowhere")

    (tmp_path / "roles.csv").write_text("id,code\n", encoding="utf-8")
    with pytest.raises(CsvDataDirectoryError, match="missing"):
        load_csv_database(tmp_path)


# -----------------------------------------------------------------------------
# Pool and repositories
# -----------------------------------------------------------------------------


@pytest.fixture
async def pool():
    settings = get_settings().model_copy(update={"csv_data_dir": EXPORT_DIR})
    pool = CsvDatabasePool(settings)
    await pool.open()
    yield pool
    await pool.close()


async def test_pool_reports_healthy_and_serves_repositories(pool: CsvDatabasePool) -> None:
    assert pool.is_open
    assert await pool.healthcheck()

    async with pool.connection() as connection:
        production = ProductionRepository(connection)
        latest = await production.get_latest_production_date()
        assert isinstance(latest, dt.date)

        summary = await production.get_production_summary(start_date=latest, end_date=latest)
        assert summary["record_count"] > 0
        assert summary["total_accepted"] + summary["total_rejected"] == summary["total_produced"]

        machines = MachineRepository(connection)
        running = await machines.get_machines(status=MachineStatus.RUNNING)
        assert running and all(row["status"] == "RUNNING" for row in running)


async def test_writes_land_in_memory_and_read_back(pool: CsvDatabasePool) -> None:
    async with pool.connection() as connection:
        audit = AuditRepository(connection)
        await audit.record(
            action="AUTH.LOGIN_SUCCESS",
            resource_type="session",
            success=True,
            metadata={"provider": "google"},
        )
        rows, _total = await audit.list_entries(limit=1, offset=0)
        assert rows[0]["metadata"] == {"provider": "google"}, "JSON comes back as a dict"

        users = UserRepository(connection)
        role = await users.get_role_by_code("VIEWER")
        created = await users.create_user(
            email="csv-test@example.com",
            full_name="CSV Test",
            role_id=role["id"],
            provider="google",
            provider_subject="csv-test-subject",
            avatar_url=None,
        )
        assert created is not None and created["role_code"] == "VIEWER"
        # `on conflict (email) do nothing` returns no row the second time.
        assert (
            await users.create_user(
                email="csv-test@example.com",
                full_name="CSV Test",
                role_id=role["id"],
                provider="google",
                provider_subject="csv-test-subject",
                avatar_url=None,
            )
            is None
        )


async def test_concurrent_connections_do_not_interfere(pool: CsvDatabasePool) -> None:
    """The dashboard borrows several connections at once (spec section 19)."""
    import asyncio

    async def count(table: str) -> int:
        async with pool.connection() as connection, connection.cursor(row_factory=dict) as cur:
            await cur.execute(f'select count(*) as n from public."{table}"')  # noqa: S608
            return (await cur.fetchone())["n"]

    counts = await asyncio.gather(*(count(table) for table in TABLE_SCHEMAS))
    assert all(value > 0 for value in counts)


async def test_unopened_pool_raises_the_not_configured_error(tmp_path: Path) -> None:
    settings = get_settings().model_copy(update={"csv_data_dir": tmp_path / "nowhere"})
    pool = CsvDatabasePool(settings)
    await pool.open()
    assert not pool.is_open
    assert not await pool.healthcheck()
    with pytest.raises(DatabaseNotConfiguredError):
        async with pool.connection():
            pass
