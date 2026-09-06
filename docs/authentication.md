# Authentication and authorization

Google OAuth 2.0 / OpenID Connect sign-in, JWT sessions, and role-based access
control. Built in Phase 4 against spec sections 25, 26 and 54–72.

---

## 1. Architecture

```
Browser
   |  1. GET /api/v1/auth/google/login
   v
FastAPI ──── Authlib generates state + nonce + PKCE verifier
   |         and stores them in a short-lived signed cookie
   |  2. 302
   v
Google  ──── user authenticates and consents
   |  3. 302 back with ?code=...&state=...
   v
FastAPI callback
   |  4. Authlib validates state
   |  5. Authlib exchanges the code server-side (with the client secret)
   |  6. Authlib verifies the ID token against Google's JWKS:
   |       signature, iss, aud, exp, iat, nonce
   |  7. account restriction        <- our policy
   |  8. resolve or provision user  <- our policy, role assigned server-side
   |  9. issue application JWT
   | 10. Set-Cookie: HttpOnly, Secure, SameSite
   |  v
Frontend  <- 303 to an allow-listed path
```

Steps 4–6 are Authlib's. Steps 7–10 are this application's. Spec section 1 is
explicit that the protocol must not be hand-rolled, and the division above is
what that means in practice: **we never touch a signature, a state value or a
code exchange.**

### What each layer holds

| Layer | Holds |
|---|---|
| Browser | Two cookies. Neither is readable as a token. |
| `security/oauth.py` | The Authlib client. Protocol only. |
| `security/jwt.py` | Application token issuing and validation. |
| `security/policy.py` | The permission matrix. All of it. |
| `security/dependencies.py` | The request flow. The only place a JWT is parsed. |
| `services/auth_service.py` | Who may sign in, and what role they get. |

---

## 2. Google Cloud configuration

You need a Google Cloud project. Nothing here costs money.

### 2.1 Create the project and consent screen

