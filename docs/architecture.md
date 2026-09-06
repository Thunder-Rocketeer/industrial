# Architecture

Decisions taken during Phases 1 to 4, and the reasoning behind them. This
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

**Five view states, derived once.** `lib/query/query-state.ts` collapses
TanStack Query's flags into a single status: `loading`, `refreshing`, `success`,
`empty`, `error`. Two of those distinctions are the reason the module exists.
Separating `refreshing` from `loading` is what stops a filter change from
blanking a table that already has rows on screen; separating `empty` from
`success` is what stops a legitimately empty result from rendering as a table
with headers, no rows and no explanation, which reads as a bug. Left to each
component, those two decisions drift, and they drift silently.

Full reference: [`frontend-data-layer.md`](./frontend-data-layer.md).

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

## 13. The backend layers

```
Router      HTTP only: parse, validate, delegate, return
   |
Service     business rules, KPI derivation, cache orchestration
   |
Repository  database access, parameterised, nothing else
   |
PostgreSQL
```

Two rules keep it honest, and both are enforced by tests rather than by review.

**No SQL above the repository.** A test parses every service and route module
and fails on a SQL keyword. That is what makes the injection surface auditable:
one directory to read.

**No KPI formula outside `services/kpi.py`.** Every percentage the application
reports comes from one of eleven pure functions. Duplicating `rejected /
inspected` in a second place is how two endpoints end up disagreeing about the
same day's defect rate while each looks plausible alone.

The maintenance endpoint got its own service purely to preserve this. It needs
no business logic, but letting a route call a repository directly would have put
data access in a handler.

## 14. Where an aggregate is computed

In PostgreSQL, always. A 90-day production summary touches roughly 3,000 rows in
the database and returns one; the alternative transfers 3,000 rows to compute a
sum in Python (spec sections 11 and 23).

Two cases are worth calling out because the reason is not obvious.

**Ideal output for the Performance term** is summed in SQL, not derived from a
total. Cycle time varies per component, so a machine that ran three parts has
three different ideal rates — the denominator is only correct if it is summed
per row.

**Production and targets are aggregated separately, then joined on the date.**
Joining first would multiply production rows by the number of target rows for
that day. It is the classic fan-out, and it inflates a sum silently: the detail
list still looks right. An integration test asserts the aggregate equals the sum
of the detail rows, which is the assertion that catches it.

## 15. Concurrency in the dashboard, and its cost

The dashboard summary needs nine independent aggregates. They run under
`asyncio.gather`, each on its own pooled connection, bounded by a semaphore
sized from `DB_MAX_CONCURRENT_QUERIES`.

The bound is the point. Spec section 19 asks for concurrency "without
sacrificing database stability" — and without a limit, a handful of simultaneous
page loads would each try to take nine connections and exhaust a pool sized for
ten.

The cost of this design is worth stating plainly: because each query takes its
own connection, the nine aggregates read in nine separate transactions and
therefore nine slightly different snapshots. For a dashboard that refreshes every
thirty seconds this is immaterial. If exact cross-aggregate consistency were ever
required, they would have to share one connection and run sequentially — trading
latency for it.

Every other endpoint takes exactly one connection for the whole request, so its
repositories all read from the same snapshot.

## 16. Degradation as a design property

Three dependencies can fail, and each has a defined behaviour rather than an
accidental one.

**Redis unavailable** — every cache operation returns "miss" and the request
reads the database. Requests are slower and entirely correct. A circuit breaker
opens after repeated failures so an outage costs one timeout per cooldown window
rather than one per request; without it, a cache outage becomes a latency
outage.

**Redis unavailable, for the rate limiter** — fails *open*. Requests are allowed
and the outage is logged. Failing closed would convert a cache outage into a
total outage, which is the worse failure.

**Database unavailable** — liveness still answers `ok`, readiness reports
`not_ready` with 503, and data endpoints return a clean `DATABASE_UNAVAILABLE`
envelope. Liveness deliberately touches nothing: if it checked the database, a
blip would have an orchestrator kill and restart every healthy instance.

The pattern throughout is that a failure degrades the response, never the
envelope. A client always gets a well-formed answer.

## 17. What the API returns, and what it does not

**Never a raw database row.** Every endpoint declares a response model and every
mapping is written out field by field. `model_validate(row)` would be shorter and
would silently publish the next column someone adds.

