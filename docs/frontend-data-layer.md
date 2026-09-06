# Frontend data layer

How the browser talks to the API, what it caches, and what it is not allowed to
do. Written for whoever adds the next feature — the rules here are the ones that
are cheap to follow and expensive to discover afterwards.

Phase 5 built this layer. It contains no visual design: Phase 6 renders it.

---

## 1. The shape of it

```
components / pages          render state, never fetch
        │
        ▼
hooks/queries/*             one hook per endpoint; owns cache policy
        │
        ▼
lib/api/*                   one function per endpoint; owns the URL
        │
        ▼
lib/api/client.ts           the single Axios instance
        │
        ▼
FastAPI  →  Redis  →  Supabase PostgreSQL
```

Each layer knows only the one below it. A component that imports `axios`, or a
hook that builds a URL, has skipped a layer and lost whatever that layer
guaranteed.

| Directory | Holds | Never holds |
| --- | --- | --- |
| `types/` | Response and filter types mirroring the backend schemas | Logic |
| `lib/api/` | One typed function per endpoint | React, cache policy |
| `lib/query/` | Query keys, client config, view-state derivation | Requests |
| `hooks/queries/` | One hook per endpoint, with its stale time | URLs, formulas |
| `lib/chart/`, `lib/table/` | Adapters from API shapes to library shapes | Calculations |
| `lib/utils/format.ts` | Display formatting | Arithmetic on metrics |

---

## 2. Axios

**One instance, in `lib/api/client.ts`.** There is a test that fails if a second
`axios.create` appears anywhere in the source, because a second instance would
miss the interceptors — and with them credentials, error normalization and the
session-expiry signal.

It is configured with:

- `baseURL` from `NEXT_PUBLIC_API_BASE_URL`, including the `/api/v1` prefix.
- `withCredentials: true`, so the browser attaches the HttpOnly session cookie.
  This is why the backend must send an explicit CORS origin and never a
  wildcard.
- `timeout` from `NEXT_PUBLIC_API_TIMEOUT_MS`, default 15s.
- `paramsSerializer: { indexes: null }`, which serializes arrays as
  `?shift=A&shift=B` — the form FastAPI expects for `Query(list[str])`.
- A request interceptor adding `Accept` and an `X-Request-ID` correlation id,
  which appears in backend logs for the same request.
- A response interceptor that normalizes every failure into an `ApiError` and
  fires the session-expiry signal on a 401.

**No Authorization header.** The session is an HttpOnly cookie the browser sends
by itself. There is no code that reads a token, because there is no token any
code could read.

### Request helpers

`get`, `post`, `put`, `patch`, `del` in `client.ts` unwrap `response.data` and
type the result. Feature modules use these, never `apiClient` directly.

---

## 3. API modules

One module per domain under `lib/api/`, one exported function per endpoint:

```ts
export async function fetchProductionSummary(
  filters: ProductionFilters = {},
): Promise<ProductionSummary> {
  const response = await get<ApiEnvelope<ProductionSummary>>("/production/summary", {
    params: buildParams(filters),
  });
  return response.data;
}
```

Two conventions:

- **Single-resource endpoints unwrap the `data` envelope.** The caller wants the
  payload, not a wrapper.
- **List endpoints return the whole `PaginatedResponse`.** The pagination
  metadata is exactly what a table needs, so unwrapping it away would mean
  fetching it and throwing it out.

### Query parameters

`lib/api/params.ts` serializes filters. Every module passes filters through
`buildParams`, which:

- drops `undefined` and `null`;
- drops empty and whitespace-only strings — `?status=` is a 422 against an enum
  field, and the user sees "those filters are not valid" for a filter they never
  set;
- keeps `0` and `false`, which are values, not absences;
- drops `NaN`, which is what an emptied number input produces;
- formats `Date` as an ISO date **in UTC**;
- drops anything it cannot serialize, rather than coercing it to
  `"[object Object]"`.

Filter values are always passed as Axios `params`. **Never** build a query
string by hand: Axios escapes values, so a filter containing `&`, `=` or a quote
stays one value instead of becoming two parameters. A test asserts this.

---

## 4. TanStack Query

### Query keys

`lib/query/query-keys.ts` is the only place keys are written. Ad-hoc string keys
inside components are forbidden — two components writing `["production", page]`
and `["production", { page }]` produce two cache entries and two requests for
the same data.

The shape is `[domain] → [domain, resource] → [domain, resource, params]`:

```ts
queryKeys.production.all               // ["production"]
queryKeys.production.list({ page: 1 }) // ["production", "list", { page: 1 }]
```

The domain prefix is what invalidates a whole domain at once
(`invalidateQueries({ queryKey: queryKeys.production.all })`).

Filters are normalized through `keyFilters()` before entering a key, so
`{ page: 1 }` and `{ page: 1, machine_id: undefined }` are the same entry rather
than two.

