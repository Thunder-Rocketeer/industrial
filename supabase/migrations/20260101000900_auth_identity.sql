-- =============================================================================
-- Migration 009 — provider identity for OAuth sign-in
--
-- Spec section 4 requires the identity key to be the provider's stable subject
-- *together with* the provider, not the subject alone. Phase 2 stored a bare
-- `google_sub`, which encodes the provider in the column name -- fine while
-- Google is the only issuer, and a schema change the moment a second one is
-- added, at exactly the point where a subject collision between two providers
-- becomes possible.
--
-- This migration generalises that identity and adds the profile fields the
-- `/auth/me` response needs.
--
-- Note on the identity itself: the subject claim is used, never the email
-- address. An email can be reassigned within a Google Workspace domain, so
-- treating it as the identity would hand a departing employee's account to
-- whoever inherits their address. Email is stored for display and for the
-- account-restriction check, and is never the key.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Generalise the subject column.
--
-- Renamed rather than added-and-backfilled: the column is semantically the same
-- value, and a rename preserves the data and the unique index rather than
-- leaving a dead column behind.
-- -----------------------------------------------------------------------------
alter table public.users
  rename column google_sub to provider_subject;

alter table public.users
  rename constraint users_google_sub_key to users_provider_subject_key;

comment on column public.users.provider_subject is
  'The identity provider''s stable subject claim (OIDC `sub`). Never the email: an address can be reassigned, a subject cannot.';


-- -----------------------------------------------------------------------------
-- Which provider the subject belongs to.
--
-- Defaulted to 'google' because that is the only configured provider, so
-- existing rows are correct without a backfill. The CHECK keeps the column a
-- closed set without the migration cost of an enum for a value that will change
-- rarely.
-- -----------------------------------------------------------------------------
alter table public.users
  add column if not exists provider text not null default 'google';

alter table public.users
  add constraint users_provider_check
  check (provider in ('google'));

comment on column public.users.provider is
  'Identity provider that issued provider_subject. Part of the identity key.';


-- -----------------------------------------------------------------------------
-- Profile fields returned by /auth/me.
--
-- `avatar_url` is a URL supplied by Google. It is stored as data and returned
-- as data; nothing in this application ever builds markup from it (spec
-- section 20). The CHECK constrains it to an https URL so a `javascript:` value
-- cannot reach a frontend that later renders it into an href or an img src.
-- -----------------------------------------------------------------------------
alter table public.users
  add column if not exists avatar_url text;

alter table public.users
  add constraint users_avatar_url_scheme_check
  check (avatar_url is null or avatar_url ~ '^https://');

comment on column public.users.avatar_url is
  'Profile image URL from the provider. Constrained to https so an unsafe scheme cannot be stored.';


-- -----------------------------------------------------------------------------
-- The identity key.
--
-- (provider, provider_subject) is what a sign-in looks up. The pair is unique
-- rather than the subject alone, so two providers issuing the same subject
-- string remain distinct users.
--
-- NULLS NOT DISTINCT would be wrong here: a seeded account that nobody has
-- signed into yet has a NULL subject, and there are several of them. The
-- default NULLS DISTINCT lets those coexist while still preventing two users
-- from claiming the same real identity.
-- -----------------------------------------------------------------------------
alter table public.users
  drop constraint if exists users_provider_subject_key;

alter table public.users
  add constraint users_provider_identity_key
  unique (provider, provider_subject);

comment on constraint users_provider_identity_key on public.users is
  'The sign-in identity. NULL subjects stay distinct so unclaimed seeded accounts can coexist.';


-- -----------------------------------------------------------------------------
-- Lookup index for the sign-in path.
--
-- Partial: only rows with a subject are ever looked up this way, and the
-- unclaimed seeded accounts would otherwise bloat the index.
-- -----------------------------------------------------------------------------
create index if not exists users_provider_identity_idx
  on public.users (provider, provider_subject)
  where provider_subject is not null;

-- Sign-in matches an unclaimed seeded account by email on first login, so that
-- lookup needs to be indexed too. `users_email_key` already covers it.
