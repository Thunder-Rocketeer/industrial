"""The fixed definition of the demo factory.

Everything here is hand-written rather than generated: lines, machines,
components, shifts, roles, users, defect catalogue and materials. These are the
facts that give the generated history something to be about, and they are the
part a reader should be able to check at a glance against spec section 7.

Volume data -- production, quality, transactions, alerts -- is derived from this
catalogue in `generator.py`.

The per-machine `efficiency` and per-component `defect_propensity` factors are
what make the demo data feel like a real factory rather than noise (spec section
31: "some machines consistently more efficient", "a small defect spike on one
component"). They are fixed attributes, not random draws, so machine CNC-T-001
is reliably the strong performer on every run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time

from app.models.enums import (
    DefectSeverity,
    MachineStatus,
    MachineType,
    RoleCode,
)

# =============================================================================
# Roles and demo users
# =============================================================================


@dataclass(frozen=True)
class RoleSpec:
    code: RoleCode
    name: str
    description: str
    rank: int


ROLES: tuple[RoleSpec, ...] = (
    RoleSpec(RoleCode.ADMIN, "Administrator", "Full application administration.", 1),
    RoleSpec(
        RoleCode.FACTORY_MANAGER,
        "Factory Manager",
        "Reads all operational data and performs management functions.",
        2,
    ),
    RoleSpec(
        RoleCode.PRODUCTION_SUPERVISOR,
        "Production Supervisor",
        "Viewer access plus production operations.",
        3,
    ),
    RoleSpec(
        RoleCode.QUALITY_ENGINEER,
        "Quality Engineer",
        "Viewer access plus quality operations.",
        4,
    ),
    RoleSpec(
        RoleCode.INVENTORY_MANAGER,
        "Inventory Manager",
        "Viewer access plus inventory operations.",
        5,
    ),
    RoleSpec(RoleCode.VIEWER, "Viewer", "Reads the dashboard and analytics.", 6),
)


@dataclass(frozen=True)
class UserSpec:
    email: str
    full_name: str
    role: RoleCode


# Spec section 50. These are development-only identities: there is no password
# anywhere in the schema, so seeding them grants nobody access. A row becomes a
# usable login only when someone signs in through Google with the matching
# address, at which point the OAuth flow attaches the Google subject claim.
DEMO_USERS: tuple[UserSpec, ...] = (
    UserSpec("admin@factory.local", "Priya Raghavan", RoleCode.ADMIN),
    UserSpec("manager@factory.local", "Daniel Okonkwo", RoleCode.FACTORY_MANAGER),
    UserSpec("supervisor@factory.local", "Mei-Ling Chen", RoleCode.PRODUCTION_SUPERVISOR),
    UserSpec("quality@factory.local", "Tomas Novak", RoleCode.QUALITY_ENGINEER),
    UserSpec("inventory@factory.local", "Aisha Bello", RoleCode.INVENTORY_MANAGER),
    UserSpec("viewer@factory.local", "Jordan Whitfield", RoleCode.VIEWER),
)


# =============================================================================
# Factory lines (spec section 7)
# =============================================================================


@dataclass(frozen=True)
class LineSpec:
    code: str
    name: str
    description: str


FACTORY_LINES: tuple[LineSpec, ...] = (
    LineSpec("LINE-A", "Line A - Brake Components", "Brake discs and drums."),
    LineSpec("LINE-B", "Line B - Drivetrain Components", "Shafts, joints and gear blanks."),
    LineSpec("LINE-C", "Line C - Steering Components", "Steering knuckles and wheel hubs."),
    LineSpec("LINE-D", "Line D - Suspension Components", "Control arms and brackets."),
)


# =============================================================================
# Shifts (spec section 7)
#
# `planned_minutes` excludes scheduled breaks, so it is the productive time the
# shift is expected to deliver -- the denominator of OEE Availability.
# The night shift legitimately wraps past midnight.
# =============================================================================


@dataclass(frozen=True)
class ShiftSpec:
    code: str
    name: str
    start_time: time
    end_time: time
    sequence: int
    planned_minutes: int
    #: Output multiplier. Spec section 31: the morning shift starts slowly,
    #: production peaks during the day, and the night shift runs lighter.
    output_factor: float


SHIFTS: tuple[ShiftSpec, ...] = (
    ShiftSpec("MORNING", "Morning", time(6, 0), time(14, 0), 1, 450, 0.94),
    ShiftSpec("EVENING", "Evening", time(14, 0), time(22, 0), 2, 450, 1.00),
    ShiftSpec("NIGHT", "Night", time(22, 0), time(6, 0), 3, 420, 0.83),
)


# =============================================================================
# Components (spec section 7)
# =============================================================================


@dataclass(frozen=True)
class ComponentSpec:
    code: str
    name: str
    category: str
    line_code: str
    #: Ideal seconds per unit at rated speed. Denominator of OEE Performance.
    ideal_cycle_time_seconds: float
    #: Nominal units produced per machine per shift at 100% efficiency.
    nominal_shift_output: int
    #: Baseline fraction of units rejected, before machine and event effects.
    defect_propensity: float


COMPONENTS: tuple[ComponentSpec, ...] = (
    # Line A - brake
    ComponentSpec("BRK-DISC", "Brake Disc", "Braking", "LINE-A", 42.0, 620, 0.021),
    ComponentSpec("BRK-DRUM", "Brake Drum", "Braking", "LINE-A", 55.0, 470, 0.024),
    # Line B - drivetrain
    ComponentSpec("DRV-SHAFT", "Drive Shaft", "Drivetrain", "LINE-B", 78.0, 330, 0.026),
    ComponentSpec("CVJ-HOUSING", "CV Joint Housing", "Drivetrain", "LINE-B", 64.0, 400, 0.029),
    ComponentSpec("GER-BLANK", "Gear Blank", "Drivetrain", "LINE-B", 36.0, 720, 0.018),
    ComponentSpec("TRN-SHAFT", "Transmission Shaft", "Drivetrain", "LINE-B", 88.0, 290, 0.031),
    # Line C - steering
    ComponentSpec("STR-KNUCKLE", "Steering Knuckle", "Steering", "LINE-C", 96.0, 265, 0.034),
    ComponentSpec("WHL-HUB", "Wheel Hub", "Steering", "LINE-C", 58.0, 440, 0.023),
    # Line D - suspension
    ComponentSpec("SUS-CTRLARM", "Control Arm", "Suspension", "LINE-D", 71.0, 360, 0.027),
    ComponentSpec("SUS-BRACKET", "Suspension Bracket", "Suspension", "LINE-D", 33.0, 780, 0.016),
)


# =============================================================================
# Machines (spec section 7: at least 12, across all seven types, mixed states)
#
# 14 machines. `efficiency` is a fixed multiplier on nominal output, so the same
# machines are consistently the strong and weak performers across the whole
# history -- which is what makes the machine comparison charts meaningful rather
# than noise. `reliability` drives how often a machine suffers downtime.
# =============================================================================


@dataclass(frozen=True)
class MachineSpec:
    code: str
    name: str
    machine_type: MachineType
    line_code: str
    status: MachineStatus
    efficiency: float
    reliability: float
    commissioned: date
    #: Component this machine is set up to run. Required when status is RUNNING.
    current_component_code: str | None = None
    #: Components it can produce. Empty means "any component on its line".
    capable_component_codes: tuple[str, ...] = field(default_factory=tuple)


MACHINES: tuple[MachineSpec, ...] = (
    # ---- Line A: brake components -------------------------------------------
    MachineSpec(
        "CNC-T-001",
        "CNC Turning Center 1",
        MachineType.CNC_TURNING_CENTER,
        "LINE-A",
        MachineStatus.RUNNING,
        efficiency=1.06,
        reliability=0.97,
        commissioned=date(2021, 3, 15),
        current_component_code="BRK-DISC",
    ),
    MachineSpec(
        "CNC-M-002",
        "CNC Milling Center 2",
        MachineType.CNC_MILLING_CENTER,
        "LINE-A",
        MachineStatus.RUNNING,
        efficiency=0.98,
        reliability=0.94,
        commissioned=date(2021, 6, 2),
        current_component_code="BRK-DRUM",
    ),
    MachineSpec(
        "GRD-G-003",
        "Grinding Machine 3",
        MachineType.GRINDING_MACHINE,
        "LINE-A",
        MachineStatus.IDLE,
        efficiency=0.91,
        reliability=0.90,
        commissioned=date(2020, 11, 8),
    ),
    MachineSpec(
        "INS-I-004",
        "Inspection Station 4",
        MachineType.INSPECTION_STATION,
        "LINE-A",
        MachineStatus.RUNNING,
        efficiency=1.02,
        reliability=0.98,
        commissioned=date(2022, 1, 20),
        current_component_code="BRK-DISC",
    ),
    # ---- Line B: drivetrain --------------------------------------------------
    MachineSpec(
        "CNC-T-005",
        "CNC Turning Center 5",
        MachineType.CNC_TURNING_CENTER,
        "LINE-B",
        MachineStatus.RUNNING,
        efficiency=1.03,
        reliability=0.95,
        commissioned=date(2021, 9, 12),
        current_component_code="DRV-SHAFT",
    ),
    MachineSpec(
        "VMC-V-006",
        "Vertical Machining Center 6",
        MachineType.VERTICAL_MACHINING_CENTER,
        "LINE-B",
        MachineStatus.RUNNING,
        efficiency=0.96,
        reliability=0.92,
        commissioned=date(2020, 5, 30),
        current_component_code="CVJ-HOUSING",
    ),
    MachineSpec(
        "HTU-H-007",
        "Heat Treatment Unit 7",
        MachineType.HEAT_TREATMENT_UNIT,
        "LINE-B",
        MachineStatus.MAINTENANCE,
        efficiency=0.88,
        reliability=0.84,
        commissioned=date(2019, 8, 14),
    ),
    MachineSpec(
        "ASM-A-008",
        "Assembly Station 8",
        MachineType.ASSEMBLY_STATION,
        "LINE-B",
        MachineStatus.RUNNING,
        efficiency=1.00,
        reliability=0.96,
        commissioned=date(2022, 4, 5),
        current_component_code="GER-BLANK",
    ),
    # ---- Line C: steering ----------------------------------------------------
    MachineSpec(
        "CNC-M-009",
        "CNC Milling Center 9",
        MachineType.CNC_MILLING_CENTER,
        "LINE-C",
        MachineStatus.RUNNING,
        efficiency=0.93,
        reliability=0.89,
        commissioned=date(2020, 2, 18),
        current_component_code="STR-KNUCKLE",
    ),
    MachineSpec(
        "VMC-V-010",
        "Vertical Machining Center 10",
        MachineType.VERTICAL_MACHINING_CENTER,
        "LINE-C",
        MachineStatus.OFFLINE,
        efficiency=0.86,
        reliability=0.79,
        commissioned=date(2019, 4, 22),
    ),
    MachineSpec(
        "INS-I-011",
        "Inspection Station 11",
        MachineType.INSPECTION_STATION,
        "LINE-C",
        MachineStatus.IDLE,
        efficiency=1.01,
        reliability=0.97,
        commissioned=date(2022, 7, 9),
    ),
    # ---- Line D: suspension --------------------------------------------------
    MachineSpec(
        "CNC-T-012",
        "CNC Turning Center 12",
        MachineType.CNC_TURNING_CENTER,
        "LINE-D",
        MachineStatus.RUNNING,
        efficiency=1.04,
        reliability=0.96,
        commissioned=date(2021, 11, 3),
        current_component_code="SUS-CTRLARM",
    ),
    MachineSpec(
        "GRD-G-013",
        "Grinding Machine 13",
        MachineType.GRINDING_MACHINE,
        "LINE-D",
        MachineStatus.RUNNING,
        efficiency=0.94,
        reliability=0.91,
        commissioned=date(2020, 9, 27),
        current_component_code="SUS-BRACKET",
    ),
    MachineSpec(
        "ASM-A-014",
        "Assembly Station 14",
        MachineType.ASSEMBLY_STATION,
        "LINE-D",
        MachineStatus.MAINTENANCE,
        efficiency=0.90,
        reliability=0.87,
        commissioned=date(2019, 12, 11),
    ),
)


# =============================================================================
# Defect catalogue (spec section 5.3)
#
# `weight` sets how often each defect is drawn. The distribution is deliberately
# skewed -- the top three account for roughly two thirds of all rejections -- so
# a Pareto chart shows a real 80/20 shape instead of eight equal bars
# (spec section 7: "Make a few defects intentionally more frequent so the Pareto
# analysis is meaningful").
# =============================================================================


@dataclass(frozen=True)
class DefectSpec:
    code: str
    name: str
    category: str
    default_severity: DefectSeverity
    description: str
    weight: float


DEFECTS: tuple[DefectSpec, ...] = (
    DefectSpec(
        "DIMENSIONAL_OOT",
        "Dimensional Out-of-Tolerance",
        "Dimensional",
        DefectSeverity.MAJOR,
        "Measured feature falls outside the drawing tolerance band.",
        28.0,
    ),
    DefectSpec(
        "SURFACE_DEFECT",
        "Surface Defect",
        "Surface",
        DefectSeverity.MINOR,
        "Scoring, pitting or tool marks on a finished face.",
        22.0,
    ),
    DefectSpec(
        "BURR",
        "Burr",
        "Surface",
        DefectSeverity.MINOR,
        "Residual material left at an edge after machining.",
        16.0,
    ),
    DefectSpec(
        "CRACK",
        "Crack",
        "Structural",
        DefectSeverity.CRITICAL,
        "Visible or detected crack; the part is scrapped.",
        11.0,
    ),
    DefectSpec(
        "THREAD_DAMAGE",
        "Thread Damage",
        "Dimensional",
        DefectSeverity.MAJOR,
        "Stripped, crossed or incomplete thread form.",
        8.0,
    ),
    DefectSpec(
        "MATERIAL_DEFECT",
        "Material Defect",
        "Material",
        DefectSeverity.CRITICAL,
        "Inclusion, porosity or incorrect material grade.",
        6.0,
    ),
    DefectSpec(
        "INCORRECT_ASSEMBLY",
        "Incorrect Assembly",
        "Assembly",
        DefectSeverity.MAJOR,
        "Component assembled out of sequence or with the wrong part.",
        5.0,
    ),
    DefectSpec(
        "HEAT_TREATMENT_FAILURE",
        "Heat Treatment Failure",
        "Process",
        DefectSeverity.CRITICAL,
        "Hardness or case depth outside specification after treatment.",
        4.0,
    ),
)


# =============================================================================
# Inventory (spec section 5.4)
#
# The four stock states are covered deliberately, and several items sit in
# CRITICAL or LOW so the alerts panel has real content on first load (spec
# section 7: "Ensure at least a few items trigger alerts").
#
# `status` is a generated column in the database, so it is not set here. The
# quantities below are chosen to land in the intended band given the thresholds:
#   CRITICAL     current <= minimum
#   LOW          minimum < current <= reorder
#   OVERSTOCKED  current >= maximum
#   HEALTHY      otherwise
# =============================================================================


@dataclass(frozen=True)
class MaterialSpec:
    sku: str
    name: str
    material_type: str
    unit: str
    current_quantity: float
    minimum_stock: float
    reorder_point: float
    maximum_stock: float
    supplier_name: str
    supplier_lead_time_days: int
    unit_cost: float
    #: Nominal units drawn per production day, used to generate the ledger.
    daily_consumption: float
    #: The band this item is intended to land in. Asserted by the tests, so a
    #: careless edit to the quantities above cannot silently remove the
    #: CRITICAL items the alerts panel depends on.
    expected_status: str


MATERIALS: tuple[MaterialSpec, ...] = (
    MaterialSpec(
        "RM-STEEL-BILLET",
        "Steel Billets",
        "Raw Material",
        "kg",
        current_quantity=42_500,
        minimum_stock=8_000,
        reorder_point=15_000,
        maximum_stock=60_000,
        supplier_name="Nordkraft Steel AB",
        supplier_lead_time_days=21,
        unit_cost=1.85,
        daily_consumption=780,
        expected_status="HEALTHY",
    ),
    MaterialSpec(
        "RM-ALU-ALLOY",
        "Aluminium Alloy",
        "Raw Material",
        "kg",
        current_quantity=9_200,
        minimum_stock=4_000,
        reorder_point=9_500,
        maximum_stock=34_000,
        supplier_name="Lumière Métaux SA",
        supplier_lead_time_days=28,
        unit_cost=3.40,
        daily_consumption=310,
        expected_status="LOW",
    ),
    MaterialSpec(
        "RM-CAST-IRON",
        "Cast Iron",
        "Raw Material",
        "kg",
        current_quantity=27_800,
        minimum_stock=6_000,
        reorder_point=12_000,
        maximum_stock=45_000,
        supplier_name="Bharat Foundries Ltd",
        supplier_lead_time_days=18,
        unit_cost=1.20,
        daily_consumption=640,
        expected_status="HEALTHY",
    ),
    MaterialSpec(
        "CP-BEARING-ASSY",
        "Bearing Assemblies",
        "Component",
        "units",
        current_quantity=850,
        minimum_stock=1_200,
        reorder_point=2_500,
        maximum_stock=9_000,
        supplier_name="Kanto Precision KK",
        supplier_lead_time_days=35,
        unit_cost=14.75,
        daily_consumption=95,
        expected_status="CRITICAL",
    ),
    MaterialSpec(
        "CP-FASTENER",
        "Fasteners",
        "Component",
        "units",
        current_quantity=196_000,
        minimum_stock=20_000,
        reorder_point=45_000,
        maximum_stock=180_000,
        supplier_name="Ostrava Fixings s.r.o.",
        supplier_lead_time_days=10,
        unit_cost=0.08,
        daily_consumption=2_400,
        expected_status="OVERSTOCKED",
    ),
    MaterialSpec(
        "CS-LUBRICANT",
        "Lubricant",
        "Consumable",
        "litres",
        current_quantity=310,
        minimum_stock=400,
        reorder_point=900,
        maximum_stock=3_200,
        supplier_name="Helios Industrial Fluids",
        supplier_lead_time_days=14,
        unit_cost=6.30,
        daily_consumption=48,
        expected_status="CRITICAL",
    ),
    MaterialSpec(
        "CS-CUT-INSERT",
        "Cutting Inserts",
        "Consumable",
        "units",
        current_quantity=1_640,
        minimum_stock=900,
        reorder_point=1_800,
        maximum_stock=7_500,
        supplier_name="Alpine Carbide GmbH",
        supplier_lead_time_days=25,
        unit_cost=11.90,
        daily_consumption=72,
        expected_status="LOW",
    ),
    MaterialSpec(
        "PK-PACKAGING",
        "Packaging Material",
        "Packaging",
        "units",
        current_quantity=24_500,
        minimum_stock=5_000,
        reorder_point=11_000,
        maximum_stock=48_000,
        supplier_name="Verpakking Nederland BV",
        supplier_lead_time_days=7,
        unit_cost=0.42,
        daily_consumption=880,
        expected_status="HEALTHY",
    ),
)


# =============================================================================
# Lookups
# =============================================================================

LINES_BY_CODE = {line.code: line for line in FACTORY_LINES}
COMPONENTS_BY_CODE = {component.code: component for component in COMPONENTS}
MACHINES_BY_CODE = {machine.code: machine for machine in MACHINES}
SHIFTS_BY_CODE = {shift.code: shift for shift in SHIFTS}
DEFECTS_BY_CODE = {defect.code: defect for defect in DEFECTS}
MATERIALS_BY_SKU = {material.sku: material for material in MATERIALS}
ROLES_BY_CODE = {role.code: role for role in ROLES}


def components_for_line(line_code: str) -> tuple[ComponentSpec, ...]:
    """Return the components produced on a given line, in catalogue order."""
    return tuple(c for c in COMPONENTS if c.line_code == line_code)


def machines_for_line(line_code: str) -> tuple[MachineSpec, ...]:
    """Return the machines belonging to a given line, in catalogue order."""
    return tuple(m for m in MACHINES if m.line_code == line_code)


def capable_components(machine: MachineSpec) -> tuple[ComponentSpec, ...]:
    """Return the components a machine can produce.

    An explicit capability list wins; otherwise the machine can run anything on
    its own line.
    """
    if machine.capable_component_codes:
        return tuple(COMPONENTS_BY_CODE[code] for code in machine.capable_component_codes)
    return components_for_line(machine.line_code)
