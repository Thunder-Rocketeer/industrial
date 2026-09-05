-- =============================================================================
-- Automobile Component Factory -- complete database schema
--
-- GENERATED FILE. Do not edit.
--
-- Built from supabase/migrations/ by `python tools/build_schema.py`.
-- The migrations are the source of truth; regenerate rather than editing here.
--
-- To apply: paste this file into the Supabase dashboard SQL editor and run it,
-- or  psql "$DATABASE_URL" -f supabase/schema.sql
--
-- The whole schema is wrapped in a single transaction, so a failure part-way
-- through leaves the database untouched rather than half-migrated.
--
-- Source migrations, in order:
--   20260101000100_schema_and_helpers.sql
--   20260101000200_enums.sql
--   20260101000300_reference_tables.sql
--   20260101000400_production_tables.sql
--   20260101000500_inventory_tables.sql
--   20260101000600_maintenance_alerts_audit.sql
--   20260101000700_indexes.sql
--   20260101000800_row_level_security.sql
-- =============================================================================

begin;


-- =============================================================================
-- BEGIN 20260101000100_schema_and_helpers.sql
-- =============================================================================

-- =============================================================================
-- Migration 001 — helper schema, trigger functions and authorization helpers
--
-- Establishes the groundwork every later migration depends on:
--   * an `app` schema that keeps helper routines out of `public`
--   * an updated_at trigger function
--   * an append-only guard used by audit_logs
--   * RBAC helper functions for the future direct-Supabase access path
--
-- Every function is declared with `SET search_path = ''` and refers to objects
-- by fully qualified name. Without that, a caller could prepend a schema to
-- search_path and shadow a referenced object -- a privilege-escalation vector
-- that Supabase's own security advisor flags.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Helper schema. Not exposed through PostgREST.
-- -----------------------------------------------------------------------------
create schema if not exists app;

comment on schema app is
  'Internal helper routines. Never exposed to PostgREST or to browser clients.';

revoke all on schema app from public;
revoke all on schema app from anon, authenticated;


-- -----------------------------------------------------------------------------
-- updated_at maintenance.
--
-- Applied as a BEFORE UPDATE trigger on every table carrying updated_at, so the
-- column is authoritative and cannot drift when a writer forgets to set it.
-- -----------------------------------------------------------------------------
create or replace function app.set_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

comment on function app.set_updated_at() is
  'BEFORE UPDATE trigger: stamps updated_at with the current UTC timestamp.';


-- -----------------------------------------------------------------------------
-- Append-only guard.
--
-- Spec section 67: an audit trail that can be edited is not an audit trail.
-- Enforced in the database so it holds regardless of which client connects --
-- including a backend bug or a service-role session.
-- -----------------------------------------------------------------------------
create or replace function app.prevent_mutation()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  raise exception
    'Table %.% is append-only; % is not permitted.',
    tg_table_schema, tg_table_name, tg_op
    using errcode = 'restrict_violation';
end;
$$;

comment on function app.prevent_mutation() is
  'BEFORE UPDATE OR DELETE trigger: rejects the operation. Used for audit_logs.';


-- -----------------------------------------------------------------------------
-- Authorization helpers.
--
-- The current architecture routes every read through FastAPI using the
-- service-role key, so these are not yet load-bearing. They exist so that the
-- RLS policies sketched in migration 008 can be enabled without redesigning
-- anything if direct Supabase access is ever introduced (spec section 66).
--
-- `auth.uid()` is Supabase's own function returning the authenticated user's
-- UUID from the request JWT; it returns NULL for anonymous requests.
-- -----------------------------------------------------------------------------
create or replace function app.current_user_id()
returns uuid
language sql
stable
security invoker
set search_path = ''
as $$
  select id
  from public.users
  where auth_user_id = auth.uid()
    and is_active
  limit 1;
$$;

comment on function app.current_user_id() is
  'Maps the Supabase auth subject to a row in public.users. NULL when anonymous.';


create or replace function app.current_user_role()
returns text
language sql
stable
security invoker
set search_path = ''
as $$
  select r.code
  from public.users u
  join public.roles r on r.id = u.role_id
  where u.auth_user_id = auth.uid()
    and u.is_active
  limit 1;
$$;

comment on function app.current_user_role() is
  'Returns the role code of the calling user, or NULL when anonymous.';


create or replace function app.has_role(required_roles text[])
returns boolean
language sql
stable
security invoker
set search_path = ''
as $$
  select coalesce(app.current_user_role() = any(required_roles), false);
$$;

comment on function app.has_role(text[]) is
  'True when the calling user holds one of the supplied role codes.';

-- =============================================================================
-- BEGIN 20260101000200_enums.sql
-- =============================================================================

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

-- =============================================================================
-- BEGIN 20260101000300_reference_tables.sql
-- =============================================================================

-- =============================================================================
-- Migration 003 — reference and master data
--
--   roles -> users
--   factory_lines -> components
--   factory_lines -> machines -> components (currently produced)
--   shifts
--   defects
--
-- Every table carries a stable, human-meaningful `code` alongside its UUID
-- primary key. The UUID is what foreign keys reference; the code is what the
-- seed derives deterministic UUIDs from (uuid5 over the code), which is what
-- makes re-seeding idempotent without storing a mapping table anywhere.
--
-- All timestamps are `timestamptz`, which PostgreSQL normalises to UTC on
-- write (spec section 6). Conversion to local time is the frontend's job.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- roles — RBAC role catalogue (spec section 56)
-- -----------------------------------------------------------------------------
create table public.roles (
  id          uuid primary key default gen_random_uuid(),
  code        text        not null,
  name        text        not null,
  description text        not null default '',
  -- Ordering for display and for "at least this privileged" comparisons.
  -- Not a permission model in itself; authorization is decided in the backend
  -- policy module (spec section 56), never by comparing ranks alone.
  rank        smallint    not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),

  constraint roles_code_key unique (code),
  constraint roles_rank_key unique (rank),
  constraint roles_code_format_check
    check (code ~ '^[A-Z][A-Z0-9_]{1,39}$'),
  constraint roles_rank_range_check
    check (rank between 1 and 100)
);

comment on table public.roles is
  'Role catalogue backing RBAC. Authorization decisions are enforced in the backend policy module; this table names the roles.';

create trigger roles_set_updated_at
  before update on public.roles
  for each row execute function app.set_updated_at();


