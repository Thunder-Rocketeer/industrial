"""In-process database loaded from the CSV exports in `supabase_csv_exports/`.

A drop-in replacement for `app.db.pool.DatabasePool` that never talks to
Supabase. At startup every CSV in the export folder is loaded into an in-memory
DuckDB database whose tables carry the same names, columns and types as the
PostgreSQL schema in `supabase/schema.sql`. The repositories then run their
existing SQL, unchanged, against that database.

WHY AN EMBEDDED SQL ENGINE RATHER THAN PANDAS

The repositories are written as SQL -- joins, window functions, `filter (where)`
aggregates, `distinct on`, lateral joins -- and every KPI relies on that SQL
producing exactly the numbers PostgreSQL would. Re-implementing ~2,000 lines of
queries in Python would mean two query surfaces that drift. DuckDB speaks the
PostgreSQL dialect closely enough that the statements run as written; the few
differences are normalised in `_translate` below, in one place.

WHAT DIFFERS FROM THE POSTGRESQL PATH

  * Placeholders: psycopg's `%s` becomes DuckDB's `?`.
  * Enum casts (`%s::public.machine_status`) are dropped. Enum columns are
    plain VARCHAR here, so the comparison works without the cast.
  * `Jsonb(...)` parameters are serialised to JSON text; JSON columns are
    parsed back into dicts on the way out, matching what psycopg returns.
  * Writes (audit inserts, login bookkeeping) land in memory only. The CSV
    files are never modified; a restart reloads them as exported.

Every DuckDB call is synchronous and runs in a worker thread via
`asyncio.to_thread`, so the event loop is never blocked by a query
(spec section 23).
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import Any

import duckdb
from psycopg import sql
from psycopg.types.json import Jsonb

from app.config import Settings, get_settings
from app.db.connection import DatabaseNotConfiguredError
from app.utils.logging import get_logger

logger = get_logger(__name__)


class CsvDataDirectoryError(RuntimeError):
    """Raised when the CSV export folder is missing or incomplete."""


# =============================================================================
# Schema
# =============================================================================

#: Column types per table, mirroring `supabase/schema.sql`. Enum types are
#: VARCHAR, `inet` is VARCHAR, `jsonb` is JSON; everything else maps directly.
#: Columns are matched to the CSV by *name*, so header order does not matter.
TABLE_SCHEMAS: dict[str, dict[str, str]] = {
    "roles": {
        "id": "UUID",
        "code": "VARCHAR",
        "name": "VARCHAR",
        "description": "VARCHAR",
        "rank": "SMALLINT",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "users": {
        "id": "UUID",
        "email": "VARCHAR",
        "full_name": "VARCHAR",
        "role_id": "UUID",
        "provider": "VARCHAR",
        "provider_subject": "VARCHAR",
        "auth_user_id": "UUID",
        "avatar_url": "VARCHAR",
        "is_active": "BOOLEAN",
        "last_login_at": "TIMESTAMPTZ",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "factory_lines": {
        "id": "UUID",
        "code": "VARCHAR",
        "name": "VARCHAR",
        "description": "VARCHAR",
        "is_active": "BOOLEAN",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "components": {
        "id": "UUID",
        "code": "VARCHAR",
        "name": "VARCHAR",
        "category": "VARCHAR",
        "line_id": "UUID",
        "unit": "VARCHAR",
        "ideal_cycle_time_seconds": "DECIMAL(8, 2)",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "shifts": {
        "id": "UUID",
        "code": "VARCHAR",
        "name": "VARCHAR",
        "start_time": "TIME",
        "end_time": "TIME",
        "sequence": "SMALLINT",
        "planned_minutes": "INTEGER",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "machines": {
        "id": "UUID",
        "code": "VARCHAR",
        "name": "VARCHAR",
        "machine_type": "VARCHAR",
        "line_id": "UUID",
        "status": "VARCHAR",
        "current_component_id": "UUID",
        "utilization_percentage": "DECIMAL(5, 2)",
        "total_downtime_minutes": "INTEGER",
        "commissioned_date": "DATE",
        "last_maintenance_date": "DATE",
        "next_maintenance_date": "DATE",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "defects": {
        "id": "UUID",
        "code": "VARCHAR",
        "name": "VARCHAR",
        "description": "VARCHAR",
        "category": "VARCHAR",
        "default_severity": "VARCHAR",
        "is_active": "BOOLEAN",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "production_records": {
        "id": "UUID",
        "record_date": "DATE",
        "shift_id": "UUID",
        "machine_id": "UUID",
        "line_id": "UUID",
        "component_id": "UUID",
        "started_at": "TIMESTAMPTZ",
        "ended_at": "TIMESTAMPTZ",
        "planned_quantity": "INTEGER",
        "produced_quantity": "INTEGER",
        "accepted_quantity": "INTEGER",
        "rejected_quantity": "INTEGER",
        "planned_minutes": "INTEGER",
        "operating_minutes": "INTEGER",
        "downtime_minutes": "INTEGER",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "quality_records": {
        "id": "UUID",
        "production_record_id": "UUID",
        "machine_id": "UUID",
        "component_id": "UUID",
        "defect_id": "UUID",
        "inspected_at": "TIMESTAMPTZ",
        "inspected_quantity": "INTEGER",
        "passed_quantity": "INTEGER",
        "rejected_quantity": "INTEGER",
        "first_pass_quantity": "INTEGER",
        "rework_quantity": "INTEGER",
        "severity": "VARCHAR",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "daily_targets": {
        "id": "UUID",
        "target_date": "DATE",
        "line_id": "UUID",
        "component_id": "UUID",
        "target_quantity": "INTEGER",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "inventory_items": {
        "id": "UUID",
        "sku": "VARCHAR",
        "name": "VARCHAR",
        "material_type": "VARCHAR",
        "component_id": "UUID",
        "unit": "VARCHAR",
        "current_quantity": "DECIMAL(14, 3)",
        "minimum_stock": "DECIMAL(14, 3)",
        "reorder_point": "DECIMAL(14, 3)",
        "maximum_stock": "DECIMAL(14, 3)",
        "supplier_name": "VARCHAR",
        "supplier_lead_time_days": "SMALLINT",
        "unit_cost": "DECIMAL(12, 2)",
        "status": "VARCHAR",
        "last_counted_at": "TIMESTAMPTZ",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "inventory_transactions": {
        "id": "UUID",
        "inventory_item_id": "UUID",
        "transaction_type": "VARCHAR",
        "quantity_delta": "DECIMAL(14, 3)",
        "balance_after": "DECIMAL(14, 3)",
        "reference": "VARCHAR",
        "notes": "VARCHAR",
        "occurred_at": "TIMESTAMPTZ",
        "created_by": "UUID",
        "created_at": "TIMESTAMPTZ",
    },
    "maintenance_records": {
        "id": "UUID",
        "machine_id": "UUID",
        "maintenance_type": "VARCHAR",
        "status": "VARCHAR",
        "scheduled_date": "DATE",
        "started_at": "TIMESTAMPTZ",
        "completed_at": "TIMESTAMPTZ",
        "downtime_minutes": "INTEGER",
        "technician": "VARCHAR",
        "description": "VARCHAR",
        "cost": "DECIMAL(12, 2)",
        "reference": "VARCHAR",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "alerts": {
        "id": "UUID",
        "alert_type": "VARCHAR",
        "severity": "VARCHAR",
        "status": "VARCHAR",
        "title": "VARCHAR",
        "description": "VARCHAR",
        "machine_id": "UUID",
        "component_id": "UUID",
        "inventory_item_id": "UUID",
        "line_id": "UUID",
        "triggered_at": "TIMESTAMPTZ",
        "acknowledged_at": "TIMESTAMPTZ",
        "acknowledged_by": "UUID",
        "resolved_at": "TIMESTAMPTZ",
        "dedupe_key": "VARCHAR",
        "created_at": "TIMESTAMPTZ",
        "updated_at": "TIMESTAMPTZ",
    },
    "audit_logs": {
        "id": "BIGINT",
        "actor_user_id": "UUID",
        "action": "VARCHAR",
        "resource_type": "VARCHAR",
        "resource_id": "VARCHAR",
        "success": "BOOLEAN",
        "request_id": "VARCHAR",
        "ip_address": "VARCHAR",
        "user_agent": "VARCHAR",
        "metadata": "JSON",
        "occurred_at": "TIMESTAMPTZ",
    },
}

#: Column defaults the write paths depend on. `users.create_user` relies on a
#: generated id and timestamps; `audit_logs.record` on a generated id.
_COLUMN_DEFAULTS: dict[str, dict[str, str]] = {
    "users": {
        "id": "gen_random_uuid()",
        "is_active": "true",
        "created_at": "now()",
        "updated_at": "now()",
    },
    "audit_logs": {
        "metadata": "'{}'",
        "occurred_at": "now()",
    },
}

#: Text columns declared `not null default ''` in the PostgreSQL schema. The
#: export writes an empty string and a NULL identically, so these are restored
#: to '' on load; every other empty cell stays NULL.
_EMPTY_TEXT_COLUMNS: dict[str, list[str]] = {
    "roles": ["description"],
    "factory_lines": ["description"],
    "defects": ["description"],
    "inventory_items": ["supplier_name"],
    "inventory_transactions": ["reference", "notes"],
    "maintenance_records": ["technician", "description"],
}

#: Unique constraints the write paths depend on. `on conflict (email)` needs a
#: unique index on `users.email` to have anything to conflict with.
_UNIQUE_COLUMNS: dict[str, list[str]] = {
    "roles": ["code"],
    "users": ["email"],
    "factory_lines": ["code"],
    "components": ["code"],
    "shifts": ["code"],
    "machines": ["code"],
    "defects": ["code"],
    "inventory_items": ["sku"],
    "maintenance_records": ["reference"],
    "alerts": ["dedupe_key"],
}


# =============================================================================
# Statement translation
# =============================================================================

_PLACEHOLDER = re.compile(r"%(%|s)")
_ENUM_CAST = re.compile(r"::public\.\w+")


def _translate(statement: sql.Composable | str) -> str:
    """Render a psycopg statement as DuckDB SQL.

    `Composable` objects are rendered with psycopg's own quoting rules, so a
    `sql.Identifier` is emitted double-quoted exactly as it would be for
    PostgreSQL -- and DuckDB reads that quoting the same way.
    """
    text = statement.as_string() if isinstance(statement, sql.Composable) else statement
    text = _ENUM_CAST.sub("", text)
    return _PLACEHOLDER.sub(lambda match: "%" if match.group(1) == "%" else "?", text)


def _adapt_param(value: Any) -> Any:
    """Convert a psycopg-flavoured parameter into something DuckDB can bind."""
    if isinstance(value, Jsonb):
        return json.dumps(value.obj)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_adapt_param(item) for item in value]
    return value


def _is_json_column(column: tuple[Any, ...]) -> bool:
    return str(column[1]).upper() == "JSON"


# =============================================================================
# Connection adapter
# =============================================================================


class CsvCursor:
    """The subset of psycopg's async cursor that `BaseRepository` uses.

    Results are fetched eagerly inside the worker thread, so `fetchall` and
    `fetchone` are plain buffer reads. Every result set in this application is
    either one aggregate row or one page of a list, so buffering costs nothing
    and saves a second thread hop per query.
    """

    def __init__(self, duck: duckdb.DuckDBPyConnection, *, as_dict: bool) -> None:
        self._duck = duck
        self._as_dict = as_dict
        self._rows: list[Any] = []
        self._position = 0
        self.rowcount = -1

    def _run(self, statement: str, params: list[Any]) -> None:
        result = self._duck.execute(statement, params)
        description = result.description or []
        rows = result.fetchall()

        # A write without RETURNING yields a single `Count` column. Report it
        # as `rowcount`, the way psycopg does, rather than as a result row.
        if len(description) == 1 and description[0][0] == "Count" and len(rows) == 1:
            self.rowcount = int(rows[0][0])
            self._rows = []
            return

        json_columns = [
            index for index, column in enumerate(description) if _is_json_column(column)
        ]
        if json_columns:
            rows = [_parse_json_cells(row, json_columns) for row in rows]

        self.rowcount = len(rows)
        if self._as_dict:
            names = [column[0] for column in description]
            self._rows = [dict(zip(names, row, strict=True)) for row in rows]
        else:
            self._rows = rows
        self._position = 0

    async def execute(
        self,
        statement: sql.Composable | str,
        params: list[Any] | tuple[Any, ...] | None = None,
    ) -> CsvCursor:
        text = _translate(statement)
        bound = [_adapt_param(value) for value in (params or [])]
        await asyncio.to_thread(self._run, text, bound)
        return self

    async def fetchall(self) -> list[Any]:
        remaining = self._rows[self._position :]
        self._position = len(self._rows)
        return remaining

    async def fetchone(self) -> Any | None:
        if self._position >= len(self._rows):
            return None
        row = self._rows[self._position]
        self._position += 1
        return row


def _parse_json_cells(row: tuple[Any, ...], json_columns: list[int]) -> tuple[Any, ...]:
    cells = list(row)
    for index in json_columns:
        if isinstance(cells[index], str):
            cells[index] = json.loads(cells[index])
    return tuple(cells)


class CsvConnection:
    """One thread-safe handle on the in-memory database.

    Mirrors the two `AsyncConnection` entry points the codebase uses:
    `cursor(row_factory=dict_row)` in the repositories and a bare `cursor()`
    in the readiness probe.
    """

    def __init__(self, duck: duckdb.DuckDBPyConnection) -> None:
        self._duck = duck

    @asynccontextmanager
    async def cursor(self, *, row_factory: Any = None) -> AsyncIterator[CsvCursor]:
        yield CsvCursor(self._duck, as_dict=row_factory is not None)

    def close(self) -> None:
        self._duck.close()


# =============================================================================
# Pool
# =============================================================================


class CsvDatabasePool:
    """Owns the in-memory database and hands out connections to it.

    Same surface as `DatabasePool` -- `open`, `close`, `connection`,
    `healthcheck`, `is_open` -- so `app.state.db_pool` and every dependency
    that reads it are unaware which backend is in use.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._db: duckdb.DuckDBPyConnection | None = None

    @property
    def is_open(self) -> bool:
        return self._db is not None

    @property
    def data_dir(self) -> Path:
        return Path(self._settings.csv_data_dir).expanduser().resolve()

    async def open(self) -> None:
        """Load every CSV into memory.

        Like `DatabasePool.open`, a missing or malformed export does not fail the
        process: liveness must answer regardless, and readiness reports the
        problem. Requests that need data raise `DatabaseNotConfiguredError`.
        """
        if self._db is not None:
            return
        try:
            self._db = await asyncio.to_thread(load_csv_database, self.data_dir)
        except CsvDataDirectoryError as exc:
            logger.warning("csv.load_failed", extra={"reason": str(exc)})
            return
        logger.info(
            "csv.loaded",
            extra={"data_dir": str(self.data_dir), "tables": len(TABLE_SCHEMAS)},
        )

    async def close(self) -> None:
        if self._db is None:
            return
        self._db.close()
        self._db = None
        logger.info("csv.closed")

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[CsvConnection]:
        """Borrow a connection for the duration of the block.

        DuckDB's `cursor()` duplicates the connection, and each duplicate may be
        used from its own thread. That is what lets the dashboard run its
        aggregates concurrently, each on a connection of its own.
        """
        if self._db is None:
            raise DatabaseNotConfiguredError(
                "The CSV data source is not available.\n\n"
                f"Expected the Supabase CSV exports in {self.data_dir}. Set "
                "CSV_DATA_DIR in server/.env if they live elsewhere."
            )
        connection = CsvConnection(self._db.cursor())
        try:
            yield connection
        finally:
            connection.close()

    async def healthcheck(self) -> bool:
        if self._db is None:
            return False
        try:
            async with self.connection() as connection, connection.cursor() as cursor:
                await cursor.execute("select 1")
                await cursor.fetchone()
        except Exception as exc:
            logger.warning("csv.healthcheck_failed", extra={"error_type": type(exc).__name__})
            return False
        return True


