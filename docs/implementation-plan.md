# Implementation plan

The phase order follows spec section 49. Each phase lists its deliverables and
the acceptance signal that says it is genuinely finished.

---

## Phase 1 — Repository setup ✅ complete

Repository structure, tooling and foundational libraries for both stacks.

**Delivered**

- Root: `.gitignore`, `.editorconfig`, `README.md`, `docker-compose.yml`, `docs/`,
  git repository initialised at the root.
- Frontend: Prettier and ESLint configuration, `.env.example`, Zod-validated env
  module, centralized Axios client with error normalization, TanStack Query
  client and query-key registry, providers, Iconify wrapper, and the full
  directory skeleton from spec section 14.
- Backend: pinned `requirements.txt`, `pyproject.toml` (Ruff + Pytest), the
  layered package structure from spec section 8, settings module, structured
  logging, application factory with CORS and error handlers, health endpoint,
  test harness, `Dockerfile`, `.env.example`.

**Acceptance**

| Check | Result |
|---|---|
| `npm run lint` | passes |
| `npm run typecheck` | passes |
| `npm run build` | passes |
| `npm run format:check` | passes |
| `ruff check .` | passes |
| `ruff format --check .` | passes |
| `pytest` | 11 passed |
| `uvicorn app.main:app` serves `/api/v1/health` | verified |

**Deliberately not done:** dashboard UI, database schema, seed data,
authentication, OAuth, Redis caching, business logic.

---

## Phase 2 — Database ✅ complete

Supabase schema, security policies and the deterministic seed.

**Delivered**

- 8 migrations in `supabase/migrations/`, plus a generated single-file
  `supabase/schema.sql` for the Supabase SQL editor.
- All 15 tables from spec section 6, with UUID primary keys, 25 foreign keys,
  58 CHECK constraints, 20 unique constraints and `timestamptz` throughout.
- 28 indexes chosen against real dashboard query patterns, 5 of them partial.
- Deny-by-default RLS: enabled *and forced* on every table, privileges revoked
  from `anon` and `authenticated`, default privileges altered so future tables
  inherit the posture. `audit_logs` is append-only by trigger.
- `python -m app.db.seed` — ~13,200 rows: 4 lines, 14 machines across all seven
  types and all four states, 10 components, 3 shifts, 8 defect types, 90 days of
  production and inspection history, inventory spanning all four stock states,
  maintenance history and upcoming work, and 10 alerts derived from that state.
- `python -m app.db.verify` — 11 acceptance checks against a live database.
- `docs/database.md` — schema reference, security decisions, seed model.

**Acceptance**

| Check | Result |
|---|---|
| Migrations parse as PostgreSQL (`pglast`/libpg_query) | 142 statements, clean |
| All 15 spec tables created | verified from the parse tree |
| RLS enabled and forced on every table | 15/15, asserted by test |
| No permissive policy exposes a browser role | asserted by test |
| Helper functions pin `search_path` | 5/5, asserted from the parse tree |
| Seed is deterministic across runs | asserted by test |
| Seed is idempotent (upsert on derived UUIDs) | asserted by test |
| Referential integrity of generated data | asserted by test |
| Quantity arithmetic matches every CHECK constraint | asserted by test |
| Defect distribution is Pareto-shaped | top three = 64% |
| Inventory covers all four stock states | asserted by test |
| `pytest` | 90 passed |
| `ruff check` / `ruff format --check` | clean |

**Not executed here:** applying the migrations and running the seed against a
live Supabase project. The Supabase MCP endpoint is unreachable from this
machine, and there is no Docker, local PostgreSQL or Supabase CLI available, so
no real PostgreSQL instance existed to run against. Everything that can be
verified without one has been, and `python -m app.db.verify` performs the
remaining checks in one command once a database exists.

---

## Phase 3 — Backend ✅ complete

Database integration, repositories, services, KPI calculations, Redis caching
and the API.

**Delivered**

