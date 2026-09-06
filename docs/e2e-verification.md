# End-to-end verification

What was actually executed in Phase 7, against what, and what was not.

The distinction matters more than the results. Phases 2–6 built a system whose
parts were tested in isolation; several of the defects recorded below were
invisible to 466 unit tests and only appeared when the pieces were connected.
Anything marked **not tested** here was not tested, and no claim is made about
it.

---

## 1. Environment

| Component | What was used | Notes |
| --- | --- | --- |
| Database | Supabase PostgreSQL **17.6.1**, region `ap-south-1`, `ACTIVE_HEALTHY` | Real hosted instance; project ref omitted |
| Connection | `aws-0-ap-south-1.pooler.supabase.com:5432`, session mode | See finding 2 |
| Cache | Redis **6.0.16** in WSL2 Ubuntu 22.04 | See "environment limits" |
| Backend | FastAPI on Python 3.10.11, `python -m app` | Windows 11 26200 |
| Frontend | Next.js 16.3.4 production build, `npm run start` | Port 3000 |
| Browser | **none** | The automation extension was not connected |

Verification ran on 2026-09-06.

---

## 2. Database

Applied all nine migrations to the live project, then seeded and verified.

```
python -m app.db.seed      # 13,094 rows
python -m app.db.verify    # 11/11 checks passed
python -m app.db.seed      # again
python -m app.db.verify    # 11/11, identical counts and KPIs
```

**Idempotency confirmed.** The second seed produced identical row counts and
identical aggregate values (395,315 produced, 2.54% defect rate) — the run is
an upsert against natural keys, not an append.

| Check | Result |
| --- | --- |
| 15 tables present | pass |
| Row counts meet spec minimums | pass — 3,033 production, 8,527 quality, 752 targets |
| 22 foreign key constraints across 11 tables | pass |
| Denormalised columns agree with their source | pass — no drift |
| 28 named indexes present (64 total) | pass |
| RLS enabled **and forced** on all 15 tables | pass |
| `anon` / `authenticated` hold no table privileges | pass |
| `audit_logs` rejects UPDATE | pass — trigger fired |
| Derived inventory status correct | pass |
| Inspections reconcile with production | pass |
| Dashboard KPI queries return sane values | pass |

Supabase's own security advisor reports **14 INFO-level `rls_enabled_no_policy`
notices and nothing higher**. That is the intended posture, not a gap: migration
008 enables and forces RLS with no permissive policies, because every read goes
through FastAPI on the service role. A table with RLS forced and no policy denies
everything, which is the deny-by-default design.

### Integration tests

`pytest -m integration` — **25 passed**. These had never executed before: no
reachable database existed in Phases 2–6, and the module skips without one.
Running them found two defects (findings 5 and 6).

They require `DATABASE_URL` to be exported into the process environment;
`conftest.py` blanks it otherwise so the unit suite touches no external service.

---

## 3. Backend

```
GET /api/v1/health        200
GET /api/v1/health/live   200
GET /api/v1/health/ready  200  {"status":"ready", database: Connected, cache: Connected}
GET /docs                 200
GET /openapi.json         200  — 44 paths, 93 schemas
```

All ten tag groups present: Alerts, Analytics, Authentication, Dashboard,
Health, Inventory, Machines, Maintenance, Production, Quality.

Structured logs carry a `request_id` per request and were inspected for
credential leakage: no token, cookie, connection string or password appeared.
`cache.operation_failed` logs the exception **type** only, deliberately, because
a Redis error can carry the connection URL.

---

## 4. Redis

Verified with `tools/e2e_probe.py cache` and `ratelimit` against a real server.

| Behaviour | Result |
| --- | --- |
| Miss writes a key | pass — `dbsize` 8 → 10 |
| Hit returns an identical payload | pass |
| Hit writes no new key | pass |
| TTL is set | pass — 300s on `acf:v1:production:summary:…` |
| A different filter is a separate entry | pass |
| `cache_hit` on the dashboard is truthful | pass — `false` then `true` |
| Rate-limit counters live in Redis | pass — `ratelimit:machines:ip:…`, TTL 60s |
| Revocation denylist in Redis | pass — `auth:revoked:jti:…`, TTL 899s |

Keys observed follow `acf:v1:<domain>:<resource>:<filters-hash>`.

### Outage and recovery

Redis was stopped with the API running.

- Every endpoint kept returning **200** with real data from PostgreSQL.
- `/health/ready` reported `degraded` — database healthy, cache unhealthy.
- The first requests took 7–15s while failures accumulated; after three
  consecutive failures the circuit breaker opened (30s cooldown) and latency
  dropped to ~600ms.
- Redis was restarted. The worker recovered **without a restart**: readiness
  returned to `ready` and `cache_hit` went `false` → `true` again.

