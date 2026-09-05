# Architecture

Decisions taken during Phases 1 and 2, and the reasoning behind them. This
document records *why* the system looks the way it does; the README covers *how*
to run it, and [`database.md`](./database.md) is the schema reference.

---

## 1. Layering

```
Browser
   |
   v
Next.js                      rendering, routing, presentation
   |
   |  Axios (single instance, credentialed)
   v
FastAPI
   |
   +-- Router                HTTP concerns only: parse, validate, delegate
   +-- Service               business logic and KPI calculation
   +-- Repository            all database access, parameterized
   |
   +----> Redis              cache, rate-limit counters
   +----> Supabase           persistent source of truth
```

Two rules hold this together, both from spec section 52:

1. **Route handlers stay thin.** A handler validates input, calls one service
   and returns a response model. It never contains a query or a calculation.
2. **Only repositories touch the database.** Services orchestrate; repositories
   execute. This is what makes SQL-injection defence auditable — there is a
   single layer to review.

Redis is a cache, never the source of truth. Any value it holds must be
reconstructible from Supabase.

## 2. Why the browser never reaches Supabase directly

The Supabase service-role key bypasses Row Level Security. Routing every read
through FastAPI means:

- Authorization is decided in one place and cannot be bypassed by calling the
  database directly.
- Aggregation happens in PostgreSQL, so the wire carries KPI values rather than
  tens of thousands of production rows (spec sections 11 and 23).
- The service-role key stays in backend memory and never enters a bundle.

## 3. Configuration

`app/config.py` declares every setting as a typed, validated Pydantic field, and
`get_settings()` is `lru_cache`d so the `.env` file is parsed once per process.

Validation is deliberately strict at the edges where a mistake is dangerous:

- A wildcard CORS origin is **rejected**, not warned about — the browser sends
  credentialed requests, so `*` is both invalid and unsafe (spec section 61).
- `ACCESS_TOKEN_EXPIRE_MINUTES` is bounded to 60, so a long-lived access token
  cannot be configured by accident (spec section 55.3).
- OpenAPI docs URLs resolve to `None` when `APP_ENV=production`, so disabling
  them is a property of the environment rather than something to remember.

Supabase, Redis and OAuth values default to empty rather than being required, so
the application can boot for health checks and tests before those services are
provisioned. The layer that needs a value validates its presence at the point
of use — a missing key surfaces as a clear error from the component that needs
it, not as an opaque startup failure.

The frontend mirrors this with `lib/env.ts`, which validates the four public
variables with Zod at module load.

## 4. Errors

