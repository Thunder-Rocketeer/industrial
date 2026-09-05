"""Validate the Supabase migrations against the real PostgreSQL grammar.

Parses every migration with `pglast`, which wraps libpg_query -- the actual
parser PostgreSQL uses. A file that parses here is syntactically valid
PostgreSQL, which catches the class of error that would otherwise only surface
when running the migration against a live database.

This is a development tool, not part of the application. Run it with:

    python tools/validate_sql.py

`pglast` is a development-only dependency; see requirements-dev.txt.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import pglast
    from pglast import parse_sql
except ImportError:  # pragma: no cover - guidance path
    sys.stderr.write(
        "pglast is not installed. Install the development dependencies:\n"
        "    pip install -r requirements-dev.txt\n"
    )
    raise SystemExit(2) from None

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"


def statement_kinds(sql: str) -> list[str]:
    """Return the node type of each top-level statement in `sql`."""
    return [type(raw.stmt).__name__ for raw in parse_sql(sql)]


def main() -> int:
    if not MIGRATIONS_DIR.is_dir():
        sys.stderr.write(f"Migrations directory not found: {MIGRATIONS_DIR}\n")
        return 2

    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        sys.stderr.write(f"No migrations found in {MIGRATIONS_DIR}\n")
        return 2

    print(f"Parsing with libpg_query via pglast {pglast.__version__}\n")

    failures = 0
    total_statements = 0

    for path in migrations:
        sql = path.read_text(encoding="utf-8")
        try:
            kinds = statement_kinds(sql)
        except Exception as exc:
            failures += 1
            print(f"FAIL  {path.name}")
            print(f"      {type(exc).__name__}: {exc}")
            continue

        total_statements += len(kinds)
        summary: dict[str, int] = {}
        for kind in kinds:
            summary[kind] = summary.get(kind, 0) + 1
        detail = ", ".join(f"{k.removesuffix('Stmt')}x{v}" for k, v in sorted(summary.items()))
        print(f"ok    {path.name}  ({len(kinds)} statements: {detail})")

    print()
    if failures:
        print(f"{failures} file(s) failed to parse.")
        return 1

    print(f"All {len(migrations)} migrations parsed cleanly ({total_statements} statements).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
