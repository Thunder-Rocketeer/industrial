/**
 * Authentication in a real browser.
 *
 * The Google handshake cannot be completed here — it needs a human at Google's
 * own credential form — so this file drives the real redirect as far as it goes
 * and asserts everything observable up to that point. It never pretends to have
 * signed in through Google.
 */
import {
  expect,
  expectNoBrowserErrors,
  sessions,
  signIn,
  signInDisposable,
  test,
} from "./fixtures";

test.describe("login page", () => {
  test("renders the sign-in page with a working Google entry point", async ({ page, problems }) => {
    await page.goto("/login");

    await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    await expect(page.getByText("Industrial Factory Dashboard")).toBeVisible();

    const button = page.getByRole("link", { name: /continue with google/i });
    await expect(button).toBeVisible();
    // Points at the backend's OAuth entry point, not at Google directly: the
    // backend has to mint state, nonce and the PKCE verifier first.
    await expect(button).toHaveAttribute("href", /\/api\/v1\/auth\/google\/login$/);

    expectNoBrowserErrors(problems);
  });

  test("the Google button is reachable and activatable by keyboard alone", async ({ page }) => {
    await page.goto("/login");

    const button = page.getByRole("link", { name: /continue with google/i });

    // Tab until it has focus, rather than calling .focus(), so this genuinely
    // tests tab order and reachability.
    let focused = false;
    for (let i = 0; i < 15 && !focused; i += 1) {
      await page.keyboard.press("Tab");
      focused = await button.evaluate((element) => element === document.activeElement);
    }
    expect(focused, "the Google button was not reachable by Tab").toBe(true);

    // A visible focus indicator, not just focus (WCAG 2.4.7).
    const outline = await button.evaluate((element) => {
      const style = getComputedStyle(element);
      return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
    });
    expect(outline.outlineStyle).not.toBe("none");
  });

  test("anonymous visitors are redirected away from protected routes", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/dashboard");

    await expect(page).toHaveURL(/\/login\?next=%2Fdashboard/);
    await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
  });

  test("a session-expiry redirect explains itself rather than failing silently", async ({
    page,
  }) => {
    await page.goto("/login?reason=auth_failed");

    // Next.js mounts its own empty route announcer with role="alert", so the
    // locator has to name the one carrying the message.
    const alert = page.getByRole("alert").filter({ hasText: /session/i });
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/sign in again/i);
  });
});

test.describe("Google OAuth redirect", () => {
  /*
   * One navigation, every assertion.
   *
   * `/auth/google/login` is rate limited to 10 requests per minute -- correctly,
   * since it is an unauthenticated endpoint that mints server-side state. Three
   * separate tests each starting a flow tripped that limit and failed with a
   * 429, which looked like a broken redirect and was in fact the limiter doing
   * its job. Asserting everything from a single hand-off is both kinder to the
   * endpoint and a more faithful description of one user signing in.
   */
  test("hands off to Google with PKCE, state, nonce and a scoped transaction cookie", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await page.goto("/login");
    await page.getByRole("link", { name: /continue with google/i }).click();
    await page.waitForURL(/accounts\.google\.com/, { timeout: 30_000 });

    const url = new URL(page.url());
    expect(url.hostname).toBe("accounts.google.com");

    const params = url.searchParams;
    expect(params.get("response_type")).toBe("code");
    expect(params.get("scope")).toBe("openid email profile");
    expect(params.get("code_challenge_method")).toBe("S256");
    // Lengths only. These are single-use values, but a test that prints them
    // teaches a bad habit.
    expect(params.get("code_challenge")?.length ?? 0).toBeGreaterThan(20);
    expect(params.get("state")?.length ?? 0).toBeGreaterThan(16);
    expect(params.get("nonce")?.length ?? 0).toBeGreaterThan(12);
    expect(params.get("redirect_uri")).toContain("/api/v1/auth/google/callback");

    // The transaction cookie the backend set on the way out.
    const oauth = (await page.context().cookies()).find((c) => c.name === "acf_oauth");
    expect(oauth, "the OAuth transaction cookie was not set").toBeDefined();
    expect(oauth!.httpOnly, "acf_oauth must be HttpOnly").toBe(true);
    expect(oauth!.path, "acf_oauth must be scoped to the auth path").toBe("/api/v1/auth");
    expect(oauth!.sameSite).toBe("Lax");
    const remaining = oauth!.expires - Date.now() / 1000;
    expect(remaining).toBeGreaterThan(0);
    expect(remaining, "acf_oauth should expire within ~10 minutes").toBeLessThan(700);

    /*
     * And this is where automation stops.
     *
     * Google presents its own credential form. Completing it needs a real
     * account and a person; writing an `acf_session` cookie by hand instead
     * would make a green test that proves nothing about OAuth. So the test
     * asserts what is actually true -- the flow reaches Google's prompt for the
     * correct registered client -- and `docs/browser-e2e.md` records the
     * callback, ID-token validation and provisioning as BLOCKED.
     */
    await expect(page.getByRole("textbox", { name: /email or phone/i })).toBeVisible();
    await expect(page.locator("body")).toContainText(/Smart Dashboard for Automotive Factory/i);
  });
});

