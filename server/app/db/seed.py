"""Deterministic database seed (spec section 30).

    python -m app.db.seed

Generates the demo factory dataset and writes it to PostgreSQL. Running it
twice produces the same database as running it once.

HOW IDEMPOTENCY WORKS

Every seeded row's primary key is derived from its natural key by UUID v5 (see
`identifiers.py`), so the identifiers are the same on every run. Each table is
therefore written with a single `INSERT ... ON CONFLICT (id) DO UPDATE`, which
inserts on the first run and refreshes in place afterwards. There is no
"delete everything first" step, so a re-seed never leaves the database empty
part-way through, and rows added by the running application alongside seeded
ones are untouched.

`audit_logs` is the exception. It is append-only by trigger, so it cannot be
updated in place; those rows are inserted with `ON CONFLICT DO NOTHING` against
the partial unique index on their metadata seed key.

RESET

`--truncate` empties the seeded tables before writing, for when the schema has
changed shape and stale rows would otherwise survive. It is destructive and
refuses to run against a production environment.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.config import Environment, Settings, get_settings
from app.db.connection import DatabaseNotConfiguredError, get_connection
from app.db.generator import SeedDataset, generate_dataset
from app.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)

#: Rows per executemany batch. Large enough to amortise round-trips, small
#: enough that a failure reports a manageable amount of context.
BATCH_SIZE = 1_000

#: Columns that must never appear in an INSERT. `status` on inventory_items is
#: a generated column: PostgreSQL rejects any attempt to supply a value.
GENERATED_COLUMNS: dict[str, frozenset[str]] = {
    "inventory_items": frozenset({"status"}),
}

#: Columns excluded from the ON CONFLICT DO UPDATE clause. `created_at` records
#: when a row first appeared and must survive a re-seed; `id` is the conflict
#: target itself.
NEVER_UPDATE = frozenset({"id", "created_at"})

#: Tables the seed owns, in foreign-key-safe order. Used by --truncate.
SEEDED_TABLES: tuple[str, ...] = (
    "roles",
    "users",
    "factory_lines",
    "shifts",
    "components",
    "defects",
    "machines",
    "production_records",
    "quality_records",
    "daily_targets",
    "inventory_items",
    "inventory_transactions",
    "maintenance_records",
    "alerts",
    "audit_logs",
)


def _adapt(value: Any) -> Any:
    """Convert a Python value into something psycopg can bind."""
    if isinstance(value, dict):
        return Jsonb(value)
    return value


def _insert_sql(table: str, columns: list[str], *, on_conflict_do_nothing: bool) -> str:
    """Build the upsert statement for a table.

    Column names come from the generated rows rather than being hard-coded, so
    adding a field to the generator does not require editing this module. They
    are quoted as identifiers; every one originates in this codebase, never in
    user input, so there is no injection surface here (spec section 57).
    """
    quoted = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join(f"%({column})s" for column in columns)

    if on_conflict_do_nothing:
        conflict = "on conflict do nothing"
    else:
        assignments = ", ".join(
            f'"{column}" = excluded."{column}"' for column in columns if column not in NEVER_UPDATE
        )
        conflict = (
            f"on conflict (id) do update set {assignments}"
            if assignments
            else "on conflict (id) do nothing"
        )

    return f'insert into public."{table}" ({quoted}) values ({placeholders}) {conflict}'  # noqa: S608


def _write_table(
    cursor: psycopg.Cursor,
    table: str,
    rows: list[dict[str, Any]],
) -> int:
    """Write one table's rows. Returns the number of rows sent."""
    if not rows:
        return 0

    excluded = GENERATED_COLUMNS.get(table, frozenset())
    columns = [column for column in rows[0] if column not in excluded]

    # audit_logs has no id column (bigint identity) and is append-only.
    on_conflict_do_nothing = "id" not in columns
    statement = _insert_sql(table, columns, on_conflict_do_nothing=on_conflict_do_nothing)

    payload = [{column: _adapt(row[column]) for column in columns} for row in rows]

    for start in range(0, len(payload), BATCH_SIZE):
        cursor.executemany(statement, payload[start : start + BATCH_SIZE])

    return len(payload)


