# Browser end-to-end verification

Phase 8. Everything recorded here was observed in Chromium, driven by Playwright,
against the **production build** of the frontend (`next build` + `next start`) and
the **live FastAPI backend** talking to the real Supabase database and Redis.

No mock adapter was enabled. `NEXT_PUBLIC_ENABLE_API_MOCKS` stayed `false`, and
`lib/api/mock/install.ts` refuses to install itself in a production bundle in any
case. Every figure asserted in these tests came out of PostgreSQL.

## How to read the status column

| Status | Meaning |
| --- | --- |
| **PASS** | The behaviour was observed in the browser and asserted. |
| **FAIL** | Tested, and broken. Every FAIL below was fixed; the row records what was found. |
| **BLOCKED** | Could not be executed because of an environment or credential limitation. Never converted into a PASS with a mock. |
| **NOT TESTED** | Deliberately not attempted. The reason is given. |

A row marked FAIL that is followed by "fixed, regression test added" means the
defect was reproduced first, fixed at the layer that owned it, and is now held
down by a named test in `client/e2e/`.

## Running the suite

```bash
# 1. Backend (Windows needs the explicit loop factory; see server/app/runtime.py)
cd server
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
    --loop app.runtime:loop_factory

# 2. Frontend, production build
cd client
npm run build && npm run start

# 3. The suite
cd client
npx playwright test
```

`e2e/global-setup.ts` checks that both servers answer before any test runs, then
mints one short-lived session per role by calling the backend's own token issuer
(`server/tools/mint_test_sessions.py`). It runs on every invocation because the
tokens live fifteen minutes — a stale session file produces failures that look
exactly like authentication bugs, and half a day was lost to that before the
setup step existed.

The suite does **not** retry (`retries: 0`), and that is load-bearing: several
tests assert against the shared rate limiter and the shared database, and a retry
would turn a real intermittent defect into a green run. Every flaky test found in
this phase was fixed at its cause rather than retried past.

`workers: 1` is the configured default. It is no longer a requirement -- once the
shared-session and date-window defects below were fixed, `--workers=2` passed too,
and faster -- but it stays the default because the tests share one backend, one
Redis and one rate-limit bucket, and a serial run is the one whose failures are
easiest to read.

### Two environment settings this machine needs

Neither is an application requirement; both are consequences of the local setup,
and both cost a working evening before they were understood.

* **`DB_POOL_MAX_SIZE=6` on the local backend.** Supabase's pooler allows 15
  clients in session mode. The default pool of 10, plus the session minter, plus
  the slots leaked by hard-killing the backend during development, exhausts it --
  and because authentication needs a database lookup, exhaustion presents as
  every page bouncing to `/login`.
* **Something must hold the WSL VM open.** It shuts down when no process is using
  it and takes Redis with it. The application degrades correctly when that
  happens (see the Redis outage row), but the suite then measures the degraded
  path instead of the one it meant to.

## What was found

Nine defects, all reproduced in the browser before anything was changed. The
first five were visual or accessibility problems; the last four were not visible
at all until the application was put under a real browser and made to fail.

### 1. Every chart rendered blank — FAIL, fixed

`globals.css` carried `max-width: 100%` on `.recharts-wrapper`, added in Phase 6
as insurance against horizontal overflow. Recharts 3 renders

```
.recharts-responsive-container   (correctly measured, e.g. 729px)
  └── div                        (0 x 0 until Recharts sizes it)
        └── .recharts-wrapper    (the element Recharts actually sizes)
```

so the `max-width` resolved against a zero-width parent and clamped the wrapper
to nothing. Because Recharts writes an explicit width onto the wrapper rather
than the middle div, it could never grow back. Legend, caption and data table all
rendered correctly; only the plot area was empty, which is why review had missed
it.

It survived Phase 6 and Phase 7 because jsdom has no layout engine — every
structural test passed against an element measuring zero.

Regression test: `dashboard.spec.ts` → "an SVG chart is actually painted, not an
empty box". It measures `.recharts-wrapper > .recharts-surface`; the child
combinator matters, because legend icons are also `.recharts-surface` and are
legitimately 10px.

