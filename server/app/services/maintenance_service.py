"""Maintenance business logic.

Not in the spec's required service list, but the maintenance endpoint needs the
same Router -> Service -> Repository path as everything else. Letting the route
call the repository directly would put data access in a handler, which is the
one thing spec section 8 is explicit about.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.models.enums import MaintenanceStatus, MaintenanceType
from app.repositories.maintenance import MaintenanceRepository
from app.schemas.filters import MaintenanceFilters
from app.schemas.machines import MaintenanceRecord
from app.services.labels import (
    MAINTENANCE_STATUS_LABELS,
    MAINTENANCE_TYPE_LABELS,
    label_for,
)


class MaintenanceService:
    """Maintenance reads."""

    def __init__(self, repository: MaintenanceRepository) -> None:
        self._repository = repository

    async def list_records(
        self, filters: MaintenanceFilters
    ) -> tuple[list[MaintenanceRecord], int]:
        """Return one page of maintenance jobs."""
        rows, total = await self._repository.get_maintenance_records(
            status=filters.status,
            machine_id=filters.machine_id,
            upcoming_only=filters.upcoming_only,
            limit=filters.limit,
            offset=filters.offset,
        )
        today = date.today()
        return [self.build_record(row, today) for row in rows], total

    @staticmethod
    def build_record(row: dict[str, Any], today: date) -> MaintenanceRecord:
        """Map a repository row to the response model.

        Shared with the machine service, which embeds maintenance history in a
        machine's detail response.
        """
        status = MaintenanceStatus(row["status"])
        maintenance_type = MaintenanceType(row["maintenance_type"])
        return MaintenanceRecord(
            id=row["id"],
            machine_id=row["machine_id"],
            machine_code=row["machine_code"],
            machine_name=row["machine_name"],
            maintenance_type=maintenance_type,
            maintenance_type_label=label_for(maintenance_type, MAINTENANCE_TYPE_LABELS),
            status=status,
            status_label=label_for(status, MAINTENANCE_STATUS_LABELS),
            scheduled_date=row["scheduled_date"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            downtime_minutes=int(row["downtime_minutes"]),
            technician=row["technician"],
            description=row["description"],
            cost=float(row["cost"]) if row["cost"] is not None else None,
            # Overdue means scheduled in the past and still outstanding.
            # A completed or cancelled job scheduled last month is not overdue.
            is_overdue=(
                row["scheduled_date"] < today
                and status in (MaintenanceStatus.SCHEDULED, MaintenanceStatus.IN_PROGRESS)
            ),
        )