# =============================================================================
# Loading
# =============================================================================


def load_csv_database(data_dir: Path) -> duckdb.DuckDBPyConnection:
    """Build an in-memory DuckDB database from the CSV export folder.

    Tables are created with explicit column types and filled with
    `read_csv(...)` matched by column name, so a re-export that reorders
    columns still loads. Every timestamp is interpreted as UTC, which is how
    Supabase writes them.

    Raises:
        CsvDataDirectoryError: If the folder or any expected file is missing.
    """
    if not data_dir.is_dir():
        raise CsvDataDirectoryError(f"CSV export folder not found: {data_dir}")
    missing = [name for name in TABLE_SCHEMAS if not (data_dir / f"{name}.csv").is_file()]
    if missing:
        raise CsvDataDirectoryError(
            f"CSV export folder {data_dir} is missing: {', '.join(sorted(missing))}.csv"
        )

    db = duckdb.connect(":memory:")
    # GLOBAL so every duplicated connection (see `CsvDatabasePool.connection`)
    # reports timestamps in UTC, as PostgreSQL does.
    db.execute("set global timezone = 'UTC'")
    db.execute("create schema public")

    for table, columns in TABLE_SCHEMAS.items():
        _create_table(db, table, columns)
        _load_table(db, table, columns, data_dir / f"{table}.csv")

    _fix_audit_metadata(db, data_dir / "audit_logs.csv")
    _resume_audit_sequence(db)
    return db


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _create_table(db: duckdb.DuckDBPyConnection, table: str, columns: dict[str, str]) -> None:
    defaults = _COLUMN_DEFAULTS.get(table, {})
    definitions = []
    for name, type_name in columns.items():
        definition = f'"{name}" {type_name}'
        if name in defaults:
            definition += f" default {defaults[name]}"
        if name == "id":
            definition += " primary key"
        definitions.append(definition)
    for name in _UNIQUE_COLUMNS.get(table, []):
        definitions.append(f'unique ("{name}")')
    # Table and column names come from TABLE_SCHEMAS above, never from input.
    db.execute(f'create table public."{table}" ({", ".join(definitions)})')