**Never HTML.** The API returns structured data; a stored `<script>` tag comes
back as a JSON string value, intact. Sanitising it here would be wrong — the
value is data, the frontend escapes on render. What makes that safe is the
content type plus `nosniff`, which stops a browser opening the response directly
from reinterpreting it as a document.

**Never an internal detail in an error.** A psycopg error message can contain the
failing SQL, a column name or a connection string. The handler sends it to the
log with `exc_info` and returns a code, a safe message and the request ID.

**Always a label with a status.** Spec section 45 forbids conveying state by
colour alone, so `status_label`, `severity_label` and the rest travel with their
enum. Producing them server-side means two components cannot render the same
status differently, and a new enum value fails a test instead of appearing raw
on screen.

## 18. Two constraints discovered while building

Recorded because both cost time and neither is obvious from the documentation.

**FastAPI allows one Pydantic model bound to the query string per route, and it
cannot be combined with additional scalar `Query` parameters.** Doing so makes
the model a required body-style field, and every request fails with
`filters: Field required`. Seven grouping endpoints hit this; the fix was to move
`limit` onto the filter model. An API test that walks every documented endpoint
is what caught it.

**Dependencies resolve before path-parameter validation.** A request to
`/machines/<not-a-uuid>` against an unreachable database returns 503, not 422 —
the connection dependency raises first. Worth knowing when reading a test
failure, and harmless in production where the database is up.

## 19. Authentication shape, revisited

Section 8 sketched this before it existed. What was built matches, and three
decisions are worth recording with their costs.

### 19.1 The session is a cookie, and the frontend knows nothing else

There is no token in JavaScript, no decoded JWT in a store, nothing in
`localStorage`. The frontend's entire notion of "am I signed in" is the answer to
`GET /auth/me`.

The cost is one request on load, and a state machine with a genuine `loading`
state. The benefit is that the client cannot hold a stale or forged opinion about
who it is, and that an injected script cannot exfiltrate a token to replay
elsewhere. The `HttpOnly` flag is doing real work: XSS can still act as the user
while the page is open, but it cannot take the session away with it.

### 19.2 The role is in the token *and* the database, and the database wins

The token carries a `role` claim, and every request loads the user anyway to
check `is_active`. So the claim saves nothing.

It is kept because it makes a token self-describing in a log, and because the
authoritative read is already paid for. The consequence is the useful direction:
a role change takes effect on the *next request*, not at token expiry.

### 19.3 Revocation fails open, deliberately

A denylist of revoked `jti` values lives in Redis. If Redis is down, the check
cannot run, and there are exactly two options.

Rejecting every request would mean a cache outage logs out every user of a
dashboard that is otherwise able to serve them — converting a degraded
dependency into a total outage, which is the failure Phase 3's whole design
avoids. So a revoked token stays usable for at most its remaining lifetime,
15 minutes by default, and the failure is logged loudly.

This is the one place in the system where availability was chosen over security,
and it is bounded by the token lifetime rather than open-ended. An application
where immediate revocation is a hard requirement should carry a server-side
session lookup and accept the per-request read.

## 20. Where authorization actually lives

Four layers claim to control access. Only one of them does.

```
proxy.ts          cookie present?          UX      -- cannot verify anything
RequireAuth       session confirmed?       UX      -- client-side, editable
permissions[]     hide a button            UX      -- advisory
require_permission  backend, every request AUTHORITATIVE
```

The top three exist so a signed-out visitor does not see a flash of empty
dashboard, and so a Viewer is not shown a button that would 403. Each can be
defeated by anyone willing to edit their own browser, and defeating them yields
an empty shell and a series of 401s.

Stating the hierarchy explicitly matters because the failure mode is quiet: a
frontend guard that looks like security invites someone to skip adding the
backend check, and nothing visibly breaks until it is exploited.

Two consequences shape the code. Routes declare a **permission**, never a role,
so the matrix is a table rather than a scattering of role lists that drift.
And protection is attached at the **router**, so an endpoint added later inherits
it instead of being unguarded until someone notices.

## 21. Two things the specification asked for that were deliberately not built

**Content-Security-Policy.** Spec section 17 asks for the headers to be reviewed
and says a CSP must be designed against real frontend requirements. Those
requirements did not exist yet — the dashboard was Phase 6. A policy written now
would be a guess, and a guessed CSP has a predictable life: it breaks something,
someone adds `unsafe-inline`, and it protects nothing while appearing to. It is
deferred with the reason recorded rather than filled in.

