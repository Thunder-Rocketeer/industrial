"use client";

import type { ReactNode } from "react";

import { MockDataBanner } from "@/components/dev/MockDataBanner";
import { AuthProvider } from "@/providers/auth-provider";
import { QueryProvider } from "@/providers/query-provider";
import { SessionExpiryWatcher } from "@/providers/session-expiry-watcher";

/**
 * Single composition point for every client-side provider.
 *
 * The root layout stays a Server Component and mounts only this one boundary.
 * Theme and toast providers are added here as later phases introduce them, so
 * the layout itself never has to change again.
 *
 * Order matters: `AuthProvider` reads the session with TanStack Query, so it
 * must sit inside `QueryProvider`.
 *
 * `MockDataBanner` renders nothing and installs nothing unless development
 * mocking is explicitly enabled (spec section 30); in a production build it
 * compiles away.
 */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryProvider>
      <AuthProvider>
        <SessionExpiryWatcher />
        <MockDataBanner />
        {children}
      </AuthProvider>
    </QueryProvider>
  );
}