-- -----------------------------------------------------------------------------
-- users — application identities
--
-- There is deliberately no password column. Authentication is Google
-- OAuth 2.0 / OIDC (spec section 54), so no credential is ever stored here and
-- the "do not store plaintext passwords" requirement is satisfied structurally
-- rather than by convention.
--
-- `google_sub` is the OIDC `sub` claim: the only Google identifier guaranteed
-- stable for a user. Email can be reassigned within a Google Workspace domain,
-- so it is a lookup key, never the identity.
-- -----------------------------------------------------------------------------
create table public.users (
  id            uuid primary key default gen_random_uuid(),
  email         text        not null,
  full_name     text        not null,
  role_id       uuid        not null,
  -- Set on first successful Google sign-in; NULL for seeded demo accounts that
  -- nobody has logged into yet.
  google_sub    text,
  -- Links to Supabase's own auth.users, used only by the RLS helper functions.
  auth_user_id  uuid,
  is_active     boolean     not null default true,
  last_login_at timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  constraint users_role_id_fkey
    foreign key (role_id) references public.roles (id)
    on delete restrict,
  constraint users_email_key unique (email),
  constraint users_google_sub_key unique (google_sub),
  constraint users_auth_user_id_key unique (auth_user_id),
  -- Stored lowercase so the unique constraint is genuinely case-insensitive
  -- without depending on the citext extension.
  constraint users_email_lowercase_check
    check (email = lower(email)),
  constraint users_email_format_check
    check (email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  constraint users_full_name_not_blank_check
    check (length(btrim(full_name)) > 0)
);

comment on table public.users is
  'Application identities. No password column by design: authentication is Google OAuth/OIDC.';
comment on column public.users.google_sub is
  'Google OIDC subject claim. The stable identity; email is only a lookup key.';

create trigger users_set_updated_at
  before update on public.users
  for each row execute function app.set_updated_at();


-- -----------------------------------------------------------------------------
-- factory_lines — production lines (spec section 7)
-- -----------------------------------------------------------------------------
create table public.factory_lines (
  id          uuid primary key default gen_random_uuid(),
  code        text        not null,
  name        text        not null,
  description text        not null default '',
  is_active   boolean     not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),

  constraint factory_lines_code_key unique (code),
  constraint factory_lines_code_format_check
    check (code ~ '^LINE-[A-Z]$'),
  constraint factory_lines_name_not_blank_check
    check (length(btrim(name)) > 0)
);

comment on table public.factory_lines is
  'Production lines. Four are seeded: brake, drivetrain, steering and suspension components.';

create trigger factory_lines_set_updated_at
  before update on public.factory_lines
  for each row execute function app.set_updated_at();


-- -----------------------------------------------------------------------------
-- components — the parts the factory manufactures (spec section 7)
-- -----------------------------------------------------------------------------
create table public.components (
  id       uuid primary key default gen_random_uuid(),
  code     text        not null,
  name     text        not null,
  category text        not null,
  line_id  uuid        not null,
  -- Unit of measure for produced quantities.
  unit     text        not null default 'units',
  -- Ideal seconds per unit at rated speed. This is the denominator of the OEE
  -- Performance term (spec section 43), so it belongs with the component rather
  -- than being hard-coded in a service.
  ideal_cycle_time_seconds numeric(8, 2) not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint components_line_id_fkey
    foreign key (line_id) references public.factory_lines (id)
    on delete restrict,
  constraint components_code_key unique (code),
  constraint components_code_format_check
    check (code ~ '^[A-Z][A-Z0-9-]{2,23}$'),
  constraint components_cycle_time_positive_check
    check (ideal_cycle_time_seconds > 0),
  constraint components_name_not_blank_check
    check (length(btrim(name)) > 0)
);

comment on column public.components.ideal_cycle_time_seconds is
  'Ideal seconds per unit. Denominator of the OEE Performance calculation.';

create trigger components_set_updated_at
  before update on public.components
  for each row execute function app.set_updated_at();


-- -----------------------------------------------------------------------------
-- shifts — the working day (spec section 7)
--
-- `planned_minutes` is the Availability denominator (spec section 43): the time
-- the shift is scheduled to produce, excluding planned breaks.
-- -----------------------------------------------------------------------------
create table public.shifts (
  id             uuid primary key default gen_random_uuid(),
  code           text        not null,
  name           text        not null,
  start_time     time        not null,
  end_time       time        not null,
  sequence       smallint    not null,
  planned_minutes integer    not null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),

  constraint shifts_code_key unique (code),
  constraint shifts_sequence_key unique (sequence),
  constraint shifts_sequence_range_check
    check (sequence between 1 and 10),
  -- A shift is at most 24h; the night shift legitimately wraps past midnight,
  -- so start < end is deliberately NOT required.
  constraint shifts_planned_minutes_range_check
    check (planned_minutes between 1 and 1440)
);

comment on column public.shifts.planned_minutes is
  'Scheduled productive minutes excluding breaks. Denominator of OEE Availability.';
comment on column public.shifts.end_time is
  'May be earlier than start_time: the night shift wraps past midnight.';

create trigger shifts_set_updated_at
  before update on public.shifts
  for each row execute function app.set_updated_at();


