# Production readiness

What Phase 7 found by running the whole stack together, what was fixed, and what
a real deployment still needs.

Companion to [`e2e-verification.md`](./e2e-verification.md), which records what
was executed. This one records what it *meant*.

---

## 1. Defects found

Seven, in a codebase with 466 passing unit tests. Each was invisible until the
parts were connected, and that is the point of the phase rather than an
indictment of the tests.

### 1. Migration ordering — SQL functions created before their tables

**Severity: blocking.** Migration 001 created `app.current_user_id()` and two
siblings as `language sql` functions selecting from `public.users`. PostgreSQL
validates a SQL function body at creation time, and `users` is not created until
migration 003, so applying the migrations to an empty database failed
immediately:

```
ERROR: 42P01: relation "public.users" does not exist
```

The Phase 2 test suite parsed every statement with `pglast` and confirmed valid
grammar — which it is. Only an actual `CREATE` against a real server checks that
the referenced object exists.

**Fix:** moved the three helpers into migration 008, beside the RLS policies
that would use them. `schema.sql` regenerated.

### 2. `DATABASE_URL` unusable — two independent problems

**Severity: blocking.**

- The password contained `@` and `#` unencoded, so the URL did not parse:
  `urlparse` returned `host=None`. Percent-encoding was required.
- The host `db.<ref>.supabase.co` **does not resolve**. Supabase moved direct
  connections to IPv6-only; IPv4 clients must use the pooler at
  `aws-0-<region>.pooler.supabase.com` with the user `postgres.<ref>`.

**Fix:** `.env` rewritten to the session-mode pooler with the password encoded.
`.env.example` documents both traps.

### 3. psycopg cannot use Windows' default event loop

**Severity: blocking on Windows.** Python 3.8+ on Windows defaults to
`ProactorEventLoop`; psycopg's async mode refuses it:

```
Psycopg cannot use the 'ProactorEventLoop' to run in async mode.
```

Every pool connection attempt failed, `/health/ready` reported the database
unreachable, and every database-backed endpoint would have errored.

Worse, the obvious fix does not work. Uvicorn 0.36+ selects the loop through a
*factory*, not the policy, and hardcodes `ProactorEventLoop` on win32 — so
`asyncio.set_event_loop_policy(...)` is ignored under uvicorn.

**Fix:** `app/runtime.py` exposes a `loop_factory`, and `app/__main__.py` runs
uvicorn with `loop="app.runtime:loop_factory"`. `python -m app` now works on any
platform. Production on Linux is unaffected — the default there is already
compatible.

### 4. Rate limiting bypassable by rotating `X-Forwarded-For`

**Severity: high — security.** Uvicorn enables `proxy_headers` by default and
rewrites `request.client` from `X-Forwarded-For` whenever the peer is in
`forwarded_allow_ips`. The application has its own, more careful rule in
`client_identifier`, which honours the header only up to `TRUSTED_PROXY_COUNT`
hops and ignores it entirely when no proxy is configured — but it never gets a
chance, because `request.client` has already been rewritten upstream.

Measured: with the limiter returning 429, a request carrying a fresh
`X-Forwarded-For` returned **200**, in a bucket keyed `ip:10.0.0.109`. Rotating
the header gives unlimited fresh buckets, removing the limit entirely —
including on the authentication endpoints.

Deployments that widen `forwarded_allow_ips` to `*`, which is common behind a
load balancer, make this reachable from the internet.

**Fix:** `proxy_headers=False` in `app/__main__.py`. One component owns the
decision, and it is the one that knows how many proxies are actually in front.
Re-verified: the bucket now keys on the real peer and the spoofed request
returns 429.

**Production deployments must do the same.** Gunicorn's `UvicornWorker` also
enables proxy headers by default; see §3.

### 5. Quality and production did not reconcile

**Severity: medium — correctness.** The quality repository filtered on
`quality_records.inspected_at`, while production filtered on
`production_records.record_date`. A night shift's inspections are timestamped
after midnight, so the two windows selected different sets of runs.

Over the same thirty days: **398,369 units inspected against 395,315 produced.**

That is not cosmetic. The dashboard prints a production defect rate beside a
quality defect rate; different denominators mean two panels on one screen
disagree and neither looks wrong. It is the failure mode the whole project has
been careful about, arrived at from a different direction.

Proven by direct SQL: filtering quality through the parent production record's
`record_date` yields exactly 395,315.

**Fix:** all quality queries now join `production_records` and window on
`pr.record_date`, including the trend's bucketing and the daily KPI totals. The
join is on a primary key covered by `quality_records_production_record_idx`.

After the fix, measured live: production 379,142 and quality 379,142 over the
same window, with all three defect rates at 2.54%.

### 6. Integration tests could never run

**Severity: medium.** The 25 tests in `test_integration_db.py` errored at setup
with a `ScopeMismatch`: a module-scoped async `pool` fixture asking for
pytest-asyncio's function-scoped loop.

They had skipped since Phase 2 because no database was reachable, and a skipped
test cannot report a broken fixture.

**Fix:** `pytest_asyncio.fixture(scope="module", loop_scope="module")` on the
pool, matching `loop_scope` on the dependent fixtures, and
`pytest.mark.asyncio(loop_scope="module")` on the module. All 25 now pass — and
finding 5 is one of the things they caught.

