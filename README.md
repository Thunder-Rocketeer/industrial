# Automobile Component Factory — Operations Dashboard

An industrial digital dashboard for **production, quality, inventory and machine
monitoring** in an automobile component manufacturing factory (brake discs,
drive shafts, gears, steering and suspension components).

Built to the specification in
[`automobile_component_factory_claude_code_spec_v2.md`](./automobile_component_factory_claude_code_spec_v2.md),
which is the authoritative document for this project.

> **Status: Phases 1–7 complete.**
> Repository structure, the Supabase schema and deterministic seed, the backend
> API (repositories, services, KPI calculations, Redis caching, 44 endpoints),
> authentication — Google OAuth 2.0 / OIDC, JWT sessions, RBAC — the frontend
> data layer, and the full responsive dashboard UI: nine routes, a reusable
> application shell, charts with text alternatives, server-driven tables and
> URL-synchronized filters.
>
> The schema and seed **have now been applied to a live Supabase project**
> (PostgreSQL 17.6) and verified end to end: 11/11 database checks, 25/25
> integration tests, and 211/211 live API checks covering the contract, RBAC,
> caching, rate limiting, injection, CSRF and open redirect. Seven integration
> defects were found and fixed — see
> [`docs/production-readiness.md`](./docs/production-readiness.md).
>
> Google sign-in was **not** completed end to end and no page has been rendered
> in a browser; no browser was available. See
> [`docs/e2e-verification.md`](./docs/e2e-verification.md) §13 for everything
> outstanding.
>
> Reference: [`docs/api.md`](./docs/api.md) ·
> [`docs/authentication.md`](./docs/authentication.md) ·
> [`docs/database.md`](./docs/database.md) ·
> [`docs/frontend-data-layer.md`](./docs/frontend-data-layer.md) ·
> [`docs/dashboard-ui.md`](./docs/dashboard-ui.md) ·
> [`docs/security-headers.md`](./docs/security-headers.md) ·
> [`docs/e2e-verification.md`](./docs/e2e-verification.md) ·
> [`docs/production-readiness.md`](./docs/production-readiness.md) ·
> [`docs/deployment.md`](./docs/deployment.md) ·
> [`docs/architecture.md`](./docs/architecture.md) ·
> [`docs/implementation-plan.md`](./docs/implementation-plan.md)

---

## Architecture

```
Browser
   |
   v
Next.js (App Router, React Server Components)
   |
   |  Axios, credentialed requests carrying an HTTP-only session cookie
   v
FastAPI  (Uvicorn in development, Gunicorn + Uvicorn workers in production)
   |
   +----> Redis                 cache and rate-limit counters
   |
   +----> Supabase PostgreSQL   persistent source of truth
```

The browser never talks to Supabase directly. All privileged database access is
mediated by the backend so that authorization and business rules stay in one
place, and so the Supabase service-role key never reaches the client.

Backend request flow is strictly layered:

```
Router  ->  Service  ->  Repository  ->  Database
 thin       business      queries only
            logic
```

### Directory layout

The specification names these directories `frontend/` and `backend/`. This
repository uses **`client/`** and **`server/`** instead; the mapping is
one-to-one and nothing else differs.