1. Open the [Google Cloud console](https://console.cloud.google.com/) and create
   a project (or pick an existing one).
2. **APIs & Services → OAuth consent screen**.
3. User type:
   - **Internal** if you have a Google Workspace organisation. Only your
     organisation can sign in, which is account restriction enforced by Google
     as well as by this application.
   - **External** otherwise. While the app is in *Testing*, only accounts you
     list as test users can sign in — which is exactly what you want for a
     course demo. Do not publish it.
4. Fill in the app name, a support email and a developer contact.
5. **Scopes**: add only `openid`, `.../auth/userinfo.email` and
   `.../auth/userinfo.profile`. Nothing else. The application never calls a
   Google API after sign-in, so any further scope would be a permission asked
   for and never used.
6. If you chose External, add your Google account under **Test users**.

### 2.2 Create the OAuth client

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type: **Web application**.
3. **Authorised JavaScript origins** — where the browser app is served:

   | Environment | Value |
   |---|---|
   | Local | `http://localhost:3000` |
   | Production | `https://app.your-domain.example` |

4. **Authorised redirect URIs** — where Google sends the authorization code.
   This is the **API**, not the frontend, and it must match
   `GOOGLE_REDIRECT_URI` character for character:

   | Environment | Value |
   |---|---|
   | Local | `http://localhost:8000/api/v1/auth/google/callback` |
   | Production | `https://api.your-domain.example/api/v1/auth/google/callback` |

5. Copy the client ID and client secret into `server/.env`.

> **The client secret is backend-only.** It must never appear in `client/`, in
> any `NEXT_PUBLIC_*` variable, or in a browser response. The browser never
> needs it: the code exchange happens server-to-server (spec section 33).

### 2.3 Configure the application

```bash
# server/.env
GOOGLE_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxx
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback

SECRET_KEY=<64+ random characters>
JWT_ISSUER=acf-dashboard
JWT_AUDIENCE=acf-dashboard-api
ACCESS_TOKEN_EXPIRE_MINUTES=15

FRONTEND_LOGIN_SUCCESS_URL=http://localhost:3000/
FRONTEND_LOGIN_FAILURE_URL=http://localhost:3000/login
```

Generate the signing key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

`JWT_SECRET_KEY` and `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` are accepted as aliases
for `SECRET_KEY` and `ACCESS_TOKEN_EXPIRE_MINUTES`, so either naming works.

---

## 3. OIDC validation

Authlib performs these before this application sees an identity. Listed so the
coverage can be checked rather than assumed.

| Check | Why it matters |
|---|---|
| `state` matches the value we issued | The CSRF defence for the callback. Without it, an attacker can complete a login *into your session* with their own account. |
| `nonce` appears in the ID token | Stops an ID token obtained elsewhere being replayed into our callback. |
| PKCE `code_verifier` matches the challenge | Closes authorization-code interception if the client secret ever leaks. |
| ID token signature against Google's JWKS | Proves Google issued it. |
| `iss` is `https://accounts.google.com` | Stops a token from another issuer being accepted. |
| `aud` is our client ID | Stops a token minted for a different application being replayed here. |
| `exp` / `iat` | Bounds replay of an old token. |

Then this application adds two of its own:

- **`email_verified` must be true.** Google will issue an ID token for an
  account whose address it has not confirmed. Accepting one would let somebody
  register an address they do not control and inherit whatever the
  account-restriction rules grant it.
- **`sub` must be present.** It is the identity; an ID token without one is
  unusable.

---

## 4. Identity and provisioning

### 4.1 The identity key is `(provider, subject)`, never the email

Google's `sub` claim is the only identifier guaranteed stable for an account.
An email address is not: inside a Workspace domain it can be reassigned. If
email were the key, the next holder of `manager@factory.local` would inherit the
Factory Manager role along with the mailbox.

The email is still stored, for display and for the account-restriction check. It
is never the key.

### 4.2 Sign-in resolution

Three steps, first match wins:

1. **Returning user** — matched on `(provider, provider_subject)`. Their name
   and avatar are refreshed from Google; their **email and role are not
   touched**.
2. **Unclaimed seeded account** — an existing row with the same email and
   `provider_subject IS NULL`. The identity is attached and the account keeps
   its seeded role. This is what makes `admin@factory.local` an Admin on first
   sign-in.
3. **New user** — provisioned with `AUTH_DEFAULT_ROLE` (`VIEWER` by default).

> **The guard on step 2.** An account can be claimed only while its
> `provider_subject` is null. The condition lives in the repository's `WHERE`
> clause, so the database enforces it. Once claimed, a different Google account
> presenting the same address is refused — that is the reassigned-mailbox attack,
> and the answer is `email_claimed_by_other_identity`.

### 4.3 Role assignment

**A role is never taken from a request.** Not from a query parameter, not from a
form field, not from a Google claim. Spec section 5 states this several ways
because it is the most tempting shortcut in an OAuth integration.

| Case | Role source |
|---|---|
| Returning user | The database. |
| Claimed seeded account | The seeded role. |
| New user | `AUTH_DEFAULT_ROLE`, from configuration. |

To promote someone, change their `role_id` in the database. There is
deliberately no endpoint for it yet.

### 4.4 Provider tokens are not stored

Google's access and refresh tokens are discarded once the ID token has been
verified. The application never calls a Google API after sign-in, so keeping
them would mean holding a credential with no purpose and real custody
obligations (spec section 4).

---

## 5. Account restriction

Enforced **server-side, after the identity has been cryptographically verified**
(spec section 28). A frontend check would be decoration.

```bash
# Either list admits an address. Both empty means any Google account.
AUTH_ALLOWED_EMAIL_DOMAINS=factory.example,partner.example
AUTH_ALLOWED_EMAILS=one.contractor@gmail.com
AUTH_AUTO_PROVISION=true
```

The domain is what follows the **last** `@`, compared for equality. Not a
substring match — `attacker@factory.example.evil.com` and
`attacker+factory.example@evil.com` both contain the allowed domain and both are
refused. There is a test for each.

`AUTH_AUTO_PROVISION=false` narrows it further: only users already in the
database may sign in, whatever their address.

> **Both lists empty means any Google account can sign in.** That is the right
> default for a local demo and wrong for anything deployed. Set at least one
> before exposing the application.

---

## 6. JWT design

### 6.1 Claims

Minimal, per spec section 6. A JWT is signed, **not encrypted** — anyone holding
it can read every claim.

| Claim | Value | Why |
|---|---|---|
| `sub` | Application user UUID | Who. |
| `iss` | `JWT_ISSUER` | Rejects tokens from elsewhere. |
| `aud` | `JWT_AUDIENCE` | Rejects tokens minted for a sibling service. |
| `iat` | Issue time | |
| `exp` | Expiry | 15 minutes by default, 60 by hard limit. |
| `jti` | Unique token id | What revocation targets. |
| `typ` | `access` | A token for one purpose cannot be replayed as another. |
| `role` | Role code | Saves a lookup; see the trade below. |

No email, no name, no avatar, no provider token.

**The `role` trade-off.** Including it saves nothing on its own — the user is
loaded from the database on every request anyway, for the active check. The
database value is therefore authoritative, and a role change takes effect on the
*next request*, not at token expiry. The claim is kept because it makes the
token self-describing for logging and debugging.

### 6.2 Algorithm handling (spec section 32)

The accepted algorithm comes from configuration and the token's own `alg` header
is **never** consulted:

```python
jwt.decode(token, key, algorithms=[configured_algorithm], ...)
```

That single argument defeats both classic attacks:

- **`alg: none`** — a token asking the verifier to skip signature checking. It
  fails because `none` is not in the list, and `resolve_algorithm` refuses to
  return it even if someone configures it.
- **Algorithm confusion** — an RS256 verifier tricked into treating the public
  key as an HMAC secret. It fails because only the configured algorithm is
  accepted.

Supported: `HS256`, `HS384`, `HS512`, `RS256`, `ES256`. HS256 is the default;
an asymmetric algorithm is worth adopting if the verification key ever needs to
live somewhere the signing key does not.

Every claim in `REQUIRED_CLAIMS` must be present, enforced by PyJWT's `require`
option — a token missing `jti` is rejected structurally rather than causing a
`KeyError` later.

---

## 7. Cookies and sessions

### 7.1 Three cookies, three jobs

| Cookie | HttpOnly | Contents | Lifetime |
|---|---|---|---|
| `acf_session` | **Yes** | The access token | Token lifetime |
| `acf_csrf` | **No** | CSRF token | Token lifetime |
| `acf_oauth` | Yes | In-flight OAuth state/nonce/PKCE | 10 minutes |

**`acf_session` is HttpOnly** so application JavaScript cannot read it. This is
the whole reason spec section 55.4 forbids `localStorage`: an injected script
can read anything JavaScript can. With an HttpOnly cookie, XSS can still make
requests as the user, but it cannot exfiltrate the token to replay later from
somewhere else.

**`acf_csrf` is deliberately readable.** The double-submit pattern requires the
frontend to echo it in a header. It is not a session secret — a cross-site
attacker can cause it to be sent but cannot read it, thanks to the same-origin
policy.

**`acf_oauth` is scoped to `/api/v1/auth`**, so the OAuth transaction is not
attached to every API request, and expires in ten minutes because an OAuth round
trip takes seconds.

### 7.2 Development versus production

| Setting | Local | Production |
|---|---|---|
| `COOKIE_SECURE` | `false` | **`true`** |
| Scheme | `http://localhost` | `https://` |
| `COOKIE_SAMESITE` | `lax` | `lax` |

`Secure` cookies are never sent over plain HTTP, so a local `COOKIE_SECURE=true`
would mean no session survives a redirect and sign-in would appear to silently
fail. Hence `false` locally — and **startup refuses to run in production without
it** (see §12).

`SameSite=Lax` is the right default: the cookie is sent on top-level navigation
(so the OAuth callback works) but not on cross-site subrequests (so a
cross-origin form post carries no session). `None` would require `Secure` and is
only correct for a genuinely cross-site frontend; reaching for it to fix a
cookie problem removes CSRF protection by accident.

---

## 8. Logout and revocation

```
POST /api/v1/auth/logout
```

1. The token's `jti` is added to a Redis denylist, with a TTL equal to its
   **remaining lifetime**.
2. Both cookies are cleared.
3. The event is audited.

The TTL is what keeps the list bounded (spec section 8): an entry is useless
once the token would have expired anyway, so Redis drops it. The list is
proportional to logouts in the last few minutes, not to sessions ever created.

### The Redis outage trade-off

If Redis is unavailable the revocation check cannot run. There are two options,
and this is the one chosen:

> **A revoked token stays usable until it expires — at most
> `ACCESS_TOKEN_EXPIRE_MINUTES`.** The failure is logged loudly.

Rejecting every request instead would mean a Redis outage logs out every user of
a dashboard that is otherwise perfectly able to serve them — turning a cache
outage into a total outage, which is the failure mode Phase 3 was built to
avoid. For an internal factory dashboard with 15-minute tokens, that is the
right trade. An application where immediate revocation is a hard requirement
should use a server-side session lookup instead and accept the per-request read.

### Deactivation is immediate

Separately from revocation, **every authenticated request loads the user and
checks `is_active`**. A deactivated account is refused on its next request, not
when its token expires (spec section 23). The response is **401**, not 403: the
session is no longer usable at all, and the client should clear it.

---

## 9. RBAC

Routes declare a **permission**. `security/policy.py` decides which roles hold
it. A route never names a role — that hard-codes today's answer and goes stale
the moment a role is added.

Protection is declared once per router:

```python
router = APIRouter(
    prefix="/production",
    dependencies=[Depends(require_permission(Permission.PRODUCTION_READ))],
)
```

so an endpoint added to that router inherits it rather than being unguarded
until someone notices.

### 9.1 Permission matrix

| Permission | Admin | Factory Mgr | Prod Super | Quality Eng | Inventory Mgr | Viewer |
|---|---|---|---|---|---|---|
| `dashboard:read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `production:read` | ✓ | ✓ | ✓ | – | – | – |
| `quality:read` | ✓ | ✓ | – | ✓ | – | – |
| `inventory:read` | ✓ | ✓ | – | – | ✓ | – |
| `machines:read` | ✓ | ✓ | ✓ | ✓ | – | – |
| `analytics:read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `alerts:read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `maintenance:read` | ✓ | ✓ | ✓ | – | – | – |
| `production:write` | ✓ | ✓ | ✓ | – | – | – |
| `quality:write` | ✓ | ✓ | – | ✓ | – | – |
| `inventory:write` | ✓ | ✓ | – | – | ✓ | – |
| `machines:write` | ✓ | ✓ | – | – | – | – |
| `maintenance:write` | ✓ | ✓ | – | – | – | – |
| `alerts:acknowledge` | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| `users:read` | ✓ | ✓ | – | – | – | – |
| `users:write` | ✓ | – | – | – | – | – |
| `audit:read` | ✓ | – | – | – | – | – |

Totals: Admin 17, Factory Manager 15, Production Supervisor 8, Quality Engineer
7, Inventory Manager 6, Viewer 3.

Two choices worth explaining:

- **Every role reads the dashboard and analytics.** Spec section 56 defines each
  role as "Viewer + …", and that is what Viewer *is*.
- **Quality Engineers can read machines.** A defect is attributed to the machine
  that produced the part, so a quality investigation that cannot see machines is
  not an investigation.

The write permissions are declared but unused — no endpoint mutates anything
yet. They are in the matrix because the matrix is the thing being designed, and
leaving the column blank would hide its shape.

### 9.2 Endpoint protection

| Access | Endpoints |
|---|---|
| Public | `/health`, `/health/live`, `/health/ready`, `/auth/status`, `/auth/csrf`, `/auth/google/login`, `/auth/google/callback` |
| Authenticated | `/auth/me`, `/auth/logout` |
| Permission-gated | Everything under `/dashboard`, `/production`, `/quality`, `/inventory`, `/machines`, `/analytics`, `/alerts`, `/maintenance` |

**401 vs 403**, and why the distinction is load-bearing:

- **401** — no session, or it is malformed, expired, revoked or belongs to a
  deactivated account. The client should sign in.
- **403** — a valid session without the permission. Signing in again changes
  nothing, so the frontend must **not** redirect to login: doing so loops
  forever between a valid session and a page it cannot see.

---

## 10. CSRF, CORS and open redirects

### 10.1 CSRF

Cookies are attached automatically, so a cross-site form post would otherwise
be indistinguishable from a deliberate request. **CORS is not a defence** — it
governs whether the attacker can *read the response*; the request still arrives
and the side effect still happens (spec section 59).

Two independent checks on unsafe methods (`POST`, `PUT`, `PATCH`, `DELETE`),
applied only when a session cookie is present:

1. **`Origin` or `Referer` must name a configured frontend.** Browsers do not
   let script forge these.
2. **Double-submit token.** `X-CSRF-Token` must match the `acf_csrf` cookie,
   compared in constant time.

Either would be close to sufficient; both are required because they fail
differently.

`SameSite=Lax` is a third layer applied by the browser, not relied on alone.

**`GET` is exempt because no `GET` in this API changes state** — a property of
the design, not an assumption. If one ever needed to, it would become a `POST`.

**The OAuth callback is exempt** because it is a top-level navigation from
Google, carrying no CSRF token and no origin of ours. It is not unprotected: the
OAuth `state` parameter is its CSRF defence, validated by Authlib first.

### 10.2 CORS

Unchanged from Phase 3. Explicit origin allow-list; a wildcard is rejected by
configuration validation because credentialed requests and wildcard origins are
mutually exclusive.

```bash
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000     # local
CORS_ALLOWED_ORIGINS=https://app.your-domain.example                 # production
```

The incoming `Origin` header is never reflected.

### 10.3 Open redirects (spec section 21)

An open redirect turns a trusted domain into a phishing tool — and after a login
the user has just typed a password and is primed to trust what comes next.

**The application never redirects to a caller-supplied URL.** A caller supplies
a *path*; the origin always comes from configuration:

```
/auth/google/login?next=/production      ->  http://localhost:3000/production
/auth/google/login?next=https://evil.example  ->  the default destination
```

Rejected forms, each a real bypass of a naive "starts with `/`" check:

| Input | Why it is refused |
|---|---|
| `//evil.example` | Scheme-relative; a browser reads it as a full URL |
| `/\evil.example` | Backslashes, which some browsers normalise to slashes |
| `/%2f%2fevil.example` | Percent-encoded slashes, decoded after validation |
| `https://evil.example` | Absolute |
| `javascript:alert(1)` | Not navigation |
| `/path\r\nLocation: …` | Response splitting |

The path is validated **twice** — once before it is stored in the OAuth session,
once when it is used — so a single mistake in session handling could not become
an open redirect.

---

## 11. Rate limiting and audit

### 11.1 Rate limiting

Uses the Phase 3 limiter; no second implementation (spec section 15).

| Scope | Default | Reasoning |
|---|---|---|
| `/auth/google/*` | `10/minute` | Unauthenticated, reaches an external provider |
| `/auth/me`, `/auth/logout`, `/auth/csrf` | `120/minute` | Called routinely by a signed-in frontend |
| Health | `600/minute` | Orchestrators poll it |
| Analytics | `30/minute` | Expensive queries |
| Everything else | `60/minute` unauthenticated, `120/minute` authenticated | |

The bucket key cannot be forged: `X-Forwarded-For` is consulted only as far as
`TRUSTED_PROXY_COUNT` permits, and ignored entirely without a configured proxy.
Once signed in, the bucket is the **user id**, so colleagues behind one NAT are
not throttled by each other.

### 11.2 Audit events (spec section 22)

Written to the append-only `audit_logs` table with the request correlation ID.

| Action | When |
|---|---|
| `AUTH.LOGIN_INITIATED` | Sign-in begins |
| `AUTH.LOGIN_SUCCESS` | Session issued |
| `AUTH.LOGIN_FAILURE` | Identity invalid or unusable |
| `AUTH.LOGIN_DENIED` | Verified identity refused by policy |
| `AUTH.OAUTH_CALLBACK_FAILURE` | Bad state, failed exchange, bad ID token |
| `AUTH.LOGOUT` | Session ended |
| `AUTH.UNAUTHORIZED_ACCESS` | Revoked token, inactive or missing user |
| `AUTH.FORBIDDEN_ACCESS` | Authenticated but lacking the permission |
| `USER.PROVISIONED` | New user created |
| `USER.IDENTITY_CLAIMED` | Seeded account linked on first sign-in |

**Never logged**: JWTs, cookies, `Authorization` headers, the Google client
secret, OAuth authorization codes, provider tokens. Redaction happens in
`AuditService`, not at each call site, so one careless `metadata={"token": …}`
cannot write a credential into a table that cannot be cleaned up.

`AUTH.FORBIDDEN_ACCESS` is the most interesting entry: it is the signature of
either a misconfigured role or someone probing the API directly, having noticed
a button was missing.

---

## 12. Production versus development

`Settings` **refuses to start** with an insecure production configuration
(spec section 34). Each check describes something correct locally and dangerous
in production:

| Refused when `APP_ENV=production` | Why |
|---|---|
| `SECRET_KEY` absent or under 32 characters | Forgeable tokens |
| `COOKIE_SECURE=false` | Session cookie over plain HTTP |
| `DEBUG=true` | Verbose errors, docs exposed |
| `GOOGLE_REDIRECT_URI` on `http://` | Authorization code over plain HTTP |
| `FRONTEND_LOGIN_*_URL` on `http://` | Session cookie over plain HTTP |
| A non-localhost `http://` CORS origin | Credentialed requests over plain HTTP |
| `COOKIE_SAMESITE=none` without `COOKIE_SECURE` | Browsers reject it; CSRF protection lost |

Development is deliberately unaffected — `http://localhost` and a non-Secure
cookie are what a developer needs.

### Security headers

Unchanged from Phase 3: `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Permissions-Policy`.

**No CSP, and no HSTS**, deliberately (spec section 17):

- A meaningful **CSP** must be written against the frontend's real script and
  style sources, which are not settled until the dashboard exists. A placeholder
  policy gives false assurance and is usually loosened to `unsafe-inline` the
  first time it breaks something.
- **HSTS** belongs at the TLS-terminating proxy, which knows whether the
  connection is HTTPS. Emitting it from an application served over `http://`
  localhost would pin a browser to HTTPS for a host that does not serve it,
  which is a self-inflicted outage on the developer's machine.

---

## 13. Frontend

The frontend treats authentication as **cookie/session based**. There is no
token in JavaScript, no decoded JWT, nothing in `localStorage` (spec section 24).

| Piece | Role |
|---|---|
| `providers/auth-provider.tsx` | `GET /auth/me` via TanStack Query. The single source of truth. |
| `components/layout/RequireAuth.tsx` | Renders children only when signed in. UX, not security. |
| `app/login/page.tsx` | "Continue with Google", failure messages, unconfigured state. |
| `proxy.ts` | Edge redirect for signed-out visitors. |
| `providers/session-expiry-watcher.tsx` | Reacts to a 401 mid-session. |

### Loading states (spec section 26)

Three states are modelled explicitly: `loading`, `authenticated`,
`unauthenticated`. **`loading` is never treated as `unauthenticated`** — that
conflation is exactly what produces redirect flicker: a protected page renders,
decides nobody is signed in because the session check has not resolved, and
bounces to login before bouncing back.

### Session expiry (spec section 27)

A 401 on any request notifies once, and the watcher clears the cached user,
clears everything fetched as them, and redirects. Two loops are avoided:

- Repeat notifications are suppressed for five seconds, so a dashboard firing
  six concurrent requests produces one redirect rather than six.
- A 401 on `/auth/me` itself is ignored — that is the *expected* answer for an
  anonymous visitor, not an expiry.

### Next.js 16 route protection

Route protection is `proxy.ts`, not `middleware.ts`. Next.js 16 renamed
Middleware to Proxy; a file named `middleware.ts` is **silently ignored**, which
is the worst failure mode a security control can have. `next build` reporting
`ƒ Proxy (Middleware)` is the confirmation that it is loaded.

It checks only that a session cookie is **present**. It cannot check validity —
the cookie is signed with a key the edge does not hold. The real guarantee is
the backend's, on every request.

---

## 14. Demo accounts

Seeded per spec section 50. **These are not credentials** — the schema has no
password column. A row becomes a usable login when someone signs in through
Google with the matching address, at which point it is claimed and keeps its
seeded role.

| Email | Role |
|---|---|
| `admin@factory.local` | Admin |
| `manager@factory.local` | Factory Manager |
| `supervisor@factory.local` | Production Supervisor |
| `quality@factory.local` | Quality Engineer |
| `inventory@factory.local` | Inventory Manager |
| `viewer@factory.local` | Viewer |

`.local` is a reserved TLD and can never resolve to a real mailbox, so **nobody
can sign in as these accounts as seeded.** To demonstrate roles, either:

- re-seed with addresses in a domain you control that Google can authenticate, or
- sign in with your own Google account (provisioned as `VIEWER`) and update its
  `role_id` in the database.

---

## 15. Troubleshooting

| Symptom | Cause |
|---|---|
| `redirect_uri_mismatch` from Google | `GOOGLE_REDIRECT_URI` does not match the console entry exactly. Check scheme, port, trailing slash. |
| Sign-in button shows "unavailable" | `GOOGLE_CLIENT_ID`/`SECRET` not set. Check `GET /api/v1/auth/status`. |
| Redirected to login immediately after signing in | Almost always `COOKIE_SECURE=true` on `http://`. The browser silently drops the cookie. |
| `403 CSRF_VALIDATION_FAILED` on logout | Frontend origin missing from `CORS_ALLOWED_ORIGINS`, or the CSRF token was not echoed. |
| `401 account_unavailable` | The user is `is_active = false`. |
| `403` on a page the user can see in the nav | Working as intended — frontend hiding is UX; the backend is authoritative. |
| Every auth endpoint returns `503 DATABASE_UNAVAILABLE` | `DATABASE_URL` is not configured. Authentication needs the database for user lookup and audit. |

---

## Phase 7 verification status

What was confirmed against a running system on 2026-09-06, and what was not.

### Verified live

The authorization redirect, against real Google infrastructure:

```
GET /api/v1/auth/google/login  ->  302 accounts.google.com/o/oauth2/v2/auth
  response_type=code · scope=openid email profile
  state=<30 chars> · nonce=<20 chars>
  code_challenge=<43 chars> · code_challenge_method=S256
Set-Cookie: acf_oauth  Path=/api/v1/auth  Max-Age=600  HttpOnly  SameSite=lax
```

Everything downstream of the session cookie, using sessions minted with the
application's own `issue_access_token` and presented in the real cookie:

| Check | Result |
| --- | --- |
| Valid session resolves `/auth/me` with role and permissions | pass |
| No token echoed back to the client | pass |
| Anonymous request | 401 |
| Malformed token | 401 |
| Token signed with a foreign key | 401 |
| `alg: none` token | 401 |
| Expired token | 401 |
| Forged `role: ADMIN` claim on a VIEWER token | **ignored** — API reports VIEWER |
| Logout revokes server-side | `session_revoked: true` |
| The same token after logout | 401 — `jti` denylist in Redis, TTL 899s |
| RBAC, 6 roles × 8 domains | 56/56 correct |
| CSRF: missing / wrong / foreign-Origin token | 403, 403, 403 |
| CSRF: correct token and Origin | 200 |
| Open redirect, six hostile `next` forms | all contained, no CRLF in `Location` |

Cookie attributes, read from `Set-Cookie`:

| Cookie | Attributes |
| --- | --- |
| `acf_session` | HttpOnly, Path=/, SameSite=lax, 15-minute token |
| `acf_csrf` | **not** HttpOnly (double-submit needs it readable), Path=/, SameSite=lax, Max-Age=900 |
| `acf_oauth` | HttpOnly, Path=/api/v1/auth, Max-Age=600, SameSite=lax |

`Secure` is absent because verification ran over `http://localhost`. Production
configuration validation refuses to start with `COOKIE_SECURE=false` — tested.

### Not verified

The Google handshake itself. No browser was available, so nothing exercised:
authenticating as a real user, the authorization code, the token exchange,
ID-token signature and claim validation, `email_verified` enforcement, domain
restriction, user provisioning on first login, or role assignment.

That is the one part of this document still resting on code review rather than
observation.