That last point only works because of finding 7.

---

## 5. Google OAuth

**Partially verified. The handshake itself was not completed.**

What was verified, live, against real Google infrastructure:

```
GET /api/v1/auth/google/login  ->  302
Location: https://accounts.google.com/o/oauth2/v2/auth
  response_type=code
  scope=openid email profile
  state=<30 chars>
  nonce=<20 chars>
  code_challenge=<43 chars>
  code_challenge_method=S256
  redirect_uri=http://localhost:8000/api/v1/auth/google/callback
Set-Cookie: acf_oauth  path=/api/v1/auth  Max-Age=600  HttpOnly  SameSite=lax
```

PKCE, state, nonce, scope and the short-lived HttpOnly transaction cookie are
all present and correct.

**Not verified:** authenticating as a Google user, the authorization code, the
token exchange, ID-token signature and claim validation, `email_verified`
enforcement, domain restriction, user provisioning, and role assignment on first
login. All of that requires a human at a browser, and the browser automation
extension was not connected.

Everything *downstream* of the session cookie was verified, using sessions
minted with the application's own `issue_access_token` — see §6.

---

## 6. Live probe results

`python -m tools.e2e_probe all` — **211 checks, 0 failures.**

| Suite | Checks | What it covers |
| --- | --- | --- |
| contract | 77 | Every documented endpoint against the frontend's TypeScript types |
| rbac | 56 | 6 roles × 8 domains, plus anonymous |
| session | 10 | Valid, anonymous, malformed, foreign-key, `alg=none`, expired, forged role |
| cache | 11 | Miss, hit, TTL, key separation, `cache_hit` |
| ratelimit | 6 | Threshold, `Retry-After`, envelope, spoofing, Redis counters |
| security | 38 | SQL injection, XSS, CSRF, open redirect |
| pagination | 14 | First, middle, last, past-the-end, filters, sorting |

### How the probe authenticates

Sessions are minted in-process with `issue_access_token` and presented in the
real `acf_session` cookie. Everything downstream is genuinely exercised —
signature verification, issuer and audience checks, expiry, the revocation
denylist, the user lookup, the active-account check and RBAC. Tokens are never
written to disk or logged.

This substitutes for the Google handshake and nothing else.

### API contract

77 checks across all nine domains. Every field the frontend declares is present,
and no field it types as non-nullable ever arrived null. **No mismatch was
found** — the Phase 5 types match the live API exactly.

Two initial failures were defects in the probe, not the application: a wrong
path (`/analytics/efficiency` for `/analytics/production-efficiency`, which the
frontend calls correctly) and an incomplete field list for `inventory.alerts`.

### RBAC

All 56 combinations behave correctly. Anonymous gets **401**; authenticated but
unauthorized gets **403** — the distinction the spec asks for.

A forged `role: ADMIN` claim on a VIEWER's token is **ignored**: the API reports
VIEWER. The role is read from the database, not from the token.

### Injection and XSS

Every SQL payload was refused with **422** before reaching the database, no
internals leaked (no traceback, no `psycopg`, no SQL text), and row counts were
unchanged afterwards (966 → 966). XSS payloads against enum parameters were
refused by validation. All responses are `application/json`; the API never emits
HTML.

### CSRF

Against `POST /auth/logout`, a genuine state change:

| Request | Result |
| --- | --- |
| No CSRF token | 403 |
| Wrong CSRF token | 403 |
| Correct token, `Origin: https://evil.example` | 403 |
| Correct token, allowed Origin | 200 |

### Open redirect

Six hostile `next` values — `//evil.example`, `/\evil.example`,
`https://evil.example`, `/%2f%2fevil.example`, `javascript:alert(1)`, and a CRLF
payload — none reached the `Location` header, and no CR or LF appeared in it.

### CORS

Preflight from `http://localhost:3000` returns that exact origin with
`allow-credentials: true`. Preflight from `https://evil.example` returns **400
with no `access-control-allow-origin`**. No wildcard.

---

## 7. KPI cross-check

Displayed values compared against direct SQL over the same window
(2026-08-08 to 2026-09-06):

```
API production: produced=379,142  rejected=9,618  defect_rate=2.54%
API quality   : inspected=379,142 rejected=9,618  defect_rate=2.54%
DB  production: produced=379,142  rejected=9,618
DB  quality   : inspected=379,142 rejected=9,618

OEE: availability=98.62%  performance=82.64%  quality=97.46%  ->  79.43%
  A x P x Q computed independently     = 79.43%   (API: 79.43%)
  availability = operating/planned     = 419,330/425,190 = 98.62%
  quality      = accepted/produced     = 369,524/379,142 = 97.46%
```

Production and quality reconcile exactly, and all three defect rates agree.
Before finding 5 they did not.