### 7. A momentary Redis outage disabled the cache permanently

**Severity: medium — reliability.** `create_redis` returned `None` if the
startup ping failed, and `CacheClient(None)` is disabled for the life of the
process. Redis being unreachable in the second a worker boots is a normal event
— an orchestrator starting the app before Redis accepts connections, or a
rolling Redis upgrade — and the response was to send every subsequent request to
PostgreSQL until someone redeployed.

**Fix:** the client is returned even when the initial ping fails, and the
circuit breaker owns the decision from there. Two connection-error retries with
a short backoff were added so a dropped idle connection is re-established rather
than counted as a failure, and `health_check_interval` reduced to 15s.

Verified: Redis stopped and restarted under a running worker, which recovered on
its own — readiness back to `ready`, caching resumed.

---

## 2. What holds up

Verified against the live stack, not asserted:

- **Deny-by-default RLS.** Enabled *and forced* on all 15 tables, no policies,
  no privileges for `anon` or `authenticated`. Supabase's advisor reports only
  INFO notices, which is the intended shape.
- **Append-only audit log.** `UPDATE` on `audit_logs` is rejected by trigger,
  for every caller including the service role.
- **Deterministic, idempotent seed.** Two runs, identical counts and identical
  KPIs.
- **RBAC.** 56 role/endpoint combinations correct. Anonymous 401, forbidden 403.
  A forged `role` claim is ignored — the database decides.
- **Token handling.** Malformed, foreign-key-signed, `alg=none` and expired
  tokens all refused. Logout revokes server-side and the same token then fails.
- **SQL injection.** Every payload refused with 422 before reaching the
  database; no internals leaked; row counts unchanged.
- **CSRF.** Missing, wrong and foreign-Origin requests all 403; correct token
  and Origin succeeds.
- **Open redirect.** Six hostile forms contained, including CRLF.
- **CORS.** Exact origin with credentials; hostile origin refused with no
  `access-control-allow-origin`. Wildcard is impossible in production — config
  validation refuses it.
- **Graceful degradation.** Redis down, dashboard still serves real data.
- **Fail-closed production config.** Seven unsafe settings each refuse to start.
- **API contract.** 77 checks; the Phase 5 TypeScript types match the live API
  exactly, with no mismatch found.

---

## 3. Before deploying

### Required

1. **Set `proxy_headers=False`** on whatever serves the app. Gunicorn's
   `UvicornWorker` enables it by default:
   ```
   gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w $WORKERS \
     --forwarded-allow-ips=""
   ```
   Then set `TRUSTED_PROXY_COUNT` to the number of proxies actually in front, so
   `client_identifier` honours exactly that many `X-Forwarded-For` hops. Getting
   this wrong in the other direction — trusting a header nobody appends — is
   finding 4.

2. **`APP_ENV=production`.** Configuration validation then enforces a 32+
   character `SECRET_KEY`, `COOKIE_SECURE=true`, `DEBUG=false`, HTTPS on the
   OAuth redirect and frontend URLs, HTTPS CORS origins, and refuses wildcard
   CORS. Verified: all seven unsafe cases refuse to start.

3. **HTTPS everywhere.** Register the production `GOOGLE_REDIRECT_URI` in the
   Google console; it must match exactly and must be `https://`.

4. **HSTS at the TLS terminator**, not the application —
   `max-age=63072000; includeSubDomains; preload`. Deliberately not emitted by
   the app, which cannot know whether the connection is really HTTPS.

5. **Percent-encode the database password** and use the pooler host. See
   finding 2.

### Recommended

6. **Roll the CSP out report-only**, watch for a week, then switch to enforcing
   by setting `NEXT_PUBLIC_CSP_REPORT_ONLY=false`. Add a `report-uri` first. See
   [`security-headers.md`](./security-headers.md).

7. **Complete the browser verification** this phase could not: Google sign-in
   end to end, every page rendered, the six breakpoints, keyboard navigation and
   a screen reader, and CSP enforcement. §13 of the verification record lists
   exactly what is outstanding.

8. **Confirm rate limiting across workers.** The counter is in Redis and shared
   by construction, but it was verified against one worker.

---

## 4. Known limitations

**Rate limiting buckets authenticated users by IP.** `client_identifier` prefers
`request.state.user_id`, but the limiter runs as middleware and the user is
resolved later, in a dependency — so the `user:` branch never fires in practice.
Colleagues behind one NAT share a bucket and can throttle each other. Fixing it
properly means moving the limiter after authentication resolution, which changes
the middleware chain; it was left alone rather than restructured during a
hardening phase. The control itself works.

**Cache latency spikes at the start of a Redis outage.** The first requests wait
out the connect timeout — measured at 7–15s — until three failures open the
circuit breaker, after which they drop to ~600ms. Bounded and self-correcting,
but worth knowing before someone reads it as a hang.

**The frontend has never been rendered in a browser.** Everything about its
appearance and interaction is unverified. Structural accessibility is asserted
in jsdom, which has no layout engine.

**Seed data is dated relative to generation.** The dashboard anchors to the most
recent date with production rather than to the wall clock, so a database seeded
long ago still displays. Re-seed for a fresh demo.