### 2. The page scrolled sideways on every small viewport — FAIL, fixed

At 375, 390, 768 and 1024px the document scrolled horizontally: `scrollWidth`
902 against a 375px body, and the page could be dragged 527px sideways. Wide
tables were leaking their intrinsic width to the root scroller.

`overflow-x: hidden` on `main` and `body` did nothing — the leak was intrinsic
sizing, not painting. `table-layout: fixed` fixed it and destroyed column sizing.
`contain: paint` on the table's scroll container fixed it while preserving both
the layout and the table's own internal scrolling.

Regression test: `responsive.spec.ts` → "a wide table scrolls inside its card,
not the page", at six widths.

### 3–5. Three axe-core violations — FAIL, fixed

Found by running axe against the live DOM on all nine pages.

* **colour contrast.** `--subtle` was `#71717a`, which measures 4.83:1 on white
  and passes — but the page background is `#f4f5f7`, where it is 4.43:1. It was
  used for exactly the text most likely to be skimmed. Now `#6b6b74`: 4.84:1 on
  the background, 5.28:1 on a card. Dark mode already passed at 5.49:1.
* **aria-hidden-focus.** Recharts' `accessibilityLayer` inserts focusable
  elements inside a container the app marks `aria-hidden`. Disabled, since the
  charts already supply a caption and a real data table.
* **definition-list.** `Stat` rendered its hint as a `<p>` beside the `<dt>`/`<dd>`
  pair, which breaks the term-description association. Moved inside the `<dd>`.

All nine pages now report zero violations across `wcag2a`, `wcag2aa`, `wcag21a`,
`wcag21aa` and `wcag22aa`.

### 6. Back did not undo a filter — FAIL, fixed

`useUrlFilters` used `router.replace`, so filter changes left no history entry
and Back navigated off the page instead of clearing the filter. Changed to
`router.push`.

### 7. The CSP blocked every script in the production build — FAIL, fixed

The most serious finding of the phase, and one that Phase 7 had recorded as
passing.

Running the production build in Chromium with a `securitypolicyviolation`
listener produced **53 violations, all `script-src-elem`**. The served HTML
carried twelve `<script>` tags and **zero** `nonce` attributes. The policy was
in report-only mode, which is the only reason the application was usable at all;
enforcing it would have served a blank page.

Phase 7's claim — "nonce stamped onto 23 of 23 script tags" — had been measured
against a stale development server left running on port 3000, not against a
production build.

Two causes, both required:

1. `proxy.ts` set only an `x-nonce` request header. Next.js reads the nonce from
   a `Content-Security-Policy` header **on the request**, and from nowhere else.
2. Even with that corrected, every route was statically prerendered (`○ (Static)`
   in the build output). A static page is generated before any request exists, so
   there is no header to read and no nonce to inject. Next.js's own guide states
   this directly: *"you must use dynamic rendering to add nonces."*

Fixed by setting the request-side CSP header in `proxy.ts` and calling
`connection()` in the root layout, which opts the whole tree into dynamic
rendering. All twelve routes now build as `ƒ (Dynamic)` and all twelve script
tags carry the request's nonce.

The cost is small *here* and would not be elsewhere: every page is behind
authentication and loads its data client-side, so the prerendered HTML was only
ever an empty shell, and `proxy.ts` already ran on each of these requests so no
CDN was caching them.

Regression tests: `security.spec.ts` → "the nonce reaches every script tag" and
"no CSP violations are reported while the app runs".

### 8. Zod's JIT compiler tripped the CSP — FAIL, fixed

With the nonce fixed, two `script-src blocked eval` violations remained on every
page that parses a schema. Traced to columns 7626 and 39841 of the shared chunk:
Zod 4's `Function("")` capability probe and its `compile()`.

Zod does guard the call — it falls back to an interpreted path if the probe
throws — but the probe *is* the forbidden operation, so it still reports a
violation. `z.config({ jitless: true })` in `lib/env.ts`, which is the only
module in the client bundle importing Zod, removes both. Validation behaviour is
unchanged; the module parses five values once at load, so the JIT was earning
nothing.