### Stale times

Set in `lib/constants/cache.ts`, chosen by how fast the underlying data moves:

| Tier | Value | Used for |
| --- | --- | --- |
| `realtime` | 30s | Dashboard summary, machine status, alerts, inventory alerts |
| `trend` | 2 min | Production and quality lists and summaries |
| `historical` | 5 min | Analytics: OEE, efficiency, downtime, defect analysis |
| `reference` | 30 min | Components, lines, shifts, defect types |

`gcTime` is 10 minutes (60 for reference data), so leaving a page and coming
back re-renders from cache instead of re-fetching.

**Only the dashboard summary polls**, every 30 seconds, and
`refetchIntervalInBackground: false` stops it while the tab is hidden. Analytics
never poll: they answer a question about a period that has already ended, and
they are the most expensive queries the API serves.

Paginated and filtered queries use `keepPreviousData`, so changing a page or a
filter keeps the previous rows on screen instead of collapsing the table to a
skeleton and back.

### The five view states

`lib/query/query-state.ts` turns a query result into one discriminated status,
so every component makes the same decision:

| Status | Meaning | UI |
| --- | --- | --- |
| `loading` | First fetch, nothing to show | Skeleton |
| `refreshing` | Has data, fetching an update | Subtle indicator, content stays |
| `success` | Has data, idle | Content |
| `empty` | Succeeded, no rows | Empty state |
| `error` | Failed | Message, and a retry if one would help |

`refreshing` is separate from `loading` because a refetch must not blank the
screen. `empty` is separate from `success` because a table with headers and no
rows and no explanation looks broken.

---

## 5. Errors and retries

`lib/api/errors.ts` normalizes every failure into an `ApiError` with a `kind`:

`network`, `timeout`, `canceled`, `unauthorized`, `forbidden`, `not_found`,
`validation`, `rate_limited`, `client`, `server`, `unknown`.

No raw `AxiosError` ever reaches a component. That matters beyond tidiness: an
Axios error carries the full request config, which is the kind of object that
ends up in a log.

### What is retried

Automatic retry applies **only** to `network`, `timeout` and `server`, at most
twice, with exponential backoff capped at 10s.

Never retried:

| Kind | Why |
| --- | --- |
| `unauthorized` (401) | The session has ended. Retrying loops. |
| `forbidden` (403) | The role is insufficient. Retrying cannot succeed and multiplies audit-log noise. |
| `not_found` (404) | It will not appear on the second try. |
| `validation` (422) | The filters are wrong. Only the user can fix that. |
| `rate_limited` (429) | The server said how long to wait. Ignoring it is how a slow backend becomes a dead one. |

`presentError()` turns an `ApiError` into a title, a message safe to show a
user, and a `canRetry` flag that decides whether a retry button appears at all.
The backend's own message is preferred where present, because it is written to
be user-safe.

### Backend unavailable

`isBackendUnavailable()` distinguishes "the service is down"
(`network | timeout | server`) from "the service refused this request"
(403, 422). Only the first is an outage.

`useBackendStatus()` watches the query cache for that condition and
`components/data/BackendUnavailable.tsx` renders one application-level notice
with a retry, while keeping the last-known data visible and stamped with the
time it was fetched. It issues no health-check request of its own: polling
during an outage adds traffic exactly when the service can least absorb it.

---

## 6. Authentication

Phase 4 owns authentication. The data layer's entire interaction with it:

1. `withCredentials: true` sends the session cookie. Nothing else is needed.
2. A 401 on any request other than the session probe fires `onSessionExpired`,
   which `SessionExpiryWatcher` turns into a redirect to sign-in.
3. Notifications are suppressed for 5 seconds after the first, so a dashboard's
   worth of concurrent 401s produces one redirect rather than eight.
4. `/auth/me` and `/auth/status` are exempt: a 401 there is the normal answer
   for an anonymous visitor, and treating it as an expiry would make every
   signed-out page load announce that a session had ended.
5. State-changing requests carry an `X-CSRF-Token` header, fetched from
   `/auth/csrf`. The CSRF token is deliberately readable — the double-submit
   pattern requires it, and it is not a session secret.

**No token is ever read, stored, logged or attached by application code.**
Frontend role checks are UX only; the backend's RBAC is authoritative, and a
user who edits client state gets a 403, not access.

---

## 7. Tables

Server-driven, in `lib/table/` and `hooks/useServerTable.ts`.

Rows are fetched one page at a time and sorted in PostgreSQL. Client-side row
models are deliberately absent: paginating in the browser needs every row
downloaded first, and sorting in the browser would reorder only the current
page — which looks right and is wrong.

Two hooks, because of render order: the query needs the page number before it
runs, and the table needs the rows after it returns.