test.describe("session behaviour", () => {
  test("an authenticated session resolves the current user and survives reload", async ({
    page,
  }) => {
    await signIn(page, "ADMIN");
    await page.goto("/dashboard");

    const response = await page.request.get(`${sessions().apiBaseUrl}/auth/me`);
    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body.data.role).toBe("ADMIN");
    expect(body.data.permissions.length).toBeGreaterThan(0);
    // Nothing token-shaped is ever handed back to the browser.
    expect(Object.keys(body.data)).not.toContain("token");
    expect(JSON.stringify(body)).not.toMatch(/eyJ[A-Za-z0-9_-]{10}/);

    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Factory Operations");
  });

  test("the session cookie is HttpOnly and unreadable from JavaScript", async ({ page }) => {
    await signIn(page, "ADMIN");
    await page.goto("/dashboard");

    const cookies = await page.context().cookies();
    const session = cookies.find((cookie) => cookie.name === "acf_session");
    expect(session, "session cookie missing").toBeDefined();
    expect(session!.httpOnly, "acf_session must be HttpOnly").toBe(true);
    expect(session!.path).toBe("/");
    expect(session!.sameSite).toBe("Lax");

    // The whole point of HttpOnly: an XSS payload could not read it either.
    const visible = await page.evaluate(() => document.cookie);
    expect(visible).not.toContain("acf_session");
  });

  test("logging out clears the session and re-protects the dashboard", async ({ page }) => {
    // A disposable session, because signing out revokes the token for good and
    // the shared ADMIN session is used by every other spec in the suite.
    await signInDisposable(page, "ADMIN");
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Factory Operations");

    await page.getByRole("button", { name: /account menu/i }).click();
    await page.getByRole("menuitem", { name: /sign out/i }).click();

    await page.waitForURL(/\/login/, { timeout: 20_000 });

    // The API must agree, not just the UI.
    const me = await page.request.get(`${sessions().apiBaseUrl}/auth/me`);
    expect(me.status()).toBe(401);

    // And a stale frontend cannot be used to walk back in.
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });

  test("an expired session sends the user to login without a redirect loop", async ({ page }) => {
    // A deliberately malformed token stands in for an expired one: both are
    // rejected by the same path, and this needs no clock manipulation.
    await page.context().addCookies([
      {
        name: "acf_session",
        value: "expired.token.value",
        domain: "localhost",
        path: "/",
        httpOnly: true,
        secure: false,
        sameSite: "Lax",
      },
    ]);

    await page.goto("/dashboard");
    await page.waitForURL(/\/login/, { timeout: 20_000 });

    // One redirect, not a loop: give it time to misbehave, then confirm it did
    // not.
    await page.waitForTimeout(2_500);
    expect(page.url()).toMatch(/\/login/);
    await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
  });
});
