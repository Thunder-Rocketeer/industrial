# Deployment

How the application is hosted, what each host needs, and how to prove a deploy
is healthy. This is the runbook; [`production-readiness.md`](./production-readiness.md)
records the reasoning behind the controls it relies on.

---

## 1. Topology

```
Browser ──► Vercel (Next.js, client/) ──► Render (FastAPI, server/) ──► CSV exports in memory
              │                                                          (server/supabase_csv_exports)
              └── /api/* is proxied by Next.js (client/next.config.ts)
```

Two hosts, one origin. The browser only ever talks to the Vercel domain;
Next.js rewrites `/api/*` to the Render service. That is not a convenience --
it is what makes sign-in work:

- The session is an **HttpOnly cookie**. A cookie set by `onrender.com` is
  invisible to a page on `vercel.app`, and `client/proxy.ts` redirects any page
  request that has no session cookie to `/login`. Cross-site, the user would be
  signed in as far as the API is concerned and signed out as far as the shell
  is concerned, forever.
- Same-origin also means `SameSite=Lax` cookies and `connect-src 'self'` in the
  CSP hold without exceptions.

The backend reads table data from the CSV exports checked in under
`server/supabase_csv_exports/` (`DATA_SOURCE=csv`). It makes no network calls
to Supabase. Writes made at runtime -- audit rows, login timestamps,
auto-provisioned users -- live in memory and reset on restart; that is the
accepted trade-off of a file-backed data source.

---

## 2. Backend on Render

[`render.yaml`](../render.yaml) at the repository root is a Render Blueprint
describing the service. Create the service from it (**New → Blueprint**) or
match it by hand in the dashboard:

| Setting | Value |
|---|---|
| Root directory | `server` |
| Build | `pip install -r requirements.txt` |
| Start | `gunicorn app.main:app --worker-class uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:$PORT` |
| Health check path | `/api/v1/health/live` |

### Configuration is in the repository

The service's public configuration is committed in
[`server/render.env`](../server/render.env): `APP_ENV=production`, the data
source, the cookie flags, the Redis switches, and every URL that names the
Vercel domain (`CORS_ALLOWED_ORIGINS`, `GOOGLE_REDIRECT_URI`,
`FRONTEND_LOGIN_*_URL`). The backend reads that file by itself whenever it
runs on Render -- it checks for the `RENDER` variable Render sets on every
service (`server/app/config.py`, `_env_files`). Local development never loads
it. To move to a new frontend domain, edit the file and push.

Anything set in the Render dashboard overrides the file, which is where the
three values that must never be committed go. Set these under
**Environment** and nothing else:

```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
SECRET_KEY=<at least 32 chars; python -c "import secrets; print(secrets.token_urlsafe(64))">
```

With `APP_ENV=production` the settings validator refuses to start on an
insecure combination -- an `http://` redirect URI, a non-Secure cookie, a
short or missing `SECRET_KEY`, `DEBUG=true` -- and the log says exactly which
one. A missing `SECRET_KEY` is the usual first-deploy failure.

### Redis

Not required. Without it the cache is bypassed and the rate limiter fails
open. When an instance exists, set `REDIS_URL` in the dashboard and flip
`CACHE_ENABLED` and `RATE_LIMIT_ENABLED` to `true` in `server/render.env`.

### Free-tier note

Render's free tier sleeps after fifteen minutes idle and takes 30-60 s to
wake. The frontend's request timeout is `NEXT_PUBLIC_API_TIMEOUT_MS`
(15 s by default); the first request after a sleep will show the "backend
unavailable" banner, and its **Retry** button recovers. Raise the timeout on
Vercel to `60000` if that is unacceptable, or keep the service warm.

---

## 3. Frontend on Vercel

[`vercel.json`](../vercel.json) declares one service, `web`, rooted at
`client/`. The API service that previously ran on Vercel was removed when the
backend moved to Render.

Environment variables (Project → Settings → Environment Variables):

```
NEXT_PUBLIC_API_BASE_URL=/api/v1
API_PROXY_TARGET=https://<service>.onrender.com
NEXT_PUBLIC_APP_ENV=production
NEXT_PUBLIC_API_TIMEOUT_MS=15000
```

- `NEXT_PUBLIC_API_BASE_URL` is **root-relative** so requests stay on the
  Vercel origin.
- `API_PROXY_TARGET` is read by `next.config.ts` at build time and turns on the
  `/api/:path*` rewrite. It is not a `NEXT_PUBLIC_` variable; it never reaches
  the browser.
- Both are baked in at build time. **Changing either requires a redeploy**, not
  just a save.

Deploy with `vercel deploy --prod` from the repository root, or by pushing to
the connected branch.

---

## 4. Google Cloud Console

The OAuth client (**APIs & Services → Credentials**) must list, exactly:

- Authorised JavaScript origin: `https://<app>.vercel.app`
- Authorised redirect URI: `https://<app>.vercel.app/api/v1/auth/google/callback`

The redirect URI goes through the Vercel proxy to Render, which is why it is
the Vercel host and not the Render one. It must equal `GOOGLE_REDIRECT_URI` on
Render character for character. Preview deployments have different hostnames
and therefore cannot complete sign-in; that is expected.

---

## 5. Verifying a deploy

In order -- each step depends on the one before.

1. **Backend is up and has data.**
   `GET https://<service>.onrender.com/api/v1/health/ready` →
   `"status": "ready"` with `database.healthy: true`. If the database is
   unhealthy the CSV folder was not found: check `CSV_DATA_DIR` against the
   root directory.
2. **Backend knows about Google.**
   `GET .../api/v1/auth/status` → `"google_configured": true`.
3. **The proxy works.**
   `GET https://<app>.vercel.app/api/v1/auth/status` returns the same body.
   A Vercel `NOT_FOUND` page means `API_PROXY_TARGET` was not set at build
   time.
4. **Sign-in.** Open `https://<app>.vercel.app`, continue with Google, land on
   `/dashboard`. Reload: still signed in (the cookie is on the right domain).
5. **Data.** The dashboard shows figures, not placeholders, and `/production`
   pages through real rows.

The login page reports `Sign-in is unavailable ... not configured` for *any*
failure to fetch `/auth/status`, including a CORS rejection or a sleeping
backend -- check step 3 before assuming credentials are missing.

---

## 6. Local development against the same layout

The defaults in `client/.env.example` and `server/.env.example` talk directly:
frontend on `:3000`, backend on `:8000`, no proxy. To exercise the proxy path
locally:

```
API_PROXY_TARGET=http://localhost:8000 NEXT_PUBLIC_API_BASE_URL=/api/v1 npm run dev
```

---

## 7. Docker

`server/Dockerfile` builds the backend with Gunicorn. The CSV exports are
inside `server/`, so they are in the image; no volume is needed. Run with the
same environment variables as Render, plus `WORKERS` to size the process pool.