The alternative — adding `'unsafe-eval'` to `script-src` — would have relaxed the
policy to accommodate a probe whose failure is already handled.

### 9. A failing backend produced a permanent retry storm — FAIL, fixed

The worst defect in the phase, and invisible to every other kind of test.

With `/dashboard/summary` returning 500, the endpoint was requested **once per
second, indefinitely**, and the dashboard showed skeletons that never resolved —
no error message, no outage banner, no end.

The request timing named the cause: a clean **1000ms, 2000ms, ~80ms** cycle,
repeating. The first two gaps are `retryDelay`'s backoff for the two retries
`shouldRetry` allows. The ~80ms is a remount.

`BackendUnavailable` returned `<>{children}</>` when healthy and
`<><div role="alert"/>{children}</>` when not. React reconciles unkeyed siblings
by position, so `children` moving from index 0 to index 1 tore down and rebuilt
the entire page beneath it. Remounting an observer on a failed query refetches it
(`retryOnMount` defaults on) with `failureCount` reset to zero — so the two-retry
cap never terminated anything. The refetch put the query back in `pending`, the
banner disappeared, the subtree remounted again, and the cycle restarted.

Two consequences, the second being the serious one. The user saw a page that
never finished loading, because no error state survived longer than the next
remount. And the API received roughly one request per second per open tab,
forever, having already reported that it was failing — a dashboard left on a wall
display would have held a struggling service under load until someone closed the
tab.

Fixed by rendering the banner as a conditional expression in a fixed slot so
`children` keeps its position. After the fix: **3 requests in 20 seconds** —
the initial attempt and two retries — then silence, with the outage banner and
per-panel errors both on screen.

Regression test: `errors.spec.ts` → "a failed request is retried twice and then
left alone", which asserts on the request count, because the request count is the
damage.

### 10. The rate limiter bucketed every signed-in user by IP address — FAIL, fixed

Surfaced as RBAC tests failing with 429s that moved between roles from run to
run — the signature of a shared bucket rather than a broken assertion.

`client_identifier` prefers `request.state.user_id`, and `_policy_for` selected
the authenticated policy from the same attribute. Both were correct in intent and
neither ever fired: `user_id` is set by `get_token_claims`, a route *dependency*,
and dependencies run after all HTTP middleware. The limiter ran first and took
both fallbacks on every authenticated request.

Reproduced directly: two different signed-in users on one address, the first
exhausting the window, the second refused on its next request with no traffic of
its own. The first user cut off at exactly **60** requests — the *unauthenticated*
allowance, not the 120 a signed-in user is entitled to — which is what identified
the cause.

For a factory this is not a footnote: shop-floor terminals sit behind one NAT, so
the whole site would have shared a single 60-per-minute budget.

Fixed by resolving the subject in the rate-limit middleware, before the policy
and the bucket are chosen, via `resolve_rate_limit_subject`. It confers no
authority — a failure to decode simply means an IP bucket — and
`get_current_user` still runs the full flow afterwards.

Regression test: `security.spec.ts` → "one user's traffic does not throttle
another on the same address".

### 11. Ordinary login-page traffic consumed the sign-in allowance — FAIL, fixed

Found while fixing the above. The bucket name came from the third path segment
while the policy came from the whole path, so `/auth/status` and
`/auth/google/login` shared one counter while being held to 120 and 10 requests a
minute respectively.

`/auth/status` is what the login page calls on open. **Twelve** calls — a dozen
reloads, an ordinary thing to do after a failed sign-in — left the next real
sign-in attempt refused with a 429. The strictest limit in the system was the
easiest to trip, by traffic never meant to count against it.

`_policy_for` now returns the bucket and the policy together, so a new
classification cannot be added without giving it a bucket. Verified: fifteen
`/auth/status` calls followed by a sign-in that still redirects to Google.

Regression test: `security.spec.ts` → "routine login-page traffic does not
consume the sign-in allowance".

### 12. The frontend's redirect check was weaker than the backend's — FAIL, fixed

`safeNextPath` rejected `//evil.example` but passed `/\evil.example` straight
through into the sign-in link. Browsers normalise a backslash to a forward slash,
so that is the same protocol-relative URL in a different coat.

