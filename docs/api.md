# API reference

Base URL: `/api/v1`. Interactive documentation is at `/docs` in development
(disabled automatically when `APP_ENV=production`).

**37 endpoints across 9 tags.** Every one is a `GET`; Phase 3 is read-only.

---

## 1. Response shapes

Three envelopes, and nothing else.

**Single resource or aggregate**

```json
{ "data": { "...": "..." } }
```

**Paginated list**

```json
{
  "data": [],
  "pagination": { "page": 1, "page_size": 25, "total": 1250 }
}
```

**Error**

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "One or more supplied values were not valid.",
    "details": { "page_size": ["Input should be less than or equal to 100"] },
    "request_id": "9f2c8e14-..."
  }
}
```

`request_id` also arrives as the `X-Request-ID` response header and appears in
the server log for the same request, so a failure can be traced end to end. Send
your own `X-Request-ID` and it is preserved.

### Error codes

| Code | Status | Meaning |
|---|---|---|
| `VALIDATION_ERROR` | 422 | A query or path parameter failed validation. `details` names the field. |
| `INVALID_SORT_FIELD` | 422 | `sort_by` is not an allow-listed key. `details` lists the permitted values. |
| `INVALID_REQUEST` | 422 | A domain rule rejected the input. |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests. See `Retry-After`. |
| `DATABASE_UNAVAILABLE` | 503 | The database is unreachable or unconfigured. |
| `DATABASE_ERROR` | 503 | A query failed. Details are in the server log only. |
| `HTTP_404` | 404 | No such resource. |
| `INTERNAL_SERVER_ERROR` | 500 | Unexpected failure. Details are in the server log only. |

Error responses never contain a stack trace, SQL, a file path or a connection
string (spec §68). When something goes wrong, quote the `request_id`.

---

## 2. Common parameters

### Date range

Applies to every production, quality, analytics and trend endpoint.

| Parameter | Type | Notes |
|---|---|---|
| `start_date` | `YYYY-MM-DD` | Inclusive, UTC |
| `end_date` | `YYYY-MM-DD` | Inclusive, UTC |

Both optional. Supplying neither gives **the last 30 days**; supplying one
anchors the window against the other. `start_date` must not be after
`end_date`, and the span is capped at **366 days** — an unbounded range would
turn a dashboard query into a reporting job (spec §64).

### Pagination

| Parameter | Type | Default | Maximum |
|---|---|---|---|
| `page` | integer ≥ 1 | 1 | 100000 |
| `page_size` | integer ≥ 1 | 25 | **100** |

### Sorting

`sort_by` accepts only allow-listed keys; anything else is a 422 naming the
permitted values. `sort_dir` is `asc` or `desc`.

| Endpoint | Permitted `sort_by` |
|---|---|
| `/production` | `date` `produced` `planned` `accepted` `rejected` `downtime` `machine` `component` |
| `/quality` | `inspected_at` `inspected` `rejected` `passed` `machine` `component` |
| `/inventory` | `name` `sku` `status` `quantity` `updated` |

### Unknown parameters are rejected

Every filter model sets `extra="forbid"`, so `?machine=...` (instead of
`machine_id`) is a 422 rather than being silently ignored. Typos surface
immediately instead of producing quietly wrong results.

---

## 3. Dashboard

### `GET /dashboard/summary`

Everything the executive dashboard needs, in one request: KPI cards, production,
quality, inventory, machine availability, OEE and open alerts. Nine aggregates
run concurrently server-side, so the response costs roughly one query's latency
rather than nine.

No parameters. Cached for 30 seconds.

```bash
curl -s http://localhost:8000/api/v1/dashboard/summary | jq '.data.kpis[] | {label, value, unit, status}'
```

Two fields deserve explanation.

**`business_date`** — the "today" the figures cover. It is anchored to the most
recent date that *has* production, not to the wall clock. Demo data is seeded up
to the day it was generated, so anchoring to the calendar would show an empty
dashboard on any later day — indistinguishable from a broken deployment.

**`cache_hit`** — whether this response came from Redis. Useful when diagnosing a
stale dashboard; it says nothing about the data itself.

Each KPI card carries its value, unit, a context sentence, a textual status
(`good` / `warning` / `critical` / `neutral`) and a trend. The frontend formats;
it does not calculate (spec §42).

### `GET /dashboard/trends`

Chart series: daily production against target, daily defect rate, daily OEE, and
the Pareto-ordered defect breakdown.

| Parameter | Notes |
|---|---|
| `start_date`, `end_date` | Default: last 30 days |
| `line_id` | UUID, optional |

---

## 4. Production

| Endpoint | Returns |
|---|---|
| `GET /production` | Paginated production runs |
| `GET /production/summary` | Aggregate quantities, minutes, achievement, efficiency, defect rate |
| `GET /production/trend` | Daily totals with the matching target |
| `GET /production/by-machine` | Totals grouped by machine |
| `GET /production/by-component` | Totals grouped by component |
| `GET /production/by-shift` | Totals grouped by shift |
| `GET /production/by-line` | Totals grouped by line |

Filters: `start_date` `end_date` `machine_id` `component_id` `shift_id`
`line_id`, plus `page` / `page_size` / `sort_by` / `sort_dir` on the list, and
`limit` on the grouping endpoints.

```bash
curl -s "http://localhost:8000/api/v1/production?start_date=2026-08-01&end_date=2026-08-31&sort_by=produced&sort_dir=desc&page_size=10"
```

> **Target comparison.** Daily targets are recorded per (date, line, component)
> and have no machine or shift dimension. When the filter includes
> `machine_id` or `shift_id`, `target_quantity` and `achievement_percentage`
> are returned as **0** rather than comparing one machine's output against a
> whole line's target — which would understate achievement while looking
> plausible. Filter by line or component to get a meaningful comparison.

> **`has_data`.** Every summary carries it. A `0.0` percentage means either
> "nothing was produced" or "everything failed", and the rate alone cannot tell
> you which — so the counts and `has_data` travel with it.

---

## 5. Quality

| Endpoint | Returns |
|---|---|
| `GET /quality` | Paginated inspection lines |
| `GET /quality/summary` | Defect rate, first pass yield, quality rate |
| `GET /quality/defects` | Pareto-ordered defect breakdown |
| `GET /quality/trend` | Daily defect rate |
| `GET /quality/by-machine` | Rejection rates per machine |
| `GET /quality/by-component` | Rejection rates per component |

Filters: `start_date` `end_date` `machine_id` `component_id` `defect_id`, plus
`rejections_only` on the list.

**The two row shapes.** Each production run has one *pass line*
(`defect_id: null`, carrying the accepted units) and one further line per defect
type found. So:

- `is_rejection` distinguishes them.
- `rejections_only=true` returns only the defect lines.
- Summaries aggregate across both, which is why `total_inspected` equals the
  units produced in the period.

**First pass yield** uses all inspected units as its denominator, not just units
that passed. A part reworked into an acceptable state did not pass first time,
so FPY is always at or below the quality rate.

The Pareto endpoint returns `share_percentage` and a running
`cumulative_percentage`, both computed server-side. Leaving the cumulative
series to the chart would mean every consumer re-deriving it and getting a
different answer from a differently sorted or truncated copy.

---

## 6. Inventory

| Endpoint | Returns |
|---|---|
| `GET /inventory` | Paginated stock lines |
| `GET /inventory/alerts` | Lines that are CRITICAL or LOW, most urgent first |
| `GET /inventory/summary` | Counts per state and overall health |
| `GET /inventory/{item_id}` | One stock line |
| `GET /inventory/{item_id}/transactions` | Paginated stock movements |
| `GET /inventory/{item_id}/trend` | Closing balance per day |

Filters: `status` (`HEALTHY` `LOW` `CRITICAL` `OVERSTOCKED`), `component_id`.

`status` is computed by the database from the quantity and its thresholds, so
the label and the number can never disagree. Each alert carries a full-sentence
`message`, readable without colour or an icon.

`quantity_delta` on a transaction is **signed**: positive adds stock, negative
removes it.

`total_stock_value` is `null` when any item has no unit cost — a partial sum
presented as a total would be worse than no number.

---

## 7. Machines

| Endpoint | Returns |
|---|---|
| `GET /machines` | The fleet, unpaginated |
| `GET /machines/summary` | Fleet counts and availability |
| `GET /machines/{machine_id}` | One machine with statistics and maintenance |

Filters: `status` (`RUNNING` `IDLE` `MAINTENANCE` `OFFLINE`), `line_id`. The
detail endpoint accepts `start_date` / `end_date` for its statistics window
(default: last 30 days).

> **Availability counts only `RUNNING` machines.** An idle machine is capable but
> not producing; counting it as available would make a stopped line look
> healthy, which is the opposite of what the dashboard is for.

`maintenance_due` is true when the next service falls within seven days **or is
already overdue** — a negative `days_until_maintenance` must not read as
"not yet".

---

## 8. Analytics

Rate-limited more strictly (30/min by default) and cached longer (15 min).

| Endpoint | Returns |
|---|---|
| `GET /analytics/oee` | OEE with its three terms |
| `GET /analytics/oee/trend` | Daily OEE |
| `GET /analytics/oee/by-machine` | OEE per machine, worst first |
| `GET /analytics/production-efficiency` | Efficiency against plan and target |
| `GET /analytics/production-efficiency/trend` | Daily efficiency |
| `GET /analytics/downtime` | Downtime per machine, worst first |
| `GET /analytics/defects` | Full defect analysis in one response |

Filters: `start_date` `end_date` `machine_id` `component_id` `line_id`.

**OEE always reports its three terms**, because a single number tells a manager
something moved but not whether to look at breakdowns, cycle times or scrap
(spec §5.6):

```
OEE = Availability × Performance × Quality
```

Each term is capped at 100%. `performance_uncapped_percentage` exposes the raw
figure: **above 100 means a component's recorded ideal cycle time is shorter
than the machine's real capability** — a reference-data problem, not a machine
outperforming physics. The cap keeps OEE interpretable; the uncapped value keeps
the problem visible.

---

## 9. Alerts and maintenance

| Endpoint | Returns |
|---|---|
| `GET /alerts` | Paginated alerts, most severe first |
| `GET /alerts/active` | Open alerts only |
| `GET /alerts/summary` | Counts by severity |
| `GET /maintenance` | Paginated maintenance jobs |

Alert filters: `status` (`OPEN` `ACKNOWLEDGED` `RESOLVED`), `severity`
(`INFO` `WARNING` `CRITICAL`), `machine_id`.
Maintenance filters: `status`, `machine_id`, `upcoming_only`.

`upcoming_only=true` switches the ordering to soonest-first so the next job is
at the top rather than buried under history.

---

## 10. Health

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness |
| `GET /health/live` | Liveness (alias) |
| `GET /health/ready` | Readiness, with dependency detail |

**Liveness touches no dependency.** If it checked the database, a database blip
would have every instance killed and restarted — turning a recoverable
dependency outage into an application outage.

**Readiness reports.** The database is required, so an unhealthy one returns
**503** with `status: not_ready`. Redis is optional: the API degrades to reading
the database directly, so an unhealthy cache returns **200** with
`status: degraded` rather than removing the instance from service.

---

## 11. Rate limiting

Redis-backed fixed windows, enforced across every worker. Configurable through
the `RATE_LIMIT_*` environment variables.

| Scope | Default |
|---|---|
| Health endpoints | 600/minute |
| Analytics endpoints | 30/minute |
| OAuth endpoints (Phase 4) | 10/minute |
| Everything else, unauthenticated | 60/minute |
| Everything else, authenticated (Phase 4) | 120/minute |

Every response carries `X-RateLimit-Limit`, `X-RateLimit-Remaining` and
`X-RateLimit-Reset`. A 429 additionally carries `Retry-After`.

Two properties worth knowing:

- **The bucket key cannot be forged.** `X-Forwarded-For` is consulted only when
  `TRUSTED_PROXY_COUNT` says a proxy is genuinely in front, and then only that
  many entries from the right. With no proxy configured the header is ignored
  entirely — otherwise a client could send a new value per request and get an
  unlimited allowance from a limiter that looks configured.
- **A Redis outage fails open.** Requests are allowed and the outage is logged.
  Failing closed would convert a cache outage into a total outage.

---

## 12. Security headers

Every response carries:

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `no-referrer` |
| `X-Frame-Options` | `DENY` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |

`nosniff` is the one that matters here. Responses are JSON, and a JSON string
can legitimately contain `<script>alert(1)</script>` — it is *data*, and the
frontend escapes it on render. Without `nosniff`, a browser asked to open such a
response directly could sniff it as HTML and execute it.

`Content-Security-Policy` and `Strict-Transport-Security` are deliberately
absent. A meaningful CSP has to be written against the frontend's real script and
style sources, so it belongs with the application shell; HSTS belongs at the
TLS-terminating proxy, which knows whether the connection is HTTPS. Adding
placeholders here would give false assurance.

---

## 13. Caching

Read-through, with tiers from spec §12. All TTLs are configurable.

| Tier | Default TTL | Used by |
|---|---|---|
| Realtime | 30s | Dashboard summary, inventory alerts, machine fleet summary |
| Trend | 5 min | Production and quality summaries, trends, defect breakdown |
| Analytics | 15 min | OEE, efficiency, defect analysis |
| Reference | 60 min | Slow-moving lookup data |

**Lists are not cached.** A filtered, paginated, sorted list has very high key
cardinality and low reuse; caching it would fill Redis with entries nobody reads
twice. Aggregates are the opposite — few keys, read constantly.

**Cached values are validated on read.** A deployment that changes a response
shape treats entries written by the previous version as misses and replaces
them, rather than serving stale-shaped data until the TTL expires.

**Nothing sensitive is cached.** Only aggregate, factory-wide business data. Keys
are built from resource names, dates and filter values — never a credential or
personal data (spec §16). When role-scoped data arrives in Phase 4, the
authorization context has to become part of the key; `CacheKeys.for_user` exists
for exactly that.

---

## 14. Worked examples

```bash
BASE=http://localhost:8000/api/v1

