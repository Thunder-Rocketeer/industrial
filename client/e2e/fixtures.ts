/**
 * Shared fixtures for the browser end-to-end suite.
 *
 * HOW AUTHENTICATION WORKS HERE, AND WHAT IT DOES NOT PROVE
 *
 * The suite drives an authenticated application, and a session cannot be got
 * from Google without a human typing a password into Google's own form. So
 * sessions are minted by `server/tools/mint_test_sessions.py` using the
 * application's own `issue_access_token`, and installed as the real
 * `acf_session` cookie in the browser context.
 *
 * Everything downstream of that cookie is therefore genuinely exercised in a
 * real browser: signature verification, issuer and audience checks, expiry, the
 * revocation denylist, the user lookup, the active-account check and RBAC.
 *
 * The Google handshake is **not** exercised. `auth.spec.ts` drives the real
 * redirect to Google as far as it goes and stops at the credential prompt;
 * `docs/browser-e2e.md` records the callback as BLOCKED. Nothing in this file
 * is evidence about OAuth.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { test as base, expect, type Page } from "@playwright/test";

import { sparePath } from "./global-setup";

// Playwright transpiles specs to CommonJS, where `import.meta` is unavailable;
// `__dirname` is what exists at runtime.
const SESSIONS_PATH = join(__dirname, ".auth", "sessions.json");

export type RoleCode =
  | "ADMIN"
  | "FACTORY_MANAGER"
  | "PRODUCTION_SUPERVISOR"
  | "QUALITY_ENGINEER"
  | "INVENTORY_MANAGER"
  | "VIEWER";

interface SessionFile {
  cookieName: string;
  csrfCookieName: string;
  apiBaseUrl: string;
  sessions: Record<
    RoleCode,
    { token: string; email: string; name: string; userId: string; expiresAt: string }
  >;
}

let cached: SessionFile | null = null;

/**
 * Re-mint when the shared sessions are close to expiring.
 *
 * Access tokens live fifteen minutes, which is the application's real setting
 * and not something a test should change. The full suite takes longer than
 * that. Minting once in `global-setup.ts` therefore left the last minutes of a
 * run authenticating with tokens that had already expired -- and the failures
 * did not look like expiry, because the browser was simply bounced to `/login`.
 * Tests with nothing to do with authentication reported "expected Factory
 * Operations, received Sign in".
 *
 * The margin is generous on purpose: a token that expires *during* a test fails
 * in the middle of an assertion rather than cleanly before it.
 *
 * This is credential upkeep, not a retry. Nothing is re-run and no assertion is
 * relaxed; the suite just declines to use a credential it knows is stale.
 */
const REMINT_MARGIN_MS = 5 * 60 * 1000;

const SERVER_DIR = join(__dirname, "..", "..", "server");
const PYTHON = join(SERVER_DIR, ".venv", "Scripts", "python.exe");

function earliestExpiry(file: SessionFile): number {
  const times = Object.values(file.sessions)
    .map((session) => Date.parse(session.expiresAt))
    .filter((value) => Number.isFinite(value));
  return times.length > 0 ? Math.min(...times) : 0;
}

function readSessionFile(): SessionFile {
  return JSON.parse(readFileSync(SESSIONS_PATH, "utf8")) as SessionFile;
}

export function sessions(): SessionFile {
  if (!cached) {
    if (!existsSync(SESSIONS_PATH)) {
      throw new Error(
        "e2e/.auth/sessions.json is missing. Generate it with:\n" +
          "  cd server && python -m tools.mint_test_sessions ../client/e2e/.auth/sessions.json\n" +
          "Tokens live 15 minutes; the suite re-mints them as it goes.",
      );
    }
    cached = readSessionFile();
  }

  if (Date.now() > earliestExpiry(cached) - REMINT_MARGIN_MS) {
    process.stdout.write("[fixtures] shared sessions near expiry; re-minting\n");
    const python = existsSync(PYTHON) ? PYTHON : "python";
    execFileSync(python, ["-m", "tools.mint_test_sessions", SESSIONS_PATH], {
      cwd: SERVER_DIR,
      encoding: "utf8",
    });
    cached = readSessionFile();
  }

  return cached;
}

/** Install a role's session cookie on a page's browser context. */
export async function signIn(page: Page, role: RoleCode = "ADMIN"): Promise<void> {
  const file = sessions();
  const session = file.sessions[role];
  if (!session) {
    throw new Error(`No minted session for role ${role}.`);
  }

  // Both hosts: the frontend is on localhost, and the cookie must also travel
  // to the API on localhost:8000 for the browser's own XHRs.
  await page.context().addCookies([
    {
      name: file.cookieName,
      value: session.token,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    },
  ]);
}

