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
