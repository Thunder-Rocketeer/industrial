"""Machine business logic."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from app.cache.service import CacheService, CacheTier
from app.models.enums import MachineStatus, MachineType
from app.repositories.machines import MachineRepository
from app.repositories.maintenance import MaintenanceRepository
from app.schemas.filters import MachineFilters
from app.schemas.machines import (
    MachineDetail,
    MachineFleetSummary,
    MachineProductionStats,
    MachineStatusCount,
    MachineSummary,
)
from app.services import kpi
from app.services.labels import MACHINE_STATUS_LABELS, MACHINE_TYPE_LABELS, label_for
from app.services.maintenance_service import MaintenanceService

#: A machine is flagged as due for service this many days ahead. Named because
#: it is a business policy, not an arbitrary constant (spec section 47).
MAINTENANCE_ATTENTION_DAYS = 7

#: Window used for a machine's production statistics when none is supplied.
DEFAULT_STATS_DAYS = 30


class MachineService:
    """Machine reads, with derived statistics and caching."""

    def __init__(
        self,
        repository: MachineRepository,
        maintenance_repository: MaintenanceRepository,
        cache: CacheService,
    ) -> None:
        self._repository = repository
        self._maintenance = maintenance_repository
        self._cache = cache

    async def list_machines(self, filters: MachineFilters) -> list[MachineSummary]:
        """Return machines matching the filter.

        Uncached: the fleet is small, the query is a single indexed scan, and
        machine status is the most volatile thing on the dashboard. Caching it
        would trade a negligible saving for a stale status board.
        """
        rows = await self._repository.get_machines(status=filters.status, line_id=filters.line_id)
        today = date.today()
        return [self._to_summary(row, today) for row in rows]

    async def get_machine(
        self,
        machine_id: UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> MachineDetail | None:
        """Return one machine with its statistics and maintenance history.

        Returns None when the machine does not exist, so the route can turn that
        into a 404 rather than the service inventing an HTTP concern.
        """
        row = await self._repository.get_machine(machine_id)
        if row is None:
            return None

        today = date.today()
        end = end_date or today
        start = start_date or (end - timedelta(days=DEFAULT_STATS_DAYS - 1))

        stats = await self._repository.get_machine_production_stats(
            machine_id=machine_id, start_date=start, end_date=end
        )
        recent = await self._maintenance.get_recent_for_machine(machine_id=machine_id, limit=5)
        upcoming = await self._maintenance.get_upcoming_for_machine(machine_id=machine_id, limit=5)

        summary = self._to_summary(row, today)
        return MachineDetail(
            **summary.model_dump(),
            production=self._to_production_stats(stats),
            recent_maintenance=[MaintenanceService.build_record(r, today) for r in recent],
            upcoming_maintenance=[MaintenanceService.build_record(r, today) for r in upcoming],
        )

    async def get_fleet_summary(self) -> MachineFleetSummary:
        """Return fleet-level availability, cached."""
        return await self._cache.get_or_set(
            self._cache.keys.machines_summary(),
            CacheTier.REALTIME,
            MachineFleetSummary,
            self._build_fleet_summary,
        )

    async def _build_fleet_summary(self) -> MachineFleetSummary:
        totals = await self._repository.get_machine_summary()
        return self.build_fleet_summary_from_totals(totals)

    @staticmethod
    def build_fleet_summary_from_totals(totals: dict[str, Any]) -> MachineFleetSummary:
        """Assemble the fleet summary from repository counts."""
        total = int(totals.get("total_machines") or 0)
        running = int(totals.get("running_count") or 0)
        idle = int(totals.get("idle_count") or 0)
        maintenance = int(totals.get("maintenance_count") or 0)
        offline = int(totals.get("offline_count") or 0)

        return MachineFleetSummary(
            total_machines=total,
            running_count=running,
            idle_count=idle,
            maintenance_count=maintenance,
            offline_count=offline,
            # Only RUNNING counts as available. An idle machine is capable but
            # not producing, and counting it as available would make a stopped
            # line look healthy.
            availability_percentage=kpi.as_percentage(running, total, cap=100.0),
            average_utilization_percentage=round(
                float(totals.get("average_utilization") or 0.0), kpi.PERCENTAGE_PRECISION
            ),
            maintenance_due_count=int(totals.get("maintenance_due_count") or 0),
            status_breakdown=[
                MachineStatusCount(
                    status=status,
                    status_label=label_for(status, MACHINE_STATUS_LABELS),
                    count=count,
                )
                for status, count in (
                    (MachineStatus.RUNNING, running),
                    (MachineStatus.IDLE, idle),
                    (MachineStatus.MAINTENANCE, maintenance),
                    (MachineStatus.OFFLINE, offline),
                )
            ],
        )

    # -- mapping --------------------------------------------------------------

    @staticmethod
    def _to_summary(row: dict[str, Any], today: date) -> MachineSummary:
        status = MachineStatus(row["status"])
        machine_type = MachineType(row["machine_type"])

        next_due = row["next_maintenance_date"]
        days_until = (next_due - today).days if next_due else None
        # Overdue counts as due: a negative number must not read as "not yet".
        maintenance_due = days_until is not None and days_until <= MAINTENANCE_ATTENTION_DAYS

        return MachineSummary(
            id=row["id"],
            code=row["code"],
            name=row["name"],
            machine_type=machine_type,
            machine_type_label=label_for(machine_type, MACHINE_TYPE_LABELS),
            line_id=row["line_id"],
            line_code=row["line_code"],
            line_name=row["line_name"],
            status=status,
            status_label=label_for(status, MACHINE_STATUS_LABELS),
            current_component_id=row["current_component_id"],
            current_component_name=row["current_component_name"],
            utilization_percentage=round(
                float(row["utilization_percentage"]), kpi.PERCENTAGE_PRECISION
            ),
            total_downtime_minutes=int(row["total_downtime_minutes"]),
            commissioned_date=row["commissioned_date"],
            last_maintenance_date=row["last_maintenance_date"],
            next_maintenance_date=next_due,
            days_until_maintenance=days_until,
            maintenance_due=maintenance_due,
        )

    @staticmethod
    def _to_production_stats(stats: dict[str, Any]) -> MachineProductionStats:
        operating = int(stats.get("operating_minutes") or 0)
        planned_minutes = int(stats.get("planned_minutes") or 0)
        produced = int(stats.get("produced_quantity") or 0)
        accepted = int(stats.get("accepted_quantity") or 0)
        rejected = int(stats.get("rejected_quantity") or 0)
        ideal_units = float(stats.get("ideal_output_units") or 0.0)

        availability = kpi.availability(operating, planned_minutes)
        # The ideal-output denominator is summed in SQL because it depends on
        # each run's component cycle time; here it is just a ratio.
        performance = kpi.as_percentage(produced, ideal_units, cap=kpi.MAX_PERCENTAGE)
        quality = kpi.quality_rate(accepted, produced)

        return MachineProductionStats(
            produced_quantity=produced,
            accepted_quantity=accepted,
            rejected_quantity=rejected,
            planned_quantity=int(stats.get("planned_quantity") or 0),
            operating_minutes=operating,
            planned_minutes=planned_minutes,
            downtime_minutes=int(stats.get("downtime_minutes") or 0),
            run_count=int(stats.get("run_count") or 0),
            availability_percentage=availability,
            performance_percentage=performance,
            quality_percentage=quality,
            oee_percentage=kpi.oee(availability, performance, quality),
            defect_rate_percentage=kpi.defect_rate(rejected, produced),
        )