/**
 * Sign in with a session that belongs to this test alone.
 *
 * Use this, not `signIn`, whenever a test destroys the session it signs in
 * with -- signing out, or anything else that revokes a token.
 *
 * WHY THIS EXISTS
 *
 * `signIn` installs a token from the shared pool minted once per run. Signing
 * out does not merely clear the cookie: the API adds the token's id to a
 * revocation denylist in Redis, and the token is dead everywhere from that
 * moment. So one test signing out took the shared ADMIN session with it, and
 * every later spec that signed in as ADMIN was silently browsing as a signed-out
 * visitor. The failures pointed nowhere near the cause -- assertions across
 * `dashboard`, `pages`, `responsive` and `errors` reported "expected Factory
 * Operations, received Sign in", on tests with no interest in authentication.
 *
 * It hid for a while behind an unlucky coincidence. The first probe written to
 * test this exact theory ran while Redis happened to be down, and the
 * revocation check fails open when the cache is unreachable, so the shared token
 * still worked and the theory looked wrong. Re-run with Redis up, the same probe
 * returns 401 for ADMIN and 200 for VIEWER.
 *
 * Minting here is cheap and, more to the point, correct: a test that consumes a
 * credential should own that credential.
 */
export async function signInDisposable(page: Page, role: RoleCode = "ADMIN"): Promise<void> {
  const file = nextSpareSession();
  const session = file.sessions[role];
  if (!session) {
    throw new Error(`No minted session for role ${role}.`);
  }
  await page.context().addCookies([
    {
      name: file.cookieName,
      value: session.token,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    },
  ]);
}

let spareIndex = 0;

/**
 * Take the next unused spare set, minting one only if the pool runs dry.
 *
 * The spares are produced by `global-setup.ts` before any test runs, so the
 * normal path touches no network at all. The fallback exists so that adding a
 * third destructive test does not silently reuse a consumed session -- it will
 * work, just more slowly, and `SPARE_SESSION_COUNT` should then be raised.
 */
function nextSpareSession(): SessionFile {
  const path = sparePath(spareIndex);
  spareIndex += 1;

  if (existsSync(path)) {
    return JSON.parse(readFileSync(path, "utf8")) as SessionFile;
  }

  const python = existsSync(PYTHON) ? PYTHON : "python";
  const target = join(tmpdir(), `acf-e2e-${process.pid}-${spareIndex}-${Date.now()}.json`);
  try {
    execFileSync(python, ["-m", "tools.mint_test_sessions", target], {
      cwd: SERVER_DIR,
      encoding: "utf8",
    });
    return JSON.parse(readFileSync(target, "utf8")) as SessionFile;
  } finally {
    rmSync(target, { force: true });
  }
}

/**
 * Record the API calls a page makes, so a test can re-ask the page's question.
 *
 * A cross-check is only meaningful when both sides asked the same thing. These
 * tests used to call an endpoint bare -- `/production`, `/analytics/oee` -- while
 * the page asked for an explicit date window, and then required the two answers
 * to be equal. They agreed for as long as the backend's default window happened
 * to match the page's, and stopped agreeing the moment it did not: the suite
 * ran past local midnight, and since this machine is UTC+5:30 the local date had
 * rolled over while the backend's had not. The page counted 966 production
 * records over one window, the test's bare call counted 927 over another, and
 * the failure read as though the UI were displaying the wrong total.
 *
 * Nothing about the application was wrong. The test was comparing two different
 * questions, so it now replays the exact URL the browser used.
 *
 * Call this *before* `page.goto`, since it starts recording from that moment.
 */
export function recordApiRequests(page: Page): string[] {
  const urls: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/v1/")) {
      urls.push(url);
    }
  });
  return urls;
}

/**
 * The URL the page actually used for an endpoint.
 *
 * Matches on the exact pathname, so `/production` does not also select
 * `/production/by-line`. `occurrence` picks between repeats -- the quality page
 * asks `/quality/defects` twice, once for the Pareto and once for the table.
 */
export function requestFor(urls: string[], endpoint: string, occurrence = 0): string {
  const matches = urls.filter((url) => new URL(url).pathname.endsWith(endpoint));
  const match = matches[occurrence];
  if (!match) {
    throw new Error(
      `The page never made request ${occurrence} to ${endpoint}. Recorded: ` +
        `${urls.map((url) => new URL(url).pathname).join(", ")}`,
    );
  }
  return match;
}

export async function signOutAllCookies(page: Page): Promise<void> {
  await page.context().clearCookies();
}

/**
 * Collected browser problems for one test.
 *
 * Console errors, uncaught page errors and failed requests are recorded rather
 * than asserted immediately, so a test can finish and report everything at once.
 */
