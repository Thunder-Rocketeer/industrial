"""Static validation of the database schema and the SQL embedded in the code.

These tests parse SQL with `pglast`, which wraps libpg_query -- the parser
PostgreSQL itself uses. A statement that parses here is valid PostgreSQL
grammar.

That matters more than usual for this project: the migrations and the verifier
are executed against a hosted Supabase instance, not from the test run, so
without these tests a syntax error would only surface when someone applied the
schema for real.

Parsing is not the same as executing. It proves grammar and structure; it cannot
prove a column exists or a constraint behaves as intended. The behavioural
checks live in `app/db/verify.py`, which runs against a live database.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pglast = pytest.importorskip(
    "pglast",
    reason="pglast provides the PostgreSQL grammar; install requirements-dev.txt",
)
from pglast import parse_sql  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
SCHEMA_FILE = REPO_ROOT / "supabase" / "schema.sql"
SERVER_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_TABLE_COUNT = 15

#: The tables spec section 6 requires.
REQUIRED_TABLES = frozenset(
    {
        "users",
        "roles",
        "factory_lines",
        "machines",
        "components",
        "shifts",
        "production_records",
        "quality_records",
        "defects",
        "inventory_items",
        "inventory_transactions",
        "maintenance_records",
        "daily_targets",
        "alerts",
        "audit_logs",
    }
)


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def all_migration_sql() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in migration_files())


# =============================================================================
# Migration files
# =============================================================================


def test_migrations_directory_is_populated() -> None:
    assert migration_files(), f"No migrations found in {MIGRATIONS_DIR}"


@pytest.mark.parametrize("path", migration_files(), ids=lambda p: p.name)
def test_migration_parses_as_postgresql(path: Path) -> None:
    """Every migration is valid PostgreSQL grammar."""
    statements = parse_sql(path.read_text(encoding="utf-8"))
    assert statements, f"{path.name} contains no statements."


def test_migrations_are_ordered_by_filename() -> None:
    """Filenames sort into the order the migrations must be applied in.

    Supabase applies migrations in lexicographic filename order, so a file
    without the timestamp prefix would silently run at the wrong point.
    """
    for path in migration_files():
        prefix = path.name.split("_", 1)[0]
        assert prefix.isdigit() and len(prefix) == 14, (
            f"{path.name} must start with a 14-digit timestamp so ordering is explicit."
        )


def test_every_required_table_is_created() -> None:
    """Spec section 6: all fifteen tables exist in the schema."""
    sql = all_migration_sql()
    created = {
        stmt.stmt.relation.relname
        for stmt in parse_sql(sql)
        if type(stmt.stmt).__name__ == "CreateStmt"
    }

    missing = REQUIRED_TABLES - created
    assert not missing, f"Missing tables: {sorted(missing)}"
    assert len(created) == EXPECTED_TABLE_COUNT, (
        f"Expected {EXPECTED_TABLE_COUNT} tables, found {len(created)}: {sorted(created)}"
    )


def test_every_table_has_row_level_security_enabled() -> None:
    """Spec sections 66 and 71: RLS on every table, and forced.

    Checked textually against the RLS migration. `ENABLE` without `FORCE` would
    leave an owner-privileged connection able to bypass every policy.
    """
    sql = (MIGRATIONS_DIR / "20260101000800_row_level_security.sql").read_text(encoding="utf-8")
    lowered = sql.lower()

    for table in sorted(REQUIRED_TABLES):
        assert f"alter table public.{table}" in lowered, (
            f"{table} is absent from the RLS migration."
        )

    enable_count = lowered.count("enable row level security")
    force_count = lowered.count("force  row level security") + lowered.count(
        "force row level security"
    )
    assert enable_count == EXPECTED_TABLE_COUNT, (
        f"Expected {EXPECTED_TABLE_COUNT} ENABLE statements, found {enable_count}."
    )
    assert force_count == EXPECTED_TABLE_COUNT, (
        f"Expected {EXPECTED_TABLE_COUNT} FORCE statements, found {force_count}."
    )


def test_browser_roles_are_revoked() -> None:
    """The deny-by-default posture revokes privileges from anon and authenticated."""
    sql = (
        (MIGRATIONS_DIR / "20260101000800_row_level_security.sql")
        .read_text(encoding="utf-8")
        .lower()
    )

    assert "revoke all on all tables    in schema public from anon, authenticated;" in sql
    assert "alter default privileges in schema public" in sql


def test_no_permissive_policy_grants_browser_access() -> None:
    """No enabled policy may expose data to `anon` or `authenticated`.

    The template at the foot of the RLS migration shows how such a policy would
    be written; this test fails if one is ever uncommented without a
    corresponding review of this test.
    """
    sql = (MIGRATIONS_DIR / "20260101000800_row_level_security.sql").read_text(encoding="utf-8")

    policies = [
        stmt.stmt for stmt in parse_sql(sql) if type(stmt.stmt).__name__ == "CreatePolicyStmt"
    ]

    for policy in policies:
        roles = {role.rolename for role in (policy.roles or []) if role.rolename}
        if roles & {"anon", "authenticated"}:
            assert not policy.permissive, (
                f"Policy {policy.policy_name} is permissive for a browser role. "
                "The architecture requires backend-mediated access (spec section 66)."
            )


def test_functions_pin_search_path() -> None:
    """Every helper function sets an empty search_path.

    A function without it can be hijacked by a caller who prepends a schema to
    search_path and shadows an object the function references. Supabase's own
    security advisor flags this, and it is a genuine privilege-escalation route
    for a SECURITY DEFINER function.
    """
    sql = (MIGRATIONS_DIR / "20260101000100_schema_and_helpers.sql").read_text(encoding="utf-8")

    # Read the parse tree rather than counting text: the file's own header
    # comment mentions `SET search_path`, which a textual count would include.
    functions = [
        stmt.stmt for stmt in parse_sql(sql) if type(stmt.stmt).__name__ == "CreateFunctionStmt"
    ]
    assert functions, "No helper functions found."

    unpinned = []
    for function in functions:
        name = ".".join(part.sval for part in function.funcname)
        pinned = any(
            option.defname == "set" and option.arg.name == "search_path"
            for option in (function.options or [])
        )
        if not pinned:
            unpinned.append(name)

    assert not unpinned, f"Functions without a pinned search_path: {unpinned}"


def test_audit_log_has_append_only_trigger() -> None:
    """Spec section 67: the audit trail cannot be rewritten."""
    sql = (
        (MIGRATIONS_DIR / "20260101000600_maintenance_alerts_audit.sql")
        .read_text(encoding="utf-8")
        .lower()
    )

    assert "before update or delete on public.audit_logs" in sql
    assert "app.prevent_mutation()" in sql


def test_required_indexes_are_declared() -> None:
    """Spec section 29's priority list is covered.

    Checks the indexed column appears on the right table, rather than requiring
    an exact index name -- several are composite, which is deliberate.
    """
    sql = (MIGRATIONS_DIR / "20260101000700_indexes.sql").read_text(encoding="utf-8")

    indexes: dict[str, list[str]] = {}
    for stmt in parse_sql(sql):
        node = stmt.stmt
        if type(node).__name__ != "IndexStmt":
            continue
        table = node.relation.relname
        columns = [p.name for p in node.indexParams if p.name]
        indexes.setdefault(table, []).extend(columns)

    required = {
        "production_records": {"record_date", "machine_id", "component_id", "shift_id"},
        "quality_records": {"inspected_at", "machine_id", "component_id", "defect_id"},
        "inventory_items": {"status", "component_id"},
        "machines": {"status"},
        "maintenance_records": {"machine_id"},
    }

    for table, columns in required.items():
        indexed = set(indexes.get(table, []))
        missing = columns - indexed
        assert not missing, f"{table} is missing an index on: {sorted(missing)}"


def test_generated_schema_is_current() -> None:
    """`supabase/schema.sql` matches the migrations it is built from.

    The single-file schema is what most people will actually apply, so a stale
    copy would mean the database does not match the reviewed migrations.
    """
    import subprocess

    result = subprocess.run(
        [__import__("sys").executable, str(SERVER_ROOT / "tools" / "build_schema.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=SERVER_ROOT,
    )
    assert result.returncode == 0, (
        f"supabase/schema.sql is out of date.\n{result.stdout}{result.stderr}"
    )


def test_generated_schema_parses() -> None:
    assert SCHEMA_FILE.exists(), "Run `python tools/build_schema.py` to generate schema.sql."
    assert parse_sql(SCHEMA_FILE.read_text(encoding="utf-8"))


# =============================================================================
# SQL embedded in Python
# =============================================================================


def _sql_literals_in(path: Path) -> list[str]:
    """Extract string literals from a module that look like SQL statements.

    The verifier's queries only ever run against a live database, so nothing
    else in the test suite would catch a syntax error in them.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    keywords = ("select", "with", "insert", "update", "delete", "truncate")

    # Constants inside an f-string are fragments of a statement, not statements.
    # Parsing `select count(*) from public."` on its own would fail for reasons
    # that say nothing about the real query, so they are excluded here; the
    # dynamic statements they build are covered by the seed's own tests.
    fragment_ids = {
        id(part)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for part in ast.walk(node)
        if isinstance(part, ast.Constant)
    }

    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in fragment_ids:
            continue
        text = node.value.strip()
        if text.lower().startswith(keywords) and len(text) > 20:
            found.append(text)
    return found


@pytest.mark.parametrize(
    "module_name",
    ["verify.py"],
)
def test_embedded_sql_parses(module_name: str) -> None:
    """Every SQL query embedded in the database modules is valid PostgreSQL."""
    path = SERVER_ROOT / "app" / "db" / module_name
    statements = _sql_literals_in(path)

    assert statements, f"No SQL literals found in {module_name}; the extractor may be broken."

    for sql in statements:
        # psycopg placeholders are not PostgreSQL syntax; substitute a literal
        # so the surrounding statement can be parsed.
        parseable = sql.replace("%s", "NULL")
        try:
            parse_sql(parseable)
        except Exception as exc:
            pytest.fail(f"Invalid SQL in {module_name}:\n{sql}\n\n{type(exc).__name__}: {exc}")