```tsx
const columns = useMemo(() => productionColumns(), []);
const tableState = useServerTableState({ initialSorting: [{ id: "date", desc: true }] });
const records = useProductionRecords({ ...filters, ...tableState.queryFilters });
const table = useServerTable({ columns, state: tableState, page: records.data });
```

Details that are easy to get wrong and are therefore centralized:

- **Page numbering.** TanStack counts from 0, the API from 1. The conversion
  lives in `toQueryFilters` and nowhere else.
- **Sort keys.** A sortable column's `id` must be a key the endpoint accepts
  (`date`, `produced`, `efficiency`, …) — not the field name. Columns the API
  cannot sort by set `enableSorting: false`, so the user is never offered a
  control that 422s.
- **Pagination metadata** from the response becomes `rowCount`, so the controls
  know there are 812 records and not just the 25 in hand.
- **Out-of-range pages.** Narrowing a filter can leave the table on page 40 of a
  result set that now has 2. `clampedPageIndex` sends it back, because an empty
  page is indistinguishable from "no matching records".

---

## 8. Charts

`lib/chart/adapters.ts`. One rule:

> **An adapter may reshape and label. It may not calculate.**

Every percentage comes from the backend, computed once, so two views cannot
disagree. An adapter that recomputed a defect rate would create a second
definition of the metric that nobody knows exists, visible only as two panels
showing different numbers for the same day.

Adapters also produce a text `summary` and a `table` of the same numbers, so a
chart is never the only way to read the data.

---

## 9. Caching, in three places

| Layer | Scope | Lifetime | Purpose |
| --- | --- | --- | --- |
| TanStack Query | One browser tab | Seconds to minutes | Avoid re-requesting what this user just saw |
| Redis | Shared, server-side | Per-endpoint TTL | Avoid re-computing what any user just asked for |
| Supabase PostgreSQL | — | Durable | The source of truth |

They are tuned independently. A frontend stale time is not a Redis TTL, and
neither is a statement about correctness: **PostgreSQL is the only authority**,
and both caches are allowed to be stale. Redis failing does not make the
dashboard unusable; it makes it slower.

---

## 10. Development mocks

Off by default. To enable:

```bash
# .env.local
NEXT_PUBLIC_ENABLE_API_MOCKS=true
```

Then restart `npm run dev`. To disable, remove the line or set it to `false`.

Three independent conditions must hold before a single fixture is served — the
flag, `NEXT_PUBLIC_APP_ENV` not being `production`, and `NODE_ENV` not being
`production`. The last is set by the build, not by the environment, so
`next build` closes the door regardless of what anyone configures, and the
bundler drops the fixtures entirely.

While mocks are active a permanent banner says so, every mocked response carries
an `X-Mock-Data: true` header, and the fixtures are named `MOCK-…` so nobody can
mistake them for real data in a screenshot. Only a handful of summary endpoints
are mocked; everything else passes through to the real backend and fails there
if it is down — deliberately, because a mock layer that answers everything makes
a broken backend look like a working application.

---

## 11. Tests

`npm test` (vitest). 97 tests, about 3 seconds.

| File | Covers |
| --- | --- |
| `tests/params.test.ts` | Filter serialization |
| `tests/api-modules.test.ts` | Paths, parameters, envelopes, error normalization |
| `tests/query-layer.test.ts` | Query keys, retry policy, error presentation, pagination |
| `tests/hooks.test.tsx` | The five states, refetch, disabled queries, cache keys |
| `tests/auth.test.ts` | Credentials, CSRF, session expiry and its suppression |
| `tests/adapters.test.ts` | Adapters pass values through; formatting |
| `tests/security.test.ts` | The section 35 review items, as assertions |

`tests/security.test.ts` greps the source tree, which is unusual and is the
point: no browser storage of tokens, no `document.cookie`, no
`dangerouslySetInnerHTML`, no `innerHTML`, no `eval`, no `javascript:` URLs, no
non-literal `location` assignment, no server-only environment variables, no
sensitive logging, and exactly one Axios instance. These are the failures a
functional test cannot see, because the unsafe version passes every assertion it
has.

Vitest runs in the `node` environment by default; files that render components
opt into jsdom with a `@vitest-environment jsdom` docblock, which keeps the
suite about ten times faster.

---

## 12. Rules, in short

**Do**

- Add a type in `types/`, a function in `lib/api/`, a hook in `hooks/queries/`.
- Put filters in Axios `params`, through `buildParams`.
- Add query keys to `query-keys.ts`.
- Read `status` from `toQueryState` rather than combining flags by hand.
- Let the backend calculate. Format the result.

**Do not**

- Create another Axios instance.
- Read a JWT from storage, or build an Authorization header.
- Write a query key inline in a component.
- Concatenate a query string.
- Recompute a KPI, a defect rate, or inventory health in the browser.
- Retry a 401, 403, 404, 422 or 429.
- Load an entire table to paginate or sort it client-side.
- Mark a whole route `"use client"` — keep the boundary narrow.
