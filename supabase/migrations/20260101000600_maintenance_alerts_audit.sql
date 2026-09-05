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