One envelope, defined once (spec sections 24 and 68):

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "…", "details": { } } }
```

Three handlers produce it: `StarletteHTTPException`, `RequestValidationError`,
and a catch-all for unhandled exceptions. The catch-all logs the traceback with
`exc_info` and returns only a generic message plus the request ID, so a client
never sees a stack trace, a SQL fragment, a filesystem path or a connection
string — but an operator can find the exact failure in the log by that ID.

On the frontend, `lib/api/errors.ts` converts every failure into an `ApiError`
with a discriminating `kind`. This is what lets retry policy be expressed as a
rule rather than a pile of status-code checks: `error.isRetryable` is true for
network, timeout and 5xx failures, and false for 401/403/404/422 — where a retry
is guaranteed to produce the same result — and for 429, where retrying would
work against the backend rate limiter.

## 5. Request correlation

Middleware assigns each request a UUID, or reuses a client-supplied
`X-Request-ID`. The value goes onto `request.state`, into every log line for
that request, and back out on the response header. The Axios client generates
one per outbound request, so a browser-side failure can be traced to the exact
server-side log entry.

## 6. Logging

`app/utils/logging.py` provides two formatters over one extraction path:

- **JSON** in production, one object per line for log aggregation.
- **key=value** in development, because a wall of JSON is harder to scan.

Both run the same redaction step. A fixed set of sensitive key names —
`password`, `token`, `access_token`, `secret_key`, `authorization`, `cookie`,
`client_secret`, `service_role_key` and others — is replaced with `[REDACTED]`
before serialization. Redaction lives in the formatter rather than at call sites
so that one careless `extra={...}` cannot leak a credential (spec section 28).

## 7. Frontend server state

TanStack Query owns all server state; React local state is never used as a
substitute (spec section 16).

**Stale-time tiers** live in `lib/constants/cache.ts` rather than being written
inline at each `useQuery` call, so volatility is a property of the data and is
tunable in one place: 30s realtime, 2min trends, 5min historical, 30min
reference.

**Query keys** are built exclusively by the registry in `lib/query/query-keys.ts`,
shaped `[domain, resource, params]`. Because TanStack Query matches keys by
prefix, invalidating `queryKeys.production.all` clears every production list and
summary regardless of the filters they were fetched under — which is what makes
cache invalidation after a mutation a one-line operation instead of a hunt for
every key that might be affected.

**The QueryClient is a factory, not a module singleton.** On the server each
request must get its own cache, or one user's data could be served to another.
The browser-side singleton lives in `providers/query-provider.tsx` and is held
in `useState` so a re-render never discards the cache.

## 8. Authentication shape (Phase 3)

Decided now because it constrains the Axios client and the CORS configuration:

- Google OAuth 2.0 / OIDC Authorization Code flow with PKCE, via Authlib.
- `state` and `nonce` validated; issuer, audience, signature and expiry checked
  strictly; the redirect URI comes from configuration and is never derived from
  an incoming `Host` header.
- The backend then issues its own short-lived JWT and delivers the session as an
  **HTTP-only, Secure, SameSite** cookie.

That last choice is why `apiClient` sets `withCredentials: true` and why there is
deliberately no Authorization-header interceptor: no token is ever readable by
application JavaScript, which removes the entire class of XSS token theft (spec
section 55.4). It is also why CORS must carry an explicit origin allow-list —
credentialed requests and wildcard origins are mutually exclusive.

## 9. Accessibility foundations

Established in Phase 1 rather than retrofitted:

- A skip link is the first focusable element in the layout.
- `maximum-scale: 5` in the viewport, so zoom is never blocked.
- A global `prefers-reduced-motion` rule, so no component has to remember it.
- `components/ui/Icon.tsx` hides icons from assistive technology by default and
  requires an explicit `label` to expose one — which keeps decorative icons
  silent and makes a meaningful icon a conscious decision.

Spec section 45 — never convey state by colour alone — is a design constraint
that the Phase 4 status components implement.

## 10. Database

The full reference is [`database.md`](./database.md). Three decisions are
architectural rather than schema detail, and belong here.

### 10.1 Denormalisation made safe by composite foreign keys

`production_records.line_id` and `quality_records.machine_id/component_id` are
derivable by a join, and stored anyway: the dashboard filters and groups by them
on nearly every query, and spec section 29 asks for indexes on columns that must
therefore exist.

The usual cost of denormalisation is drift. It is avoided structurally. Each
parent carries a redundant-looking `UNIQUE (id, <column>)` whose only purpose is
to be the target of a composite foreign key from the child. PostgreSQL then
rejects any child row whose copy disagrees with its parent. No trigger, no
application-level check, and no way for the two to diverge.

This is the pattern to reach for whenever a denormalised column is worth its
keep: make the database prove the copy is correct rather than trusting the code
that writes it.

### 10.2 The quality grain

One row per `(production_record, defect)`, with exactly one NULL-defect row per
production record carrying the passes.

The tempting alternative is one row per production record with a "primary
defect" column. It is simpler and it is wrong: a run that produced three kinds
of defect would record one and silently discard the rest, and the Pareto chart
in spec section 5.3 would be built on incomplete data while looking perfectly
plausible.

With this grain, inspected quantities sum back to what was produced, defect rate
is a plain ratio, and the Pareto chart is a `GROUP BY` with no post-processing.
The cost is one extra concept — the two legal row shapes — which a CHECK
constraint enforces so it cannot be got wrong.

### 10.3 Deriving what can be derived

`inventory_items.status` is a generated column, not a stored value. Stock health
is a pure function of quantity against thresholds, so computing it in the
database removes every path by which the number and its label could disagree,
and removes the need for a job to keep it fresh.

The line between this and spec section 42's "keep calculations in backend
services" is worth stating: **invariants of a single row belong in the database;
aggregates across rows belong in services.** A row describing 3 units of a
material with a minimum of 50 must never be labelled healthy — that is an
invariant. Today's OEE across fourteen machines is an aggregate, and stays in a
service.

## 11. Determinism in the seed

Two separate mechanisms, doing two different jobs. Conflating them is the usual
reason "deterministic" seeds turn out not to be.

**Identifiers** are derived, not generated: `uuid5(namespace, natural_key)`. The
same natural key yields the same UUID in any process on any machine. Three
things follow. Re-seeding becomes a plain `ON CONFLICT (id) DO UPDATE` with no
lookup table. A foreign key can be computed before the row it points at exists,
so generation order is free — which is why the generator builds production
records *before* machines and derives machine utilisation from them. And the
dataset can be compared across runs, which is what makes the determinism tests
possible without a database.

**Values** come from `random.Random` seeded by a blake2b hash. Python's built-in
`hash()` is salted per process for strings, so a seed built on it would produce
different data every run while appearing deterministic within one.

Each random stream is keyed to the coordinates of the thing being generated —
date, shift, machine — rather than drawn from one shared sequence. Generation is
therefore order-independent: adding a machine to the catalogue changes only that
machine's rows and leaves the rest of the history byte-identical. A single
shared stream would reshuffle ninety days of data every time the catalogue
changed, which would make the seed reproducible but not stable, and would break
every test that asserts on a specific window.

## 12. Generation separated from persistence

`generator.py` contains no database code. `seed.py` contains no generation
logic.

That split is what allows the dataset's properties — determinism, referential
integrity, quantity arithmetic, the defect distribution, the inventory ledger
reconciling to stated stock — to be tested without a database at all. It also
makes a failure unambiguous: either the data is wrong or the write is, never
both at once.

It has a third effect worth naming. Spec section 31 requires that values are not
randomised on every API request. With generation living in a module that nothing
in the request path imports, that is guaranteed structurally rather than by
remembering.

## 13. Typography

`next/font/google` downloads font files at build time. That makes the build
depend on reaching `fonts.gstatic.com`, which fails on offline and
network-restricted machines — including the one this project is developed on.
Phase 1 replaced it with a system font stack, which also removes a
render-blocking external fetch and eliminates font-swap layout shift. For a
dense operational data UI the visual cost is negligible. To adopt a bespoke
typeface later, self-host the woff2 files and use `next/font/local`, which has
no network dependency.
