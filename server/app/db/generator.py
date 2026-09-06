"""Deterministic generation of the demo factory dataset.

This module contains no database code at all. It turns the fixed catalogue in
`reference_data.py` into complete table rows, and nothing else. The separation
matters for three reasons:

  * the whole dataset can be tested -- determinism, referential integrity,
    quantity arithmetic, defect distribution -- without a database
  * generation and persistence fail independently, so a seeding error is always
    clearly one or the other
  * spec section 31's "do not make values random on every API request" is
    structurally guaranteed: nothing here runs in a request path

DETERMINISM

Every random draw comes from a `random.Random` seeded by `stable_seed()`, which
hashes its inputs with blake2b. Python's built-in `hash()` is deliberately not
used: it is salted per process for strings, so it would produce different data
on every run.

Each draw is seeded from the *coordinates of the thing being generated* -- the
date, shift and machine -- rather than from one shared stream. That makes
generation order-independent: adding a machine changes only that machine's rows,
and the others keep the values they had before. A single shared stream would
reshuffle the entire history whenever the catalogue changed.

REALISM (spec section 31)

The dataset is shaped by fixed effects rather than noise:
  * the plant does not run on Sundays and runs reduced on Saturdays
  * the morning shift starts slowly, evening peaks, night runs lighter
  * some machines are consistently more efficient than others
  * less reliable machines suffer downtime more often
  * one component has a deliberate defect spike in a known window
  * inventory declines steadily between periodic replenishments
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.db.identifiers import derive_id
from app.db.reference_data import (
    COMPONENTS,
    DEFECTS,
    DEMO_USERS,
    FACTORY_LINES,
    MACHINES,
    MATERIALS,
    ROLES,
    SHIFTS,
    ComponentSpec,
    MachineSpec,
    ShiftSpec,
    capable_components,
)
from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    AlertType,
    DefectSeverity,
    InventoryTransactionType,
    MachineStatus,
    MaintenanceStatus,
    MaintenanceType,
)

# =============================================================================
# Tunable model constants
#
# Named rather than inlined, per spec section 47: no magic numbers for rules
# that shape the data a reader is asked to trust.
# =============================================================================

#: Saturday runs a reduced schedule; Sunday is a full plant shutdown.
SATURDAY_OUTPUT_FACTOR = 0.72
SUNDAY_IS_SHUTDOWN = True

#: Per-run efficiency jitter around a machine's fixed efficiency.
EFFICIENCY_JITTER = (0.93, 1.07)

#: Unplanned downtime, in minutes, when a stoppage occurs.
DOWNTIME_MINUTES_RANGE = (25, 135)

#: A machine sits idle for a whole shift this often, independent of downtime.
IDLE_SHIFT_PROBABILITY = 0.06

#: Defect rate jitter multiplier.
DEFECT_RATE_JITTER = (0.7, 1.4)

#: Spec section 31: "a small defect spike on one component".
DEFECT_SPIKE_COMPONENT = "STR-KNUCKLE"
DEFECT_SPIKE_START_DAYS_AGO = 25
DEFECT_SPIKE_END_DAYS_AGO = 17
DEFECT_SPIKE_MULTIPLIER = 3.4

#: Share of accepted units that needed rework, so First Pass Yield is below the
#: pass rate rather than identical to it.
REWORK_FRACTION_RANGE = (0.004, 0.021)

#: Management sets the daily target slightly above the achievable plan, so
#: achievement lands realistically below 100% rather than exactly at it.
TARGET_STRETCH_RANGE = (1.02, 1.09)

#: Machines whose live status stops production in the recent past.
OFFLINE_DAYS_BEFORE_TODAY = 6
MAINTENANCE_DAYS_BEFORE_TODAY = 2

#: Preventive maintenance cadence.
MAINTENANCE_INTERVAL_DAYS = 45

#: Inventory replenishment cadence, per material.
REPLENISHMENT_INTERVAL_DAYS = 21

#: Rolling window used to compute the utilisation figure shown per machine.
UTILIZATION_WINDOW_DAYS = 14

#: Hour of day each movement type is recorded at. Ordered so that, within a
#: single day, adjustments precede receipts which precede issues -- matching the
#: order the ledger walk assigns running balances in.
_MOVEMENT_HOUR = {
    InventoryTransactionType.ADJUSTMENT: time(8, 0),
    InventoryTransactionType.RECEIPT: time(10, 0),
    InventoryTransactionType.ISSUE: time(14, 0),
}

UTC = timezone.utc


def stable_seed(*parts: object) -> int:
    """Derive a reproducible integer seed from arbitrary values.

    Uses blake2b rather than the built-in `hash()`, whose string hashing is
    randomised per process by PYTHONHASHSEED and would therefore produce a
    different dataset on every run.
    """
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def rng_for(*parts: object) -> random.Random:
    """Return a Random stream keyed to the supplied coordinates."""
    return random.Random(stable_seed(*parts))


def _weighted_choice(rng: random.Random, items: list[Any], weights: list[float]) -> Any:
    """Pick one item with probability proportional to its weight."""
    return rng.choices(items, weights=weights, k=1)[0]


# =============================================================================
# Dataset container
# =============================================================================


@dataclass
class SeedDataset:
    """Generated rows, keyed by table, in foreign-key-safe insertion order.

    Field order is the insertion order: parents before children throughout.
    """

    roles: list[dict[str, Any]] = field(default_factory=list)
    users: list[dict[str, Any]] = field(default_factory=list)
    factory_lines: list[dict[str, Any]] = field(default_factory=list)
    shifts: list[dict[str, Any]] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    defects: list[dict[str, Any]] = field(default_factory=list)
    machines: list[dict[str, Any]] = field(default_factory=list)
    production_records: list[dict[str, Any]] = field(default_factory=list)
    quality_records: list[dict[str, Any]] = field(default_factory=list)
    daily_targets: list[dict[str, Any]] = field(default_factory=list)
    inventory_items: list[dict[str, Any]] = field(default_factory=list)
    inventory_transactions: list[dict[str, Any]] = field(default_factory=list)
    maintenance_records: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    audit_logs: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Row count per table, in insertion order."""
        return {name: len(rows) for name, rows in self.tables()}

    def tables(self) -> list[tuple[str, list[dict[str, Any]]]]:
        """Return (table name, rows) pairs in foreign-key-safe order."""
        return [
            ("roles", self.roles),
            ("users", self.users),
            ("factory_lines", self.factory_lines),
            ("shifts", self.shifts),
            ("components", self.components),
            ("defects", self.defects),
            ("machines", self.machines),
            ("production_records", self.production_records),
            ("quality_records", self.quality_records),
            ("daily_targets", self.daily_targets),
            ("inventory_items", self.inventory_items),
            ("inventory_transactions", self.inventory_transactions),
            ("maintenance_records", self.maintenance_records),
            ("alerts", self.alerts),
            ("audit_logs", self.audit_logs),
        ]

    def total_rows(self) -> int:
        return sum(len(rows) for _, rows in self.tables())