-- -----------------------------------------------------------------------------
-- machines — equipment on the shop floor (spec section 5.5)
--
-- The UNIQUE (id, line_id) constraint at the end looks redundant next to the
-- primary key, and on its own it is. Its purpose is to serve as the target of a
-- composite foreign key from production_records, which carries a denormalised
-- line_id for query performance. That composite FK is what makes the
-- denormalisation provably consistent -- the database rejects any production
-- row whose line_id disagrees with its machine's line, so the two can never
-- drift. See migration 004.
-- -----------------------------------------------------------------------------
create table public.machines (
  id                   uuid primary key default gen_random_uuid(),
  code                 text                  not null,
  name                 text                  not null,
  machine_type         public.machine_type   not null,
  line_id              uuid                  not null,
  status               public.machine_status not null default 'IDLE',
  -- What the machine is set up to run right now. NULL when idle or offline.
  current_component_id uuid,
  -- Rolling utilisation percentage shown on the machines board.
  utilization_percentage numeric(5, 2)       not null default 0,
  -- Cumulative unplanned downtime, in minutes.
  total_downtime_minutes integer             not null default 0,
  commissioned_date      date                not null,
  last_maintenance_date  date,
  next_maintenance_date  date,
  created_at             timestamptz         not null default now(),
  updated_at             timestamptz         not null default now(),

  constraint machines_line_id_fkey
    foreign key (line_id) references public.factory_lines (id)
    on delete restrict,
  constraint machines_current_component_id_fkey
    foreign key (current_component_id) references public.components (id)
    on delete set null,
  constraint machines_code_key unique (code),
  constraint machines_code_format_check
    check (code ~ '^[A-Z]{2,4}-[A-Z]{1,3}-[0-9]{3}$'),
  constraint machines_utilization_range_check
    check (utilization_percentage between 0 and 100),
  constraint machines_downtime_non_negative_check
    check (total_downtime_minutes >= 0),
  -- A running machine must be set up with something to run.
  constraint machines_running_requires_component_check
    check (status <> 'RUNNING' or current_component_id is not null),
  constraint machines_maintenance_order_check
    check (
      last_maintenance_date is null
      or next_maintenance_date is null
      or next_maintenance_date >= last_maintenance_date
    ),
  constraint machines_last_maintenance_after_commission_check
    check (last_maintenance_date is null or last_maintenance_date >= commissioned_date),

  -- Composite-FK target. See the note in this table's header comment.
  constraint machines_id_line_id_key unique (id, line_id)
);

comment on constraint machines_id_line_id_key on public.machines is
  'Target for the composite FK from production_records, which guarantees a production row cannot claim a line its machine does not belong to.';

create trigger machines_set_updated_at
  before update on public.machines
  for each row execute function app.set_updated_at();


-- -----------------------------------------------------------------------------
-- defects — the defect-type catalogue (spec section 5.3)
--
-- A catalogue, not an occurrence log. Individual occurrences live in
-- quality_records, which references this table. Keeping them separate is what
-- makes a Pareto chart a simple GROUP BY rather than a string aggregation over
-- free text.
-- -----------------------------------------------------------------------------
create table public.defects (
  id               uuid primary key default gen_random_uuid(),
  code             text                   not null,
  name             text                   not null,
  description      text                   not null default '',
  category         text                   not null,
  default_severity public.defect_severity not null,
  is_active        boolean                not null default true,
  created_at       timestamptz            not null default now(),
  updated_at       timestamptz            not null default now(),

  constraint defects_code_key unique (code),
  constraint defects_code_format_check
    check (code ~ '^[A-Z][A-Z0-9_]{2,31}$'),
  constraint defects_name_not_blank_check
    check (length(btrim(name)) > 0)
);

comment on table public.defects is
  'Catalogue of defect types. Occurrences are rows in quality_records referencing this table.';

create trigger defects_set_updated_at
  before update on public.defects
  for each row execute function app.set_updated_at();

-- =============================================================================
-- BEGIN 20260101000400_production_tables.sql
-- =============================================================================

-- =============================================================================
-- Migration 004 — production, quality and target tables
--
-- These three carry essentially all the volume in the database and back every
-- KPI on the dashboard, so their constraints are written to make an
-- arithmetically impossible row impossible to store rather than merely
-- unlikely.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- production_records — one row per machine, per component, per shift, per day
--
-- Grain: (record_date, shift_id, machine_id, component_id). That tuple is
-- UNIQUE, which does double duty -- it states the grain explicitly, and it
-- gives the seed a natural ON CONFLICT target so re-running upserts rather
-- than duplicating (spec section 30, requirement 4).
--
-- On the denormalised line_id: a machine already belongs to a line, so line_id
-- here is derivable by a join. It is stored anyway because the dashboard
-- filters and groups by line constantly (spec section 5.2) and the join is pure
-- overhead on every such query. The redundancy is safe because the composite
-- foreign key below refers to machines (id, line_id) -- PostgreSQL therefore
-- rejects any row whose line_id disagrees with its machine's actual line. The
-- value cannot drift, so this is denormalisation without the usual cost.
-- -----------------------------------------------------------------------------
create table public.production_records (
  id           uuid primary key default gen_random_uuid(),
  record_date  date  not null,
  shift_id     uuid  not null,
  machine_id   uuid  not null,
  line_id      uuid  not null,
  component_id uuid  not null,

  -- Wall-clock bounds of the run, in UTC.
  started_at   timestamptz not null,
  ended_at     timestamptz not null,

  planned_quantity  integer not null,
  produced_quantity integer not null,
  accepted_quantity integer not null,
  rejected_quantity integer not null,

  -- Minutes the shift was scheduled to produce, and how those minutes were
  -- actually spent. Availability = operating / planned (spec section 43).
  planned_minutes   integer not null,
  operating_minutes integer not null,
  downtime_minutes  integer not null default 0,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint production_records_shift_id_fkey
    foreign key (shift_id) references public.shifts (id)
    on delete restrict,
  constraint production_records_component_id_fkey
    foreign key (component_id) references public.components (id)
    on delete restrict,
  -- Composite FK: guarantees line_id always matches the machine's line.
  constraint production_records_machine_line_fkey
    foreign key (machine_id, line_id) references public.machines (id, line_id)
    on delete restrict,

  -- The grain of the table, and the seed's idempotency key.
  constraint production_records_grain_key
    unique (record_date, shift_id, machine_id, component_id),

  constraint production_records_quantities_non_negative_check
    check (
      planned_quantity  >= 0 and
      produced_quantity >= 0 and
      accepted_quantity >= 0 and
      rejected_quantity >= 0
    ),
  -- Every unit produced was either accepted or rejected. Nothing vanishes.
  constraint production_records_quantity_balance_check
    check (accepted_quantity + rejected_quantity = produced_quantity),
  constraint production_records_minutes_non_negative_check
    check (planned_minutes > 0 and operating_minutes >= 0 and downtime_minutes >= 0),
  -- A machine cannot operate for longer than the shift was scheduled.
  constraint production_records_operating_within_planned_check
    check (operating_minutes <= planned_minutes),
  constraint production_records_downtime_within_planned_check
    check (downtime_minutes <= planned_minutes),
  constraint production_records_time_order_check
    check (ended_at > started_at),
  -- Nothing can be produced in zero operating minutes.
  constraint production_records_output_requires_time_check
    check (produced_quantity = 0 or operating_minutes > 0),

  -- Composite-FK target for quality_records; see that table's header.
  constraint production_records_id_machine_component_key
    unique (id, machine_id, component_id)
);