**The application was never vulnerable** — `is_safe_relative_path` on the backend
rejects backslashes, and all five hostile payloads were confirmed to be discarded
with the redirect still going to `accounts.google.com`. But the frontend has a
filter whose stated job is to drop hostile values before they reach a link a user
might see or copy, and it had a hole. It now mirrors the backend's rule,
including the percent-decoding pass that catches `/%2f%2fevil.example`.

The test that found this was itself wrong, and worth recording: it asserted that
the payload must not appear in the sign-in link, and called that "the open
redirect defence". It is not — the API is. The test now checks each layer for
what that layer actually owns.

## Why the full suite failed while every spec passed alone

The suite was first run end to end late in the phase and reported **66 failed,
70 passed**, while every spec file passed when run on its own. Almost every
failure read the same way -- "expected Factory Operations, received Sign in" --
on tests with no interest in authentication.

Three separate causes, found by reproducing rather than reasoning.

### 1. Signing out destroyed a session the whole suite shared

`auth.spec.ts` signs out for real, and `security.spec.ts`'s CSRF happy path
does too. Signing out does not merely clear the cookie: the API adds the token's
id to a revocation denylist in Redis, and the token is dead everywhere from that
moment. Both tests were using the shared ADMIN session minted once per run, so
from the moment the first of them ran, every later spec that signed in as ADMIN
was browsing as a signed-out visitor.

**This nearly went uncorrected.** The first probe written to test exactly this
theory returned 200 for all six roles after `auth.spec.ts`, which appeared to
disprove it. Redis happened to be down at that moment, and the revocation check
fails open when the cache is unreachable, so the revoked token still worked. Run
with Redis healthy, the same probe returns ADMIN 401 / VIEWER 200. A green probe
was evidence of a broken dependency, not of a working session.

Fixed with `signInDisposable()`: a test that consumes a credential gets its own.
The spare sessions are minted by `global-setup.ts` before any test runs, so the
normal path makes no network call mid-suite -- an earlier version minted inside
the test, and a DNS blip then failed a CSRF assertion with `getaddrinfo failed`,
which reads as a CSRF defect and is nothing of the sort.

### 2. Cross-checks compared two different questions

Four assertions in `pages.spec.ts` called an endpoint bare -- `/production`,
`/analytics/oee`, `/quality/summary`, `/quality/defects` -- while the page asked
for an explicit date window, then required the two answers to match. They agreed
only for as long as the backend's default window happened to match the page's.

The suite ran past local midnight on a UTC+5:30 machine, so the local date had
rolled over while UTC had not. The page counted **966** production records over
one window and the bare call counted **927** over another; OEE read 79.4% against
the test's 80.2%. Both looked like the UI displaying wrong figures.

`recordApiRequests()` and `requestFor()` now let a test replay the exact URL the
browser used. Two of the four had been passing on luck.

### 3. Sessions expired mid-run

Access tokens live fifteen minutes -- the application's real setting, not
something a test should change -- and the suite took longer than that. The last
minutes of every run authenticated with expired credentials. `fixtures.ts` now
re-mints when the shared sessions are within five minutes of expiry. Nothing is
re-run and no assertion is relaxed; the suite declines to use a credential it
knows is stale.

### And two environment failures, which is why the picture was confusing

Neither is an application defect, and both are load- and duration-dependent,
which is exactly why short single-spec runs never saw them.

* **Supabase pooler exhaustion.** The pooler allows 15 clients in session mode
  (`EMAXCONNSESSION`, confirmed in the backend log). Repeatedly hard-killing the
  backend during this phase leaked slots. Authentication needs a database lookup,
  so pool starvation also presents as "signed out", and hanging requests left
  "Updating" on screen until `waitForData` timed out. The local backend now runs
  with `DB_POOL_MAX_SIZE=6` for headroom.
* **Redis disappearing.** The WSL VM shuts down when no process holds it, taking
  Redis with it. A persistent holder now keeps it up.

