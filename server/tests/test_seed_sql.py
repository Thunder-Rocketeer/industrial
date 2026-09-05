"""Tests for the SQL the seed generates.

The seed builds its statements from the generated rows rather than hard-coding
column lists, so the statements themselves are worth testing: a mistake here
would only surface when someone ran the seed against a real database.

Every generated statement is parsed with `pglast` to confirm it is valid
PostgreSQL, and checked for the properties that make the seed idempotent.
"""

from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("pglast", reason="pglast provides the PostgreSQL grammar")
from pglast import parse_sql

from app.config import Environment, Settings
from app.db.generator import generate_dataset
from app.db.seed import (
    GENERATED_COLUMNS,
    NEVER_UPDATE,
    SEEDED_TABLES,
    _insert_sql,
    build_parser,
    main,
)

REFERENCE_DATE = date(2026, 9, 5)


@pytest.fixture(scope="module")
def dataset():
    return generate_dataset(random_seed=20260101, history_days=7, reference_date=REFERENCE_DATE)


# =============================================================================
# Statement generation
# =============================================================================


def test_every_table_produces_valid_sql(dataset) -> None:
    """The upsert built for each table parses as PostgreSQL."""
    for table, rows in dataset.tables():
        if not rows:
            continue
        excluded = GENERATED_COLUMNS.get(table, frozenset())
        columns = [column for column in rows[0] if column not in excluded]
        statement = _insert_sql(table, columns, on_conflict_do_nothing="id" not in columns)

        # psycopg named placeholders are not PostgreSQL syntax.
        parseable = statement
        for column in columns:
            parseable = parseable.replace(f"%({column})s", "NULL")

        parsed = parse_sql(parseable)
        assert len(parsed) == 1, f"{table} produced more than one statement."
        assert type(parsed[0].stmt).__name__ == "InsertStmt"


def test_upsert_updates_on_conflict() -> None:
    """Re-running the seed must refresh rows rather than fail or duplicate."""
    sql = _insert_sql("machines", ["id", "code", "name"], on_conflict_do_nothing=False)

    assert "on conflict (id) do update set" in sql
    assert '"code" = excluded."code"' in sql
    assert '"name" = excluded."name"' in sql


def test_created_at_survives_a_reseed() -> None:
    """`created_at` records when a row first appeared and must not be rewritten."""
    sql = _insert_sql(
        "machines", ["id", "code", "created_at", "updated_at"], on_conflict_do_nothing=False
    )

    assert '"created_at" = excluded."created_at"' not in sql
    assert '"updated_at" = excluded."updated_at"' in sql
    assert '"id" = excluded."id"' not in sql


def test_never_update_covers_id_and_created_at() -> None:
    assert {"id", "created_at"} == NEVER_UPDATE


def test_generated_columns_are_never_inserted(dataset) -> None:
    """PostgreSQL rejects any INSERT that supplies a generated column.

    `inventory_items.status` is derived from the stock thresholds, so the seed
    must omit it entirely.
    """
    assert "status" in GENERATED_COLUMNS["inventory_items"]

    for row in dataset.inventory_items:
        assert "status" not in row, (
            "The generator must not emit inventory_items.status; it is a generated column."
        )


def test_append_only_table_uses_do_nothing() -> None:
    """audit_logs cannot be updated, so its insert must not try."""
    sql = _insert_sql("audit_logs", ["action", "success"], on_conflict_do_nothing=True)

    assert "on conflict do nothing" in sql
    assert "do update" not in sql


def test_audit_logs_carry_no_id_column(dataset) -> None:
    """The identity column must be left to the database to allocate."""
    for row in dataset.audit_logs:
        assert "id" not in row


def test_identifiers_are_quoted() -> None:
    """Column and table names are quoted, so a reserved word cannot break the SQL."""
    sql = _insert_sql("users", ["id", "email"], on_conflict_do_nothing=False)

    assert 'insert into public."users"' in sql
    assert '"id", "email"' in sql


def test_seeded_tables_list_matches_the_dataset(dataset) -> None:
    """--truncate must cover exactly the tables the seed writes."""
    assert tuple(name for name, _ in dataset.tables()) == SEEDED_TABLES


# =============================================================================
# CLI
# =============================================================================


def test_dry_run_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    """--dry-run reports counts without needing a database."""
    exit_code = main(["--dry-run", "--history-days", "3", "--reference-date", "2026-09-05"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Dry run: nothing was written." in captured.out
    assert "production_records" in captured.out


def test_truncate_is_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """The seed is a development tool and must not empty a production database."""
    production = Settings(app_env=Environment.PRODUCTION, _env_file=None)
    monkeypatch.setattr("app.db.seed.get_settings", lambda: production)

    assert main(["--truncate", "--dry-run"]) == 2


def test_reference_date_must_be_iso_formatted() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--reference-date", "05/09/2026"])


def test_cli_accepts_the_documented_flags() -> None:
    args = build_parser().parse_args(
        ["--seed", "7", "--history-days", "30", "--reference-date", "2026-01-15", "--truncate"]
    )

    assert args.seed == 7
    assert args.history_days == 30
    assert args.reference_date == date(2026, 1, 15)
    assert args.truncate is True


def test_missing_database_url_reports_actionable_guidance(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A seed run without DATABASE_URL must say what to do, not stack-trace."""
    unconfigured = Settings(database_url="", _env_file=None)
    monkeypatch.setattr("app.db.seed.get_settings", lambda: unconfigured)
    monkeypatch.setattr("app.db.connection.get_settings", lambda: unconfigured)

    exit_code = main(["--history-days", "1", "--reference-date", "2026-09-05"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "DATABASE_URL is not set" in captured.err
    assert "Supabase" in captured.err