comment on table public.production_records is
  'Production output at (date, shift, machine, component) grain. The UNIQUE on those four columns states the grain and serves as the seed idempotency key.';
comment on column public.production_records.line_id is
  'Denormalised from machines.line_id for query performance. Kept consistent by the composite FK production_records_machine_line_fkey, so it cannot drift.';
comment on column public.production_records.operating_minutes is
  'Minutes actually producing. Numerator of OEE Availability.';

create trigger production_records_set_updated_at
  before update on public.production_records
  for each row execute function app.set_updated_at();


-- -----------------------------------------------------------------------------
-- quality_records — inspection outcomes for a production run
--
-- Grain: one row per (production_record, defect type).
--
--   * exactly one row per production record has defect_id IS NULL. That is the
--     "passed" line: passed_quantity > 0, rejected_quantity = 0.
--   * each additional row has defect_id NOT NULL and records the units rejected
--     for that specific defect: rejected_quantity > 0, passed_quantity = 0.
--
-- So SUM(inspected_quantity) over a production record equals its
-- produced_quantity, defect rate is a plain ratio, and a Pareto chart is
-- `GROUP BY defect_id ORDER BY sum(rejected_quantity) DESC` with no
-- post-processing. The alternative -- a single row per production record with a
-- "primary defect" -- would lose every secondary defect and make the Pareto
-- chart wrong.
--
-- UNIQUE ... NULLS NOT DISTINCT treats the single NULL-defect row as a
-- duplicate of itself, which both enforces "at most one pass line" and gives
-- the seed its ON CONFLICT target. That clause requires PostgreSQL 15+;
-- Supabase runs 15 or later.
-- -----------------------------------------------------------------------------
create table public.quality_records (
  id                   uuid primary key default gen_random_uuid(),
  production_record_id uuid not null,
  -- Denormalised from the production record. Held consistent by the composite
  -- FK below, and required because spec section 29 calls for indexes on
  -- quality_records(machine_id) and quality_records(component_id).
  machine_id           uuid not null,
  component_id         uuid not null,
  -- NULL on the pass line; the defect type on a rejection line.
  defect_id            uuid,

  inspected_at      timestamptz not null,
  inspected_quantity integer    not null,
  passed_quantity    integer    not null default 0,
  rejected_quantity  integer    not null default 0,
  -- Units that passed first time with no rework. Numerator of First Pass Yield
  -- (spec section 43). Only meaningful on the pass line.
  first_pass_quantity integer   not null default 0,
  rework_quantity     integer   not null default 0,
  -- Severity of this occurrence, which may differ from the defect's default.
  severity public.defect_severity,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint quality_records_production_record_id_fkey
    foreign key (production_record_id) references public.production_records (id)
    on delete cascade,
  -- Guarantees the denormalised machine_id and component_id match the parent.
  constraint quality_records_production_machine_component_fkey
    foreign key (production_record_id, machine_id, component_id)
    references public.production_records (id, machine_id, component_id)
    on delete cascade,
  constraint quality_records_defect_id_fkey
    foreign key (defect_id) references public.defects (id)
    on delete restrict,

  constraint quality_records_grain_key
    unique nulls not distinct (production_record_id, defect_id),

  constraint quality_records_quantities_non_negative_check
    check (
      inspected_quantity  >= 0 and
      passed_quantity     >= 0 and
      rejected_quantity   >= 0 and
      first_pass_quantity >= 0 and
      rework_quantity     >= 0
    ),
  constraint quality_records_quantity_balance_check
    check (passed_quantity + rejected_quantity = inspected_quantity),
  constraint quality_records_first_pass_within_passed_check
    check (first_pass_quantity <= passed_quantity),
  constraint quality_records_rework_within_passed_check
    check (rework_quantity <= passed_quantity),
  -- The shape rule that makes the grain coherent: a rejection line names a
  -- defect and rejects units; a pass line does neither.
  constraint quality_records_defect_shape_check
    check (
      (defect_id is null     and rejected_quantity = 0 and severity is null)
      or
      (defect_id is not null and rejected_quantity > 0 and passed_quantity = 0
                             and first_pass_quantity = 0 and severity is not null)
    )
);

comment on table public.quality_records is
  'Inspection outcomes at (production_record, defect) grain. Exactly one NULL-defect row per production record carries the passes; each further row carries one defect type''s rejections.';
comment on constraint quality_records_defect_shape_check on public.quality_records is
  'Enforces the two legal row shapes: a pass line (no defect, no rejects) or a rejection line (a defect, only rejects).';

create trigger quality_records_set_updated_at
  before update on public.quality_records
  for each row execute function app.set_updated_at();


-- -----------------------------------------------------------------------------
-- daily_targets — planned output per line, component and day
--
-- Grain: (target_date, line_id, component_id). Targets are set per component
-- rather than only per line so that "actual vs target by component" (spec
-- section 5.2) is answerable without apportioning a line total.
-- -----------------------------------------------------------------------------
create table public.daily_targets (
  id           uuid primary key default gen_random_uuid(),
  target_date  date    not null,
  line_id      uuid    not null,
  component_id uuid    not null,
  target_quantity integer not null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),

  constraint daily_targets_line_id_fkey
    foreign key (line_id) references public.factory_lines (id)
    on delete cascade,
  constraint daily_targets_component_id_fkey
    foreign key (component_id) references public.components (id)
    on delete cascade,

  constraint daily_targets_grain_key
    unique (target_date, line_id, component_id),
  constraint daily_targets_quantity_positive_check
    check (target_quantity > 0)
);

comment on table public.daily_targets is
  'Planned daily output per line and component. Denominator of the production achievement KPI.';

create trigger daily_targets_set_updated_at
  before update on public.daily_targets
  for each row execute function app.set_updated_at();

-- =============================================================================
-- BEGIN 20260101000500_inventory_tables.sql
-- =============================================================================

