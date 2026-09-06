import type { Metadata, Viewport } from "next";
import { connection } from "next/server";

import { AppProviders } from "@/providers/app-providers";
import { env } from "@/lib/env";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: env.NEXT_PUBLIC_APP_NAME,
    template: `%s | ${env.NEXT_PUBLIC_APP_NAME}`,
  },
  description:
    "Production, quality, inventory and machine monitoring for an automobile component factory.",
  // The dashboard is behind authentication and holds operational data.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Spec section 19: never block zoom; users must be able to scale the UI.
  maximumScale: 5,
};

/**
 * `connection()` opts the whole application into dynamic rendering, and it is
 * the CSP nonce that requires it.
 *
 * Next.js stamps the per-request nonce onto its scripts during *server-side
 * rendering*, reading it from the `Content-Security-Policy` header on the
 * incoming request (see `proxy.ts`). A statically prerendered page is built
 * before any request exists, so there is no header to read and no nonce to
 * stamp -- the HTML ships with bare `<script>` tags that the policy then
 * blocks. Awaiting a connection here tells Next.js to wait for a real request
 * before rendering, which is what makes the header available.
 *
 * Phase 7 measured this against a dev server and read it as working. Phase 8
 * ran the production build in Chromium and found 53 `script-src-elem`
 * violations: twelve script tags, zero nonces. Enforcing the policy would have
 * served a blank page.
 *
 * It sits in the root layout because the root layout is part of every route, so
 * one call covers `/login`, `/` and the whole authenticated tree.
 *
 * The cost is small here and would not be elsewhere. Every page in this
 * application is behind authentication and loads its data client-side through
 * TanStack Query, so the prerendered HTML was only ever an empty shell -- and
 * `proxy.ts` already runs on each of these requests, so no CDN was caching them
 * either. What is given up is the static shell, not any real caching.
 *
 * Next.js 16 note: `export const dynamic = "force-dynamic"` is no longer the
 * documented route to this, and is removed outright under Cache Components.
 * `connection()` is the supported API.
 */
export default async function RootLayout({ children }: LayoutProps<"/">) {
  await connection();

  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        {/* Spec section 19: keyboard users must be able to bypass the nav. */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:rounded focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-zinc-900 focus:shadow focus:outline focus:outline-2 focus:outline-offset-2 focus:outline-blue-600 dark:focus:bg-zinc-900 dark:focus:text-zinc-50"
        >
          Skip to main content
        </a>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
