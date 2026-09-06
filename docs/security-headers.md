# Security headers and Content-Security-Policy

Phase 4 deferred the CSP with a reason recorded: a policy written before the
frontend existed would have been a guess, and a guessed CSP has a predictable
life — it breaks something, someone adds `unsafe-inline`, and it protects
nothing while appearing to.

The frontend now exists. This document records **what it actually loads**, the
policy that follows from that, and the one place the policy cannot be tight.

Nothing here is deployed yet. It is a recommendation with the evidence attached.

---

## 1. What the application actually loads

Measured against the Phase 6 production build (`next build`, Next.js 16.3.4,
Turbopack), by reading the emitted HTML and the client chunks.

| Resource | Source | Notes |
| --- | --- | --- |
| Scripts | `/_next/static/chunks/*.js`, same origin | 8–12 per route |
| **Inline scripts** | 2 per page | `self.__next_f.push(...)` — the RSC flight payload |
| Stylesheet | `/_next/static/chunks/*.css`, same origin | One file, Tailwind output |
| `<style>` elements | none | |
| Inline `style=` in server HTML | none | |
| Inline `style=` at runtime | yes | Chart geometry and bar widths — see §4 |
| Fonts | none fetched | System font stack; `next/font/google` deliberately not used |
| Images | avatar only | `https://*.googleusercontent.com`, from `/auth/me` |
| Icons | none fetched | Bundled locally — see §3 |
| XHR / fetch | the API origin only | `NEXT_PUBLIC_API_BASE_URL` |
| `eval` / `new Function` | none | Confirmed absent from production chunks |
| Web workers, frames | none | |

The two inline scripts are not optional and not removable: they are how the App
Router streams server-rendered data to the client. They are the reason the
policy needs a nonce rather than a flat `script-src 'self'`.

---

## 2. The recommended policy

```
default-src 'self';
script-src 'self' 'nonce-{NONCE}' 'strict-dynamic';
style-src-elem 'self';
style-src-attr 'unsafe-inline';
img-src 'self' data: https://*.googleusercontent.com;
font-src 'self';
connect-src 'self' https://api.factory.example;
form-action 'self';
frame-ancestors 'none';
base-uri 'none';
object-src 'none';
upgrade-insecure-requests
```

Replace `https://api.factory.example` with the deployment's real API origin —
the same value as `NEXT_PUBLIC_API_BASE_URL`, origin only. When the API is
served from the same origin as the frontend, drop it and `'self'` suffices.

Clause by clause:

- **`script-src 'self' 'nonce-…' 'strict-dynamic'`** — the nonce covers the two
  RSC inline scripts. `'strict-dynamic'` lets those scripts load the chunks they
  reference without every chunk URL being enumerated, and it makes host
  allow-listing irrelevant, which is the point: a host allow-list is bypassable
  through any JSONP endpoint on an allowed host.
- **`style-src-elem 'self'`** — the one stylesheet. No `'unsafe-inline'` here,
  because there are no `<style>` elements.
- **`style-src-attr 'unsafe-inline'`** — required; see §4.
- **`img-src`** — `data:` because a chart library may emit data-URI images;
  `*.googleusercontent.com` for the Google account avatar. If avatars are
  dropped, remove it.
- **`connect-src`** — the API and nothing else. Notably **not**
  `api.iconify.design`; see §3.
- **`frame-ancestors 'none'`** — clickjacking. Supersedes `X-Frame-Options`,
  which should still be sent for older browsers.
- **`base-uri 'none'`** — stops an injected `<base>` from re-pointing every
  relative script URL, which is a classic CSP bypass.
- **`object-src 'none'`** — no plugins, ever.

### What is deliberately absent

`'unsafe-eval'` is **not** present and is not needed: no `eval` or
`new Function` appears in the production chunks. Recharts renders SVG through
React and does not compile expressions at runtime.

No wildcard `*` appears anywhere.

---

## 3. Why `connect-src` needs no CDN

`@iconify/react` resolves an unknown icon name by fetching it from
`api.iconify.design`, falling back to `api.simplesvg.com` and `api.unisvg.com`.
Left alone that would have meant three third-party hosts in `connect-src`, for
decoration — and every icon on a factory dashboard depending on a public CDN
being reachable from a possibly segmented network.

Phase 6 removed the dependency instead of allow-listing it. `npm run icons`
extracts the 43 icons the source actually references from the
`@iconify-json/*` devDependencies into `lib/icons.generated.ts` (13 KB), which
`components/ui/Icon.tsx` registers at module load. Iconify then finds every
icon locally and never issues a request.