A transient DNS failure to the pooler also interrupted two runs
(`getaddrinfo failed`). Notably, the backend recovered from it unaided: it went
`not_ready` on the database and returned to `ready` about sixty seconds later
with no restart.

### Two test defects found by repetition alone

Repeat runs are the only reason these surfaced.

* `errors.spec.ts` asserted that no HTTP status code reached the screen by
  scanning the whole of `main` for `500`. "500" is an ordinary number on a
  factory dashboard -- a shift target, a produced count -- so the test failed on
  one run in three on real data. The requirement is that the *error* must not
  leak its status, so the check now reads the error regions, where the pattern is
  also widened to any 4xx/5xx.
* The rate-limit regression test filled the bucket with up to 400 sequential
  requests and tripped the 45-second test timeout on a slower backend. The fix
  was not a longer timeout: the requests are now issued concurrently, which takes
  8.6 seconds and is a truer exercise of a rate limiter than traffic no limiter
  would ever need to stop.

## Open findings (not fixed)

### During a total outage, each panel repeats the outage message

`BackendUnavailable` states in its own documentation that it exists so that eight
panels do not each report the same outage. They still do: with the API
unreachable, the dashboard shows the application-level banner *and* eight
"Cannot reach the server" boxes beneath it.

Not changed, deliberately. Suppressing per-panel errors during a global outage is
a design decision affecting every view, not a defect fix, and the panels are at
least telling the truth. Recorded here for a decision rather than settled
unilaterally.

### A timed-out request takes about 48 seconds to report itself

`NEXT_PUBLIC_API_TIMEOUT_MS` is 15s and a timeout is retryable, so the user waits
three full attempts plus backoff before being told anything. Measured at 49.2s in
`errors.spec.ts`. This is the configured behaviour rather than a defect, but 48
seconds of skeleton is a long time on an operations screen, and either a shorter
timeout or no retry on timeout would be worth considering.

## Google OAuth: BLOCKED, not passed

The sign-in handoff was driven in a real browser as far as it can go without
entering credentials, and it is correct up to that point:

* the browser reached `accounts.google.com/v3/signin/identifier`;
* `response_type=code`, `scope=openid email profile`;
* `code_challenge_method=S256` with a 43-character challenge;
* a 30-character `state` and a 20-character `nonce`;
* `redirect_uri` pointing at the registered backend callback;
* Google's own consent screen named the registered client, "Smart Dashboard for
  Automotive Factory".

Google then required an account password. Entering credentials is not something
this process does, so the callback, code exchange, and first-session creation
**cannot be verified here**. They are marked BLOCKED below.

Everything downstream of a session was tested using sessions minted by the
backend's own token issuer. That exercises the real cookie, the real JWT
validation, the real revocation store and the real RBAC — but it is **not**
evidence that the OAuth callback works, and is not presented as such anywhere in
this document.

Screenshot: `artifacts/e2e/02-oauth-google-consent-BLOCKED.png`. It shows
Google's own sign-in page; no credential was typed and none is visible.

## Status matrix

### Authentication and session

| # | Behaviour | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Login page renders with a working Google entry point | PASS | `auth.spec.ts` |
| 2 | Google button reachable and activatable by keyboard alone | PASS | `auth.spec.ts` |
| 3 | Anonymous visitors redirected away from protected routes | PASS | `auth.spec.ts` |
| 4 | Handoff to Google carries PKCE, state, nonce, scoped transaction cookie | PASS | `auth.spec.ts` |
| 5 | Google consent screen reached and identifies the registered client | PASS | screenshot 02 |
| 6 | OAuth callback, code exchange, first session creation | BLOCKED | Google requires interactive credentials |
| 7 | Session cookie is HttpOnly and unreadable from JavaScript | PASS | `auth.spec.ts` |
| 8 | Authenticated session resolves the current user and survives reload | PASS | `auth.spec.ts` |
| 9 | Logout clears the session and re-protects the dashboard | PASS | `auth.spec.ts` |
| 10 | Expired session redirects to login without a loop, and explains itself | PASS | `auth.spec.ts` |

### Data correctness