def _load_table(
    db: duckdb.DuckDBPyConnection, table: str, columns: dict[str, str], path: Path
) -> None:
    # JSON columns are filled with an empty object here and rewritten by
    # `_fix_audit_metadata`: the export wrote `metadata` as a Python dict
    # literal, which DuckDB's JSON reader would reject.
    read_types = ", ".join(
        f"{_quote_literal(name)}: {_quote_literal(type_name)}"
        for name, type_name in columns.items()
        if type_name != "JSON"
    )
    empty_text = _EMPTY_TEXT_COLUMNS.get(table, [])
    select_list = ", ".join(
        f"'{{}}'::JSON as \"{name}\""
        if type_name == "JSON"
        else f'coalesce("{name}", \'\') as "{name}"'
        if name in empty_text
        else f'"{name}"'
        for name, type_name in columns.items()
    )
    db.execute(
        f'insert into public."{table}" by name '  # noqa: S608 - names are from TABLE_SCHEMAS
        f"select {select_list} from read_csv({_quote_literal(str(path))}, "
        f"header = true, types = {{{read_types}}}, nullstr = '')"
    )


def _fix_audit_metadata(db: duckdb.DuckDBPyConnection, path: Path) -> None:
    """Convert `audit_logs.metadata` from Python-literal text to real JSON.

    The exporter wrote the jsonb column with `str(dict)`, giving single-quoted
    keys and `True`/`None`. Rows are rewritten one by one; the table is small.
    """
    rows = db.execute(
        f"select id, metadata from read_csv({_quote_literal(str(path))}, "  # noqa: S608
        "header = true, all_varchar = true, nullstr = '')"
    ).fetchall()
    for row_id, raw in rows:
        db.execute(
            "update public.audit_logs set metadata = ? where id = ?",
            [json.dumps(_python_literal_to_object(raw)), int(row_id)],
        )


def _python_literal_to_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        try:
            value = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return {}
    return value if isinstance(value, dict) else {}


def _resume_audit_sequence(db: duckdb.DuckDBPyConnection) -> None:
    """Give `audit_logs.id` a generated default that continues after the export."""
    highest = db.execute("select coalesce(max(id), 0) from public.audit_logs").fetchone()
    next_id = int(highest[0] if highest else 0) + 1
    db.execute(f"create sequence public.audit_logs_id_seq start with {next_id}")
    db.execute(
        "alter table public.audit_logs alter column id "
        "set default nextval('public.audit_logs_id_seq')"
    )
