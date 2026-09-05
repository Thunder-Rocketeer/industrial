"""Human-readable labels for every enum value.

Spec section 45 is unambiguous: state must never be conveyed by colour alone,
and the text must remain understandable in greyscale. That means every status
the API reports travels with a label the frontend can render as words.

The labels are produced server-side rather than mapped in the UI for two
reasons. A label is part of the API contract, so two components cannot render
the same status differently. And a new enum value added by a migration surfaces
here as a missing entry -- caught by a test -- rather than as a raw
`HEAT_TREATMENT_FAILURE` appearing on someone's screen.
"""

from __future__ import annotations

from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    AlertType,
    DefectSeverity,
    InventoryStatus,
    MachineStatus,
    MachineType,
    MaintenanceStatus,
    MaintenanceType,
)

MACHINE_STATUS_LABELS: dict[MachineStatus, str] = {
    MachineStatus.RUNNING: "Running",
    MachineStatus.IDLE: "Idle",
    MachineStatus.MAINTENANCE: "Under maintenance",
    MachineStatus.OFFLINE: "Offline",
}

MACHINE_TYPE_LABELS: dict[MachineType, str] = {
    MachineType.CNC_TURNING_CENTER: "CNC Turning Center",
    MachineType.CNC_MILLING_CENTER: "CNC Milling Center",
    MachineType.VERTICAL_MACHINING_CENTER: "Vertical Machining Center",
    MachineType.GRINDING_MACHINE: "Grinding Machine",
    MachineType.HEAT_TREATMENT_UNIT: "Heat Treatment Unit",
    MachineType.INSPECTION_STATION: "Inspection Station",
    MachineType.ASSEMBLY_STATION: "Assembly Station",
}

INVENTORY_STATUS_LABELS: dict[InventoryStatus, str] = {
    InventoryStatus.HEALTHY: "Healthy",
    InventoryStatus.LOW: "Low",
    InventoryStatus.CRITICAL: "Critical",
    InventoryStatus.OVERSTOCKED: "Overstocked",
}

ALERT_SEVERITY_LABELS: dict[AlertSeverity, str] = {
    AlertSeverity.INFO: "Info",
    AlertSeverity.WARNING: "Warning",
    AlertSeverity.CRITICAL: "Critical",
}

ALERT_STATUS_LABELS: dict[AlertStatus, str] = {
    AlertStatus.OPEN: "Open",
    AlertStatus.ACKNOWLEDGED: "Acknowledged",
    AlertStatus.RESOLVED: "Resolved",
}

ALERT_TYPE_LABELS: dict[AlertType, str] = {
    AlertType.CRITICAL_INVENTORY: "Critical inventory",
    AlertType.LOW_INVENTORY: "Low inventory",
    AlertType.MAINTENANCE_DUE: "Maintenance due",
    AlertType.MAINTENANCE_OVERDUE: "Maintenance overdue",
    AlertType.PRODUCTION_TARGET_RISK: "Production target at risk",
    AlertType.HIGH_DEFECT_RATE: "High defect rate",
    AlertType.MACHINE_OFFLINE: "Machine offline",
}

MAINTENANCE_STATUS_LABELS: dict[MaintenanceStatus, str] = {
    MaintenanceStatus.SCHEDULED: "Scheduled",
    MaintenanceStatus.IN_PROGRESS: "In progress",
    MaintenanceStatus.COMPLETED: "Completed",
    MaintenanceStatus.CANCELLED: "Cancelled",
}

MAINTENANCE_TYPE_LABELS: dict[MaintenanceType, str] = {
    MaintenanceType.PREVENTIVE: "Preventive",
    MaintenanceType.CORRECTIVE: "Corrective",
    MaintenanceType.PREDICTIVE: "Predictive",
    MaintenanceType.CALIBRATION: "Calibration",
}

DEFECT_SEVERITY_LABELS: dict[DefectSeverity, str] = {
    DefectSeverity.MINOR: "Minor",
    DefectSeverity.MAJOR: "Major",
    DefectSeverity.CRITICAL: "Critical",
}


def label_for(value: object, mapping: dict, fallback: str = "Unknown") -> str:
    """Return a label, falling back to a readable form of the raw value.

    The fallback exists so that an enum value added by a migration but not yet
    added here renders as "Heat Treatment Failure" rather than crashing a
    dashboard. A test asserts every current value has a real entry, so the
    fallback should never be reached in practice.
    """
    if value in mapping:
        return mapping[value]
    raw = getattr(value, "value", value)
    if isinstance(raw, str):
        return raw.replace("_", " ").title()
    return fallback


# =============================================================================
# KPI status thresholds
#
# The dashboard shows each KPI with a textual status. Thresholds live here so
# "what counts as a bad defect rate" is one decision rather than a number
# repeated across services (spec section 47: no magic numbers for business
# rules).
# =============================================================================

#: Production achievement, as a percentage.
ACHIEVEMENT_GOOD = 95.0
ACHIEVEMENT_WARNING = 85.0

#: Defect rate, as a percentage. Lower is better, so the comparison inverts.
DEFECT_RATE_GOOD = 3.0
DEFECT_RATE_WARNING = 6.0

#: OEE, as a percentage. 85% is the widely cited "world class" figure.
OEE_GOOD = 75.0
OEE_WARNING = 60.0

#: Machine availability, as a percentage.
AVAILABILITY_GOOD = 85.0
AVAILABILITY_WARNING = 70.0

#: Inventory health, as a percentage of stock lines in a healthy state.
INVENTORY_HEALTH_GOOD = 80.0
INVENTORY_HEALTH_WARNING = 60.0

STATUS_LABELS = {
    "good": "On target",
    "warning": "Needs attention",
    "critical": "Action required",
    "neutral": "No data",
}


def status_for(value: float, good: float, warning: float, *, higher_is_better: bool = True) -> str:
    """Classify a KPI value as good, warning or critical.

    Args:
        higher_is_better: False for metrics such as defect rate, where crossing
            a threshold upward is the bad direction.

    Returns:
        One of ``good``, ``warning`` or ``critical`` -- never a colour. The
        frontend maps these to colour *and* text, so the meaning survives
        greyscale (spec section 45).
    """
    if higher_is_better:
        if value >= good:
            return "good"
        return "warning" if value >= warning else "critical"

    if value <= good:
        return "good"
    return "warning" if value <= warning else "critical"


def trend_direction(change_percentage: float | None) -> str:
    """Describe a trend as a word rather than an arrow or a colour."""
    if change_percentage is None:
        return "unknown"
    if change_percentage > 0.05:
        return "up"
    if change_percentage < -0.05:
        return "down"
    return "flat"
