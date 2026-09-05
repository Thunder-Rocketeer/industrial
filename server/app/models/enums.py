"""Domain enumerations mirroring the PostgreSQL enum types.

One definition per database type, kept in the same order as the migration that
creates it. These are the vocabulary shared by the seed, the repositories and
(from Phase 3) the API schemas, so a value never has to be spelled as a bare
string anywhere in the codebase.

Each subclasses `str` so members serialise directly to the wire representation
and can be passed to psycopg without conversion. `enum.StrEnum` would be
tidier, but it is Python 3.11+ and this project targets 3.10.
"""

from __future__ import annotations

from enum import Enum


class RoleCode(str, Enum):
    """RBAC roles (spec section 56)."""

    ADMIN = "ADMIN"
    FACTORY_MANAGER = "FACTORY_MANAGER"
    PRODUCTION_SUPERVISOR = "PRODUCTION_SUPERVISOR"
    QUALITY_ENGINEER = "QUALITY_ENGINEER"
    INVENTORY_MANAGER = "INVENTORY_MANAGER"
    VIEWER = "VIEWER"


class MachineType(str, Enum):
    """Machine capability class (spec section 5.5)."""

    CNC_TURNING_CENTER = "CNC_TURNING_CENTER"
    CNC_MILLING_CENTER = "CNC_MILLING_CENTER"
    VERTICAL_MACHINING_CENTER = "VERTICAL_MACHINING_CENTER"
    GRINDING_MACHINE = "GRINDING_MACHINE"
    HEAT_TREATMENT_UNIT = "HEAT_TREATMENT_UNIT"
    INSPECTION_STATION = "INSPECTION_STATION"
    ASSEMBLY_STATION = "ASSEMBLY_STATION"


class MachineStatus(str, Enum):
    """Live operational state of a machine (spec section 5.5)."""

    RUNNING = "RUNNING"
    IDLE = "IDLE"
    MAINTENANCE = "MAINTENANCE"
    OFFLINE = "OFFLINE"


class InventoryStatus(str, Enum):
    """Stock health (spec section 5.4).

    Derived by a generated column in the database, never written by the
    application. Mirrored here so services can reason about the values.
    """

    HEALTHY = "HEALTHY"
    LOW = "LOW"
    CRITICAL = "CRITICAL"
    OVERSTOCKED = "OVERSTOCKED"


class InventoryTransactionType(str, Enum):
    """Direction and reason for a stock movement."""

    RECEIPT = "RECEIPT"
    ISSUE = "ISSUE"
    RETURN = "RETURN"
    SCRAP = "SCRAP"
    ADJUSTMENT = "ADJUSTMENT"


class MaintenanceType(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    CORRECTIVE = "CORRECTIVE"
    PREDICTIVE = "PREDICTIVE"
    CALIBRATION = "CALIBRATION"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DefectSeverity(str, Enum):
    """How serious a defect occurrence is (spec section 5.3)."""

    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class AlertType(str, Enum):
    """Alert taxonomy (spec section 34)."""

    CRITICAL_INVENTORY = "CRITICAL_INVENTORY"
    LOW_INVENTORY = "LOW_INVENTORY"
    MAINTENANCE_DUE = "MAINTENANCE_DUE"
    MAINTENANCE_OVERDUE = "MAINTENANCE_OVERDUE"
    PRODUCTION_TARGET_RISK = "PRODUCTION_TARGET_RISK"
    HIGH_DEFECT_RATE = "HIGH_DEFECT_RATE"
    MACHINE_OFFLINE = "MACHINE_OFFLINE"


class AlertSeverity(str, Enum):
    """Spec section 34. Ordered least to most severe."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
