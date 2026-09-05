"""Concatenate the migrations into a single applyable schema file.

    python tools/build_schema.py

Writes `supabase/schema.sql`, which is every migration in order wrapped in one
transaction. It exists because applying migrations normally requires the
Supabase CLI, and the common path for this project is pasting SQL into the
Supabase dashboard's SQL editor -- which takes one file, not eight.

The migrations remain the source of truth. This file is generated from them and
must never be edited by hand; `--check` verifies it is current, so a stale copy
cannot ship unnoticed.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
OUTPUT_PATH = REPO_ROOT / "supabase" / "schema.sql"

HEADER = """\
-- =============================================================================
-- Automobile Component Factory -- complete database schema
--
-- GENERATED FILE. Do not edit.
--
-- Built from supabase/migrations/ by `python tools/build_schema.py`.
-- The migrations are the source of truth; regenerate rather than editing here.
--
-- To apply: paste this file into the Supabase dashboard SQL editor and run it,
-- or  psql "$DATABASE_URL" -f supabase/schema.sql
--
-- The whole schema is wrapped in a single transaction, so a failure part-way
-- through leaves the database untouched rather than half-migrated.
--
-- Source migrations, in order:
{migration_list}
-- =============================================================================

begin;

"""

FOOTER = """
commit;

-- =============================================================================
-- Next step:  cd server && python -m app.db.seed
-- Then:       cd server && python -m app.db.verify
-- =============================================================================
"""


def build() -> str:
    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        raise SystemExit(f"No migrations found in {MIGRATIONS_DIR}")

    listing = "\n".join(f"--   {path.name}" for path in migrations)
    parts = [HEADER.format(migration_list=listing)]

    for path in migrations:
        parts.append(f"\n-- {'=' * 77}\n-- BEGIN {path.name}\n-- {'=' * 77}\n\n")
        parts.append(path.read_text(encoding="utf-8").rstrip() + "\n")

    parts.append(FOOTER)
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python tools/build_schema.py")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if schema.sql is out of date instead of rewriting it.",
    )
    args = parser.parse_args()

    content = build()

    if args.check:
        if not OUTPUT_PATH.exists():
            sys.stderr.write(f"{OUTPUT_PATH} does not exist. Run without --check.\n")
            return 1
        if OUTPUT_PATH.read_text(encoding="utf-8") != content:
            sys.stderr.write(
                f"{OUTPUT_PATH.name} is out of date with the migrations.\n"
                "Regenerate it: python tools/build_schema.py\n"
            )
            return 1
        print(f"{OUTPUT_PATH.name} is up to date.")
        return 0

    OUTPUT_PATH.write_text(content, encoding="utf-8")
    line_count = content.count("\n")
    generated = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} ({line_count:,} lines) at {generated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
