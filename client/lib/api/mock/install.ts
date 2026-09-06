/**
 * Development-only API mocking (spec section 30).
 *
 * HOW TO TURN IT ON
 *
 *   In `.env.local`:  NEXT_PUBLIC_ENABLE_API_MOCKS=true
 *   Then restart `npm run dev`.
 *
 * HOW TO TURN IT OFF
 *
 *   Remove the line, or set it to `false`, and restart. Off is the default; it
 *   has to be switched on deliberately.
 *
 * WHY IT CANNOT REACH PRODUCTION
 *
 * Spec section 30 is explicit: mock data must never silently stand in for
 * production data. Three independent things have to be true before a single
 * fixture is served, and no one of them is sufficient:
 *
 *   1. `NEXT_PUBLIC_ENABLE_API_MOCKS` is "true";
 *   2. `NEXT_PUBLIC_APP_ENV` is not "production";
 *   3. `NODE_ENV` is not "production" -- set by the build, not by an
 *      environment variable, so `next build` closes this door regardless of
 *      what anyone puts in the environment. It also lets the bundler drop this
 *      module and every fixture from the production bundle.
 *
 * Conditions 1 and 2 are `apiMocksEnabled` in `lib/env.ts`; condition 3 is
 * checked again here, at the point of use.
 *
 * WHAT IT COVERS
 *
 * Only the handful of endpoints listed below. Anything else passes through to
 * the real backend and fails there if it is down -- deliberately. A mock layer
 * that answered *everything* would make a broken backend look like a working
 * application, which is the failure mode section 30 is guarding against.
 *
 * Every mocked response is also stamped with an `X-Mock-Data: true` header, so
 * a mocked response is identifiable in the network tab without reading source.
 */
import type { AxiosInstance } from "axios";

import { apiMocksEnabled } from "@/lib/env";

import {
  mockAlertSummary,
  mockAlerts,
  mockDashboardSummary,
  mockMachineFleetSummary,
  mockMachines,
  mockProductionSummary,
  mockQualitySummary,
} from "./fixtures";

/** Endpoints served from fixtures, in the order they are matched. */
const MOCKED_ROUTES: { pattern: RegExp; data: unknown }[] = [
  { pattern: /\/dashboard\/summary$/, data: mockDashboardSummary },
  { pattern: /\/production\/summary$/, data: mockProductionSummary },
  { pattern: /\/quality\/summary$/, data: mockQualitySummary },
  { pattern: /\/machines\/summary$/, data: mockMachineFleetSummary },
  { pattern: /\/machines$/, data: mockMachines },
  { pattern: /\/alerts\/summary$/, data: mockAlertSummary },
  { pattern: /\/alerts\/active$/, data: mockAlerts },
];

let installed = false;

/**
 * Install the mock adapter on the shared Axios instance.
 *
 * A no-op unless mocking is enabled. Safe to call more than once: React strict
 * mode mounts effects twice in development, and a second adapter would replace
 * the first.
 *
 * Returns whether mocking is active, so a caller can render a visible banner.
 */
export async function installApiMocks(client: AxiosInstance): Promise<boolean> {
  if (!apiMocksEnabled || process.env.NODE_ENV === "production") {
    return false;
  }
  if (installed) {
    return true;
  }

  // Imported dynamically so `axios-mock-adapter` -- a devDependency -- is never
  // part of a production build's module graph.
  const { default: MockAdapter } = await import("axios-mock-adapter");

  const mock = new MockAdapter(client, {
    // Anything not listed above goes to the real backend.
    onNoMatch: "passthrough",
    // A little latency, so loading and refreshing states are actually visible
    // during development rather than resolving in the same frame.
    delayResponse: 300,
  });

  for (const route of MOCKED_ROUTES) {
    mock.onGet(route.pattern).reply(200, { data: route.data }, { "X-Mock-Data": "true" });
  }

  installed = true;

  // Loud on purpose. Nobody should be looking at this data without knowing.
  console.warn(
    "[api] MOCK DATA IS ENABLED. Responses for dashboard, production, quality, " +
      "machine and alert summaries come from local fixtures, not the backend. " +
      "Set NEXT_PUBLIC_ENABLE_API_MOCKS=false to disable.",
  );

  return true;
}

/** Whether mocking is configured on. Read by the development banner. */
export function areApiMocksEnabled(): boolean {
  return apiMocksEnabled && process.env.NODE_ENV !== "production";
}