---

## 8. Database performance

`EXPLAIN (ANALYZE, BUFFERS)` on the hot paths.

**Production summary over 30 days** — 4.2ms.
`Index Scan using production_records_record_date_idx`, 51 buffer hits, no disk
reads.

**Defect Pareto** (join across 8,527 quality rows) — 160ms.
`Seq Scan on quality_records` with 5,494 of 8,527 rows matching, joined against
an index scan on `production_records`. The sequential scan is the **correct**
plan at this selectivity — an index scan returning 64% of a 322-page table would
be slower — and every buffer was a cache hit. No index is missing;
`quality_records_production_record_idx` and
`quality_records_defect_inspected_idx` both exist.

No index changes were made. The plans are appropriate for the data volume, and
changing them on theory is what the spec warns against.

---

## 9. Frontend

Built and served, but **not opened in a browser**.

| Check | Result |
| --- | --- |
| `next build` | 12 routes, succeeds |
| `/login` served | 200, 18KB, skip link present |
| Proxy redirect for an anonymous visitor | `307 -> /login?next=%2Fdashboard` |
| CSP header emitted | yes, report-only, with a per-request nonce |
| Nonce stamped onto scripts | **23 of 23 script tags**, including all 3 inline |
| External resource references | **none** — everything same-origin |
| Inline `<style>` blocks / `style=` attributes in served HTML | 0 / 0 |
| `javascript:` URLs, `eval(` | 0 / 0 |
| Frontend tests | 201 passed |

The nonce result is the important one: it is the mechanism most likely to break
under a strict CSP, and it works.

**Not verified:** how any page looks or behaves, responsive layout at any
breakpoint, keyboard navigation in a real browser, screen-reader output, chart
rendering, filter interaction, and whether the CSP blocks anything at runtime.

---

## 10. Test suites

| Suite | Result |
| --- | --- |
| `ruff check` | passed |
| `ruff format --check` | 99 files formatted |
| `pytest` | **466 passed**, 25 skipped |
| `pytest -m integration` | **25 passed** (live database) |
| `npm run lint` | passed |
| `npm run typecheck` | passed |
| `npm run format:check` | passed |
| `npm run build` | succeeds |
| `npm test` | **201 passed** |
| `tools/e2e_probe.py all` | **211 passed, 0 failed** |

---

## 11. Dependency audit

- `npm audit` (with and without dev): **0 vulnerabilities**.
- `pip-audit`: initially 16 findings, all in `pip` (23.0.1) and `setuptools`
  (65.5.0) — virtualenv build tooling, absent from `requirements.txt` and never
  imported by the application. Upgraded both; now **0 known vulnerabilities**.
- No application runtime dependency had a known vulnerability at any point.

---

## 12. Environment limits worth recording

**WSL2 networking is unreliable for a long-running service.** Redis in WSL was
intermittently unreachable from Windows even while `redis-cli ping` succeeded
inside the VM. Two changes were needed:

1. `~/.wslconfig` with `networkingMode=mirrored`, so WSL shares the host network
   stack instead of NAT with localhost forwarding.
2. Binding Redis to `0.0.0.0` in `/etc/redis/redis.conf`.

Even then the WSL VM shuts down when no process holds it open, taking Redis with
it. Verification runs held it open for their duration.

None of this reflects on the application. It is recorded so the next person does
not read an intermittent `ConnectionRefusedError` as a bug in the cache layer.

---

## 13. What was not tested

Stated plainly, because the spec asks for exactly this:

1. **Google sign-in end to end.** No browser was available. The authorization
   redirect was verified against real Google; the callback, token exchange,
   ID-token validation, `email_verified` check, domain restriction, user
   provisioning and first-login role assignment were not.
2. **Any page in a browser.** No dashboard, production, quality, inventory,
   machines, analytics, alerts or maintenance page was rendered visually.
3. **Responsive layout.** Nothing was checked at 375 / 390 / 768 / 1024 / 1280 /
   1440px. Structural assertions in `tests/a11y.test.tsx` run in jsdom, which
   has no layout engine and cannot detect horizontal overflow.
4. **Keyboard and screen-reader behaviour** in a real browser. Semantics are
   asserted structurally; actual focus order and announcements were not observed.
5. **CSP enforcement.** The header is emitted and the nonce propagates
   correctly, but no browser evaluated the policy, so nothing confirms it blocks
   nothing legitimate. It ships report-only for that reason.
6. **Cookie attributes in browser devtools.** They were read from `Set-Cookie`
   response headers instead, which is the same information from the server side.
7. **Multi-worker rate limiting.** Verified against a single worker. The counter
   is in Redis and therefore shared by construction, but this was not
   demonstrated with two workers running.
8. **Load and concurrency.** No sustained or parallel load was applied.