**Resolved in Phase 6.** The frontend now exists and its resource requirements
were measured against a production build, not guessed. The policy, the evidence
behind each clause, and the single relaxation it needs
(`style-src-attr 'unsafe-inline'`, for chart geometry) are in
[`security-headers.md`](./security-headers.md). It is documented and ready
rather than enabled, because a CSP should ship report-only first.

**HSTS.** It belongs at the TLS-terminating proxy, which knows whether the
connection is HTTPS. Emitting it from an application served over `http://`
localhost would pin the developer's browser to HTTPS for a host that does not
serve it — a self-inflicted outage, and a confusing one.

## 22. Typography

`next/font/google` downloads font files at build time. That makes the build
depend on reaching `fonts.gstatic.com`, which fails on offline and
network-restricted machines — including the one this project is developed on.
Phase 1 replaced it with a system font stack, which also removes a
render-blocking external fetch and eliminates font-swap layout shift. For a
dense operational data UI the visual cost is negligible. To adopt a bespoke
typeface later, self-host the woff2 files and use `next/font/local`, which has
no network dependency.

## 23. Three caches, one source of truth

The dashboard has caching in three places, and they answer different questions.

| Layer | Scope | Lifetime | Question it answers |
| --- | --- | --- | --- |
| TanStack Query | One browser tab | Seconds to minutes | Did *this user* just see this? |
| Redis | Shared, server-side | Per-endpoint TTL | Did *anyone* just ask this? |
| PostgreSQL | — | Durable | What is true? |

They are tuned independently, and neither cache is a statement about
correctness: both are permitted to be stale, and only PostgreSQL is authoritative.
This is what makes Redis optional at runtime — losing it makes the dashboard
slower, not broken — and it is why a frontend stale time is never derived from a
Redis TTL. Coupling them would mean a change to a server-side TTL silently
altering how often a browser refetches.

## 24. Calculation happens once, in the backend

Every percentage the dashboard displays — OEE and its three terms, defect rate,
first-pass yield, achievement against target, stock utilization, inventory
health — is computed by `services/kpi.py` and sent as a number.

The frontend formats it. Chart adapters reshape and label it. Table cells render
it. Nothing in the browser divides one API field by another.

The rule is not about tidiness. A second implementation of a metric does not
announce itself: it agrees with the first almost everywhere and disagrees
exactly where the edge cases live — the day a machine ran for four minutes, the
shift with a zero denominator, the defect list truncated to twenty rows whose
cumulative percentage no longer reaches 100. What a user sees then is two panels
on one screen reporting different numbers for the same day, and no way to tell
which is right.

Cumulative percentages make the point sharply. `cumulative_percentage` on a
defect depends on that row's position in the sorted set. An adapter that
re-sorted the rows, or recomputed the running total over a truncated copy, would
produce a Pareto curve that is wrong in a way no assertion about any single row
would catch.

## 25. The dashboard renders; it does not decide

Every number on the interface arrives calculated. That constraint shaped three
choices that would otherwise look like over-engineering.

**The dashboard is one request.** `/dashboard/summary` returns production,
quality, inventory, machines, OEE, the KPI cards and the alerts together, and
the backend computes its nine aggregates concurrently. Eight hooks would mean
eight round trips, eight loading states, and a screen that assembles itself in
pieces while a manager waits to learn whether the factory is all right.

**Chart adapters map and label; they never calculate.** A recomputed defect rate
would agree with the backend almost everywhere and disagree exactly where the
edge cases live — the day a machine ran four minutes, the shift with a zero
denominator, the truncated defect list whose cumulative share no longer reaches
100. The user would then see two panels on one screen reporting different
numbers for the same day, with no way to tell which is right.

**Bar widths are the one exception, and are not numbers.** `TargetVsActual` and
`StatusDistribution` scale a bar to a proportion. That is a drawing decision: it
produces no figure anybody reads, and every percentage rendered as text beside
it came from `services/kpi.py`.

## 26. Status is a word first

Spec section 45 and WCAG 1.4.1 both forbid conveying state by colour alone, and
the usual reading of that is "add an icon". This application takes the stricter
line: every status renders **text** — Running, Critical, Below target — with the
tint and the dot as reinforcement.

