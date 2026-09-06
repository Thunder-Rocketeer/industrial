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
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { test as base, expect, type Page } from "@playwright/test";

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
  sessions: Record<RoleCode, { token: string; email: string; name: string; userId: string }>;
}

let cached: SessionFile | null = null;

export function sessions(): SessionFile {
  if (cached) {
    return cached;
  }
  if (!existsSync(SESSIONS_PATH)) {
    throw new Error(
      "e2e/.auth/sessions.json is missing. Generate it with:\n" +
        "  cd server && python -m tools.mint_test_sessions ../client/e2e/.auth/sessions.json\n" +
        "Tokens live 15 minutes; re-run if the suite has been idle.",
    );
  }
  cached = JSON.parse(readFileSync(SESSIONS_PATH, "utf8")) as SessionFile;
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
  problems: async ({ page }, use) => {
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

    await use(problems);
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