```
IR_Project/
├── client/                     Next.js 16 + TypeScript + Tailwind CSS 4
│   ├── app/                    App Router routes
│   ├── app/(app)/              9 authenticated routes, each page + view
│   ├── components/
│   │   ├── ui/                 Card, Button, Status, Drawer, States, Icon
│   │   ├── layout/             AppShell, Sidebar, PageHeader, UserMenu
│   │   ├── dashboard/          KpiCard, Gauges, AlertsPanel, LastUpdated
│   │   ├── charts/             Recharts wrappers + accessible ChartFrame
│   │   ├── tables/             DataTable, TablePagination
│   │   ├── filters/            date range, select and debounced search
│   │   └── data/               QueryBoundary, BackendUnavailable
│   ├── lib/
│   │   ├── api/                Axios client, 8 domain modules, param builder
│   │   │   └── mock/           development-only fixtures, off by default
│   │   ├── query/              query client, key registry, view-state derivation
│   │   ├── table/              server-driven pagination, typed column defs
│   │   ├── chart/              adapters from API shapes to chart input
│   │   ├── constants/          cache tiers, pagination bounds
│   │   └── utils/              display formatting
│   ├── hooks/                  queries/, useServerTable, useUrlFilters
│   ├── scripts/                generate-icons.mjs (offline icon registry)
│   ├── types/                  API contract types (9 modules)
│   ├── providers/              query, auth and session-expiry providers
│   ├── tests/                  vitest: 201 tests
│   └── proxy.ts                Next.js 16 route protection (not middleware.ts)
│
├── server/                     FastAPI + Python 3.10
│   ├── app/
│   │   ├── main.py             application factory, middleware, error handlers
│   │   ├── config.py           validated settings from the environment
│   │   ├── dependencies.py     shared FastAPI dependencies
│   │   ├── api/routes/         9 route modules, 37 endpoints
│   │   ├── schemas/            Pydantic request/response models + filters
│   │   ├── services/           business logic, KPI formulas, display labels
│   │   ├── repositories/       database access, parameterised
│   │   ├── models/             domain entities and enums
│   │   ├── db/                 pool, connections, seed and verify commands
│   │   ├── cache/              Redis client, keys, serializer, service
│   │   ├── security/           OAuth/OIDC, JWT, RBAC, CSRF, rate limiting
│   │   └── utils/              logging and cross-cutting helpers
│   ├── tools/                  SQL validation, schema builder
│   └── tests/
│
├── supabase/
│   ├── migrations/             schema source of truth (8 migrations)
│   └── schema.sql              generated single-file schema, for the SQL editor
│
├── docs/                       architecture, database, API, auth, data layer, plan
└── docker-compose.yml          Redis, plus optional full stack
```

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node.js | 20 or later | Next.js 16 requires Node 20+ |
| npm | 10 or later | Ships with Node |
| Python | 3.10 or later | The checked-in venv is 3.10.11 |
| Redis | 7 | Easiest via `docker compose up -d redis` |
| Docker | any recent | Optional, for Redis and production images |
| Supabase | — | A free hosted project is sufficient |

---

## Environment variables

Secrets live only in `.env` files, which are git-ignored. Copy the templates and
fill in real values. Never commit a filled-in `.env`.

```bash
cp client/.env.example client/.env.local
cp server/.env.example server/.env
```

### Frontend — `client/.env.local`

Every `NEXT_PUBLIC_*` value is inlined into the browser bundle and is public by
definition. Nothing secret may go here.

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Backend base URL including the `/api/v1` prefix |
| `NEXT_PUBLIC_API_TIMEOUT_MS` | Axios request timeout |
| `NEXT_PUBLIC_APP_NAME` | Application name shown in titles and the shell |
| `NEXT_PUBLIC_APP_ENV` | `development`, `staging` or `production` |

The frontend validates these with Zod at startup (`client/lib/env.ts`) and fails
immediately with an actionable message if any is missing or malformed.

### Backend — `server/.env`

Grouped by concern; see `server/.env.example` for the full annotated list.

| Group | Variables |
|---|---|
| Application | `APP_NAME` `APP_ENV` `DEBUG` `API_V1_PREFIX` `HOST` `PORT` `WORKERS` `LOG_LEVEL` |
| CORS | `CORS_ALLOWED_ORIGINS` (comma-separated; a wildcard is rejected) |
| Data source | `DATA_SOURCE` (`csv`, the default, or `postgres`) `CSV_DATA_DIR` |
| Supabase | `SUPABASE_URL` `SUPABASE_ANON_KEY` `SUPABASE_SERVICE_ROLE_KEY` `DATABASE_URL` (only with `DATA_SOURCE=postgres`) |
| Redis | `REDIS_URL` `CACHE_TTL_DASHBOARD` `CACHE_TTL_TRENDS` `CACHE_TTL_ANALYTICS` `CACHE_TTL_REFERENCE` |
| Security | `SECRET_KEY` `JWT_ALGORITHM` `JWT_ISSUER` `JWT_AUDIENCE` `ACCESS_TOKEN_EXPIRE_MINUTES` `COOKIE_SECURE` `COOKIE_SAMESITE` `COOKIE_DOMAIN` `SESSION_COOKIE_NAME` `CSRF_COOKIE_NAME` |
| Auth policy | `AUTH_ALLOWED_EMAIL_DOMAINS` `AUTH_ALLOWED_EMAILS` `AUTH_AUTO_PROVISION` `AUTH_DEFAULT_ROLE` |
| Google OAuth | `GOOGLE_CLIENT_ID` `GOOGLE_CLIENT_SECRET` `GOOGLE_REDIRECT_URI` `GOOGLE_OIDC_ISSUER` `FRONTEND_LOGIN_SUCCESS_URL` `FRONTEND_LOGIN_FAILURE_URL` |
| Rate limiting | `RATE_LIMIT_ENABLED` `RATE_LIMIT_OAUTH` `RATE_LIMIT_AUTHENTICATED` `RATE_LIMIT_ANALYTICS` `RATE_LIMIT_UNAUTHENTICATED` |
| Seed | `SEED_RANDOM_SEED` `SEED_HISTORY_DAYS` |