-- =============================================================================
-- Migration 005 — inventory
--
--   inventory_items -> inventory_transactions
--   components      -> inventory_items (optional; raw materials have no part)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- inventory_items — raw materials and consumables (spec section 5.4)
--
-- `status` is a GENERATED column rather than a stored value. Stock health is a
-- pure function of the quantity against its thresholds, so deriving it removes
-- the entire class of bug where the number and the label disagree -- there is
-- no code path that can write an inconsistent status, and no background job is
-- needed to keep it fresh. It is a stored generated column, so it indexes
-- normally, which spec section 29 asks for.
--
-- Order of the CASE arms matters: a quantity at or below minimum_stock is
-- CRITICAL even though it is also at or below reorder_point.
--
-- This is data integrity, not a KPI. Aggregate calculations stay in backend
-- services per spec section 42; what lives here is the invariant that a row
-- describing 3 units of a material with a minimum of 50 is never labelled
-- healthy.
-- -----------------------------------------------------------------------------
create table public.inventory_items (
  id           uuid primary key default gen_random_uuid(),
  sku          text not null,
  name         text not null,
  material_type text not null,
  -- Set when the item is a finished/semi-finished part tracked as a component.
  -- NULL for raw materials such as steel billets, which are not components.
  component_id uuid,

  unit         text not null,
  current_quantity numeric(14, 3) not null,
  minimum_stock    numeric(14, 3) not null,
  reorder_point    numeric(14, 3) not null,
  maximum_stock    numeric(14, 3) not null,

  supplier_name           text not null default '',
  supplier_lead_time_days smallint,
  unit_cost               numeric(12, 2),

  status public.inventory_status
    generated always as (
      case
        when current_quantity <= minimum_stock then 'CRITICAL'::public.inventory_status
        when current_quantity <= reorder_point then 'LOW'::public.inventory_status
        when current_quantity >= maximum_stock then 'OVERSTOCKED'::public.inventory_status
        else 'HEALTHY'::public.inventory_status
      end
    ) stored,

  last_counted_at timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  constraint inventory_items_component_id_fkey
    foreign key (component_id) references public.components (id)
    on delete set null,

  constraint inventory_items_sku_key unique (sku),
  constraint inventory_items_sku_format_check
    check (sku ~ '^[A-Z][A-Z0-9-]{2,23}$'),
  constraint inventory_items_quantities_non_negative_check
    check (
      current_quantity >= 0 and
      minimum_stock    >= 0 and
      reorder_point    >= 0 and
      maximum_stock    >  0
    ),
  -- The thresholds must describe a coherent ladder, or `status` is meaningless.
  constraint inventory_items_threshold_order_check
    check (minimum_stock <= reorder_point and reorder_point < maximum_stock),
  constraint inventory_items_lead_time_range_check
    check (supplier_lead_time_days is null or supplier_lead_time_days between 0 and 365),
  constraint inventory_items_unit_cost_non_negative_check
    check (unit_cost is null or unit_cost >= 0),
  constraint inventory_items_name_not_blank_check
    check (length(btrim(name)) > 0)
);

comment on column public.inventory_items.status is
  'Derived, never written. CRITICAL at or below minimum, LOW at or below reorder point, OVERSTOCKED at or above maximum, otherwise HEALTHY.';
comment on constraint inventory_items_threshold_order_check on public.inventory_items is
  'minimum <= reorder < maximum. Without this ladder the generated status column would be incoherent.';

create trigger inventory_items_set_updated_at
  before update on public.inventory_items
  for each row execute function app.set_updated_at();


-- -----------------------------------------------------------------------------
-- inventory_transactions — the stock movement ledger
--
-- Movements are signed: `quantity_delta` is positive for anything that adds
-- stock and negative for anything that removes it. A single signed column
-- means running balances are a plain SUM with no CASE over the type, and the
-- CHECK below ties the sign to the movement type so the two cannot contradict
-- each other.
--
-- `balance_after` is the running balance at the time of the movement, kept so
-- the inventory trend chart is a single indexed read rather than a window
-- function over the whole ledger.
-- -----------------------------------------------------------------------------
create table public.inventory_transactions (
  id                uuid not null default gen_random_uuid(),
  inventory_item_id uuid not null,
  transaction_type  public.inventory_transaction_type not null,
  quantity_delta    numeric(14, 3) not null,
  balance_after     numeric(14, 3) not null,
  reference         text not null default '',
  notes             text not null default '',
  occurred_at       timestamptz not null,
  created_by        uuid,
  created_at        timestamptz not null default now(),

  constraint inventory_transactions_pkey primary key (id),
  constraint inventory_transactions_item_id_fkey
    foreign key (inventory_item_id) references public.inventory_items (id)
    on delete cascade,
  constraint inventory_transactions_created_by_fkey
    foreign key (created_by) references public.users (id)
    on delete set null,

  -- A movement of zero is not a movement.
  constraint inventory_transactions_delta_non_zero_check
    check (quantity_delta <> 0),
  constraint inventory_transactions_balance_non_negative_check
    check (balance_after >= 0),
  -- The sign must agree with the movement type. ADJUSTMENT may go either way.
  constraint inventory_transactions_delta_sign_check
    check (
      case transaction_type
        when 'RECEIPT'    then quantity_delta > 0
        when 'RETURN'     then quantity_delta > 0
        when 'ISSUE'      then quantity_delta < 0
        when 'SCRAP'      then quantity_delta < 0
        when 'ADJUSTMENT' then true
      end
    ),
  -- Idempotency key for the seed: one movement per item per reference.
  constraint inventory_transactions_item_reference_key
    unique (inventory_item_id, reference)
);

comment on table public.inventory_transactions is
  'Signed stock movement ledger. Positive delta adds stock, negative removes it.';
comment on constraint inventory_transactions_delta_sign_check on public.inventory_transactions is
  'Ties the sign of quantity_delta to the movement type so a RECEIPT cannot reduce stock.';

-- =============================================================================
-- BEGIN 20260101000600_maintenance_alerts_audit.sql
-- =============================================================================

-- =============================================================================
-- Migration 006 — maintenance, alerts and the audit trail
-- =============================================================================