| # | Behaviour | Status | Evidence |
| --- | --- | --- | --- |
| 11 | Every dashboard section renders real data with no browser errors | PASS | `dashboard.spec.ts` |
| 12 | KPI cards show real values, not placeholders | PASS | `dashboard.spec.ts` |
| 13 | No NaN, undefined, null or Infinity anywhere on any page | PASS | `dashboard.spec.ts` |
| 14 | Figures on screen agree with the API response | PASS | `dashboard.spec.ts`, `pages.spec.ts` |
| 15 | "Last updated" is stated without claiming to be live | PASS | `dashboard.spec.ts` |
| 16 | Charts are actually painted, not empty boxes | PASS (was FAIL) | finding 1 |

### Pages, navigation and interaction

| # | Behaviour | Status | Evidence |
| --- | --- | --- | --- |
| 17 | All nine routes render at a direct URL | PASS | `pages.spec.ts` |
| 18 | Every sidebar link navigates client-side and marks itself current | PASS | `pages.spec.ts` |
| 19 | Browser back and forward move between pages | PASS | `pages.spec.ts` |
| 20 | Each page sets a distinct document title | PASS | `pages.spec.ts` |
| 21 | Filters change the URL, the request and the results | PASS | `pages.spec.ts` |
| 22 | A filter survives reload, and Back undoes it | PASS (was FAIL) | finding 6 |
| 23 | Pagination moves through real rows without overlap | PASS | `pages.spec.ts` |
| 24 | Sorting re-sorts against the backend | PASS | `pages.spec.ts` |
| 25 | An impossible filter shows an empty state, not a broken table | PASS | `pages.spec.ts` |
| 26 | Machine detail opens the right machine; bad ids fail safely | PASS | `pages.spec.ts` |

### Responsive and accessibility

| # | Behaviour | Status | Evidence |
| --- | --- | --- | --- |
| 27 | No horizontal page scroll at 375/390/768/1024/1280/1440 | PASS (was FAIL) | finding 2 |
| 28 | A wide table scrolls inside its card, not the page | PASS (was FAIL) | finding 2 |
| 29 | Mobile drawer navigates, traps focus, restores it on close | PASS | `responsive.spec.ts`, `accessibility.spec.ts` |
| 30 | Zero axe violations (WCAG 2.2 A/AA) on all nine pages | PASS (was FAIL) | findings 3–5 |
| 31 | Every interactive control shows a visible focus ring | PASS | `accessibility.spec.ts` |
| 32 | One h1 per page, no skipped heading levels, labelled landmarks | PASS | `accessibility.spec.ts` |
| 33 | Status is conveyed as text, never by colour alone | PASS | `accessibility.spec.ts` |
| 34 | Charts carry a caption and a keyboard-reachable data table | PASS | `accessibility.spec.ts` |
| 35 | `prefers-reduced-motion` is honoured | PASS | `accessibility.spec.ts` |

### Security

| # | Behaviour | Status | Evidence |
| --- | --- | --- | --- |
| 36 | Security headers present on every response | PASS | `security.spec.ts` |
| 37 | CSP is nonce-based, with no `unsafe-eval` and no wildcards | PASS | `security.spec.ts` |
| 38 | The nonce reaches every script tag in the production build | PASS (was FAIL) | finding 7 |
| 39 | No CSP violations while the application runs | PASS (was FAIL) | findings 7, 8 |
| 40 | XSS payloads in filters and in API text render inert | PASS | `security.spec.ts` |
| 41 | SQL injection payloads are rejected and change no data | PASS | `security.spec.ts` |
| 42 | A hostile `next` never takes the browser off-origin | PASS (was FAIL, defence-in-depth) | finding 12 |
| 43 | CSRF: cross-origin and wrong-token POSTs refused, correct one succeeds | PASS | `security.spec.ts` |
| 44 | RBAC enforced by the API for all six roles, independent of the UI | PASS | `security.spec.ts` |
| 45 | No token in `localStorage`/`sessionStorage`, no secret in the bundle, no JWT in a URL | PASS | `security.spec.ts` |
| 46 | The browser talks only to the app origin and its API | PASS | `security.spec.ts` |
| 47 | Rate limiting buckets per user, not per address | PASS (was FAIL) | finding 10 |
| 48 | Login-page traffic does not consume the sign-in allowance | PASS (was FAIL) | finding 11 |