# =============================================================================
# Generator
# =============================================================================


class FactoryDataGenerator:
    """Builds the complete demo dataset for a fixed seed and date window.

    Args:
        random_seed: Base seed. The same value always yields the same dataset.
        history_days: Days of production history to generate, ending on
            `reference_date` inclusive.
        reference_date: The "today" the dataset is built around. Defaults to the
            current UTC date. Tests pass a fixed date so assertions are stable.
    """

    def __init__(
        self,
        random_seed: int = 20260101,
        history_days: int = 90,
        reference_date: date | None = None,
    ) -> None:
        if history_days < 1:
            raise ValueError("history_days must be at least 1.")

        self.random_seed = random_seed
        self.history_days = history_days
        self.reference_date = reference_date or datetime.now(tz=UTC).date()
        self.start_date = self.reference_date - timedelta(days=history_days - 1)

    # -- helpers --------------------------------------------------------------

    def _dates(self) -> list[date]:
        return [self.start_date + timedelta(days=offset) for offset in range(self.history_days)]

    def _days_ago(self, day: date) -> int:
        return (self.reference_date - day).days

    def _day_output_factor(self, day: date) -> float:
        """Output multiplier for the calendar day. 0.0 means no production."""
        weekday = day.weekday()  # Monday is 0
        if weekday == 6 and SUNDAY_IS_SHUTDOWN:
            return 0.0
        if weekday == 5:
            return SATURDAY_OUTPUT_FACTOR
        return 1.0

    def _machine_is_available(self, machine: MachineSpec, day: date) -> bool:
        """Whether a machine was producing on a given day.

        A machine's catalogue status describes the present. Machines currently
        offline or under maintenance stopped producing shortly before the
        reference date; before that they ran normally.
        """
        days_ago = self._days_ago(day)
        if machine.status is MachineStatus.OFFLINE:
            return days_ago > OFFLINE_DAYS_BEFORE_TODAY
        if machine.status is MachineStatus.MAINTENANCE:
            return days_ago > MAINTENANCE_DAYS_BEFORE_TODAY
        return True

    def _component_for(self, machine: MachineSpec, day: date, shift: ShiftSpec) -> ComponentSpec:
        """Choose which component a machine runs in a given shift.

        Rotates through the machine's capable components on a stable cycle so a
        machine's output is spread across its parts rather than fixed to one,
        while remaining reproducible.
        """
        options = capable_components(machine)
        index = stable_seed(self.random_seed, "component", machine.code, day, shift.code)
        return options[index % len(options)]

    def _defect_multiplier(self, component: ComponentSpec, day: date) -> float:
        """Extra defect pressure on a component for a given day."""
        days_ago = self._days_ago(day)
        in_spike_window = (
            component.code == DEFECT_SPIKE_COMPONENT
            and DEFECT_SPIKE_END_DAYS_AGO <= days_ago <= DEFECT_SPIKE_START_DAYS_AGO
        )
        return DEFECT_SPIKE_MULTIPLIER if in_spike_window else 1.0

    @staticmethod
    def _shift_bounds(day: date, shift: ShiftSpec) -> tuple[datetime, datetime]:
        """Return the UTC start and end of a shift on a given day.

        The night shift ends the following morning, so the end is rolled forward
        a day whenever it is not after the start.
        """
        started = datetime.combine(day, shift.start_time, tzinfo=UTC)
        ended = datetime.combine(day, shift.end_time, tzinfo=UTC)
        if ended <= started:
            ended += timedelta(days=1)
        return started, ended

    # -- reference tables -----------------------------------------------------

    def _generate_roles(self, dataset: SeedDataset) -> None:
        for role in ROLES:
            dataset.roles.append(
                {
                    "id": derive_id("role", role.code.value),
                    "code": role.code.value,
                    "name": role.name,
                    "description": role.description,
                    "rank": role.rank,
                }
            )

    def _generate_users(self, dataset: SeedDataset) -> None:
        for user in DEMO_USERS:
            dataset.users.append(
                {
                    "id": derive_id("user", user.email),
                    "email": user.email,
                    "full_name": user.full_name,
                    "role_id": derive_id("role", user.role.value),
                    "provider": "google",
                    # Populated by the OAuth flow on first sign-in, not seeded:
                    # a seeded value would claim a Google identity that does not
                    # exist, and anyone who knew it could impersonate the account.
                    "provider_subject": None,
                    "avatar_url": None,
                    "auth_user_id": None,
                    "is_active": True,
                    "last_login_at": None,
                }
            )

    def _generate_lines(self, dataset: SeedDataset) -> None:
        for line in FACTORY_LINES:
            dataset.factory_lines.append(
                {
                    "id": derive_id("factory_line", line.code),
                    "code": line.code,
                    "name": line.name,
                    "description": line.description,
                    "is_active": True,
                }
            )

    def _generate_shifts(self, dataset: SeedDataset) -> None:
        for shift in SHIFTS:
            dataset.shifts.append(
                {
                    "id": derive_id("shift", shift.code),
                    "code": shift.code,
                    "name": shift.name,
                    "start_time": shift.start_time,
                    "end_time": shift.end_time,
                    "sequence": shift.sequence,
                    "planned_minutes": shift.planned_minutes,
                }
            )

    def _generate_components(self, dataset: SeedDataset) -> None:
        for component in COMPONENTS:
            dataset.components.append(
                {
                    "id": derive_id("component", component.code),
                    "code": component.code,
                    "name": component.name,
                    "category": component.category,
                    "line_id": derive_id("factory_line", component.line_code),
                    "unit": "units",
                    "ideal_cycle_time_seconds": component.ideal_cycle_time_seconds,
                }
            )

    def _generate_defects(self, dataset: SeedDataset) -> None:
        for defect in DEFECTS:
            dataset.defects.append(
                {
                    "id": derive_id("defect", defect.code),
                    "code": defect.code,
                    "name": defect.name,
                    "description": defect.description,
                    "category": defect.category,
                    "default_severity": defect.default_severity.value,
                    "is_active": True,
                }
            )

    # -- production and quality ----------------------------------------------

    def _generate_production_and_quality(self, dataset: SeedDataset) -> None:
        """Generate production runs, their inspections and the daily targets.

        Targets are derived from the day's planned quantities once they are
        known, so a target is always a stretch on a realistic plan rather than
        an unrelated number.
        """
        defect_specs = list(DEFECTS)
        defect_weights = [d.weight for d in defect_specs]

        for day in self._dates():
            day_factor = self._day_output_factor(day)
            if day_factor == 0.0:
                continue

            # Planned quantity accumulated per (line, component) for targets.
            planned_by_line_component: dict[tuple[str, str], int] = {}

            for shift in SHIFTS:
                for machine in MACHINES:
                    if not self._machine_is_available(machine, day):
                        continue

                    rng = rng_for(self.random_seed, "run", day, shift.code, machine.code)

                    if rng.random() < IDLE_SHIFT_PROBABILITY:
                        continue

                    component = self._component_for(machine, day, shift)
                    started_at, ended_at = self._shift_bounds(day, shift)

                    planned_minutes = shift.planned_minutes
                    planned_quantity = round(
                        component.nominal_shift_output * shift.output_factor * day_factor
                    )

                    # Downtime: less reliable machines stop more often.
                    downtime_minutes = 0
                    if rng.random() > machine.reliability:
                        downtime_minutes = rng.randint(*DOWNTIME_MINUTES_RANGE)
                        downtime_minutes = min(downtime_minutes, planned_minutes)
                    operating_minutes = planned_minutes - downtime_minutes

                    # Output scales with time actually available and with the
                    # machine's fixed efficiency, plus modest run-to-run jitter.
                    efficiency = machine.efficiency * rng.uniform(*EFFICIENCY_JITTER)
                    time_ratio = operating_minutes / planned_minutes
                    produced_quantity = max(0, round(planned_quantity * time_ratio * efficiency))

                    # Rejections.
                    defect_rate = (
                        component.defect_propensity
                        * self._defect_multiplier(component, day)
                        * rng.uniform(*DEFECT_RATE_JITTER)
                    )
                    rejected_quantity = min(
                        produced_quantity, round(produced_quantity * defect_rate)
                    )
                    accepted_quantity = produced_quantity - rejected_quantity

                    production_id = derive_id(
                        "production_record", day, shift.code, machine.code, component.code
                    )
                    machine_id = derive_id("machine", machine.code)
                    component_id = derive_id("component", component.code)

                    dataset.production_records.append(
                        {
                            "id": production_id,
                            "record_date": day,
                            "shift_id": derive_id("shift", shift.code),
                            "machine_id": machine_id,
                            "line_id": derive_id("factory_line", machine.line_code),
                            "component_id": component_id,
                            "started_at": started_at,
                            "ended_at": ended_at,
                            "planned_quantity": planned_quantity,
                            "produced_quantity": produced_quantity,
                            "accepted_quantity": accepted_quantity,
                            "rejected_quantity": rejected_quantity,
                            "planned_minutes": planned_minutes,
                            "operating_minutes": operating_minutes,
                            "downtime_minutes": downtime_minutes,
                        }
                    )

                    key = (machine.line_code, component.code)
                    planned_by_line_component[key] = (
                        planned_by_line_component.get(key, 0) + planned_quantity
                    )

                    self._generate_quality_for_run(
                        dataset=dataset,
                        rng=rng,
                        production_id=production_id,
                        machine_id=machine_id,
                        component_id=component_id,
                        inspected_at=ended_at,
                        accepted_quantity=accepted_quantity,
                        rejected_quantity=rejected_quantity,
                        defect_specs=defect_specs,
                        defect_weights=defect_weights,
                    )

            self._generate_targets_for_day(dataset, day, planned_by_line_component)

    def _generate_quality_for_run(
        self,
        *,
        dataset: SeedDataset,
        rng: random.Random,
        production_id: Any,
        machine_id: Any,
        component_id: Any,
        inspected_at: datetime,
        accepted_quantity: int,
        rejected_quantity: int,
        defect_specs: list[Any],
        defect_weights: list[float],
    ) -> None:
        """Emit the inspection rows for one production run.

        One pass line carrying the accepted units, then one rejection line per
        distinct defect type found. Together they sum back to the run's produced
        quantity, which is what the quantity-balance test checks.
        """
        # The pass line. Always emitted, even at zero, so every production
        # record has exactly one -- which is what the NULLS NOT DISTINCT unique
        # constraint expects.
        rework_quantity = round(accepted_quantity * rng.uniform(*REWORK_FRACTION_RANGE))
        rework_quantity = min(rework_quantity, accepted_quantity)

        dataset.quality_records.append(
            {
                "id": derive_id("quality_record", production_id, "PASS"),
                "production_record_id": production_id,
                "machine_id": machine_id,
                "component_id": component_id,
                "defect_id": None,
                "inspected_at": inspected_at,
                "inspected_quantity": accepted_quantity,
                "passed_quantity": accepted_quantity,
                "rejected_quantity": 0,
                "first_pass_quantity": accepted_quantity - rework_quantity,
                "rework_quantity": rework_quantity,
                "severity": None,
            }
        )

        if rejected_quantity <= 0:
            return

        # Spread the rejections across one to three defect types, drawn against
        # the catalogue weights so the Pareto distribution holds in aggregate.
        distinct_defects = min(rejected_quantity, rng.choice([1, 1, 2, 2, 3]))
        chosen: list[Any] = []
        while len(chosen) < distinct_defects:
            candidate = _weighted_choice(rng, defect_specs, defect_weights)
            if candidate not in chosen:
                chosen.append(candidate)

        # Split the rejected units across the chosen defects, giving the first
        # (most likely) defect the largest share.
        remaining = rejected_quantity
        for position, defect in enumerate(chosen):
            is_last = position == len(chosen) - 1
            if is_last:
                share = remaining
            else:
                # Leave at least one unit for each remaining defect.
                max_share = remaining - (len(chosen) - position - 1)
                share = max(1, round(remaining * rng.uniform(0.45, 0.75)))
                share = min(share, max_share)
            remaining -= share

            severity = defect.default_severity
            # A minor defect occasionally presents as a major one.
            if severity is DefectSeverity.MINOR and rng.random() < 0.12:
                severity = DefectSeverity.MAJOR

            dataset.quality_records.append(
                {
                    "id": derive_id("quality_record", production_id, defect.code),
                    "production_record_id": production_id,
                    "machine_id": machine_id,
                    "component_id": component_id,
                    "defect_id": derive_id("defect", defect.code),
                    "inspected_at": inspected_at,
                    "inspected_quantity": share,
                    "passed_quantity": 0,
                    "rejected_quantity": share,
                    "first_pass_quantity": 0,
                    "rework_quantity": 0,
                    "severity": severity.value,
                }
            )

    def _generate_targets_for_day(
        self,
        dataset: SeedDataset,
        day: date,
        planned_by_line_component: dict[tuple[str, str], int],
    ) -> None:
        for (line_code, component_code), planned_total in sorted(planned_by_line_component.items()):
            rng = rng_for(self.random_seed, "target", day, line_code, component_code)
            target = max(1, round(planned_total * rng.uniform(*TARGET_STRETCH_RANGE)))
            dataset.daily_targets.append(
                {
                    "id": derive_id("daily_target", day, line_code, component_code),
                    "target_date": day,
                    "line_id": derive_id("factory_line", line_code),
                    "component_id": derive_id("component", component_code),
                    "target_quantity": target,
                }
            )

    # -- maintenance ----------------------------------------------------------

    def _generate_maintenance(self, dataset: SeedDataset) -> dict[str, dict[str, date]]:
        """Generate maintenance history and return each machine's key dates.

        Returns:
            Mapping of machine code to its `last` and `next` maintenance dates,
            used when building the machine rows.
        """
        machine_dates: dict[str, dict[str, date]] = {}

        for machine in MACHINES:
            machine_id = derive_id("machine", machine.code)
            rng = rng_for(self.random_seed, "maintenance", machine.code)

            # Walk preventive services backwards from just before the reference
            # date on a fixed cadence, offset per machine so the whole fleet is
            # not serviced on the same day.
            offset = stable_seed(machine.code) % MAINTENANCE_INTERVAL_DAYS
            last_completed: date | None = None
            occurrence = 0

            days_back = offset
            while days_back < self.history_days:
                scheduled = self.reference_date - timedelta(days=days_back)
                if scheduled < machine.commissioned:
                    break

                duration = rng.randint(90, 340)
                started = datetime.combine(scheduled, time(8, 0), tzinfo=UTC)
                dataset.maintenance_records.append(
                    {
                        "id": derive_id("maintenance", machine.code, scheduled, "PREVENTIVE"),
                        "machine_id": machine_id,
                        "maintenance_type": MaintenanceType.PREVENTIVE.value,
                        "status": MaintenanceStatus.COMPLETED.value,
                        "scheduled_date": scheduled,
                        "started_at": started,
                        "completed_at": started + timedelta(minutes=duration),
                        "downtime_minutes": duration,
                        "technician": rng.choice(
                            ["R. Persson", "N. Adeyemi", "L. Fournier", "S. Iqbal"]
                        ),
                        "description": f"Scheduled preventive service for {machine.name}.",
                        "cost": round(rng.uniform(180, 1450), 2),
                        "reference": f"PM-{machine.code}-{scheduled.isoformat()}",
                    }
                )
                if last_completed is None or scheduled > last_completed:
                    last_completed = scheduled
                occurrence += 1
                days_back += MAINTENANCE_INTERVAL_DAYS

            # Corrective work for the machines that are currently down. These
            # are the "machines requiring attention" of spec section 7.
            if machine.status is MachineStatus.MAINTENANCE:
                started_on = self.reference_date - timedelta(days=MAINTENANCE_DAYS_BEFORE_TODAY)
                dataset.maintenance_records.append(
                    {
                        "id": derive_id("maintenance", machine.code, started_on, "CORRECTIVE"),
                        "machine_id": machine_id,
                        "maintenance_type": MaintenanceType.CORRECTIVE.value,
                        "status": MaintenanceStatus.IN_PROGRESS.value,
                        "scheduled_date": started_on,
                        "started_at": datetime.combine(started_on, time(7, 30), tzinfo=UTC),
                        "completed_at": None,
                        "downtime_minutes": 0,
                        "technician": "N. Adeyemi",
                        "description": (
                            f"Unplanned corrective maintenance on {machine.name}; "
                            "machine withdrawn from service."
                        ),
                        "cost": None,
                        "reference": f"CM-{machine.code}-{started_on.isoformat()}",
                    }
                )
            elif machine.status is MachineStatus.OFFLINE:
                reported_on = self.reference_date - timedelta(days=OFFLINE_DAYS_BEFORE_TODAY)
                dataset.maintenance_records.append(
                    {
                        "id": derive_id("maintenance", machine.code, reported_on, "CORRECTIVE"),
                        "machine_id": machine_id,
                        "maintenance_type": MaintenanceType.CORRECTIVE.value,
                        "status": MaintenanceStatus.SCHEDULED.value,
                        "scheduled_date": self.reference_date + timedelta(days=2),
                        "started_at": None,
                        "completed_at": None,
                        "downtime_minutes": 0,
                        "technician": "",
                        "description": (
                            f"{machine.name} reported offline; spindle drive fault "
                            "awaiting replacement part."
                        ),
                        "cost": None,
                        "reference": f"CM-{machine.code}-{reported_on.isoformat()}",
                    }
                )

            # Upcoming preventive service.
            next_due = (
                last_completed + timedelta(days=MAINTENANCE_INTERVAL_DAYS)
                if last_completed
                else self.reference_date + timedelta(days=MAINTENANCE_INTERVAL_DAYS)
            )
            dataset.maintenance_records.append(
                {
                    "id": derive_id("maintenance", machine.code, next_due, "SCHEDULED"),
                    "machine_id": machine_id,
                    "maintenance_type": MaintenanceType.PREVENTIVE.value,
                    "status": MaintenanceStatus.SCHEDULED.value,
                    "scheduled_date": next_due,
                    "started_at": None,
                    "completed_at": None,
                    "downtime_minutes": 0,
                    "technician": "",
                    "description": f"Next preventive service due for {machine.name}.",
                    "cost": None,
                    "reference": f"PM-{machine.code}-{next_due.isoformat()}-NEXT",
                }
            )

            machine_dates[machine.code] = {
                "last": last_completed or machine.commissioned,
                "next": next_due,
            }

        return machine_dates

    # -- machines -------------------------------------------------------------

    def _generate_machines(
        self,
        dataset: SeedDataset,
        machine_dates: dict[str, dict[str, date]],
    ) -> None:
        """Build machine rows, deriving utilisation from the generated history.

        Utilisation and cumulative downtime are computed from the production
        records rather than invented, so the machines board agrees with the
        production module instead of telling a different story.
        """
        window_start = self.reference_date - timedelta(days=UTILIZATION_WINDOW_DAYS)

        operating: dict[Any, int] = {}
        downtime_total: dict[Any, int] = {}

        for record in dataset.production_records:
            machine_id = record["machine_id"]
            downtime_total[machine_id] = (
                downtime_total.get(machine_id, 0) + record["downtime_minutes"]
            )
            if record["record_date"] >= window_start:
                operating[machine_id] = operating.get(machine_id, 0) + record["operating_minutes"]

        # The utilisation denominator is every minute the plant was scheduled to
        # run in the window, not merely the shifts this machine happened to work.
        # Counting only worked shifts would let a machine that sat idle all week
        # report full utilisation, because an idle shift produces no record at
        # all -- so the time it wasted would simply be missing from both sides of
        # the ratio.
        available_minutes = sum(
            shift.planned_minutes
            for day in self._dates()
            if day >= window_start and self._day_output_factor(day) > 0.0
            for shift in SHIFTS
        )

        for machine in MACHINES:
            machine_id = derive_id("machine", machine.code)
            utilization = (
                round(100.0 * operating.get(machine_id, 0) / available_minutes, 2)
                if available_minutes
                else 0.0
            )

            dataset.machines.append(
                {
                    "id": machine_id,
                    "code": machine.code,
                    "name": machine.name,
                    "machine_type": machine.machine_type.value,
                    "line_id": derive_id("factory_line", machine.line_code),
                    "status": machine.status.value,
                    "current_component_id": (
                        derive_id("component", machine.current_component_code)
                        if machine.current_component_code
                        else None
                    ),
                    "utilization_percentage": min(100.0, utilization),
                    "total_downtime_minutes": downtime_total.get(machine_id, 0),
                    "commissioned_date": machine.commissioned,
                    "last_maintenance_date": machine_dates[machine.code]["last"],
                    "next_maintenance_date": machine_dates[machine.code]["next"],
                }
            )

    # -- inventory ------------------------------------------------------------

    def _generate_inventory(self, dataset: SeedDataset) -> None:
        """Build inventory items and their movement ledger.

        The ledger is walked *backwards* from each item's known current
        quantity. That is what guarantees the final balance equals the item's
        stated stock exactly -- generating forwards from a guessed opening
        balance would drift, and the CRITICAL and LOW items the alerts panel
        depends on would stop being critical or low.

        Walking backwards also produces the shape spec section 31 asks for:
        issues are negative, so earlier balances are higher, and stock declines
        steadily between replenishments.
        """
        admin_id = derive_id("user", "admin@factory.local")
        inventory_manager_id = derive_id("user", "inventory@factory.local")

        for material in MATERIALS:
            item_id = derive_id("inventory_item", material.sku)

            dataset.inventory_items.append(
                {
                    "id": item_id,
                    "sku": material.sku,
                    "name": material.name,
                    "material_type": material.material_type,
                    # Raw materials are not components; only the component-typed
                    # stock lines link back to a manufactured part.
                    "component_id": None,
                    "unit": material.unit,
                    "current_quantity": material.current_quantity,
                    "minimum_stock": material.minimum_stock,
                    "reorder_point": material.reorder_point,
                    "maximum_stock": material.maximum_stock,
                    "supplier_name": material.supplier_name,
                    "supplier_lead_time_days": material.supplier_lead_time_days,
                    "unit_cost": material.unit_cost,
                    "last_counted_at": datetime.combine(
                        self.reference_date, time(6, 0), tzinfo=UTC
                    ),
                    # `status` is a generated column; deliberately not set here.
                }
            )

            # Build the movement list newest-first, then assign balances by
            # walking back from the current quantity.
            movements: list[dict[str, Any]] = []
            for days_ago in range(0, self.history_days):
                day = self.reference_date - timedelta(days=days_ago)
                if self._day_output_factor(day) == 0.0:
                    continue

                rng = rng_for(self.random_seed, "inventory", material.sku, day)

                consumed = material.daily_consumption * rng.uniform(0.82, 1.18)
                movements.append(
                    {
                        "type": InventoryTransactionType.ISSUE,
                        "delta": -round(consumed, 3),
                        "day": day,
                        "reference": f"ISS-{material.sku}-{day.isoformat()}",
                        "notes": "Issued to production.",
                        "created_by": inventory_manager_id,
                    }
                )

                # Periodic replenishment, offset per material.
                offset = stable_seed(material.sku) % REPLENISHMENT_INTERVAL_DAYS
                if days_ago % REPLENISHMENT_INTERVAL_DAYS == offset and days_ago > 0:
                    received = material.daily_consumption * rng.uniform(11.0, 16.0)
                    movements.append(
                        {
                            "type": InventoryTransactionType.RECEIPT,
                            "delta": round(received, 3),
                            "day": day,
                            "reference": f"GRN-{material.sku}-{day.isoformat()}",
                            "notes": f"Goods received from {material.supplier_name}.",
                            "created_by": inventory_manager_id,
                        }
                    )

                # Occasional stock-take correction.
                if rng.random() < 0.02:
                    movements.append(
                        {
                            "type": InventoryTransactionType.ADJUSTMENT,
                            "delta": round(material.daily_consumption * rng.uniform(-0.3, 0.3), 3)
                            or 1.0,
                            "day": day,
                            "reference": f"ADJ-{material.sku}-{day.isoformat()}",
                            "notes": "Stock-take correction.",
                            "created_by": admin_id,
                        }
                    )

            # Walk backwards: the newest movement lands on the current quantity.
            balance_after = float(material.current_quantity)
            for movement in movements:
                delta = float(movement["delta"])
                # A movement can only be recorded if the resulting balance is
                # non-negative; skip any that would violate the CHECK.
                if balance_after < 0:
                    break

                # Fixed hour per movement type, so that within a day the
                # chronological order matches the order balances were assigned
                # in. A random hour would let a receipt appear to happen after
                # the issue whose balance it precedes.
                occurred_at = datetime.combine(
                    movement["day"], _MOVEMENT_HOUR[movement["type"]], tzinfo=UTC
                )
                dataset.inventory_transactions.append(
                    {
                        "id": derive_id("inventory_transaction", movement["reference"]),
                        "inventory_item_id": item_id,
                        "transaction_type": movement["type"].value,
                        "quantity_delta": delta,
                        "balance_after": round(balance_after, 3),
                        "reference": movement["reference"],
                        "notes": movement["notes"],
                        "occurred_at": occurred_at,
                        "created_by": movement["created_by"],
                    }
                )
                balance_after = round(balance_after - delta, 3)

    # -- alerts ---------------------------------------------------------------

    def _generate_alerts(self, dataset: SeedDataset) -> None:
        """Derive alerts from the state the rest of the seed produced.

        Alerts are not invented independently: each one refers to a condition
        that is genuinely visible in the seeded data, so a user who follows an
        alert to its module finds the situation it describes.
        """
        now = datetime.combine(self.reference_date, time(6, 30), tzinfo=UTC)
        manager_id = derive_id("user", "manager@factory.local")

        def add(
            *,
            key: str,
            alert_type: AlertType,
            severity: AlertSeverity,
            title: str,
            description: str,
            triggered_at: datetime,
            status: AlertStatus = AlertStatus.OPEN,
            machine_code: str | None = None,
            component_code: str | None = None,
            sku: str | None = None,
            line_code: str | None = None,
        ) -> None:
            acknowledged_at = (
                triggered_at + timedelta(hours=1)
                if status in (AlertStatus.ACKNOWLEDGED, AlertStatus.RESOLVED)
                else None
            )
            dataset.alerts.append(
                {
                    "id": derive_id("alert", key),
                    "alert_type": alert_type.value,
                    "severity": severity.value,
                    "status": status.value,
                    "title": title,
                    "description": description,
                    "machine_id": derive_id("machine", machine_code) if machine_code else None,
                    "component_id": (
                        derive_id("component", component_code) if component_code else None
                    ),
                    "inventory_item_id": derive_id("inventory_item", sku) if sku else None,
                    "line_id": derive_id("factory_line", line_code) if line_code else None,
                    "triggered_at": triggered_at,
                    "acknowledged_at": acknowledged_at,
                    "acknowledged_by": manager_id if acknowledged_at else None,
                    "resolved_at": (
                        triggered_at + timedelta(hours=5)
                        if status is AlertStatus.RESOLVED
                        else None
                    ),
                    "dedupe_key": key,
                }
            )

        # -- inventory alerts, straight from the stock thresholds --------------
        for material in MATERIALS:
            if material.current_quantity <= material.minimum_stock:
                add(
                    key=f"inventory:critical:{material.sku}",
                    alert_type=AlertType.CRITICAL_INVENTORY,
                    severity=AlertSeverity.CRITICAL,
                    title=f"Critical stock: {material.name}",
                    description=(
                        f"{material.name} is at {material.current_quantity:,.0f} "
                        f"{material.unit}, at or below the minimum of "
                        f"{material.minimum_stock:,.0f}. Supplier lead time is "
                        f"{material.supplier_lead_time_days} days; production on "
                        f"dependent lines is at risk."
                    ),
                    triggered_at=now - timedelta(hours=9),
                    sku=material.sku,
                )
            elif material.current_quantity <= material.reorder_point:
                add(
                    key=f"inventory:low:{material.sku}",
                    alert_type=AlertType.LOW_INVENTORY,
                    severity=AlertSeverity.WARNING,
                    title=f"Reorder due: {material.name}",
                    description=(
                        f"{material.name} has fallen to "
                        f"{material.current_quantity:,.0f} {material.unit}, below the "
                        f"reorder point of {material.reorder_point:,.0f}. Raise a "
                        f"purchase order to cover the "
                        f"{material.supplier_lead_time_days}-day lead time."
                    ),
                    triggered_at=now - timedelta(hours=20),
                    sku=material.sku,
                )

        # -- machine state alerts ---------------------------------------------
        for machine in MACHINES:
            if machine.status is MachineStatus.OFFLINE:
                add(
                    key=f"machine:offline:{machine.code}",
                    alert_type=AlertType.MACHINE_OFFLINE,
                    severity=AlertSeverity.CRITICAL,
                    title=f"{machine.code} offline",
                    description=(
                        f"{machine.name} has been offline since "
                        f"{(self.reference_date - timedelta(days=OFFLINE_DAYS_BEFORE_TODAY))}. "
                        "A spindle drive fault is awaiting a replacement part; the "
                        "line is running short-handed."
                    ),
                    triggered_at=now - timedelta(days=OFFLINE_DAYS_BEFORE_TODAY),
                    machine_code=machine.code,
                    line_code=machine.line_code,
                )
            elif machine.status is MachineStatus.MAINTENANCE:
                add(
                    key=f"machine:maintenance:{machine.code}",
                    alert_type=AlertType.MAINTENANCE_DUE,
                    severity=AlertSeverity.WARNING,
                    title=f"{machine.code} under maintenance",
                    description=(
                        f"{machine.name} is withdrawn from service for unplanned "
                        "corrective maintenance. Output for the line is reduced "
                        "until it returns."
                    ),
                    triggered_at=now - timedelta(days=MAINTENANCE_DAYS_BEFORE_TODAY),
                    status=AlertStatus.ACKNOWLEDGED,
                    machine_code=machine.code,
                    line_code=machine.line_code,
                )

        # -- quality: the deliberate defect spike ------------------------------
        add(
            key=f"quality:defect-spike:{DEFECT_SPIKE_COMPONENT}",
            alert_type=AlertType.HIGH_DEFECT_RATE,
            severity=AlertSeverity.WARNING,
            title="Elevated defect rate on Steering Knuckle",
            description=(
                "Steering Knuckle rejection rates ran roughly three times the "
                "normal level for eight days. Dimensional out-of-tolerance was the "
                "dominant category. The cause was traced to tool wear on the "
                "Line C milling centre and corrected."
            ),
            triggered_at=now - timedelta(days=DEFECT_SPIKE_START_DAYS_AGO),
            status=AlertStatus.RESOLVED,
            component_code=DEFECT_SPIKE_COMPONENT,
            line_code="LINE-C",
        )

        # -- production target risk -------------------------------------------
        add(
            key="production:target-risk:LINE-C",
            alert_type=AlertType.PRODUCTION_TARGET_RISK,
            severity=AlertSeverity.WARNING,
            title="Line C at risk of missing today's target",
            description=(
                "Line C is tracking below its daily target with one machine "
                "offline. Consider redistributing steering knuckle volume to the "
                "remaining machining centre."
            ),
            triggered_at=now - timedelta(hours=3),
            line_code="LINE-C",
        )

        # -- informational ------------------------------------------------------
        add(
            key="maintenance:window:LINE-B",
            alert_type=AlertType.MAINTENANCE_DUE,
            severity=AlertSeverity.INFO,
            title="Planned maintenance window on Line B",
            description=(
                "The heat treatment unit is scheduled for its next preventive "
                "service. Plan drivetrain throughput around the window."
            ),
            triggered_at=now - timedelta(hours=30),
            status=AlertStatus.ACKNOWLEDGED,
            line_code="LINE-B",
        )

    # -- audit ----------------------------------------------------------------

    def _generate_audit_logs(self, dataset: SeedDataset) -> None:
        """Seed a short audit trail so the log has shape before Phase 3.

        No identifier is assigned: audit_logs uses a bigint identity column, and
        letting the database allocate it is what keeps the trail append-only.
        Idempotency comes from the `seed_key` in each row's metadata, which a
        partial unique index constrains. The seed inserts with ON CONFLICT DO
        NOTHING, so re-running adds nothing and the trail is never mutated --
        which is what the append-only trigger requires.
        """
        for index, user in enumerate(DEMO_USERS):
            occurred = datetime.combine(self.reference_date, time(5, 45), tzinfo=UTC) - timedelta(
                hours=index * 3
            )
            dataset.audit_logs.append(
                {
                    "actor_user_id": derive_id("user", user.email),
                    "action": "AUTH.LOGIN_SUCCESS",
                    "resource_type": "session",
                    "resource_id": None,
                    "success": True,
                    "request_id": f"seed-{index:04d}",
                    "ip_address": None,
                    "user_agent": "seed",
                    "metadata": {
                        "provider": "google",
                        "seed_key": f"login-success-{user.email}",
                    },
                    "occurred_at": occurred,
                }
            )

        dataset.audit_logs.append(
            {
                "actor_user_id": None,
                "action": "AUTH.LOGIN_FAILURE",
                "resource_type": "session",
                "resource_id": None,
                "success": False,
                "request_id": "seed-9001",
                "ip_address": None,
                "user_agent": "seed",
                "metadata": {"reason": "issuer_mismatch", "seed_key": "login-failure-1"},
                "occurred_at": datetime.combine(self.reference_date, time(4, 12), tzinfo=UTC),
            }
        )

    # -- entry point ----------------------------------------------------------

    def generate(self) -> SeedDataset:
        """Build the complete dataset.

        Generation order differs from insertion order: production is generated
        before machines because machine utilisation is derived from it. That is
        possible only because every identifier comes from `derive_id`, so a
        foreign key can be computed before the row it points at exists.
        """
        dataset = SeedDataset()

        self._generate_roles(dataset)
        self._generate_users(dataset)
        self._generate_lines(dataset)
        self._generate_shifts(dataset)
        self._generate_components(dataset)
        self._generate_defects(dataset)

        self._generate_production_and_quality(dataset)

        machine_dates = self._generate_maintenance(dataset)
        self._generate_machines(dataset, machine_dates)

        self._generate_inventory(dataset)
        self._generate_alerts(dataset)
        self._generate_audit_logs(dataset)

        return dataset


def generate_dataset(
    random_seed: int = 20260101,
    history_days: int = 90,
    reference_date: date | None = None,
) -> SeedDataset:
    """Convenience wrapper around :class:`FactoryDataGenerator`."""
    return FactoryDataGenerator(
        random_seed=random_seed,
        history_days=history_days,
        reference_date=reference_date,
    ).generate()
