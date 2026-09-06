"""Tests for the deterministic seed generator.

The generator produces the dataset without touching a database, so everything
that matters about the data can be verified here: determinism, referential
integrity, the arithmetic the database CHECK constraints enforce, and the
realism properties the dashboard depends on.

These tests are the reason the seed can be trusted before it has ever been run
against a live Supabase project. What they cannot prove is that PostgreSQL
accepts the rows -- that is `app/db/verify.py`'s job.

A fixed `reference_date` is used throughout. Without it the dataset would shift
daily and assertions about specific windows could not be written.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import pytest

from app.db.generator import (
    DEFECT_SPIKE_COMPONENT,
    DEFECT_SPIKE_END_DAYS_AGO,
    DEFECT_SPIKE_START_DAYS_AGO,
    SeedDataset,
    generate_dataset,
    stable_seed,
)
from app.db.identifiers import SEED_NAMESPACE, derive_id
from app.db.reference_data import (
    COMPONENTS,
    DEFECTS,
    DEMO_USERS,
    FACTORY_LINES,
    MACHINES,
    MATERIALS,
    ROLES,
    SHIFTS,
)
from app.models.enums import MachineStatus, MachineType

REFERENCE_DATE = date(2026, 9, 5)
HISTORY_DAYS = 90
RANDOM_SEED = 20260101


@pytest.fixture(scope="module")
def dataset() -> SeedDataset:
    return generate_dataset(
        random_seed=RANDOM_SEED,
        history_days=HISTORY_DAYS,
        reference_date=REFERENCE_DATE,
    )


# =============================================================================
# Determinism (spec section 30, requirement 2)
# =============================================================================


def test_two_runs_produce_identical_data(dataset: SeedDataset) -> None:
    """The same seed and window always produce the same dataset."""
    other = generate_dataset(
        random_seed=RANDOM_SEED, history_days=HISTORY_DAYS, reference_date=REFERENCE_DATE
    )

    assert dataset.counts() == other.counts()
    for (name, left), (_, right) in zip(dataset.tables(), other.tables(), strict=True):
        assert left == right, f"Table {name} differs between two runs of the same seed."


def test_a_different_seed_produces_different_data() -> None:
    """Changing the seed actually changes the data.

    Guards against a bug where the seed is accepted but never reaches the random
    streams, which would make determinism trivially true and the seed parameter
    meaningless.
    """
    a = generate_dataset(random_seed=1, history_days=14, reference_date=REFERENCE_DATE)
    b = generate_dataset(random_seed=2, history_days=14, reference_date=REFERENCE_DATE)

    assert a.production_records != b.production_records


def test_stable_seed_is_stable_across_processes() -> None:
    """`stable_seed` must not depend on PYTHONHASHSEED.

    Python randomises `hash()` for strings per process. If the generator used
    it, the "deterministic" seed would produce different data on every run,
    which is the exact failure this hashing choice exists to prevent.
    """
    assert stable_seed("LINE-A", "MORNING", 7) == stable_seed("LINE-A", "MORNING", 7)
    # Value pinned so a change to the hashing scheme is a deliberate decision:
    # changing it reshuffles every seeded dataset.
    assert stable_seed("acf") == 2_170_707_943_574_845_780


def test_derived_ids_are_stable() -> None:
    """Identifiers depend only on the natural key, never on ordering or time."""
    assert derive_id("machine", "CNC-T-001") == derive_id("machine", "CNC-T-001")
    assert derive_id("machine", "CNC-T-001") != derive_id("component", "CNC-T-001")
    # Pinned: changing the namespace orphans every previously seeded database
    # rather than updating it.
    assert str(SEED_NAMESPACE) == "7f4d2c18-3b9a-5e64-9d21-8a6c0f5b1e73"


def test_derive_id_requires_a_natural_key() -> None:
    with pytest.raises(ValueError, match="natural key is required"):
        derive_id("machine")


def test_ids_are_unique_within_every_table(dataset: SeedDataset) -> None:
    """A collision would silently overwrite a row during the upsert."""
    for name, rows in dataset.tables():
        if not rows or "id" not in rows[0]:
            continue
        ids = [row["id"] for row in rows]
        assert len(ids) == len(set(ids)), f"Duplicate ids in {name}."


# =============================================================================
# Catalogue coverage (spec section 7)
# =============================================================================


def test_reference_data_meets_spec_minimums(dataset: SeedDataset) -> None:
    assert len(dataset.factory_lines) == 4
    assert len(dataset.machines) >= 12
    assert len(dataset.components) >= 10
    assert len(dataset.shifts) >= 3
    assert len(dataset.defects) == 8
    assert len(dataset.roles) == 6
    assert len(dataset.inventory_items) == 8


def test_every_machine_type_is_represented() -> None:
    """Spec section 7 names seven machine types; all must appear."""
    present = {machine.machine_type for machine in MACHINES}
    assert present == set(MachineType), f"Missing types: {set(MachineType) - present}"


def test_every_machine_status_is_represented() -> None:
    """Mixed operational states, so the machines board is not uniform."""
    present = {machine.status for machine in MACHINES}
    assert present == set(MachineStatus)


def test_machines_are_spread_across_all_lines() -> None:
    by_line: dict[str, int] = defaultdict(int)
    for machine in MACHINES:
        by_line[machine.line_code] += 1

    assert set(by_line) == {line.code for line in FACTORY_LINES}
    assert all(count >= 3 for count in by_line.values()), by_line


def test_running_machines_have_a_current_component() -> None:
    """Mirrors the machines_running_requires_component_check CHECK constraint."""
    for machine in MACHINES:
        if machine.status is MachineStatus.RUNNING:
            assert machine.current_component_code, f"{machine.code} is RUNNING with no component."


def test_demo_users_cover_every_role() -> None:
    """Spec section 50, and every role in section 56 has a demo account."""
    seeded_roles = {user.role for user in DEMO_USERS}
    assert seeded_roles == {role.code for role in ROLES}

    emails = {user.email for user in DEMO_USERS}
    for required in (
        "admin@factory.local",
        "manager@factory.local",
        "quality@factory.local",
        "inventory@factory.local",
    ):
        assert required in emails


def test_seeded_users_carry_no_credentials(dataset: SeedDataset) -> None:
    """No user row may claim a Google identity that does not exist.

    A seeded `google_sub` would let anyone who knew the value impersonate the
    account once OAuth is wired up in Phase 3.
    """
    for user in dataset.users:
        assert user["provider_subject"] is None
        assert user["auth_user_id"] is None
        assert "password" not in user
        assert "password_hash" not in user


# =============================================================================
# Referential integrity
# =============================================================================


def test_no_orphan_foreign_keys(dataset: SeedDataset) -> None:
    """Every reference resolves to a row that the seed also creates."""
    ids = {name: {row["id"] for row in rows if "id" in row} for name, rows in dataset.tables()}

    references = [
        ("users", "role_id", "roles"),
        ("components", "line_id", "factory_lines"),
        ("machines", "line_id", "factory_lines"),
        ("production_records", "machine_id", "machines"),
        ("production_records", "component_id", "components"),
        ("production_records", "shift_id", "shifts"),
        ("production_records", "line_id", "factory_lines"),
        ("quality_records", "production_record_id", "production_records"),
        ("quality_records", "machine_id", "machines"),
        ("quality_records", "component_id", "components"),
        ("daily_targets", "line_id", "factory_lines"),
        ("daily_targets", "component_id", "components"),
        ("inventory_transactions", "inventory_item_id", "inventory_items"),
        ("maintenance_records", "machine_id", "machines"),
    ]

    for table, column, target in references:
        rows = dict(dataset.tables())[table]
        for row in rows:
            value = row[column]
            assert value in ids[target], (
                f"{table}.{column} = {value} has no matching row in {target}."
            )


def test_nullable_references_resolve_when_set(dataset: SeedDataset) -> None:
    machine_ids = {row["id"] for row in dataset.machines}
    component_ids = {row["id"] for row in dataset.components}
    item_ids = {row["id"] for row in dataset.inventory_items}
    defect_ids = {row["id"] for row in dataset.defects}

    for alert in dataset.alerts:
        for column, valid in (
            ("machine_id", machine_ids),
            ("component_id", component_ids),
            ("inventory_item_id", item_ids),
        ):
            if alert[column] is not None:
                assert alert[column] in valid

    for record in dataset.quality_records:
        if record["defect_id"] is not None:
            assert record["defect_id"] in defect_ids


def test_denormalised_line_matches_the_machine(dataset: SeedDataset) -> None:
    """production_records.line_id must agree with its machine's line.

    The composite foreign key makes this impossible to violate in the database.
    The generator has to get it right for the insert to succeed at all, so the
    check belongs here too.
    """
    machine_line = {row["id"]: row["line_id"] for row in dataset.machines}
    for record in dataset.production_records:
        assert record["line_id"] == machine_line[record["machine_id"]]


def test_denormalised_quality_columns_match_the_production_record(
    dataset: SeedDataset,
) -> None:
    parents = {row["id"]: row for row in dataset.production_records}
    for record in dataset.quality_records:
        parent = parents[record["production_record_id"]]
        assert record["machine_id"] == parent["machine_id"]
        assert record["component_id"] == parent["component_id"]


# =============================================================================
# Constraint compliance
#
# Each of these mirrors a CHECK constraint. A failure here means the seed would
# be rejected by PostgreSQL, which is far cheaper to discover in a test than in
# a half-applied migration.
# =============================================================================


def test_production_quantities_balance(dataset: SeedDataset) -> None:
    for record in dataset.production_records:
        assert (
            record["accepted_quantity"] + record["rejected_quantity"] == record["produced_quantity"]
        )
        assert record["accepted_quantity"] >= 0
        assert record["rejected_quantity"] >= 0
        assert record["planned_quantity"] >= 0


def test_production_minutes_are_within_the_shift(dataset: SeedDataset) -> None:
    for record in dataset.production_records:
        assert record["planned_minutes"] > 0
        assert 0 <= record["operating_minutes"] <= record["planned_minutes"]
        assert 0 <= record["downtime_minutes"] <= record["planned_minutes"]
        assert record["ended_at"] > record["started_at"]
        if record["produced_quantity"] > 0:
            assert record["operating_minutes"] > 0


def test_quality_rows_take_one_of_the_two_legal_shapes(dataset: SeedDataset) -> None:
    """Mirrors quality_records_defect_shape_check."""
    for record in dataset.quality_records:
        if record["defect_id"] is None:
            assert record["rejected_quantity"] == 0
            assert record["severity"] is None
        else:
            assert record["rejected_quantity"] > 0
            assert record["passed_quantity"] == 0
            assert record["first_pass_quantity"] == 0
            assert record["severity"] is not None

        assert (
            record["passed_quantity"] + record["rejected_quantity"] == record["inspected_quantity"]
        )
        assert record["first_pass_quantity"] <= record["passed_quantity"]
        assert record["rework_quantity"] <= record["passed_quantity"]


def test_each_production_record_has_exactly_one_pass_line(dataset: SeedDataset) -> None:
    """Required by the UNIQUE NULLS NOT DISTINCT grain constraint."""
    pass_lines: dict[object, int] = defaultdict(int)
    for record in dataset.quality_records:
        if record["defect_id"] is None:
            pass_lines[record["production_record_id"]] += 1

    for record in dataset.production_records:
        assert pass_lines[record["id"]] == 1, (
            f"Production record {record['id']} has {pass_lines[record['id']]} pass lines."
        )


def test_inspections_reconcile_with_production(dataset: SeedDataset) -> None:
    """Inspected units must sum to produced units, with nothing lost."""
    inspected: dict[object, int] = defaultdict(int)
    rejected: dict[object, int] = defaultdict(int)
    for record in dataset.quality_records:
        inspected[record["production_record_id"]] += record["inspected_quantity"]
        rejected[record["production_record_id"]] += record["rejected_quantity"]

    for record in dataset.production_records:
        assert inspected[record["id"]] == record["produced_quantity"]
        assert rejected[record["id"]] == record["rejected_quantity"]


def test_grain_keys_are_unique(dataset: SeedDataset) -> None:
    """Mirrors the UNIQUE constraints that make the upsert idempotent."""
    production_grain = {
        (r["record_date"], r["shift_id"], r["machine_id"], r["component_id"])
        for r in dataset.production_records
    }
    assert len(production_grain) == len(dataset.production_records)

    quality_grain = {(r["production_record_id"], r["defect_id"]) for r in dataset.quality_records}
    assert len(quality_grain) == len(dataset.quality_records)

    target_grain = {
        (r["target_date"], r["line_id"], r["component_id"]) for r in dataset.daily_targets
    }
    assert len(target_grain) == len(dataset.daily_targets)

    assert len({r["dedupe_key"] for r in dataset.alerts}) == len(dataset.alerts)
    assert len({r["reference"] for r in dataset.maintenance_records}) == len(
        dataset.maintenance_records
    )


def test_inventory_thresholds_form_a_valid_ladder() -> None:
    """Mirrors inventory_items_threshold_order_check."""
    for material in MATERIALS:
        assert material.minimum_stock <= material.reorder_point < material.maximum_stock, (
            f"{material.sku} has an incoherent threshold ladder."
        )
        assert material.current_quantity >= 0


def test_inventory_transaction_signs_match_their_type(dataset: SeedDataset) -> None:
    """Mirrors inventory_transactions_delta_sign_check."""
    positive = {"RECEIPT", "RETURN"}
    negative = {"ISSUE", "SCRAP"}

    for transaction in dataset.inventory_transactions:
        delta = transaction["quantity_delta"]
        kind = transaction["transaction_type"]

        assert delta != 0, "A movement of zero is not a movement."
        assert transaction["balance_after"] >= 0
        if kind in positive:
            assert delta > 0, f"{kind} must increase stock."
        elif kind in negative:
            assert delta < 0, f"{kind} must decrease stock."


def test_maintenance_status_matches_its_timestamps(dataset: SeedDataset) -> None:
    """Mirrors maintenance_records_status_consistency_check."""
    for record in dataset.maintenance_records:
        status = record["status"]
        started, completed = record["started_at"], record["completed_at"]

        if status == "COMPLETED":
            assert started is not None and completed is not None
            assert completed >= started
        elif status == "IN_PROGRESS":
            assert started is not None and completed is None
        elif status == "SCHEDULED":
            assert started is None and completed is None


def test_alerts_are_well_formed(dataset: SeedDataset) -> None:
    """Mirrors the subject, description and status CHECK constraints."""
    for alert in dataset.alerts:
        assert alert["title"].strip()
        # Spec section 45: an alert must be readable as text, not just a colour.
        assert alert["description"].strip()
        assert any(
            alert[column] is not None
            for column in ("machine_id", "component_id", "inventory_item_id", "line_id")
        ), f"Alert {alert['dedupe_key']} has no subject."

        status = alert["status"]
        if status == "OPEN":
            assert alert["acknowledged_at"] is None and alert["resolved_at"] is None
        elif status == "ACKNOWLEDGED":
            assert alert["acknowledged_at"] is not None and alert["resolved_at"] is None
        elif status == "RESOLVED":
            assert alert["resolved_at"] is not None


def test_machine_dates_are_ordered(dataset: SeedDataset) -> None:
    """Mirrors the machine maintenance-date CHECK constraints."""
    for machine in dataset.machines:
        commissioned = machine["commissioned_date"]
        last = machine["last_maintenance_date"]
        nxt = machine["next_maintenance_date"]

        assert last is None or last >= commissioned
        assert last is None or nxt is None or nxt >= last
        assert 0 <= machine["utilization_percentage"] <= 100
        assert machine["total_downtime_minutes"] >= 0


def test_audit_metadata_carries_a_seed_key(dataset: SeedDataset) -> None:
    """Seeded audit rows need a seed key, or re-running would duplicate them.

    audit_logs is append-only, so the seed cannot clean up after itself; the
    partial unique index on this key is the only thing making it idempotent.
    """
    keys = [row["metadata"]["seed_key"] for row in dataset.audit_logs]
    assert len(keys) == len(set(keys)), "Seeded audit rows must have unique seed keys."


# =============================================================================
# Realism (spec section 31)
# =============================================================================


def test_history_covers_the_requested_window(dataset: SeedDataset) -> None:
    """Spec section 7 asks for 30-90 days of history."""
    dates = {record["record_date"] for record in dataset.production_records}
    span = (max(dates) - min(dates)).days + 1

    assert 30 <= span <= 365
    assert span >= HISTORY_DAYS - 7  # allow for non-working days at the edges
    assert max(dates) <= REFERENCE_DATE


def test_the_plant_does_not_run_on_sundays(dataset: SeedDataset) -> None:
    sundays = [r for r in dataset.production_records if r["record_date"].weekday() == 6]
    assert not sundays, f"{len(sundays)} production records fall on a Sunday."


def test_output_varies_by_shift(dataset: SeedDataset) -> None:
    """Spec section 31: the morning starts slowly and the night shift is lighter."""
    shift_ids = {derive_id("shift", shift.code): shift.code for shift in SHIFTS}
    output: dict[str, int] = defaultdict(int)
    for record in dataset.production_records:
        output[shift_ids[record["shift_id"]]] += record["produced_quantity"]

    assert output["EVENING"] > output["MORNING"] > output["NIGHT"], output


def test_machines_differ_consistently_in_performance(dataset: SeedDataset) -> None:
    """Some machines must be reliably better, not merely different on average."""
    produced: dict[object, int] = defaultdict(int)
    runs: dict[object, int] = defaultdict(int)
    for record in dataset.production_records:
        produced[record["machine_id"]] += record["produced_quantity"]
        runs[record["machine_id"]] += 1

    rates = {m: produced[m] / runs[m] for m in produced if runs[m]}
    assert max(rates.values()) > min(rates.values()) * 1.3, (
        "Machine performance is too uniform to be worth charting."
    )


def test_utilisation_spans_a_realistic_range(dataset: SeedDataset) -> None:
    """Running machines should be busy; stopped machines clearly should not."""
    by_status: dict[str, list[float]] = defaultdict(list)
    for machine in dataset.machines:
        by_status[machine["status"]].append(machine["utilization_percentage"])

    running_avg = sum(by_status["RUNNING"]) / len(by_status["RUNNING"])
    assert running_avg > 80.0, f"Running machines average only {running_avg:.1f}% utilisation."

    for stopped in ("OFFLINE", "MAINTENANCE"):
        if by_status[stopped]:
            assert max(by_status[stopped]) < running_avg, (
                f"A {stopped} machine reports higher utilisation than a running one."
            )


def test_defect_distribution_is_pareto_shaped(dataset: SeedDataset) -> None:
    """Spec section 7: some defects must be markedly more common than others.

    Without a skew the Pareto chart in spec section 5.3 would show eight roughly
    equal bars and tell the user nothing.
    """
    defect_names = {derive_id("defect", d.code): d.code for d in DEFECTS}
    rejected: dict[str, int] = defaultdict(int)
    for record in dataset.quality_records:
        if record["defect_id"] is not None:
            rejected[defect_names[record["defect_id"]]] += record["rejected_quantity"]

    assert len(rejected) == len(DEFECTS), "Every defect type should occur at least once."

    ranked = sorted(rejected.values(), reverse=True)
    total = sum(ranked)
    top_three_share = sum(ranked[:3]) / total

    assert 0.55 <= top_three_share <= 0.85, (
        f"Top three defects account for {top_three_share:.0%}; "
        "the distribution is not usefully Pareto-shaped."
    )
    assert ranked[0] > ranked[-1] * 3, "The most and least common defects are too close."


def test_the_defect_spike_is_visible_in_its_window(dataset: SeedDataset) -> None:
    """Spec section 31: "a small defect spike on one component"."""
    spike_component = derive_id("component", DEFECT_SPIKE_COMPONENT)
    parents = {row["id"]: row for row in dataset.production_records}

    in_window = [0, 0]  # rejected, inspected
    outside = [0, 0]

    for record in dataset.quality_records:
        if record["component_id"] != spike_component:
            continue
        parent = parents[record["production_record_id"]]
        days_ago = (REFERENCE_DATE - parent["record_date"]).days
        bucket = (
            in_window
            if DEFECT_SPIKE_END_DAYS_AGO <= days_ago <= DEFECT_SPIKE_START_DAYS_AGO
            else outside
        )
        bucket[0] += record["rejected_quantity"]
        bucket[1] += record["inspected_quantity"]

    spike_rate = in_window[0] / in_window[1]
    baseline_rate = outside[0] / outside[1]

    assert spike_rate > baseline_rate * 2, (
        f"Spike window rate {spike_rate:.2%} is not clearly above the baseline {baseline_rate:.2%}."
    )


def test_inventory_covers_all_four_stock_states() -> None:
    """Spec section 7: healthy, low, critical and overstocked must all appear."""

    def band(material: object) -> str:
        if material.current_quantity <= material.minimum_stock:
            return "CRITICAL"
        if material.current_quantity <= material.reorder_point:
            return "LOW"
        if material.current_quantity >= material.maximum_stock:
            return "OVERSTOCKED"
        return "HEALTHY"

    bands = {material.sku: band(material) for material in MATERIALS}
    assert set(bands.values()) == {"CRITICAL", "LOW", "OVERSTOCKED", "HEALTHY"}

    # The declared expectation must match the arithmetic, so an edit to a
    # quantity cannot silently drop the items the alerts panel depends on.
    for material in MATERIALS:
        assert bands[material.sku] == material.expected_status, (
            f"{material.sku} lands in {bands[material.sku]}, "
            f"but is declared as {material.expected_status}."
        )

    assert sum(1 for b in bands.values() if b == "CRITICAL") >= 2


def test_inventory_ledger_ends_at_the_current_quantity(dataset: SeedDataset) -> None:
    """The most recent movement's balance must equal the item's stock.

    This is what keeps the CRITICAL and LOW items genuinely critical and low. If
    the ledger drifted from the stated quantity, the inventory trend chart would
    contradict the status badge beside it.
    """
    by_item: dict[object, list[dict]] = defaultdict(list)
    for transaction in dataset.inventory_transactions:
        by_item[transaction["inventory_item_id"]].append(transaction)

    for item in dataset.inventory_items:
        movements = sorted(by_item[item["id"]], key=lambda t: t["occurred_at"])
        assert movements, f"{item['sku']} has no stock movements."
        assert abs(movements[-1]["balance_after"] - item["current_quantity"]) < 0.01, (
            f"{item['sku']} ledger ends at {movements[-1]['balance_after']} "
            f"but stock is {item['current_quantity']}."
        )


def test_alerts_reference_real_conditions(dataset: SeedDataset) -> None:
    """Every critical-inventory alert must name an actually critical item."""
    items = {row["id"]: row for row in dataset.inventory_items}

    critical_alerts = [
        alert for alert in dataset.alerts if alert["alert_type"] == "CRITICAL_INVENTORY"
    ]
    assert critical_alerts, "No critical inventory alerts were generated."

    for alert in critical_alerts:
        item = items[alert["inventory_item_id"]]
        assert item["current_quantity"] <= item["minimum_stock"], (
            f"Alert claims {item['sku']} is critical, but stock is above the minimum."
        )

    offline_alerts = [a for a in dataset.alerts if a["alert_type"] == "MACHINE_OFFLINE"]
    offline_machines = {
        row["id"] for row in dataset.machines if row["status"] == MachineStatus.OFFLINE.value
    }
    for alert in offline_alerts:
        assert alert["machine_id"] in offline_machines


def test_alerts_span_every_severity(dataset: SeedDataset) -> None:
    """Spec section 34 requires Info, Warning and Critical."""
    severities = {alert["severity"] for alert in dataset.alerts}
    assert severities == {"INFO", "WARNING", "CRITICAL"}


def test_maintenance_covers_past_and_future(dataset: SeedDataset) -> None:
    """Spec section 7: completed, recently completed and upcoming work."""
    statuses = {record["status"] for record in dataset.maintenance_records}
    assert "COMPLETED" in statuses
    assert "SCHEDULED" in statuses

    scheduled_dates = [r["scheduled_date"] for r in dataset.maintenance_records]
    assert any(d > REFERENCE_DATE for d in scheduled_dates), "No upcoming maintenance."
    assert any(d < REFERENCE_DATE for d in scheduled_dates), "No maintenance history."

    recent_cutoff = REFERENCE_DATE - timedelta(days=60)
    assert any(
        r["status"] == "COMPLETED" and r["scheduled_date"] >= recent_cutoff
        for r in dataset.maintenance_records
    ), "No recently completed maintenance."


def test_targets_are_a_stretch_on_the_plan(dataset: SeedDataset) -> None:
    """Achievement should land realistically below 100%, not exactly at it."""
    targets = {
        (t["target_date"], t["line_id"], t["component_id"]): t["target_quantity"]
        for t in dataset.daily_targets
    }

    produced: dict[tuple, int] = defaultdict(int)
    for record in dataset.production_records:
        key = (record["record_date"], record["line_id"], record["component_id"])
        produced[key] += record["produced_quantity"]

    matched = [(produced[k], v) for k, v in targets.items() if k in produced]
    assert matched, "No daily target joins to production."

    total_produced = sum(p for p, _ in matched)
    total_target = sum(t for _, t in matched)
    achievement = 100.0 * total_produced / total_target

    assert 75.0 <= achievement <= 100.0, (
        f"Overall achievement of {achievement:.1f}% is not a believable factory."
    )


# =============================================================================
# Parameters
# =============================================================================


def test_history_days_controls_the_window() -> None:
    short = generate_dataset(
        random_seed=RANDOM_SEED, history_days=14, reference_date=REFERENCE_DATE
    )
    dates = {r["record_date"] for r in short.production_records}

    assert (max(dates) - min(dates)).days < 14
    assert len(short.production_records) < 800


def test_history_days_must_be_positive() -> None:
    with pytest.raises(ValueError, match="history_days"):
        generate_dataset(history_days=0)


def test_every_component_is_produced(dataset: SeedDataset) -> None:
    """A component that never runs would show as an empty row on every chart."""
    produced = {record["component_id"] for record in dataset.production_records}
    for component in COMPONENTS:
        assert derive_id("component", component.code) in produced, (
            f"{component.code} is never produced."
        )
