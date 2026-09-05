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
