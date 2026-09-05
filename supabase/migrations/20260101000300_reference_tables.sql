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
