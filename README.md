# Automobile Component Factory — Operations Dashboard

An industrial digital dashboard for **production, quality, inventory and machine
monitoring** in an automobile component manufacturing factory (brake discs,
drive shafts, gears, steering and suspension components).

Built to the specification in
[`automobile_component_factory_claude_code_spec_v2.md`](./automobile_component_factory_claude_code_spec_v2.md),
which is the authoritative document for this project.

> **Status: Phase 1 complete — foundations only.**
> Repository structure, tooling and the frontend/backend scaffolding are in
> place and verified. The database schema, seed data, authentication, Redis
> caching, business logic and dashboard UI are implemented in Phases 2–10. See
> [`docs/implementation-plan.md`](./docs/implementation-plan.md).

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
│   ├── components/             layout, dashboard, production, quality,
│   │                           inventory, machines, charts, tables, ui
│   ├── lib/
│   │   ├── api/                centralized Axios client + error normalization
│   │   ├── query/              TanStack Query client and query-key registry
│   │   ├── constants/          cache tiers, pagination bounds
│   │   └── utils/
│   ├── hooks/                  data-fetching hooks
│   ├── types/                  API contract types
│   └── providers/              client-side React providers
│
├── server/                     FastAPI + Python 3.10
│   ├── app/
│   │   ├── main.py             application factory, middleware, error handlers
│   │   ├── config.py           validated settings from the environment
│   │   ├── dependencies.py     shared FastAPI dependencies
│   │   ├── api/                router + route modules
│   │   ├── schemas/            Pydantic request/response models
│   │   ├── services/           business logic and KPI calculations
│   │   ├── repositories/       database access
│   │   ├── models/             domain entities and enums
│   │   ├── db/                 Supabase/PostgreSQL connections, seed command
│   │   ├── cache/              Redis client, keys, invalidation
│   │   ├── security/           OAuth/OIDC, JWT, RBAC
│   │   └── utils/              logging and cross-cutting helpers
│   └── tests/
│
├── docs/                       architecture notes and the phase plan
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
| Supabase | `SUPABASE_URL` `SUPABASE_ANON_KEY` `SUPABASE_SERVICE_ROLE_KEY` `DATABASE_URL` |
| Redis | `REDIS_URL` `CACHE_TTL_DASHBOARD` `CACHE_TTL_TRENDS` `CACHE_TTL_ANALYTICS` `CACHE_TTL_REFERENCE` |
| Security | `SECRET_KEY` `JWT_ALGORITHM` `JWT_ISSUER` `JWT_AUDIENCE` `ACCESS_TOKEN_EXPIRE_MINUTES` `REFRESH_TOKEN_EXPIRE_DAYS` `COOKIE_SECURE` `COOKIE_SAMESITE` `COOKIE_DOMAIN` |
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

## Supabase setup

*Introduced in Phase 2. Currently a placeholder.*

1. Create a project at [supabase.com](https://supabase.com).
2. From **Project Settings → API**, copy the project URL, the anon key and the
   service-role key into `server/.env`.
3. From **Project Settings → Database**, copy the connection string into
   `DATABASE_URL`.
4. Apply the schema migrations (Phase 2).

Supabase migrations remain the source of truth for the database schema.

## Redis setup

```bash
docker compose up -d redis
docker compose exec redis redis-cli ping   # -> PONG
```

Or install Redis natively and point `REDIS_URL` at it.

## Database seed

*Introduced in Phase 2.*

```bash
cd server
python -m app.db.seed
```

The seed is deterministic: `SEED_RANDOM_SEED` fixes the pseudo-random stream, so
the same seed always produces the same demo database. It is safe to re-run
against a fresh development database and preserves referential integrity.

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
uvicorn app.main:app --reload     # http://localhost:8000
```

Interactive API documentation is at <http://localhost:8000/docs> in development.
It is disabled automatically when `APP_ENV=production`.

### Backend commands

| Command | Purpose |
|---|---|
| `uvicorn app.main:app --reload` | Development server with auto-reload |
| `pytest` | Run the test suite |
| `pytest -m security` | Run only the security tests |
| `ruff check .` | Lint |
| `ruff check --fix .` | Lint with autofix |
| `ruff format .` | Format |

---

## Testing

```bash
# backend
cd server && pytest

# frontend
cd client && npm run lint && npm run typecheck && npm run build
```

Backend tests use a `TestClient` against an application built with test
settings, so no live Supabase or Redis instance is required. Tests that do need
real services are marked `@pytest.mark.integration`.

## Production build

```bash
# frontend
cd client && npm run build && npm start

# backend
cd server && gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w $WORKERS
```

Two notes on the production backend command:

- **Gunicorn does not run on Windows.** It depends on the POSIX `fcntl` module.
  On a Windows development machine, exercise the production process manager
  through the container instead: `docker compose --profile full up backend`.
- `uvicorn.workers.UvicornWorker` emits a `DeprecationWarning`. It still works
  and is the form given in the specification. The successor is the separate
  `uvicorn-worker` package, which can be adopted at deployment time.

Never use `--reload` in production.

## Deployment notes

```
Browser  ->  Next.js  ->  FastAPI / Gunicorn  ->  Redis + Supabase
```

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
| Content Security Policy | Deferred to the security phase. A CSP must be written against the application's real script and style sources; a placeholder policy would give false assurance. |

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
