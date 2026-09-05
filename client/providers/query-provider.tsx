"use client";

import { useState, type ReactNode } from "react";
import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { createQueryClient } from "@/lib/query/query-client";

/**
 * Browser-side singleton.
 *
 * On the server this stays `undefined` and a fresh client is created per
 * request, so cached data can never cross between users. In the browser the
 * same client is reused across re-renders and Fast Refresh cycles, which is
 * what preserves the cache during development.
 */
let browserQueryClient: QueryClient | undefined;

function getQueryClient(): QueryClient {
  if (typeof window === "undefined") {
    return createQueryClient();
  }
  browserQueryClient ??= createQueryClient();
  return browserQueryClient;
}

export function QueryProvider({ children }: { children: ReactNode }) {
  // `useState` with an initializer guarantees the client is created once per
  // mount and is never re-created by a re-render, which would drop the cache.
  const [queryClient] = useState(getQueryClient);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