### Failure handling

| # | Behaviour | Status | Evidence |
| --- | --- | --- | --- |
| 49 | 401 ends the session and returns the user to sign-in | PASS | `errors.spec.ts` |
| 50 | 403 is refused permanently and does not bounce to sign-in | PASS | `errors.spec.ts` |
| 51 | 404 reports a missing record rather than an empty page | PASS | `errors.spec.ts` |
| 52 | 422 surfaces the backend's specific message, with no retry offered | PASS | `errors.spec.ts` |
| 53 | 429 explains the wait and offers no pointless retry | PASS | `errors.spec.ts` |
| 54 | 500 shows a recoverable error and the retry actually re-requests | PASS | `errors.spec.ts` |
| 55 | No status code, stack trace or internal URL ever reaches the screen | PASS | `errors.spec.ts` |
| 56 | An unreachable API is reported as a connection problem | PASS | `errors.spec.ts` |
| 57 | Going offline pauses rather than fails; reconnecting refreshes | PASS | `errors.spec.ts` |
| 58 | A request that never arrives times out and says so | PASS | `errors.spec.ts` (49.2s) |
| 59 | A failed request is retried twice, then left alone | PASS (was FAIL) | finding 9 |
| 60 | One failed region does not take the page or navigation with it | PASS | `errors.spec.ts` |
| 61 | A slow region shows a shaped skeleton announced to assistive tech | PASS | `errors.spec.ts` |
| 62 | A refresh keeps existing figures on screen rather than blanking | PASS | `errors.spec.ts`, `dashboard.spec.ts` |
| 63 | An outage is announced once at application level | PASS | `errors.spec.ts` |
| 64 | Per-panel errors are suppressed during a global outage | FAIL | open finding, not fixed |

### Infrastructure

| # | Behaviour | Status | Evidence |
| --- | --- | --- | --- |
| 65 | The API keeps serving with Redis stopped (cache fails open) | PASS | manual, recorded below |
| 66 | Multi-worker session consistency | NOT TESTED | single-worker uvicorn locally; needs a real multi-worker deployment |
| 67 | Cross-browser (Firefox, WebKit) | NOT TESTED | Chromium only, per the phase brief |
| 68 | Real mobile hardware | NOT TESTED | emulated viewports and touch only |

## Performance

Measured on the production build against the live backend.

### API requests per page load

Counted from `page.on("request")` across a full load to a settled state.

| Page | Requests | Duplicates |
| --- | --- | --- |
| `/dashboard` | 4 | 0 |
| `/production` | 9 | 0 |
| `/quality` | 9 | 0 |
| `/inventory` | 6 | 0 |
| `/machines` | 5 | 0 |
| `/analytics` | 10 | 0 |
| `/alerts` | 4 | 0 |
| `/maintenance` | 7 | 0 |

**Zero duplicate requests on every page.** Two of the four requests on every page
are shared shell calls (`/auth/me`, `/alerts/summary`); the rest are the page's
own. `/dashboard` is deliberately four rather than nine because
`/dashboard/summary` returns production, quality, inventory, machines, OEE, KPIs
and alerts in one response.

## Screenshots

`artifacts/e2e/`:

| File | What it shows |
| --- | --- |
| `01-login-desktop.png` | Sign-in page, signed out |
| `02-oauth-google-consent-BLOCKED.png` | Google's own sign-in page — the point at which verification stops |
| `03-dashboard-desktop.png` | Dashboard, 1440×900, real data |
| `04-production.png` … `10-maintenance.png` | Each remaining page with live data |
| `11-dashboard-mobile.png` | Dashboard at 390×844 |
| `12-mobile-drawer-open.png` | Mobile navigation drawer open |

No screenshot contains a token, a cookie value, or a credential. The OAuth
screenshot shows an empty Google sign-in form.

Playwright's own run output — traces, videos, failure screenshots, the HTML
report — is written to `artifacts/e2e/test-results/` and is gitignored. It is
regenerated by every run and is tens of megabytes.