export interface BrowserProblems {
  consoleErrors: string[];
  pageErrors: string[];
  failedRequests: string[];
}

/**
 * Console noise that is expected and is not a defect.
 *
 * `/auth/me` returning 401 is the *correct* answer for an anonymous visitor —
 * it is how the auth provider discovers there is no session — and Chromium logs
 * every non-2xx fetch to the console regardless. Filtering it here keeps the
 * signal meaningful; everything else counts.
 */
const EXPECTED_CONSOLE = [/401 \(Unauthorized\)/i];

export const test = base.extend<{ problems: BrowserProblems }>({
  problems: async ({ page }, runTest) => {
    const problems: BrowserProblems = {
      consoleErrors: [],
      pageErrors: [],
      failedRequests: [],
    };

    page.on("console", (message) => {
      if (message.type() !== "error") {
        return;
      }
      const text = message.text();
      // Chromium puts the failing URL in the message *location*, not the text,
      // so both have to be considered before deciding this is a real error.
      const where = message.location()?.url ?? "";
      const combined = `${text} ${where}`;
      if (where.includes("/auth/me") && /401/.test(text)) {
        return;
      }
      if (EXPECTED_CONSOLE.some((pattern) => pattern.test(combined)) && where.includes("/auth/")) {
        return;
      }
      problems.consoleErrors.push(`${text}${where ? ` @ ${where}` : ""}`);
    });

    page.on("pageerror", (error) => {
      problems.pageErrors.push(error.message);
    });

    page.on("requestfailed", (request) => {
      // Aborted navigations during teardown are noise, not failures.
      const failure = request.failure()?.errorText ?? "";
      if (failure.includes("ERR_ABORTED")) {
        return;
      }
      problems.failedRequests.push(`${request.method()} ${request.url()} — ${failure}`);
    });

    // Named `runTest` rather than Playwright's conventional `use`: the
    // react-hooks lint rule reads a bare `use(...)` as React's `use` hook
    // and rejects it outside a component. Same function, different name.
    await runTest(problems);
  },
});

/** Assert a page produced no unexpected browser-level errors. */
export function expectNoBrowserErrors(problems: BrowserProblems): void {
  expect(problems.pageErrors, "uncaught page errors").toEqual([]);
  expect(problems.consoleErrors, "console errors").toEqual([]);
  expect(problems.failedRequests, "failed network requests").toEqual([]);
}

/**
 * Is the document wider than the viewport?
 *
 * The single most useful responsive check, and the one jsdom structurally
 * cannot perform: it has no layout engine, so Phase 6's structural tests could
 * never have caught horizontal overflow.
 */
export async function horizontalOverflow(page: Page): Promise<{
  overflows: boolean;
  scrollWidth: number;
  innerWidth: number;
  culprits: string[];
}> {
  return page.evaluate(() => {
    const scrollWidth = document.documentElement.scrollWidth;
    const innerWidth = window.innerWidth;
    const culprits: string[] = [];

    if (scrollWidth > innerWidth) {
      for (const element of Array.from(document.querySelectorAll<HTMLElement>("*"))) {
        const box = element.getBoundingClientRect();
        if (box.right > innerWidth + 1 && box.width > 0) {
          const id = element.id ? `#${element.id}` : "";
          const cls =
            typeof element.className === "string" && element.className
              ? `.${element.className.split(/\s+/).slice(0, 3).join(".")}`
              : "";
          culprits.push(
            `${element.tagName.toLowerCase()}${id}${cls} right=${Math.round(box.right)}`,
          );
          if (culprits.length >= 5) {
            break;
          }
        }
      }
    }

    return { overflows: scrollWidth > innerWidth, scrollWidth, innerWidth, culprits };
  });
}

/**
 * Wait until the data on screen is the data that was asked for.
 *
 * Two signals, and both are needed.
 *
 * `aria-busy` covers a *first* load: a skeleton is on screen and there is
 * nothing else to look at.
 *
 * The "Updating" indicator covers a *refetch*, and this is the one that matters
 * for filter tests. The application deliberately keeps the previous rows
 * mounted while new ones load -- `keepPreviousData`, so a filter change never
 * blanks the table -- which means that immediately after choosing a filter the
 * DOM still holds the old, unfiltered rows and no skeleton is present. A test
 * that waits only for `aria-busy` reads those stale rows and reports a filter
 * bug that does not exist.
 *
 * Waiting for the refresh indicator to clear is real synchronisation, not a
 * sleep: it is the same signal the interface shows a person.
 */
export async function waitForData(page: Page): Promise<void> {
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByText("Updating", { exact: true })).toHaveCount(0, { timeout: 30_000 });
}

export { expect };
