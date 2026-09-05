-- =============================================================================
-- Migration 002 — enumerated domain types
--
-- Native enum types rather than text + CHECK. The domain is fixed and small, so
-- an enum documents the allowed values in the catalogue, keeps them out of
-- every dependent CHECK clause, and makes an invalid value impossible to store
-- rather than merely rejected in one place.
--
-- Values use SCREAMING_SNAKE so the wire representation is stable and
-- unambiguous; display labels are the API layer's concern.
--
-- Note: adding a value later requires ALTER TYPE ... ADD VALUE, which cannot
-- run inside a transaction block on PostgreSQL below 12. Supabase runs 15+, so
-- this is safe, but the constraint is worth knowing before extending a type.
-- =============================================================================

-- Machine capability class (spec section 5.5).
create type public.machine_type as enum (
  'CNC_TURNING_CENTER',
  'CNC_MILLING_CENTER',
  'VERTICAL_MACHINING_CENTER',
  'GRINDING_MACHINE',
  'HEAT_TREATMENT_UNIT',
  'INSPECTION_STATION',
  'ASSEMBLY_STATION'
);

-- Live operational state of a machine (spec section 5.5).
create type public.machine_status as enum (
  'RUNNING',
  'IDLE',
  'MAINTENANCE',
  'OFFLINE'
);

-- Stock health, derived rather than entered -- see inventory_items.status.
create type public.inventory_status as enum (
  'HEALTHY',
  'LOW',
  'CRITICAL',
  'OVERSTOCKED'
);

-- Direction and reason for a stock movement.
create type public.inventory_transaction_type as enum (
  'RECEIPT',      -- delivery from a supplier, increases stock
  'ISSUE',        -- consumed by production, decreases stock
  'RETURN',       -- unused material returned to store, increases stock
  'SCRAP',        -- written off, decreases stock
  'ADJUSTMENT'    -- stock-take correction, either direction
);

create type public.maintenance_type as enum (
  'PREVENTIVE',
  'CORRECTIVE',
  'PREDICTIVE',
  'CALIBRATION'
);

create type public.maintenance_status as enum (
  'SCHEDULED',
  'IN_PROGRESS',
  'COMPLETED',
  'CANCELLED'
);

-- How serious a defect occurrence is (spec section 5.3).
create type public.defect_severity as enum (
  'MINOR',
  'MAJOR',
  'CRITICAL'
);

-- Alert taxonomy (spec section 34).
create type public.alert_type as enum (
  'CRITICAL_INVENTORY',
  'LOW_INVENTORY',
  'MAINTENANCE_DUE',
  'MAINTENANCE_OVERDUE',
  'PRODUCTION_TARGET_RISK',
  'HIGH_DEFECT_RATE',
  'MACHINE_OFFLINE'
);

create type public.alert_severity as enum (
  'INFO',
  'WARNING',
  'CRITICAL'
);

create type public.alert_status as enum (
  'OPEN',
  'ACKNOWLEDGED',
  'RESOLVED'
);
