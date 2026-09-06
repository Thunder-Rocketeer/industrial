import type { ReactNode } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { RequireAuth } from "@/components/layout/RequireAuth";

/**
 * Layout for every authenticated page (spec sections 1 and 35).
 *
 * This file is a **Server Component**, and stays one. It renders no state and
 * calls no hook; it composes two client components and passes children through.
 * That keeps the client boundary where spec section 35 wants it -- around the
 * interactive parts -- instead of marking the whole route tree `"use client"`.
 *
 * `RequireAuth` is UX, not security. It prevents the flash of an authenticated
 * shell for a signed-out visitor. Every page inside fetches through an API that
 * enforces the same rules server-side, so defeating this yields an empty shell
 * and a series of 401s (spec section 30 of the Phase 4 brief).
 */
export default function AuthenticatedLayout({ children }: { children: ReactNode }) {
  return (
    <RequireAuth>
      <AppShell>{children}</AppShell>
    </RequireAuth>
  );
}