This is enforced, not assumed: `tests/icons.test.tsx` renders all 43 icons with
`fetch` instrumented and asserts zero calls, and separately asserts that every
icon name in the source resolves from the local registry. Adding an icon
without re-running `npm run icons` fails that test — which matters, because such
a change would still render correctly on a developer's machine while quietly
reintroducing the CDN dependency in production.

The three hostnames still appear as string constants inside the Iconify library
code in the bundle. They are its default configuration; no code path reaches
them once every icon resolves locally.

---

## 4. The one concession: `style-src-attr 'unsafe-inline'`

Charts and proportional bars set geometry through inline `style` attributes —
a bar's width is a percentage computed from data, and Recharts positions every
SVG element the same way. There is no realistic way to avoid this with any
charting library, and generating a stylesheet class per possible percentage is
not a serious alternative.

CSP splits inline styles into two directives, and the distinction matters here:

- `style-src-elem` governs `<style>` blocks and stylesheet links. This
  application has none, so it stays `'self'`.
- `style-src-attr` governs the `style="…"` attribute. This is what needs
  relaxing.

The exposure is much narrower than the phrase `'unsafe-inline'` suggests. A
style attribute cannot execute script. The residual risk is CSS-based data
exfiltration — an injected attribute using a selector-driven background URL to
signal page content — and that requires an HTML injection to exist in the first
place. Both defences against that remain in force: React escapes all rendered
content, and `dangerouslySetInnerHTML` appears nowhere in the codebase (asserted
by `tests/security.test.ts`).

Nonces do not apply to style attributes; there is no `'nonce-…'` mechanism for
them. So this concession is inherent to rendering data-driven geometry, not a
shortcut around an avoidable implementation. It is the only relaxation in the
policy and it is scoped to the narrower of the two style directives, which is
the important part: `style-src: 'unsafe-inline'` would have covered both.

---

## 5. Implementation

The nonce must be generated per request and cannot be static, so it belongs in
`proxy.ts` (Next.js 16's renamed Middleware). Sketch:

```ts
export function proxy(request: NextRequest) {
  const nonce = crypto.randomUUID().replace(/-/g, "");

  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    "style-src-elem 'self'",
    "style-src-attr 'unsafe-inline'",
    "img-src 'self' data: https://*.googleusercontent.com",
    "font-src 'self'",
    `connect-src 'self' ${API_ORIGIN}`,
    "form-action 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "object-src 'none'",
    "upgrade-insecure-requests",
  ].join("; ");

  // Next.js reads this header and stamps the nonce onto the scripts it emits.
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);

  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}
```

Two things to get right:

1. **The existing auth redirect must be preserved.** `proxy.ts` currently
   redirects signed-out visitors to `/login`. The CSP header has to be attached
   to the redirect response as well, not only to `NextResponse.next()`.
2. **Roll out in report-only first.** Ship
   `Content-Security-Policy-Report-Only` with a `report-uri`, watch for a week,
   then switch the header name. A CSP that breaks a production dashboard on
   deployment day teaches everyone that CSPs are trouble.

### Other headers

Sent alongside, all from the proxy:

| Header | Value | Why |
| --- | --- | --- |
| `X-Content-Type-Options` | `nosniff` | Stops MIME sniffing turning a JSON response into script |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Keeps filter values in URLs out of third-party referrers |
| `X-Frame-Options` | `DENY` | Older-browser companion to `frame-ancestors` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=()` | The dashboard needs none of them |

### HSTS stays a deployment concern

`Strict-Transport-Security` is **not** emitted by the application, and this is
unchanged from Phase 4's decision. It belongs at the TLS-terminating proxy,
which knows whether the connection is actually HTTPS. Emitting it from an app
served over `http://localhost` would pin a developer's browser to HTTPS for a
host that does not serve it — a self-inflicted outage, and a confusing one to
diagnose. The reverse proxy or load balancer should send
`max-age=63072000; includeSubDomains; preload` once HTTPS is confirmed working.

---

## 6. Verification checklist

Before enabling enforcement:

- [ ] Load every route with the policy in report-only mode; confirm no
      violations beyond the known style-attribute ones.
- [ ] Confirm charts render — they are the most likely thing to trip
      `style-src-attr`.
- [ ] Complete a full Google sign-in round trip; the redirect leaves and
      re-enters the origin.
- [ ] Confirm the avatar loads, or drop `*.googleusercontent.com`.
- [ ] Confirm no icon requests appear in the network tab (they should not, per
      §3).
- [ ] Re-run `npm test`; `tests/icons.test.tsx` and `tests/security.test.ts`
      cover the assumptions this policy rests on.