The reason is specific to where this runs. A factory floor has daylight washing
out screens, monochrome print-outs pinned to a board, and roughly one man in
twelve with a colour-vision deficiency. A status that depends on distinguishing
amber from red is not a theoretical accessibility failure there; it is a
practical one on a normal Tuesday.

That decision is what forces the labels to come from the backend. `status_label`
and `severity_label` are sent alongside every code, and the UI renders those
strings rather than mapping codes to words itself — otherwise the interface
develops a second vocabulary that drifts from the API's.

## 27. Icons do not depend on the internet

`@iconify/react` resolves an unknown icon name by fetching it from
`api.iconify.design`, with two more public hosts as fallbacks. That is a
reasonable default for a public web app and a poor one here: it makes every icon
depend on a CDN being reachable from a network that may be segmented, it forces
three third-party hosts into the CSP's `connect-src` for decoration, and it
tells a third party which pages are being viewed.

So the icons are extracted at build time instead. `npm run icons` scans the
source, pulls exactly the 43 icons referenced out of the `@iconify-json/*`
devDependencies, and writes a 13 KB data module that is registered at load. No
request is ever made.

The interesting part is the failure mode this creates and how it is closed.
Adding an icon without regenerating the registry still renders correctly in
development — Iconify quietly fetches it — so the regression is invisible
exactly where it would be caught. `tests/icons.test.tsx` therefore renders every
bundled icon with `fetch` instrumented and asserts zero calls, and separately
asserts that every icon name in the source resolves locally.

## 28. What running it together revealed

Phases 2–6 tested the parts. Phase 7 connected them to a real Supabase instance,
a real Redis and a real browserless HTTP client, and found seven defects that
466 unit tests could not. They share a shape worth naming, because it predicts
where the next one will be.

**A test that never runs proves nothing.** The 25 integration tests had skipped
since Phase 2 for want of a database. When one appeared they errored at setup on
a `ScopeMismatch` that had been there all along — and once fixed, they
immediately caught a real reconciliation bug. A skipped test is not a passing
test; it is an unopened envelope.

**Validating a statement is not the same as executing it.** Phase 2 parsed all
155 SQL statements with the real PostgreSQL grammar and they were all valid.
Migration 001 still failed on first contact, because a `language sql` function
body is checked against the catalogue at creation time and the table it selected
from did not exist yet. Grammar is not semantics.

**The layer beneath can quietly undo the layer above.** `client_identifier`
implements a careful trusted-proxy rule and it was correct. Uvicorn rewrote
`request.client` from `X-Forwarded-For` before the application saw it, so the
rule never applied and rate limiting could be bypassed by rotating a header.
Neither component was wrong on its own; the composition was. This is the failure
mode that unit tests are structurally blind to, because each side passes its own
tests.

**Two ways of saying "when" is one too many.** Quality windowed on
`inspected_at`, production on `record_date`. Both defensible, both indexed, both
tested — and together they made the dashboard print 398,369 inspected against
395,315 produced for the same thirty days, with a defect rate that disagreed
with the one in the next panel. The project had been careful about computing a
metric once; it had not been careful about *dating* it once.

**Degradation has to be tried, not designed.** The circuit breaker worked
exactly as intended once Redis was actually stopped. But `create_redis` returned
`None` when the startup ping failed, which disabled the cache for the life of
the worker — a boot-order race in an orchestrator would have quietly sent every
request to PostgreSQL until someone redeployed. The recovery path had never been
walked.

## 29. Dating a measurement

`quality_records` rows carry `inspected_at`, a timestamp of when an inspection
physically happened. `production_records` rows carry `record_date`, the business
date of a shift. For a night shift these differ: the run belongs to Tuesday and
its inspections are stamped early Wednesday.

Filtering quality by `inspected_at` therefore answers "what did we inspect
between these dates", which is a reasonable question and the wrong one here. The
dashboard shows quality beside production, and the defect rate's denominator has
to be the production the card above it reports.

So every quality aggregate now joins its parent production record and windows on
`pr.record_date`. The grain the schema is built on — (date, shift, machine,
component) — is the authority on when something happened, and a child row
inherits its parent's business date rather than asserting its own.

The join costs nothing measurable: it is on a primary key covered by
`quality_records_production_record_idx`, and the Pareto query already did it.

