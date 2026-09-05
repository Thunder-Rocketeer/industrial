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