- `app/db/pool.py` — async connection pool, one per worker, with a server-side
  statement timeout and graceful startup when the database is unreachable.
- `app/repositories/` — 6 repositories over a shared base that owns the
  SQL-injection boundary: parameterised values, an allow-list for sort fields,
  and `psycopg.sql` composition for the one identifier that must be interpolated.
- `app/services/` — 8 services. `kpi.py` holds every formula from spec section 43
  as pure functions; `labels.py` holds the display text that keeps state readable
  without colour.
- `app/schemas/` — explicit request and response models for every endpoint, with
  bounded pagination, date ranges and enum filters.
- `app/cache/` — client, keys, serializer and service. Read-through with
  volatility tiers, a circuit breaker, and degradation to the database on any
  failure.
- `app/security/rate_limit.py` — Redis-backed fixed-window limiting with
  unforgeable client identity and fail-open behaviour.
- **37 endpoints** across 9 OpenAPI tags, including every endpoint in spec
  section 9.
- Security headers, structured error envelope with correlation IDs, and
  liveness/readiness probes that do not conflate.
- `docs/api.md` — full API reference.

**Acceptance**

| Check | Result |
|---|---|
| `ruff check .` | clean |
| `ruff format --check .` | clean |
| `pytest` | 337 passed, 25 skipped |
| Security tests (injection, XSS, rate limiting, headers) | pass |
| Cache tests (hit, miss, TTL, Redis unavailable) | pass |
| KPI formula tests | 39 pass |
| Application starts and serves `/api/v1/health` | verified |
| All 37 endpoints reachable through the route layer | verified |
| OpenAPI: every endpoint has summary, description, tag, response model | verified |

**Two real bugs the tests caught**

- Seven grouping endpoints returned 422 for every request: FastAPI does not
  allow a `Query()`-bound Pydantic model alongside additional scalar `Query`
  parameters. Fixed by moving `limit` onto the filter models.
- `kpi.defect_rate` was uncapped while the response schema declared `le=100`, so
  inconsistent data would have produced a 500 rather than a visible number.

**Not executed here:** anything requiring a live database. The 25 integration
tests, and `python -m app.db.verify`, run the moment `DATABASE_URL` is set.

**Deliberately deferred to Phase 4:** Google OAuth, JWT issuing and validation,
RBAC, CSRF, and Content-Security-Policy.

---

## Phase 4 — Authentication and authorization ✅ complete

Google OAuth 2.0 / OIDC, JWT sessions, RBAC and the frontend auth foundation.

**Delivered**

- Migration 009: generalised the identity to `(provider, provider_subject)` and
  added `avatar_url`.
- `security/oauth.py` — Authlib Google client with discovery, PKCE, `state` and
  `nonce`. No protocol step is reimplemented.
- `security/jwt.py` — issuing and validation with an explicit algorithm list, so
  `alg: none` and algorithm confusion are structurally impossible.
- `security/policy.py` — 17 permissions across 6 roles, in one matrix.
- `security/dependencies.py` — the full request flow; the only place a JWT is
  parsed.
- `security/revocation.py`, `cookies.py`, `csrf.py`, `redirects.py`.
- `services/auth_service.py` — provisioning policy and account restriction.
- `services/audit_service.py` — 10 authentication events, with redaction applied
  centrally.
- 6 auth endpoints; every business router gated by a permission.
- Frontend: auth provider, login page, `RequireAuth`, `proxy.ts`, centralized
  401 handling.
- `docs/authentication.md`.

**Acceptance**

| Check | Result |
|---|---|
| `ruff check` / `ruff format --check` | clean |
| `pytest` | 466 passed, 25 skipped |
| Frontend lint / typecheck / build | pass |
| `alg: none`, wrong key, tampered payload, wrong `iss`/`aud`, expired, missing claim | all rejected |
| 12 open-redirect payloads | all rejected |
| Every business endpoint requires a session | verified |
| Role without permission gets 403, with permission passes | verified |
| Inactive user rejected with a valid token | verified |
| Revoked token rejected | verified |
| Real Google authorization redirect (state, nonce, PKCE S256) | verified |

