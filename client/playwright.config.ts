import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for the browser end-to-end suite (Phase 8).
 *
 * These tests drive the **real running application**: the production Next.js
 * build on :3000, FastAPI on :8000, a live Supabase PostgreSQL and a live
 * Redis. Nothing is mocked. If the stack is not up, the tests fail rather than
 * quietly passing against fixtures — which is the entire point of the phase.
 *
 * Deliberately no `webServer` block. Starting the stack from the test runner
 * would hide whether it starts correctly, and the backend needs a specific loop
 * factory on Windows (see `server/app/runtime.py`). Bring it up yourself:
 *
 *   server:  python -m app
 *   client:  npm run build && npm run start
 *   auth:    python -m tools.mint_test_sessions ../client/e2e/.auth/sessions.json
 */
export default defineConfig({
  testDir: "./e2e",
  outputDir: "../artifacts/e2e/test-results",

  /*
   * Checks the stack is up and mints fresh sessions.
   *
   * Access tokens live fifteen minutes, so a suite that reused a file from an
   * earlier run would start failing partway through with a login page where a
   * dashboard should be -- indistinguishable from an authentication bug.
   */
  globalSetup: "./e2e/global-setup.ts",

  /*
   * Serial, single worker.
   *
   * The suite shares one live database and one Redis with real rate limiting.
   * Parallel workers would race on cache keys and burn the shared 120/minute
   * budget, producing 429s that look like product defects. A slower honest run
   * beats a fast ambiguous one.
   */
  fullyParallel: false,
  workers: 1,

  /*
   * No retries.
   *
   * Retrying is how a flaky assertion becomes a green tick. If a test here is
   * unstable, the instability is the finding.
   */
  retries: 0,

  forbidOnly: true,
  timeout: 45_000,
  expect: { timeout: 10_000 },

  reporter: [
    ["list"],
    ["json", { outputFile: "../artifacts/e2e/results.json" }],
    ["html", { outputFolder: "../artifacts/e2e/html-report", open: "never" }],
  ],

  use: {
    baseURL: "http://localhost:3000",
    // Evidence on failure only: a trace per test would be gigabytes.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
});
