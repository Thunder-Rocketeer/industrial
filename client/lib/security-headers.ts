/**
 * Security response headers, including the Content-Security-Policy.
 *
 * Phase 4 deferred the CSP with a reason: a policy written before the frontend
 * existed would have been a guess. Phase 6 measured what the built application
 * actually loads and wrote the policy down. Phase 7 applies it, which is where
 * the remaining question gets answered -- whether it actually holds when the
 * application runs.
 *
 * ROLLOUT MODE
 *
 * `CSP_REPORT_ONLY` decides which header name is used. Report-only is the
 * default because a CSP that breaks a production dashboard on deployment day
 * teaches everyone that CSPs are trouble. Set `NEXT_PUBLIC_CSP_REPORT_ONLY` to
 * "false" to enforce.
 *
 * THE NONCE
 *
 * Next.js streams server-rendered data to the client through two inline
 * `<script>` elements (`self.__next_f.push(...)`). They are not removable --
 * they are how the App Router works -- so the policy needs either a hash of
 * their contents, which changes on every render, or a per-request nonce. Next
 * reads the nonce from the CSP header it receives and stamps it onto the
 * scripts it emits, so generating one here is sufficient.
 *
 * `'strict-dynamic'` then lets those nonced scripts load the chunks they
 * reference without every chunk URL being enumerated. It also makes host
 * allow-listing irrelevant, which is the point: an allow-list is bypassable
 * through any open redirect or JSONP endpoint on an allowed host.
 */

/** Directives that never vary by request. */
function staticDirectives(apiOrigin: string): string[] {
  return [
    "default-src 'self'",
    // No <style> elements are emitted; the single stylesheet is same-origin.
    "style-src-elem 'self'",
    /*
     * The one relaxation in the policy, and it is unavoidable.
     *
     * Chart geometry is expressed as inline style attributes -- a bar's width
     * is a percentage computed from data, and Recharts positions every SVG
     * element the same way. CSP has no nonce mechanism for style *attributes*,
     * so there is no stricter formulation available.
     *
     * It is scoped deliberately to `style-src-attr`, the narrower of the two
     * style directives: `style-src 'unsafe-inline'` would have covered
     * `<style>` elements as well. A style attribute cannot execute script; the
     * residual risk is CSS-based exfiltration, which needs an HTML injection to
     * exist first -- and React's escaping plus the absence of
     * `dangerouslySetInnerHTML` (asserted in tests/security.test.ts) is what
     * stands there.
     */
    "style-src-attr 'unsafe-inline'",
    // `data:` for chart-library images; googleusercontent for the account avatar.
    "img-src 'self' data: https://*.googleusercontent.com",
    // System font stack only. Nothing is fetched.
    "font-src 'self'",
    `connect-src 'self' ${apiOrigin}`.trim(),
    "form-action 'self'",
    // Clickjacking. Supersedes X-Frame-Options, which is still sent for
    // browsers that predate it.
    "frame-ancestors 'none'",
    // Stops an injected <base> re-pointing every relative script URL.
    "base-uri 'none'",
    "object-src 'none'",
  ];
}

/**
 * The API origin the browser is allowed to call.
 *
 * Derived from the same variable the Axios client uses, so the policy cannot
 * drift from the address the application actually calls. Falls back to `'self'`
 * when the API is same-origin or unset.
 */
export function apiOriginForCsp(baseUrl: string | undefined): string {
  if (!baseUrl) {
    return "";
  }
  try {
    return new URL(baseUrl).origin;
  } catch {
    return "";
  }
}

export function buildCsp(nonce: string, apiOrigin: string): string {
  return [
    ...staticDirectives(apiOrigin),
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
  ].join("; ");
}

/**
 * Headers sent on every response.
 *
 * `Strict-Transport-Security` is deliberately absent. It belongs at the
 * TLS-terminating proxy, which knows whether the connection is actually HTTPS;
 * emitting it from an application served over `http://localhost` would pin a
 * developer's browser to HTTPS for a host that does not serve it.
 */
export const BASE_SECURITY_HEADERS: Record<string, string> = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "X-Frame-Options": "DENY",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
};

/** Generate a per-request nonce. */
export function createNonce(): string {
  return crypto.randomUUID().replace(/-/g, "");
}
