import type { NextConfig } from "next";

/**
 * Backend that `/api/*` is forwarded to.
 *
 * WHY A PROXY RATHER THAN CALLING THIS HOST FROM THE BROWSER
 *
 * The session is an HttpOnly cookie, and `proxy.ts` gates every page on that
 * cookie being present. A cookie set by `onrender.com` is never visible to a
 * page on `vercel.app`, so calling this host directly leaves the user signed
 * in as far as the API is concerned and signed out as far as the shell is
 * concerned. Rewriting `/api/*` keeps the browser on one origin: the cookie
 * is set here, sent back here, and the API never sees the difference.
 * `NEXT_PUBLIC_API_BASE_URL` must stay the root-relative `/api/v1`.
 *
 * `API_PROXY_TARGET` (server-side only, never `NEXT_PUBLIC_`) points the proxy
 * at a backend started with `python -m app` for a fully local run. It defaults
 * to the hosted deployment, so a build with no override behaves as before.
 */
const API_PROXY_TARGET = process.env.API_PROXY_TARGET ?? "https://industrial-1-807h.onrender.com";

const nextConfig: NextConfig = {
  // Surfaces unsafe lifecycles and side effects during development.
  reactStrictMode: true,

  // Do not advertise the framework version to clients.
  poweredByHeader: false,

  // Keep type errors fatal at build time. Explicit rather than implicit, so
  // nobody has to guess whether a broken build can ship.
  typescript: { ignoreBuildErrors: false },

  // Note: Next.js 16 removed `next lint` and the `eslint` config option.
  // Linting is a separate CLI step -- see the `lint` script in package.json.

  // Security headers are configured here in the security phase (spec section
  // 62). CSP in particular must be written against the real script/style
  // sources of the finished app, so it is deliberately not stubbed out now.

  async rewrites() {
    return {
      // `beforeFiles` so the rewrite wins even if a route under `/api` were
      // ever added to this app by mistake.
      beforeFiles: [{ source: "/api/:path*", destination: `${API_PROXY_TARGET}/api/:path*` }],
    };
  },
};

export default nextConfig;