def _truncate(cursor: psycopg.Cursor) -> None:
    """Empty every seeded table.

    TRUNCATE rather than DELETE, for two reasons: it is far faster on the
    production and quality tables, and the append-only trigger on audit_logs
    blocks DELETE but not TRUNCATE. CASCADE handles the foreign keys, so the
    table order does not matter here.
    """
    table_list = ", ".join(f'public."{table}"' for table in SEEDED_TABLES)
    logger.warning("seed.truncate", extra={"tables": len(SEEDED_TABLES)})
    cursor.execute(f"truncate table {table_list} restart identity cascade")


def seed_database(
    dataset: SeedDataset,
    *,
    settings: Settings | None = None,
    truncate: bool = False,
) -> dict[str, int]:
    """Write a generated dataset to PostgreSQL in a single transaction.

    The whole seed commits or rolls back together, so an interrupted run cannot
    leave the database holding half a factory.

    Returns:
        Rows written per table.
    """
    settings = settings or get_settings()
    written: dict[str, int] = {}

    with get_connection(settings) as connection:
        with connection.cursor() as cursor:
            if truncate:
                _truncate(cursor)

            for table, rows in dataset.tables():
                started = time.perf_counter()
                count = _write_table(cursor, table, rows)
                written[table] = count
                logger.info(
                    "seed.table_written",
                    extra={
                        "table": table,
                        "rows": count,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )
        connection.commit()

    return written


def _parse_reference_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected a date as YYYY-MM-DD, got {raw!r}.") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.db.seed",
        description="Generate and load the deterministic demo factory dataset.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed. Defaults to SEED_RANDOM_SEED from the environment.",
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=None,
        help="Days of production history. Defaults to SEED_HISTORY_DAYS.",
    )
    parser.add_argument(
        "--reference-date",
        type=_parse_reference_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="The date the dataset is built around. Defaults to today (UTC).",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Empty the seeded tables first. Destructive; refused in production.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and report counts without connecting to the database.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(level=settings.log_level, use_json=False)

    random_seed = args.seed if args.seed is not None else settings.seed_random_seed
    history_days = (
        args.history_days if args.history_days is not None else settings.seed_history_days
    )

    if args.truncate and settings.app_env is Environment.PRODUCTION:
        sys.stderr.write(
            "Refusing to --truncate with APP_ENV=production.\n"
            "The seed is a development tool; it must never run against production data.\n"
        )
        return 2

    logger.info(
        "seed.generating",
        extra={
            "random_seed": random_seed,
            "history_days": history_days,
            "reference_date": str(args.reference_date or "today"),
        },
    )

    started = time.perf_counter()
    dataset = generate_dataset(
        random_seed=random_seed,
        history_days=history_days,
        reference_date=args.reference_date,
    )
    generation_ms = round((time.perf_counter() - started) * 1000, 1)

    counts = dataset.counts()
    width = max(len(name) for name in counts)

    print(f"\nGenerated {dataset.total_rows():,} rows in {generation_ms:,.0f} ms\n")
    for name, count in counts.items():
        print(f"  {name:<{width}}  {count:>7,}")
    print()

    if args.dry_run:
        print("Dry run: nothing was written.")
        return 0

    try:
        written = seed_database(dataset, settings=settings, truncate=args.truncate)
    except DatabaseNotConfiguredError as exc:
        sys.stderr.write(f"\n{exc}\n")
        return 2
    except psycopg.Error as exc:
        # Report the database's own message, which names the constraint that
        # rejected the data -- the single most useful fact when a seed fails.
        sys.stderr.write(f"\nDatabase error while seeding: {exc}\n")
        return 1

    total = sum(written.values())
    print(f"Seed complete: {total:,} rows written.")
    print("Run `python -m app.db.verify` to validate the result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