-- -----------------------------------------------------------------------------
-- maintenance_records — scheduled and completed work on machines
-- -----------------------------------------------------------------------------
create table public.maintenance_records (
  id         uuid primary key default gen_random_uuid(),
  machine_id uuid not null,
  maintenance_type   public.maintenance_type   not null,
  status             public.maintenance_status not null default 'SCHEDULED',

  scheduled_date date not null,
  started_at     timestamptz,
  completed_at   timestamptz,
  downtime_minutes integer not null default 0,

  technician  text not null default '',
  description text not null default '',
  cost        numeric(12, 2),

  -- Idempotency key for the seed: a machine has one job of a given type on a
  -- given date.
  reference   text not null,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint maintenance_records_machine_id_fkey
    foreign key (machine_id) references public.machines (id)
    on delete cascade,

  constraint maintenance_records_reference_key unique (reference),
  constraint maintenance_records_downtime_non_negative_check
    check (downtime_minutes >= 0),
  constraint maintenance_records_cost_non_negative_check
    check (cost is null or cost >= 0),
  constraint maintenance_records_time_order_check
    check (completed_at is null or started_at is null or completed_at >= started_at),
  -- Status and timestamps must tell the same story: completed work has a
  -- completion time, and work not yet started has neither.
  constraint maintenance_records_status_consistency_check
    check (
      case status
        when 'COMPLETED'   then completed_at is not null and started_at is not null
        when 'IN_PROGRESS' then started_at is not null and completed_at is null
        when 'SCHEDULED'   then started_at is null and completed_at is null
        when 'CANCELLED'   then completed_at is null
      end
    )
);

comment on constraint maintenance_records_status_consistency_check on public.maintenance_records is
  'Keeps status and the timestamp columns consistent: completed work has both timestamps, scheduled work has neither.';

create trigger maintenance_records_set_updated_at
  before update on public.maintenance_records
  for each row execute function app.set_updated_at();