**Not verified:** a complete interactive sign-in. It needs a browser, a live
database and a Google account whose address the deployment admits. Everything up
to the redirect to Google is verified against real Google infrastructure.

---

## Phase 5 — Frontend data layer ✅ complete

The typed path from the browser to the API, with no visual design. Reference:
[`frontend-data-layer.md`](./frontend-data-layer.md).

**Types.** Nine modules under `types/` mirroring the 56 backend response schemas,
with the invariants that are easy to get wrong written down: `has_data`
separating "nothing ran" from "everything failed", `target_quantity` being 0
when filtering by machine or shift, `KpiTrend.change_percentage` being nullable
on purpose.

**API modules.** Eight domain modules under `lib/api/`, all on the single Axios
instance from Phase 1. Single-resource endpoints unwrap the `data` envelope;
list endpoints return the whole `PaginatedResponse`, because the pagination
metadata is what a table needs. Filters go through `buildParams`, which drops
unset values rather than sending `?status=` and provoking a 422.

**Query layer.** Centralized keys (`[domain, resource, params]`, filters
normalized so `{page:1}` and `{page:1, machine_id:undefined}` share one entry),
four stale tiers by volatility, and a five-state discriminator —
`loading | refreshing | success | empty | error` — so a refetch never blanks the
screen and an empty result never reads as a broken one.

**Hooks.** Eight modules under `hooks/queries/`, one hook per endpoint, each
owning its stale time. Only the dashboard summary polls.

**Tables and charts.** Server-driven pagination and sorting
(`hooks/useServerTable.ts`, `lib/table/`), with the 0-based/1-based conversion in
one function and sortable column ids matching the backend's allow-list. Chart
adapters reshape and label; they never calculate.

**Backend-unavailable state.** `useBackendStatus` watches the query cache for
transport and 5xx failures and renders one application-level notice with a retry,
keeping last-known data visible and timestamped.

**Development mocks.** Off by default, gated behind three independent conditions,
loudly labelled, and impossible to reach in a production build.

**Tests:** 97 frontend tests, ~3s, including a security suite that greps the
source for the spec section 35 review items.

**Deliberately not done:** any dashboard visual design.

---

## Phase 6 — Dashboard

KPI cards, alerts panel, production trend, quality summary, machine status and
inventory health, wired to `/api/v1/dashboard/summary` and `/trends` through the
Phase 5 hooks.

**Acceptance:** every async region has loading (skeleton), error (with retry),
empty and success states. A reader understands factory status in 5–10 seconds.

---

## Phase 7 — Detailed modules

Production, quality, inventory, machines and analytics pages, each with a
TanStack Table (sorting, filtering, pagination, column visibility, empty state),
filters, and the charts from spec section 32. Virtualization via TanStack Virtual
where row counts justify it.

---

## Phase 8 — Accessibility and responsive polish

Keyboard navigation, screen-reader semantics, heading hierarchy, contrast,
focus states, touch targets, reduced motion, and text alternatives for every
chart. Target WCAG 2.2 AA.

---

## Phase 9 — Performance

Review API call patterns, TanStack Query cache configuration, Redis hit rates,
database query plans and indexes, bundle size, chart rendering and table
rendering. Measure before optimizing.

---

## Phase 10 — Testing

Backend: authentication, validation, production/quality/inventory calculations,
OEE, API responses, cache behaviour — plus the security tests required by spec
section 70 (OAuth state/nonce/issuer/audience, JWT expiry/signature/algorithm,
SQL injection, XSS, CSRF, rate limiting, security headers).

Frontend: dashboard rendering, loading and error states, filters, tables,
navigation, authenticated route behaviour.

---

## Phase 11 — Final documentation

Architecture, setup, seed process, demo credentials, API reference, deployment
and known assumptions.
