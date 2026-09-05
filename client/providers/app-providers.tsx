"use client";

import type { ReactNode } from "react";

import { QueryProvider } from "@/providers/query-provider";

/**
 * Single composition point for every client-side provider.
 *
 * The root layout stays a Server Component and mounts only this one boundary.
 * Theme, toast and auth-session providers are added here as later phases
 * introduce them, so the layout itself never has to change again.
 */
export function AppProviders({ children }: { children: ReactNode }) {
  return <QueryProvider>{children}</QueryProvider>;
}
