-- =============================================================================
-- Migration 001 — helper schema, trigger functions and authorization helpers
--
-- Establishes the groundwork every later migration depends on:
--   * an `app` schema that keeps helper routines out of `public`
--   * an updated_at trigger function
--   * an append-only guard used by audit_logs
--
-- The RBAC helper functions live in migration 008 instead, beside the RLS
-- policies that would use them: they are SQL-language functions that select
-- from public.users, and PostgreSQL validates a SQL function body at creation
-- time. Defining them here -- before migration 003 creates the table -- fails
-- with 42P01 the moment the migration is actually applied to a database.
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