-- -----------------------------------------------------------------------------
-- alerts — operational notifications (spec section 34)
--
-- `dedupe_key` is what stops the same condition producing a new alert on every
-- evaluation. It is a caller-supplied natural key ("this machine, this
-- condition, this day"), UNIQUE, so re-raising an alert updates the existing
-- row rather than filling the panel with duplicates. It is also the seed's
-- idempotency key.
--
-- The subject columns are all nullable and independent: an inventory alert
-- names an item, a machine alert names a machine. The CHECK requires at least
-- one, so an alert can never be about nothing.
-- -----------------------------------------------------------------------------
create table public.alerts (
  id       uuid primary key default gen_random_uuid(),
  alert_type public.alert_type     not null,
  severity   public.alert_severity not null,
  status     public.alert_status   not null default 'OPEN',

  title       text not null,
  description text not null,

  -- Subject of the alert. At least one must be set.
  machine_id        uuid,
  component_id      uuid,
  inventory_item_id uuid,
  line_id           uuid,

  triggered_at    timestamptz not null,
  acknowledged_at timestamptz,
  acknowledged_by uuid,
  resolved_at     timestamptz,

  dedupe_key text not null,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint alerts_machine_id_fkey
    foreign key (machine_id) references public.machines (id) on delete cascade,
  constraint alerts_component_id_fkey
    foreign key (component_id) references public.components (id) on delete cascade,
  constraint alerts_inventory_item_id_fkey
    foreign key (inventory_item_id) references public.inventory_items (id) on delete cascade,
  constraint alerts_line_id_fkey
    foreign key (line_id) references public.factory_lines (id) on delete cascade,
  constraint alerts_acknowledged_by_fkey
    foreign key (acknowledged_by) references public.users (id) on delete set null,

  constraint alerts_dedupe_key_key unique (dedupe_key),
  constraint alerts_title_not_blank_check
    check (length(btrim(title)) > 0),
  -- Spec section 45: an alert must be understandable as text, so the
  -- description is required rather than decorative.
  constraint alerts_description_not_blank_check
    check (length(btrim(description)) > 0),
  constraint alerts_has_subject_check
    check (
      machine_id is not null
      or component_id is not null
      or inventory_item_id is not null
      or line_id is not null
    ),
  constraint alerts_status_consistency_check
    check (
      case status
        when 'OPEN'         then acknowledged_at is null and resolved_at is null
        when 'ACKNOWLEDGED' then acknowledged_at is not null and resolved_at is null
        when 'RESOLVED'     then resolved_at is not null
      end
    ),
  constraint alerts_time_order_check
    check (
      (acknowledged_at is null or acknowledged_at >= triggered_at)
      and (resolved_at is null or resolved_at >= triggered_at)
    )
);

comment on column public.alerts.dedupe_key is
  'Natural key for the underlying condition. UNIQUE, so re-raising the same condition updates the existing alert instead of duplicating it.';

create trigger alerts_set_updated_at
  before update on public.alerts
  for each row execute function app.set_updated_at();


-- -----------------------------------------------------------------------------
-- audit_logs — security-sensitive action trail (spec section 67)
--
-- Append-only, enforced by a trigger rather than by convention: an audit trail
-- that the application can rewrite proves nothing. UPDATE and DELETE are
-- rejected for every caller, including a service-role session.
--
-- The primary key is a bigint identity, not a UUID. This is the one table where
-- insert order carries meaning and volume is highest; a monotonic key keeps
-- index writes append-only and makes "the last N events" a trivial scan. Spec
-- section 6 asks for UUIDs "where practical", and here a sequence is the better
-- fit.
--
-- `metadata` is jsonb for context that varies by action. Secrets must never be
-- put in it -- the backend redacts before writing (spec sections 28 and 67).
-- -----------------------------------------------------------------------------
create table public.audit_logs (
  id            bigint generated always as identity primary key,
  actor_user_id uuid,
  action        text not null,
  resource_type text not null,
  resource_id   text,
  success       boolean not null,
  -- Correlation ID from the request that caused this entry, so an audit row
  -- can be tied to the matching application log lines.
  request_id    text,
  ip_address    inet,
  user_agent    text,
  metadata      jsonb not null default '{}'::jsonb,
  occurred_at   timestamptz not null default now(),

  constraint audit_logs_actor_user_id_fkey
    foreign key (actor_user_id) references public.users (id)
    on delete set null,
  constraint audit_logs_action_format_check
    check (action ~ '^[A-Z][A-Z0-9_.]{2,63}$'),
  constraint audit_logs_resource_type_not_blank_check
    check (length(btrim(resource_type)) > 0),
  constraint audit_logs_metadata_is_object_check
    check (jsonb_typeof(metadata) = 'object')
);

comment on table public.audit_logs is
  'Append-only trail of security-sensitive actions. UPDATE and DELETE are blocked by trigger for every caller.';
comment on column public.audit_logs.metadata is
  'Action-specific context. Never store tokens, passwords or keys here; the backend redacts before writing.';

create trigger audit_logs_prevent_mutation
  before update or delete on public.audit_logs
  for each row execute function app.prevent_mutation();

-- =============================================================================
-- BEGIN 20260101000700_indexes.sql
-- =============================================================================

-- =============================================================================
-- Migration 007 — indexes
--
-- Chosen against the queries the dashboard actually runs, per spec section 29:
-- "Do not blindly index every column."
--
-- Two rules shaped this file.
--
-- 1. Composite over single-column where the access pattern is compound. Every
--    production and quality query filters a date range first and then groups by
--    machine, component or line. `(machine_id, record_date DESC)` serves both
--    "this machine over this period" and "this machine, most recent first";
--    a bare `(machine_id)` serves neither well. The leading column of a
--    composite index also satisfies queries that filter on it alone, so the
--    single-column index would be redundant.
--
-- 2. No index that PostgreSQL already provides. A PRIMARY KEY or UNIQUE
--    constraint creates its own index, so `production_records(record_date,
--    shift_id, machine_id, component_id)` is already covered by the grain
--    constraint and is not repeated here.
--
-- Every index is created IF NOT EXISTS so the migration is re-runnable.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- production_records
--
-- Dashboard: "today's output", "last 30 days by line", "this machine's trend".
-- The date-only index leads on record_date because almost every query bounds
-- the period before it does anything else.
-- -----------------------------------------------------------------------------
create index if not exists production_records_record_date_idx
  on public.production_records (record_date desc);

create index if not exists production_records_machine_date_idx
  on public.production_records (machine_id, record_date desc);

create index if not exists production_records_component_date_idx
  on public.production_records (component_id, record_date desc);

create index if not exists production_records_line_date_idx
  on public.production_records (line_id, record_date desc);

-- Shift comparison ("output by shift over this period") groups by shift within
-- a date range, so the date belongs in the index too.
create index if not exists production_records_shift_date_idx
  on public.production_records (shift_id, record_date desc);


-- -----------------------------------------------------------------------------
-- quality_records
--
-- The Pareto chart is the hot query: sum rejections by defect over a period.
-- The partial index below covers exactly that, excluding the ~30% of rows that
-- are pass lines and can never contribute to it. Smaller index, fewer pages
-- read, and the planner can use it as a covering index for the aggregate.
-- -----------------------------------------------------------------------------
create index if not exists quality_records_inspected_at_idx
  on public.quality_records (inspected_at desc);

create index if not exists quality_records_machine_inspected_idx
  on public.quality_records (machine_id, inspected_at desc);

create index if not exists quality_records_component_inspected_idx
  on public.quality_records (component_id, inspected_at desc);

-- Pareto and defect-trend queries only ever look at rejection lines.
create index if not exists quality_records_defect_inspected_idx
  on public.quality_records (defect_id, inspected_at desc)
  where defect_id is not null;

-- Joining a production record to its inspection lines. The grain constraint
-- indexes (production_record_id, defect_id), whose leading column serves this,
-- but an explicit narrow index keeps the common single-record lookup cheap.
create index if not exists quality_records_production_record_idx
  on public.quality_records (production_record_id);


-- -----------------------------------------------------------------------------
-- machines
-- -----------------------------------------------------------------------------
create index if not exists machines_status_idx
  on public.machines (status);

create index if not exists machines_line_status_idx
  on public.machines (line_id, status);

-- "Which machines are due for maintenance?" -- only rows that have a due date.
create index if not exists machines_next_maintenance_idx
  on public.machines (next_maintenance_date)
  where next_maintenance_date is not null;


-- -----------------------------------------------------------------------------
-- inventory
-- -----------------------------------------------------------------------------
create index if not exists inventory_items_status_idx
  on public.inventory_items (status);

create index if not exists inventory_items_component_idx
  on public.inventory_items (component_id)
  where component_id is not null;

-- The alerts panel asks only for items needing attention. A partial index over
-- two of the four status values is a fraction of the size of the full one.
create index if not exists inventory_items_needs_attention_idx
  on public.inventory_items (status, name)
  where status in ('CRITICAL', 'LOW');

-- Stock movement history for one item, newest first.
create index if not exists inventory_transactions_item_occurred_idx
  on public.inventory_transactions (inventory_item_id, occurred_at desc);


-- -----------------------------------------------------------------------------
-- maintenance_records
-- -----------------------------------------------------------------------------
create index if not exists maintenance_records_machine_scheduled_idx
  on public.maintenance_records (machine_id, scheduled_date desc);

-- "What is coming up?" filters on status and orders by date.
create index if not exists maintenance_records_status_scheduled_idx
  on public.maintenance_records (status, scheduled_date);


-- -----------------------------------------------------------------------------
-- alerts
--
-- The alerts panel reads open alerts, most severe and most recent first. That
-- is a small slice of the table once history accumulates, so a partial index
-- on the open ones keeps the panel query independent of total alert volume.
-- -----------------------------------------------------------------------------
create index if not exists alerts_open_triggered_idx
  on public.alerts (severity desc, triggered_at desc)
  where status = 'OPEN';

create index if not exists alerts_status_triggered_idx
  on public.alerts (status, triggered_at desc);

create index if not exists alerts_machine_triggered_idx
  on public.alerts (machine_id, triggered_at desc)
  where machine_id is not null;


-- -----------------------------------------------------------------------------
-- daily_targets
--
-- The grain constraint already indexes (target_date, line_id, component_id),
-- which covers date-bounded and date+line lookups via its leading columns.
-- Only the component-first access pattern needs its own index.
-- -----------------------------------------------------------------------------
create index if not exists daily_targets_component_date_idx
  on public.daily_targets (component_id, target_date desc);


-- -----------------------------------------------------------------------------
-- users and audit_logs
-- -----------------------------------------------------------------------------
create index if not exists users_role_idx
  on public.users (role_id);

create index if not exists audit_logs_occurred_at_idx
  on public.audit_logs (occurred_at desc);

create index if not exists audit_logs_actor_occurred_idx
  on public.audit_logs (actor_user_id, occurred_at desc)
  where actor_user_id is not null;

-- "Everything that happened to this resource", for incident review.
create index if not exists audit_logs_resource_idx
  on public.audit_logs (resource_type, resource_id, occurred_at desc);

-- Idempotency for seeded audit rows.
--
-- audit_logs is append-only, so the seed cannot delete and re-insert its own
-- rows the way it does elsewhere. This partial unique index gives those rows a
-- conflict target instead, letting the seed use ON CONFLICT DO NOTHING and stay
-- re-runnable without ever mutating the trail.
--
-- The index is partial on `metadata ? 'seed_key'`, so it constrains only rows
-- the seed created. Audit entries written by the running application carry no
-- seed_key and are entirely unaffected -- they can repeat freely, which is what
-- an audit trail requires.
create unique index if not exists audit_logs_seed_key_idx
  on public.audit_logs ((metadata ->> 'seed_key'))
  where metadata ? 'seed_key';

-- =============================================================================
-- BEGIN 20260101000800_row_level_security.sql
-- =============================================================================

-- =============================================================================
-- Migration 008 — Row Level Security
--
-- SECURITY POSTURE: deny by default.
--
-- The architecture routes every read and write through FastAPI using the
-- service-role key (spec section 66: "prefer backend-mediated data access so
-- authorization and business rules remain centralized"). No browser ever holds
-- a Supabase credential. So the correct RLS configuration is not a set of
-- permissive policies -- it is the absence of them.
--
-- Three independent layers produce that:
--
--   1. RLS is ENABLED on every table. With no permissive policy present,
--      PostgreSQL denies all access to any role subject to RLS.
--   2. RLS is FORCED, so the table owner is subject to it too. Without FORCE,
--      an owner-privileged connection would silently bypass every policy.
--   3. Table privileges are REVOKED from `anon` and `authenticated`, and
--      default privileges are altered so future tables inherit the same.
--      Layer 3 means that even if a policy were added by mistake, the grant it
--      would need still does not exist.
--
-- The backend's `service_role` holds the BYPASSRLS attribute, which takes
-- precedence over FORCE, so the FastAPI service continues to work normally.
-- Authorization for those requests is decided in the backend RBAC policy
-- module (spec section 56), not here.
--
-- IF DIRECT BROWSER ACCESS IS EVER INTRODUCED: the helper functions from
-- migration 001 and the worked policy template at the foot of this file are the
-- starting point. Adding a policy alone is not enough -- the corresponding
-- GRANT must be restored too.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Layer 1 and 2 — enable and force RLS on every table.
-- -----------------------------------------------------------------------------
alter table public.roles                  enable row level security;
alter table public.roles                  force  row level security;

alter table public.users                  enable row level security;
alter table public.users                  force  row level security;

alter table public.factory_lines          enable row level security;
alter table public.factory_lines          force  row level security;

alter table public.components             enable row level security;
alter table public.components             force  row level security;

alter table public.shifts                 enable row level security;
alter table public.shifts                 force  row level security;

alter table public.machines               enable row level security;
alter table public.machines               force  row level security;

alter table public.defects                enable row level security;
alter table public.defects                force  row level security;

alter table public.production_records     enable row level security;
alter table public.production_records     force  row level security;

alter table public.quality_records        enable row level security;
alter table public.quality_records        force  row level security;

alter table public.daily_targets          enable row level security;
alter table public.daily_targets          force  row level security;

alter table public.inventory_items        enable row level security;
alter table public.inventory_items        force  row level security;

alter table public.inventory_transactions enable row level security;
alter table public.inventory_transactions force  row level security;

alter table public.maintenance_records    enable row level security;
alter table public.maintenance_records    force  row level security;

alter table public.alerts                 enable row level security;
alter table public.alerts                 force  row level security;

alter table public.audit_logs             enable row level security;
alter table public.audit_logs             force  row level security;


-- -----------------------------------------------------------------------------
-- Layer 3 — revoke privileges from the browser-facing roles.
--
-- `anon` is the role behind the Supabase publishable key; `authenticated` is
-- the role a signed-in Supabase session assumes. Neither is used by this
-- architecture, so neither needs any privilege on any table.
--
-- USAGE on the schema is left in place: revoking it produces confusing errors
-- from PostgREST rather than clean permission denials, and it grants no access
-- to data on its own.
-- -----------------------------------------------------------------------------
revoke all on all tables    in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on all functions in schema public from anon, authenticated;

-- Applies the same posture to anything created later, so a future migration
-- cannot accidentally ship a world-readable table.
alter default privileges in schema public
  revoke all on tables from anon, authenticated;
alter default privileges in schema public
  revoke all on sequences from anon, authenticated;
alter default privileges in schema public
  revoke all on functions from anon, authenticated;


-- -----------------------------------------------------------------------------
-- The one explicitly enforced rule, rather than an absence.
--
-- audit_logs is append-only for every caller including service_role, enforced
-- by the trigger installed in migration 006. This policy documents the same
-- intent at the RLS layer: even were the table opened for reading later, no
-- policy permits UPDATE or DELETE.
--
-- The policy is restrictive, so it ANDs with any permissive policy added
-- later. A future grant cannot accidentally re-open mutation.
-- -----------------------------------------------------------------------------
create policy audit_logs_no_mutation
  on public.audit_logs
  as restrictive
  for all
  to public
  using (true)
  with check (false);

comment on policy audit_logs_no_mutation on public.audit_logs is
  'Restrictive policy: permits reads but never INSERT/UPDATE via RLS-subject roles. Combined with the append-only trigger, the audit trail cannot be rewritten.';


-- =============================================================================
-- TEMPLATE — direct browser access (NOT ENABLED)
--
-- Left as commented SQL rather than a separate document so that whoever needs
-- it finds it next to the posture it would change.
--
-- To expose a table directly to signed-in browser users, BOTH steps are
-- required. The policy alone does nothing without the grant.
--
--   -- Step 1: restore the privilege revoked above.
--   grant select on public.machines to authenticated;
--
--   -- Step 2: add a permissive policy scoped to a role.
--   create policy machines_read_for_staff
--     on public.machines
--     for select
--     to authenticated
--     using (
--       app.has_role(array[
--         'ADMIN', 'FACTORY_MANAGER', 'PRODUCTION_SUPERVISOR',
--         'QUALITY_ENGINEER', 'INVENTORY_MANAGER', 'VIEWER'
--       ])
--     );
--
-- Before enabling any of this, note what it costs: authorization would then be
-- split between backend policy code and database policies, and the two would
-- have to be kept in agreement. That is the reason the current design keeps it
-- in one place.
-- =============================================================================

commit;

-- =============================================================================
-- Next step:  cd server && python -m app.db.seed
-- Then:       cd server && python -m app.db.verify
-- =============================================================================
