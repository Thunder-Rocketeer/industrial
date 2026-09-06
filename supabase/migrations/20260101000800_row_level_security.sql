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
-- IF DIRECT BROWSER ACCESS IS EVER INTRODUCED: the helper functions below and
-- the worked policy template at the foot of this file are the
-- starting point. Adding a policy alone is not enough -- the corresponding
-- GRANT must be restored too.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Authorization helpers.
--
-- Defined here rather than in migration 001 because they are SQL-language
-- functions selecting from public.users, and PostgreSQL validates a SQL
-- function body when the function is created. They cannot exist before
-- migration 003 creates the table.
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