# The whole dashboard in one call
curl -s "$BASE/dashboard/summary" | jq '.data | {business_date, cache_hit}'

# Production for one line in August, best days first
curl -s "$BASE/production?line_id=<uuid>&start_date=2026-08-01&end_date=2026-08-31&sort_by=produced&sort_dir=desc"

# Why is OEE down?  Look at the three terms.
curl -s "$BASE/analytics/oee?start_date=2026-08-01&end_date=2026-08-31" \
  | jq '.data | {availability_percentage, performance_percentage, quality_percentage, oee_percentage}'

# Which defects dominate?
curl -s "$BASE/quality/defects?limit=8" \
  | jq '.data[] | {defect_name, share_percentage, cumulative_percentage}'

# What needs attention right now?
curl -s "$BASE/inventory/alerts" | jq '.data[] | {name, status_label, message}'
curl -s "$BASE/alerts/active"    | jq '.data[] | {severity_label, title}'

# Rejected: an unknown sort key
curl -s "$BASE/production?sort_by=id;drop%20table%20x" | jq '.error'
```

---

## 15. Accessibility of the payload

Spec §45 requires that state is never conveyed by colour alone, and that the
text remains understandable in greyscale. The API therefore returns a label
alongside every status:

```json
{
  "status": "CRITICAL",
  "status_label": "Critical",
  "message": "Lubricant is at 310 litres, at or below the minimum of 400."
}
```

The same applies to `machine_type_label`, `severity_label`,
`maintenance_type_label`, and to KPI cards, which carry `status_label` and a
textual `trend.direction` (`up` / `down` / `flat` / `unknown`) rather than an
arrow or a colour.

Labels are produced server-side rather than mapped in the UI for two reasons: a
label is part of the API contract, so two components cannot render the same
status differently; and a new enum value added by a migration surfaces as a
failing test rather than as a raw `HEAT_TREATMENT_FAILURE` on someone's screen.
