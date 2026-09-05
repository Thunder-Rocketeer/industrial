"""Validate a seeded database (spec section 30).

    python -m app.db.verify

Runs the Phase 2 acceptance checks against a live PostgreSQL database and
prints a pass/fail report:

    1. every expected table exists
    2. row counts are non-zero and plausible
    3. foreign key constraints are present
    4. every expected index exists
    5. RLS is enabled and forced, and no policy exposes data to the browser
       roles
    6. CHECK constraints hold against the seeded data
    7. representative dashboard KPI queries return sane values

Exits non-zero if any check fails, so it can gate a deployment.

This is the executable form of the Phase 2 validation checklist. It queries the
catalogue rather than trusting the migrations to have been applied, so it
reports the state of the database as it actually is.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config import Settings, get_settings
from app.db.connection import DatabaseNotConfiguredError, get_connection

EXPECTED_TABLES: tuple[str, ...] = (
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

#: Minimum row counts a correctly seeded database must satisfy. These encode
#: the spec's own floors -- at least 12 machines, at least 10 components, four
#: lines, three shifts, eight defect types (spec section 7).
MINIMUM_ROWS: dict[str, int] = {
    "roles": 6,
    "users": 4,
    "factory_lines": 4,
    "shifts": 3,
    "components": 10,
    "defects": 8,
    "machines": 12,
    "production_records": 500,
    "quality_records": 500,
    "daily_targets": 100,
    "inventory_items": 8,
    "inventory_transactions": 100,
    "maintenance_records": 10,
    "alerts": 5,
    "audit_logs": 1,
}

EXPECTED_INDEXES: tuple[str, ...] = (
    "production_records_record_date_idx",
    "production_records_machine_date_idx",
    "production_records_component_date_idx",
    "production_records_line_date_idx",
    "production_records_shift_date_idx",
    "quality_records_inspected_at_idx",
    "quality_records_machine_inspected_idx",
    "quality_records_component_inspected_idx",
    "quality_records_defect_inspected_idx",
    "quality_records_production_record_idx",
    "machines_status_idx",
    "machines_line_status_idx",
    "machines_next_maintenance_idx",
    "inventory_items_status_idx",
    "inventory_items_component_idx",
    "inventory_items_needs_attention_idx",
    "inventory_transactions_item_occurred_idx",
    "maintenance_records_machine_scheduled_idx",
    "maintenance_records_status_scheduled_idx",
    "alerts_open_triggered_idx",
    "alerts_status_triggered_idx",
    "alerts_machine_triggered_idx",
    "daily_targets_component_date_idx",
    "users_role_idx",
    "audit_logs_occurred_at_idx",
    "audit_logs_actor_occurred_idx",
    "audit_logs_resource_idx",
    "audit_logs_seed_key_idx",
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str

    def render(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return f"  [{mark}] {self.name}\n         {self.detail}"


def _scalar(cursor: psycopg.Cursor, sql: str, params: Any = None) -> Any:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    if row is None:
        return None
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


# =============================================================================
# Checks
# =============================================================================


def check_tables(cursor: psycopg.Cursor) -> CheckResult:
    cursor.execute(
        """
        select table_name
        from information_schema.tables
        where table_schema = 'public' and table_type = 'BASE TABLE'
        """
    )
    present = {row["table_name"] for row in cursor.fetchall()}
    missing = [table for table in EXPECTED_TABLES if table not in present]

    if missing:
        return CheckResult(
            "Schema: all expected tables exist",
            False,
            f"Missing {len(missing)}: {', '.join(missing)}",
        )
    return CheckResult(
        "Schema: all expected tables exist",
        True,
        f"{len(EXPECTED_TABLES)} tables present.",
    )


def check_row_counts(cursor: psycopg.Cursor) -> CheckResult:
    shortfalls: list[str] = []
    counts: dict[str, int] = {}

    for table, minimum in MINIMUM_ROWS.items():
        # Table names come from this module's own constant, never from input.
        count = _scalar(cursor, f'select count(*) from public."{table}"')  # noqa: S608
        counts[table] = int(count or 0)
        if counts[table] < minimum:
            shortfalls.append(f"{table}={counts[table]} (expected >= {minimum})")

    summary = ", ".join(f"{t}={c:,}" for t, c in counts.items())
    if shortfalls:
        return CheckResult(
            "Data: row counts meet the spec minimums",
            False,
            "Below minimum: " + "; ".join(shortfalls),
        )
    return CheckResult("Data: row counts meet the spec minimums", True, summary)


def check_foreign_keys(cursor: psycopg.Cursor) -> CheckResult:
    """Confirm foreign keys are declared and that none are violated.

    PostgreSQL enforces foreign keys on write, so a violation cannot normally
    exist. The value here is confirming the constraints were actually created:
    a table built without them would accept orphans silently.
    """
    cursor.execute(
        """
        select conrelid::regclass::text as table_name, count(*) as fk_count
        from pg_constraint
        where contype = 'f'
          and connamespace = 'public'::regnamespace
        group by conrelid
        order by 1
        """
    )
    rows = cursor.fetchall()
    total = sum(row["fk_count"] for row in rows)

    # Every child table must carry at least one foreign key.
    child_tables = {
        "users",
        "components",
        "machines",
        "production_records",
        "quality_records",
        "daily_targets",
        "inventory_transactions",
        "maintenance_records",
        "alerts",
    }
    with_fks = {row["table_name"].replace("public.", "") for row in rows}
    missing = sorted(child_tables - with_fks)

    if missing:
        return CheckResult(
            "Integrity: foreign keys declared",
            False,
            f"No foreign key on: {', '.join(missing)}",
        )
    return CheckResult(
        "Integrity: foreign keys declared",
        True,
        f"{total} foreign key constraints across {len(rows)} tables.",
    )


def check_denormalisation_consistency(cursor: psycopg.Cursor) -> CheckResult:
    """Verify the denormalised columns agree with their source of truth.

    Composite foreign keys are supposed to make this impossible, so a non-zero
    result here means a constraint is missing rather than that data drifted.
    """
    line_drift = _scalar(
        cursor,
        """
        select count(*)
        from public.production_records p
        join public.machines m on m.id = p.machine_id
        where p.line_id <> m.line_id
        """,
    )
    quality_drift = _scalar(
        cursor,
        """
        select count(*)
        from public.quality_records q
        join public.production_records p on p.id = q.production_record_id
        where q.machine_id <> p.machine_id or q.component_id <> p.component_id
        """,
    )

    if line_drift or quality_drift:
        return CheckResult(
            "Integrity: denormalised columns agree with their source",
            False,
            f"production_records line drift={line_drift}, quality_records drift={quality_drift}",
        )
    return CheckResult(
        "Integrity: denormalised columns agree with their source",
        True,
        "No drift; the composite foreign keys are doing their job.",
    )


def check_indexes(cursor: psycopg.Cursor) -> CheckResult:
    cursor.execute("select indexname from pg_indexes where schemaname = 'public'")
    present = {row["indexname"] for row in cursor.fetchall()}
    missing = [index for index in EXPECTED_INDEXES if index not in present]

    if missing:
        return CheckResult(
            "Performance: expected indexes exist",
            False,
            f"Missing {len(missing)}: {', '.join(missing)}",
        )
    return CheckResult(
        "Performance: expected indexes exist",
        True,
        f"All {len(EXPECTED_INDEXES)} named indexes present ({len(present)} total in schema).",
    )


def check_row_level_security(cursor: psycopg.Cursor) -> CheckResult:
    """Verify RLS is enabled and forced on every table."""
    cursor.execute(
        """
        select relname, relrowsecurity, relforcerowsecurity
        from pg_class
        where relnamespace = 'public'::regnamespace
          and relkind = 'r'
          and relname = any(%s)
        """,
        (list(EXPECTED_TABLES),),
    )
    rows = cursor.fetchall()

    not_enabled = [r["relname"] for r in rows if not r["relrowsecurity"]]
    not_forced = [r["relname"] for r in rows if not r["relforcerowsecurity"]]

    problems: list[str] = []
    if not_enabled:
        problems.append(f"RLS not enabled: {', '.join(sorted(not_enabled))}")
    if not_forced:
        problems.append(f"RLS not forced: {', '.join(sorted(not_forced))}")

    if problems:
        return CheckResult("Security: RLS enabled and forced", False, "; ".join(problems))
    return CheckResult(
        "Security: RLS enabled and forced",
        True,
        f"All {len(rows)} tables have RLS enabled and forced.",
    )


def check_browser_roles_have_no_access(cursor: psycopg.Cursor) -> CheckResult:
    """Verify anon and authenticated cannot read any table.

    This is the check that actually proves the deny-by-default posture. It looks
    for granted privileges rather than for policies, because a policy without a
    grant is inert and a grant without a policy is still denied by RLS -- but a
    grant is the thing that would have to exist for either to matter.
    """
    cursor.execute(
        """
        select grantee, table_name, privilege_type
        from information_schema.role_table_grants
        where table_schema = 'public'
          and grantee in ('anon', 'authenticated')
        order by grantee, table_name
        """
    )
    grants = cursor.fetchall()

    cursor.execute(
        """
        select polname, polrelid::regclass::text as table_name, polpermissive
        from pg_policy
        where polrelid in (
            select oid from pg_class
            where relnamespace = 'public'::regnamespace and relkind = 'r'
        )
        """
    )
    policies = cursor.fetchall()
    permissive = [p for p in policies if p["polpermissive"]]

    if grants:
        sample = ", ".join(
            f"{g['grantee']}->{g['table_name']}:{g['privilege_type']}" for g in grants[:5]
        )
        return CheckResult(
            "Security: browser roles have no table access",
            False,
            f"{len(grants)} unexpected grant(s). Sample: {sample}",
        )

    detail = "No privileges granted to anon or authenticated."
    if permissive:
        detail += (
            f" Note: {len(permissive)} permissive policy/policies exist but are "
            "inert without a grant."
        )
    return CheckResult("Security: browser roles have no table access", True, detail)


def check_audit_log_is_append_only(cursor: psycopg.Cursor) -> CheckResult:
    """Verify the append-only trigger on audit_logs actually rejects an update.

    Behavioural rather than structural: the trigger is exercised inside a
    savepoint that is always rolled back, so the check proves the guard works
    without altering the trail.
    """
    cursor.execute("savepoint audit_probe")
    try:
        cursor.execute(
            "update public.audit_logs set success = not success "
            "where id = (select min(id) from public.audit_logs)"
        )
    except psycopg.Error as exc:
        cursor.execute("rollback to savepoint audit_probe")
        return CheckResult(
            "Security: audit_logs is append-only",
            True,
            f"UPDATE correctly rejected: {str(exc).splitlines()[0]}",
        )

    cursor.execute("rollback to savepoint audit_probe")
    return CheckResult(
        "Security: audit_logs is append-only",
        False,
        "An UPDATE on audit_logs succeeded; the append-only trigger is missing.",
    )


def check_generated_status(cursor: psycopg.Cursor) -> CheckResult:
    """Verify the derived inventory status matches its own definition."""
    mismatched = _scalar(
        cursor,
        """
        select count(*)
        from public.inventory_items
        where status <> case
            when current_quantity <= minimum_stock then 'CRITICAL'::public.inventory_status
            when current_quantity <= reorder_point then 'LOW'::public.inventory_status
            when current_quantity >= maximum_stock then 'OVERSTOCKED'::public.inventory_status
            else 'HEALTHY'::public.inventory_status
        end
        """,
    )
    cursor.execute(
        "select status, count(*) as n from public.inventory_items group by status order by 1"
    )
    spread = ", ".join(f"{r['status']}={r['n']}" for r in cursor.fetchall())

    if mismatched:
        return CheckResult(
            "Data: derived inventory status is correct",
            False,
            f"{mismatched} item(s) disagree with the status definition.",
        )
    return CheckResult("Data: derived inventory status is correct", True, spread)


def check_quantity_arithmetic(cursor: psycopg.Cursor) -> CheckResult:
    """Verify inspections sum back to what was produced."""
    unbalanced = _scalar(
        cursor,
        """
        select count(*)
        from (
            select p.id, p.produced_quantity, coalesce(sum(q.inspected_quantity), 0) as inspected
            from public.production_records p
            left join public.quality_records q on q.production_record_id = p.id
            group by p.id, p.produced_quantity
            having p.produced_quantity <> coalesce(sum(q.inspected_quantity), 0)
        ) as mismatched
        """,
    )
    missing_pass_line = _scalar(
        cursor,
        """
        select count(*)
        from public.production_records p
        where not exists (
            select 1 from public.quality_records q
            where q.production_record_id = p.id and q.defect_id is null
        )
        """,
    )

    if unbalanced or missing_pass_line:
        return CheckResult(
            "Data: inspections reconcile with production",
            False,
            f"{unbalanced} run(s) unbalanced, {missing_pass_line} without a pass line.",
        )
    return CheckResult(
        "Data: inspections reconcile with production",
        True,
        "Every production run's inspections sum to its produced quantity.",
    )


def check_kpi_queries(cursor: psycopg.Cursor) -> CheckResult:
    """Run representative dashboard aggregates and sanity-check the results.

    These are the shapes Phase 3 services will use. Running them here proves the
    seeded data can actually answer the questions from spec section 3, and that
    the answers are in a plausible range rather than merely non-null.
    """
    findings: list[str] = []
    problems: list[str] = []

    # Production achievement over the last 30 days (spec section 43).
    cursor.execute(
        """
        select
            coalesce(sum(p.produced_quantity), 0) as produced,
            coalesce(sum(p.accepted_quantity), 0) as accepted,
            coalesce(sum(p.rejected_quantity), 0) as rejected
        from public.production_records p
        where p.record_date >= current_date - interval '30 days'
        """
    )
    row = cursor.fetchone()
    produced = int(row["produced"])
    rejected = int(row["rejected"])
    if produced <= 0:
        problems.append("No production in the last 30 days.")
    else:
        defect_rate = 100.0 * rejected / produced
        findings.append(f"30d produced={produced:,} defect_rate={defect_rate:.2f}%")
        if not 0.1 <= defect_rate <= 25.0:
            problems.append(f"Defect rate {defect_rate:.2f}% is outside a plausible range.")

    # Defect Pareto: the top three categories should dominate.
    cursor.execute(
        """
        select d.name, sum(q.rejected_quantity) as rejected
        from public.quality_records q
        join public.defects d on d.id = q.defect_id
        where q.defect_id is not null
        group by d.name
        order by rejected desc
        """
    )
    pareto = cursor.fetchall()
    if not pareto:
        problems.append("No defect data for a Pareto chart.")
    else:
        total = sum(int(r["rejected"]) for r in pareto)
        top3 = sum(int(r["rejected"]) for r in pareto[:3])
        share = 100.0 * top3 / total if total else 0.0
        findings.append(f"Pareto top-3 share={share:.1f}% across {len(pareto)} categories")
        if share < 50.0:
            problems.append(
                f"Top three defects account for only {share:.1f}%; "
                "the distribution is too flat for a meaningful Pareto chart."
            )

    # Machine availability by status.
    cursor.execute("select status, count(*) as n from public.machines group by status")
    statuses = {r["status"]: int(r["n"]) for r in cursor.fetchall()}
    findings.append("machines " + ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
    if len(statuses) < 3:
        problems.append("Fewer than three distinct machine statuses; the board will look flat.")

    # Inventory alerts.
    open_alerts = _scalar(cursor, "select count(*) from public.alerts where status = 'OPEN'")
    findings.append(f"open_alerts={open_alerts}")
    if not open_alerts:
        problems.append("No open alerts; the alerts panel would be empty.")

    # Target achievement.
    cursor.execute(
        """
        with actual as (
            select record_date, line_id, component_id, sum(produced_quantity) as produced
            from public.production_records
            where record_date >= current_date - interval '30 days'
            group by 1, 2, 3
        )
        select
            coalesce(sum(a.produced), 0) as produced,
            coalesce(sum(t.target_quantity), 0) as target
        from actual a
        join public.daily_targets t
          on t.target_date = a.record_date
         and t.line_id = a.line_id
         and t.component_id = a.component_id
        """
    )
    row = cursor.fetchone()
    target = int(row["target"] or 0)
    actual = int(row["produced"] or 0)
    if target <= 0:
        problems.append("No daily targets joinable to production.")
    else:
        achievement = 100.0 * actual / target
        findings.append(f"30d target achievement={achievement:.1f}%")
        if not 50.0 <= achievement <= 130.0:
            problems.append(f"Target achievement {achievement:.1f}% is implausible.")

    if problems:
        return CheckResult("KPI: dashboard queries return sane values", False, "; ".join(problems))
    return CheckResult("KPI: dashboard queries return sane values", True, "; ".join(findings))


CHECKS = (
    check_tables,
    check_row_counts,
    check_foreign_keys,
    check_denormalisation_consistency,
    check_indexes,
    check_row_level_security,
    check_browser_roles_have_no_access,
    check_audit_log_is_append_only,
    check_generated_status,
    check_quantity_arithmetic,
    check_kpi_queries,
)


def run_checks(settings: Settings | None = None) -> list[CheckResult]:
    """Execute every check and return the results."""
    settings = settings or get_settings()
    results: list[CheckResult] = []

    with get_connection(settings) as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            for check in CHECKS:
                try:
                    results.append(check(cursor))
                except psycopg.Error as exc:
                    connection.rollback()
                    results.append(
                        CheckResult(
                            check.__name__,
                            False,
                            f"{type(exc).__name__}: {str(exc).splitlines()[0]}",
                        )
                    )
        # Nothing here writes, but the audit probe opened a savepoint.
        connection.rollback()

    return results


def main() -> int:
    try:
        results = run_checks()
    except DatabaseNotConfiguredError as exc:
        sys.stderr.write(f"\n{exc}\n")
        return 2
    except psycopg.Error as exc:
        sys.stderr.write(f"\nCould not connect to the database: {exc}\n")
        return 2

    print("\nDatabase verification\n" + "=" * 70)
    for result in results:
        print(result.render())

    failed = [result for result in results if not result.passed]
    print("=" * 70)
    if failed:
        print(f"{len(failed)} of {len(results)} checks FAILED.\n")
        return 1

    print(f"All {len(results)} checks passed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
