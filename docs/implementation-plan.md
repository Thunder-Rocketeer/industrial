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

## Phase 2 — Database

Design the Supabase schema and produce deterministic seed data.

- Tables from spec section 6: `users`, `roles`, `factory_lines`, `machines`,
  `components`, `production_records`, `quality_records`, `defects`,
  `inventory_items`, `inventory_transactions`, `maintenance_records`,
  `daily_targets`, `shifts`, `alerts`, `audit_logs`.
- Primary keys (UUID), foreign keys, unique / NOT NULL / CHECK constraints,
  created and updated timestamps, all stored in UTC.
- Indexes on the columns listed in spec section 29 — driven by real query
  patterns, not applied blindly to every column.
- `python -m app.db.seed`: 4 factory lines, 12+ machines with mixed states, 10+
  components, 30–90 days of production history across shifts, quality records
  with a deliberately skewed defect distribution so the Pareto chart is
  meaningful, inventory spanning healthy/low/critical/overstocked, and
  completed plus upcoming maintenance.
- Seeding is deterministic under `SEED_RANDOM_SEED`, idempotent, and safe on a
  fresh database.

**Acceptance:** the seed runs twice without duplicating rows; every foreign key
resolves; a documented reset path exists.

---

## Phase 3 — Backend

- `app/db/`: Supabase client and PostgreSQL connection pool, opened in the
  application lifespan so each worker holds one pool.
- `app/schemas/`: explicit request and response models for every endpoint. No
  raw database structure is ever returned (spec section 10).
- `app/repositories/`: all queries, parameterized. Sort and filter fields
  resolved through an explicit allow-list map (spec section 57).
- `app/services/`: KPI calculations per spec section 43 — production
  achievement, defect rate, first-pass yield, availability, performance,
  quality, OEE, inventory health.
- `app/cache/`: Redis client, the key patterns from spec section 12, TTLs from
  configuration, and centralized invalidation (spec section 13).
- `app/security/`: Google OAuth 2.0 / OIDC via Authlib with PKCE, `state` and
  `nonce` validation, strict issuer/audience/signature/expiry checks; JWT
  issuing and verification with a fixed algorithm; RBAC policy in one module.
- `app/api/routes/`: the endpoints from spec section 9.
- Redis-backed rate limiting (spec section 60) and audit logging (section 67).

**Acceptance:** every endpoint has a response model; no query is built by string
concatenation; unauthenticated requests get 401 and unauthorized ones get 403.

---

## Phase 4 — Frontend foundation

- Authenticated application shell: sidebar, header, content region, toasts.
- Login page and route protection. Note that Next.js 16 renames middleware to
  **`proxy.ts`**; optimistic redirects belong there, authoritative checks stay
  on the backend.
- Theme and styling foundations: the status colour system, spacing and
  typography scales, and the accessible status components required by spec
  section 45 (state is never conveyed by colour alone).
- Typed API modules under `lib/api/` built on the existing Axios client.
- Data-fetching hooks in `hooks/`, using the query-key registry.

**Acceptance:** navigation works by keyboard, focus is always visible, the shell
is usable at mobile, tablet and desktop widths.

---

## Phase 5 — Dashboard

KPI cards, alerts panel, production trend, quality summary, machine status and
inventory health, wired to `/api/v1/dashboard/summary` and `/trends`.

**Acceptance:** every async region has loading (skeleton), error (with retry),
empty and success states. A reader understands factory status in 5–10 seconds.

---

## Phase 6 — Detailed modules

Production, quality, inventory, machines and analytics pages, each with a
TanStack Table (sorting, filtering, pagination, column visibility, empty state),
filters, and the charts from spec section 32. Virtualization via TanStack Virtual
where row counts justify it.

---

## Phase 7 — Accessibility and responsive polish

Keyboard navigation, screen-reader semantics, heading hierarchy, contrast,
focus states, touch targets, reduced motion, and text alternatives for every
chart. Target WCAG 2.2 AA.

---

## Phase 8 — Performance

Review API call patterns, TanStack Query cache configuration, Redis hit rates,
database query plans and indexes, bundle size, chart rendering and table
rendering. Measure before optimizing.

---

## Phase 9 — Testing

Backend: authentication, validation, production/quality/inventory calculations,
OEE, API responses, cache behaviour — plus the security tests required by spec
section 70 (OAuth state/nonce/issuer/audience, JWT expiry/signature/algorithm,
SQL injection, XSS, CSRF, rate limiting, security headers).

Frontend: dashboard rendering, loading and error states, filters, tables,
navigation, authenticated route behaviour.

---

## Phase 10 — Final documentation

Architecture, setup, seed process, demo credentials, API reference, deployment
and known assumptions.