Generate a signing key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

> The **Supabase service-role key bypasses Row Level Security**. It is
> backend-only. It must never appear in `client/`, in any `NEXT_PUBLIC_*`
> variable, or in a browser response.

---

## Data source

By default (`DATA_SOURCE=csv`) the API reads its table data from the CSV
exports in [`server/supabase_csv_exports/`](./server/supabase_csv_exports) -- one file per
table -- and never contacts Supabase. At startup the files are loaded into an
in-memory DuckDB database with the same table names, columns and types as the
PostgreSQL schema, and the repositories run their existing SQL against it
(`server/app/db/csv_store.py`). Writes made while the server runs -- audit
entries, login bookkeeping -- stay in memory; the CSV files are never modified.

To re-export, drop fresh `<table>.csv` files into that folder (or point
`CSV_DATA_DIR` elsewhere) and restart the server. To query Supabase directly
instead, set `DATA_SOURCE=postgres` and follow the setup below.

## Supabase setup

1. Create a project at [supabase.com](https://supabase.com).
2. From **Project Settings → API**, copy the project URL, the anon key and the
   service-role key into `server/.env`.
3. From **Project Settings → Database → Connection string → URI**, copy the
   connection string into `DATABASE_URL`.
4. Apply the schema. Open the project's **SQL Editor**, paste the contents of
   [`supabase/schema.sql`](./supabase/schema.sql) and run it. The whole schema
   is wrapped in one transaction, so a failure leaves the database untouched.

   With the Supabase CLI installed, `supabase db push` does the same thing from
   `supabase/migrations/`.

The migrations in `supabase/migrations/` are the source of truth;
`supabase/schema.sql` is generated from them by `python tools/build_schema.py`.

Full reference: [`docs/database.md`](./docs/database.md).

## Authentication setup

Sign-in is Google OAuth 2.0 / OpenID Connect. Without credentials the API still
runs — only the login endpoints report themselves unavailable.

1. Create an OAuth client in the [Google Cloud console](https://console.cloud.google.com/)
   (**APIs & Services → Credentials → OAuth client ID → Web application**).
2. Authorised redirect URI, matching `GOOGLE_REDIRECT_URI` exactly:

   ```
   http://localhost:8000/api/v1/auth/google/callback
   ```

3. Put the client ID and secret in `server/.env`, and generate a signing key:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(64))"
   ```

Full walkthrough, the permission matrix and the security decisions:
[`docs/authentication.md`](./docs/authentication.md).

> The **Google client secret is backend-only**. It must never appear in
> `client/` or in any `NEXT_PUBLIC_*` variable. The browser never needs it.

## Redis setup

```bash
docker compose up -d redis
docker compose exec redis redis-cli ping   # -> PONG
```

Or install Redis natively and point `REDIS_URL` at it.

## Database seed

```bash
cd server
python -m app.db.seed      # write ~13,200 rows of demo factory data
python -m app.db.verify    # 11 checks against the result
```

The seed is deterministic and idempotent. `SEED_RANDOM_SEED` fixes the
pseudo-random stream and every row's primary key is derived from its natural key
by UUID v5, so re-running refreshes rows in place rather than duplicating them.
The whole seed runs in one transaction.

| Command | Purpose |
|---|---|
| `python -m app.db.seed` | Seed with the configured defaults (90 days) |
| `python -m app.db.seed --dry-run` | Generate and report counts, write nothing |
| `python -m app.db.seed --history-days 30` | Shorter history |
| `python -m app.db.seed --seed 12345` | Different deterministic dataset |
| `python -m app.db.seed --truncate` | Reset the seeded tables first (destructive; refused in production) |
| `python -m app.db.verify` | Validate schema, indexes, RLS and KPI queries |

What gets seeded: 4 production lines, 14 machines across all seven types and all
four states, 10 components, 3 shifts, 8 defect types, 90 days of production and
inspection history, 8 inventory items spanning all four stock states,
maintenance history and upcoming work, and 10 alerts derived from that state.

See [`docs/database.md`](./docs/database.md) for the realism model and the
verification checklist.

---

## Frontend setup

```bash
cd client
npm install
cp .env.example .env.local
npm run dev             # http://localhost:3000
```

### Frontend commands

| Command | Purpose |
|---|---|
| `npm run dev` | Development server with Fast Refresh |
| `npm run build` | Production build |
| `npm start` | Serve the production build |
| `npm run lint` | ESLint |
| `npm run lint:fix` | ESLint with autofix |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Vitest, single run (201 tests) |
| `npm run icons` | Regenerate the bundled icon registry |
| `npm run test:watch` | Vitest in watch mode |
| `npm run format` | Prettier, writing changes |
| `npm run format:check` | Prettier, check only |

> Next.js 16 removed `next lint` and the `eslint` key in `next.config.ts`.
> Linting runs through the ESLint CLI, which is what `npm run lint` invokes.

## Backend setup

```bash
cd server
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
python -m app                     # http://localhost:8000
```

Interactive API documentation is at <http://localhost:8000/docs> in development.
It is disabled automatically when `APP_ENV=production`.

### Backend commands

| Command | Purpose |
|---|---|
| `python -m app` | Development server. Use this rather than calling uvicorn directly — see below |
| `python -m app --reload` | Same, reloading on source changes |
| `python -m tools.e2e_probe all` | Live end-to-end probe against a running API |
| `pytest` | Run the test suite |
| `pytest -m security` | Run only the security tests |
| `ruff check .` | Lint |
| `ruff check --fix .` | Lint with autofix |
| `ruff format .` | Format |
| `pytest -m security` | Security tests only |
| `pytest -m integration` | Live-database tests (needs `DATABASE_URL`) |
| `python -m app.db.seed` | Seed the demo dataset |
| `python -m app.db.verify` | Validate the seeded database |
| `python tools/validate_sql.py` | Parse the migrations with the PostgreSQL grammar |
| `python tools/build_schema.py` | Regenerate `supabase/schema.sql` |

Development tooling lives in `requirements-dev.txt`:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

---

## API

44 endpoints under `/api/v1`, documented interactively at
<http://localhost:8000/docs> and in full in [`docs/api.md`](./docs/api.md).

```
/dashboard/summary        everything the dashboard needs, in one request
/dashboard/trends         chart series
/production               + /summary /trend /by-{machine,component,shift,line}
/quality                  + /summary /defects /trend /by-{machine,component}
/inventory                + /alerts /summary /{id} /{id}/transactions /{id}/trend
/machines                 + /summary /{id}
/analytics/oee            + /trend /by-machine
/analytics/production-efficiency  + /trend
/analytics/downtime  /analytics/defects
/alerts                   + /active /summary
/maintenance
/health  /health/live  /health/ready
/auth/google/login  /auth/google/callback  /auth/logout  /auth/me
/auth/status  /auth/csrf
```

**Every business endpoint requires a session.** Public: the health probes,
`/auth/status` and `/auth/csrf`. See
[`docs/authentication.md`](./docs/authentication.md).

Responses use three envelopes and nothing else:

```json
{ "data": {} }
{ "data": [], "pagination": { "page": 1, "page_size": 25, "total": 1250 } }
{ "error": { "code": "...", "message": "...", "request_id": "..." } }
```

Every response carries `X-Request-ID`, which also appears in the server log for
the same request. Quote it when reporting a problem.

```bash
curl -s http://localhost:8000/api/v1/dashboard/summary | jq '.data.kpis[] | {label, value, unit, status}'
```

---

## Testing

```bash
# backend
cd server && pytest

# frontend
cd client && npm run lint && npm run typecheck && npm test && npm run build
```

**466 backend tests and 201 frontend tests, no external services required.** API
tests override the service dependencies with fakes, the cache tests use an
in-memory Redis stand-in that can be told to fail, and the SQL is validated by
parsing it with the real PostgreSQL grammar (`pglast`). On the frontend, the
Axios adapter is stubbed so every request path is exercised without a network,
and `tests/security.test.ts` greps the source for the security review items —
no token in browser storage, no unsafe HTML, no arbitrary redirect, one Axios
instance, one chart library, one icon library. `tests/a11y.test.tsx` renders the
real dashboard and checks heading order, accessible names, duplicate ids and
chart text alternatives.

A further **25 integration tests** run against a live database and are skipped
unless `DATABASE_URL` is set. They are the ones that prove a column exists, a
join does not fan out, and an aggregate reconciles with its rows:

```bash
cd server
# after applying the schema and seeding
pytest -m integration
```

## Production build

```bash
# frontend
cd client && npm run build && npm start

# backend
cd server && gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w $WORKERS \n  --forwarded-allow-ips=""
```

Two notes on the production backend command:

- **Gunicorn does not run on Windows.** It depends on the POSIX `fcntl` module.
  On a Windows development machine, exercise the production process manager
  through the container instead: `docker compose --profile full up backend`.
- **`--forwarded-allow-ips=""` is not optional.** Uvicorn trusts
  `X-Forwarded-For` by default and rewrites `request.client` from it, which
  silently overrides the application's own `TRUSTED_PROXY_COUNT` rule. Phase 7
  measured the consequence: a client rotating that header gets a fresh
  rate-limit bucket per request, removing the limit entirely. Let the
  application decide, and set `TRUSTED_PROXY_COUNT` to the number of proxies
  actually in front. See `docs/production-readiness.md`.
- **Why `python -m app` rather than `uvicorn` in development.** On Windows,
  uvicorn selects `ProactorEventLoop`, which psycopg's async mode cannot use —
  the pool never connects and every database endpoint fails. `python -m app`
  passes a compatible loop factory and disables proxy headers. On Linux the
  loop default is already fine.
- `uvicorn.workers.UvicornWorker` emits a `DeprecationWarning`. It still works
  and is the form given in the specification. The successor is the separate
  `uvicorn-worker` package, which can be adopted at deployment time.

Never use `--reload` in production.

## Deployment notes

```
Browser  ->  Vercel (Next.js, proxies /api/*)  ->  Render (FastAPI / Gunicorn)  ->  CSV exports
```

The step-by-step runbook -- Render blueprint, Vercel variables, Google Cloud
Console entries and a verification checklist -- is
[`docs/deployment.md`](./docs/deployment.md). The principles:

- Keep the browser on one origin. The frontend proxies `/api/*` to the backend
  (`API_PROXY_TARGET`); calling a cross-site API directly breaks the cookie
  session.
- Serve everything over HTTPS. Set `COOKIE_SECURE=true` and `APP_ENV=production`.
- Set `CORS_ALLOWED_ORIGINS` to the real frontend origin. A wildcard is rejected
  by configuration validation because requests carry credentials.
- Size `WORKERS` to the deployment: roughly `(2 x CPU cores) + 1`.
- `GOOGLE_REDIRECT_URI` must be registered exactly in the Google Cloud console
  and must never be derived from an incoming `Host` header or query parameter.
- Provide secrets through the platform's secret manager, not a committed file.

---

## Known assumptions and deviations

| Topic | Decision |
|---|---|
| Directory names | `client/` and `server/` instead of the spec's `frontend/` and `backend/`, matching the existing scaffold. |
| Typography | A system font stack rather than `next/font/google`. Google Fonts are downloaded at build time, which breaks builds on offline or network-restricted machines and adds an external dependency for no gain in a dense data UI. To use a bespoke typeface, self-host the woff2 files with `next/font/local`. |
| Python version | 3.10, so `enum.StrEnum` and `datetime.UTC` (both 3.11+) are avoided. |
| `passlib` + `bcrypt` | `passlib 1.7.4` reads `bcrypt.__about__.__version__`, which `bcrypt 5.x` no longer exposes, producing a warning on first use. Authentication is Google OAuth/OIDC per spec section 54, so no password hashing is expected; if a local password path is ever added, replace `passlib` with the `bcrypt` library directly. |
| Content Security Policy | Still deferred. A CSP must be written against the frontend's real script and style sources, which are not settled until the dashboard exists; a placeholder would give false assurance and is usually loosened the first time it breaks something. HSTS belongs at the TLS proxy. |
| Demo accounts cannot sign in as seeded | `.local` is a reserved TLD, so Google can never authenticate `admin@factory.local`. Re-seed with a domain you control, or promote your own account in the database. |

## Specification cross-reference

| Area | Spec section |
|---|---|
| Application structure and routes | 4 |
| Dashboard modules | 5 |
| Data model and indexing | 6, 29 |
| Seed data | 7, 30, 31 |
| Backend architecture and API design | 8, 9, 24 |
| Redis caching and invalidation | 12, 13 |
| Frontend architecture, Axios, Query, Table | 14–17 |
| Responsive design and accessibility | 18, 19, 45 |
| Security architecture | 54–72 |
