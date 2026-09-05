import type { NextConfig } from "next";

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
};

export default nextConfig;
