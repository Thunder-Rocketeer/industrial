/**
 * Security, exercised through a real browser rather than an HTTP client.
 *
 * The difference matters. A curl-based CSRF test can send whatever cookies it
 * likes; a browser applies SameSite, origin rules and the same-origin policy on
 * its own, so what passes here is what a real attacker's page would face.
 */
import { expect, sessions, signIn, signInDisposable, test, waitForData } from "./fixtures";

const API = () => sessions().apiBaseUrl;

test.describe("headers", () => {
  test("every response carries the security headers", async ({ page }) => {
    const response = await page.goto("/login");
    const headers = response!.headers();

    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
    expect(headers["permissions-policy"]).toContain("camera=()");

    // HSTS must not be forced on plain-HTTP localhost.
    expect(headers["strict-transport-security"]).toBeUndefined();
  });

  test("the CSP is present, nonce-based, and free of unsafe-eval or wildcards", async ({
    page,
  }) => {
    const response = await page.goto("/login");
    const headers = response!.headers();

    const csp =
      headers["content-security-policy"] ?? headers["content-security-policy-report-only"];
    expect(csp, "no CSP header").toBeTruthy();

    expect(csp).toContain("default-src 'self'");
    expect(csp).toMatch(/script-src [^;]*'nonce-[a-f0-9]+'/);
    expect(csp).toContain("'strict-dynamic'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("base-uri 'none'");
    expect(csp).toContain("object-src 'none'");

    // The things a policy must never quietly acquire.
    expect(csp, "unsafe-eval must not appear").not.toContain("unsafe-eval");
    expect(csp, "no wildcard source").not.toMatch(/(^|[\s;])\*($|[\s;])/);
    expect(csp, "script-src must not be unsafe-inline").not.toMatch(
      /script-src[^;]*'unsafe-inline'/,
    );
  });

  test("the nonce reaches every script tag", async ({ page }) => {
    const response = await page.goto("/login");
    const csp =
      response!.headers()["content-security-policy"] ??
      response!.headers()["content-security-policy-report-only"];
    const nonce = /nonce-([a-f0-9]+)/.exec(csp!)?.[1];
    expect(nonce).toBeTruthy();

    const counts = await page.evaluate((expected) => {
      const scripts = Array.from(document.querySelectorAll("script"));
      return {
        total: scripts.length,
        withNonce: scripts.filter(
          (s) => s.nonce === expected || s.getAttribute("nonce") === expected,
        ).length,
      };
    }, nonce);

    expect(counts.total).toBeGreaterThan(0);
    // If any script lacked the nonce, enforcing the policy would break the page.
    expect(counts.withNonce, "scripts missing the nonce").toBe(counts.total);
  });

  test("no CSP violations are reported while the app runs", async ({ page }) => {
    const violations: string[] = [];
    await page.addInitScript(() => {
      document.addEventListener("securitypolicyviolation", (event) => {
        (window as unknown as { __csp: string[] }).__csp ??= [];
        (window as unknown as { __csp: string[] }).__csp.push(
          `${event.violatedDirective} blocked ${event.blockedURI}`,
        );
      });
    });

    await signIn(page, "ADMIN");
    for (const route of ["/dashboard", "/production", "/analytics"]) {
      await page.goto(route);
      await waitForData(page);
      const found = await page.evaluate(
        () => (window as unknown as { __csp?: string[] }).__csp ?? [],
      );
      violations.push(...found.map((entry) => `${route}: ${entry}`));
    }

    expect(violations, "CSP violations observed in the browser").toEqual([]);
  });
});

test.describe("XSS", () => {
  test("a script payload in a filter is rendered inert, not executed", async ({ page }) => {
    await signIn(page, "ADMIN");

    let dialogFired = false;
    page.on("dialog", async (dialog) => {
      dialogFired = true;
      await dialog.dismiss();
    });

    const payloads = [
      "<script>alert(1)</script>",
      "<img src=x onerror=alert(1)>",
      '"><svg/onload=alert(1)>',
    ];

    for (const payload of payloads) {
      await page.goto(`/production?machine_id=${encodeURIComponent(payload)}`);
      await page.waitForTimeout(800);

      // Nothing executed...
      expect(dialogFired, `a dialog fired for ${payload}`).toBe(false);
      // ...and nothing was injected into the DOM.
      const injected = await page.evaluate(
        () => document.querySelectorAll("script:not([src]):not([nonce])").length,
      );
      expect(injected, "an unnonced inline script appeared").toBe(0);
      expect(await page.locator("img[src='x']").count()).toBe(0);
    }
  });

  test("hostile text from the API is displayed as text", async ({ page }) => {
    await signIn(page, "ADMIN");

    // Intercept the alerts response and return a hostile description, to prove
    // the renderer escapes whatever the database might hold.
    await page.route(`${API()}/alerts*`, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      if (body.data?.length) {
        body.data[0].title = "<script>alert('xss')</script>";
        body.data[0].description = "<img src=x onerror=alert('xss')> and <b>bold</b>";
      }
      await route.fulfill({ response, json: body });
    });

    let dialogFired = false;
    page.on("dialog", async (dialog) => {
      dialogFired = true;
      await dialog.dismiss();
    });

    await page.goto("/alerts");
    await waitForData(page);
    await page.waitForTimeout(500);

    expect(dialogFired).toBe(false);
    // The payload is on the page, as literal text.
    await expect(page.locator("main")).toContainText("<script>alert('xss')</script>");
    // And no element was created from it.
    expect(await page.locator("main img[src='x']").count()).toBe(0);
    expect(await page.locator("main b").count()).toBe(0);
  });
});

test.describe("SQL injection", () => {
  test("hostile filter values are rejected and change no data", async ({ page }) => {
    await signIn(page, "ADMIN");

    const before = await (await page.request.get(`${API()}/production?page_size=1`)).json();

    for (const payload of ["' OR 1=1 --", "'; DROP TABLE production_records; --"]) {
      await page.goto(`/production?machine_id=${encodeURIComponent(payload)}`);
      await waitForData(page);

      const text = await page.locator("main").innerText();
      // A safe, human message — never a database error.
      expect(text).not.toMatch(/psycopg|SQLSTATE|Traceback|syntax error/i);
    }

    const after = await (await page.request.get(`${API()}/production?page_size=1`)).json();
    expect(after.pagination.total, "row count changed").toBe(before.pagination.total);
  });
});

test.describe("open redirect", () => {
  const HOSTILE = [
    "//evil.example",
    "/\\evil.example",
    "https://evil.example",
    "/%2f%2fevil.example",
    "javascript:alert(1)",
  ];

  test("a hostile `next` never takes the browser off-origin", async ({ page }) => {
    /*
     * Two layers, checked separately, because they have different jobs.
     *
     * The login page drops a hostile `next` so it never reaches a link. The API
     * validates `next` again and discards it, and that check is the one that
     * decides -- it holds even for a request that never went near the login
     * page. Asserting only the first would leave the real control untested;
     * asserting only the second would let the page quietly start emitting links
     * that carry an attacker's URL.
     *
     * The first version of this test conflated them: it required the payload to
     * be absent from the sign-in link and called that the open-redirect
     * defence. It did find something real -- `/\evil.example` was passing the
     * page's check, because that check rejected `//` and said nothing about a
     * backslash, which a browser normalises to a slash. But the reason the
     * application was not vulnerable was the API, which the test never looked
     * at.
     */
    for (const target of HOSTILE) {
      await page.context().clearCookies();
      await page.goto(`/login?next=${encodeURIComponent(target)}`);
      await page.waitForTimeout(300);

      // The login page has not navigated anywhere itself.
      expect(new URL(page.url()).origin, `left the origin for ${target}`).toBe(
        "http://localhost:3000",
      );

      // LAYER 1 -- the page refuses to carry the payload into its sign-in link.
      const href = await page
        .getByRole("link", { name: /continue with google/i })
        .getAttribute("href");
      expect(href, "the sign-in link should exist").toBeTruthy();

      const link = new URL(href!);
      expect(link.origin, `sign-in link host changed for ${target}`).toBe(new URL(API()).origin);
      expect(link.pathname).toMatch(/\/auth\/google\/login$/);
      expect(
        link.searchParams.get("next"),
        `the login page forwarded a hostile next for ${target}`,
      ).toBeNull();

      // LAYER 2 -- and the API discards it even when handed the payload
      // directly, which is how a real attacker would deliver it.
      const direct = `${API()}/auth/google/login?next=${encodeURIComponent(target)}`;
      const response = await page.request.get(direct, { maxRedirects: 0 });
      expect(
        response.status(),
        `${target} should still start the OAuth flow`,
      ).toBeGreaterThanOrEqual(300);
      expect(response.status()).toBeLessThan(400);

      const location = response.headers()["location"] ?? "";
      expect(new URL(location).origin, `redirected off Google for ${target}`).toBe(
        "https://accounts.google.com",
      );
      expect(location, `payload survived into the redirect for ${target}`).not.toContain("evil");
      expect(location.toLowerCase()).not.toContain("javascript:");
    }
  });
});

test.describe("CSRF", () => {
  test("a cross-origin POST without a token is refused", async ({ page }) => {
    await signIn(page, "ADMIN");
    await page.goto("/dashboard");
    await waitForData(page);

    // Issued from the page, so the browser attaches cookies exactly as it would
    // for a real request.
    const status = await page.evaluate(async (api) => {
      const response = await fetch(`${api}/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
      return response.status;
    }, API());

    expect(status, "a POST without a CSRF token must be refused").toBe(403);
  });

  test("a wrong token is refused and the correct one succeeds", async ({ page }) => {
    // The success path here is a real sign-out, which revokes the token. It
    // gets its own session so the rest of the suite keeps the shared one.
    await signInDisposable(page, "ADMIN");
    await page.goto("/dashboard");
    await waitForData(page);

    const wrong = await page.evaluate(async (api) => {
      const response = await fetch(`${api}/auth/logout`, {
        method: "POST",
        credentials: "include",
        headers: { "X-CSRF-Token": "not-the-token" },
      });
      return response.status;
    }, API());
    expect(wrong).toBe(403);

    const good = await page.evaluate(async (api) => {
      const csrf = await (await fetch(`${api}/auth/csrf`, { credentials: "include" })).json();
      const response = await fetch(`${api}/auth/logout`, {
        method: "POST",
        credentials: "include",
        headers: { "X-CSRF-Token": csrf.data.csrf_token },
      });
      return response.status;
    }, API());
    expect(good).toBe(200);
  });
});

test.describe("RBAC", () => {
  /**
   * Roles and the domains the backend grants them, from `security/policy.py`.
   * The browser test asserts both halves: the navigation hides what a role
   * cannot use, and — far more importantly — the API refuses it anyway.
   */
  const MATRIX: { role: Parameters<typeof signIn>[1]; allowed: string[]; denied: string[] }[] = [
    {
      role: "ADMIN",
      allowed: ["/production", "/quality", "/inventory", "/maintenance"],
      denied: [],
    },
    { role: "FACTORY_MANAGER", allowed: ["/production", "/quality", "/inventory"], denied: [] },
    {
      role: "PRODUCTION_SUPERVISOR",
      allowed: ["/production", "/machines"],
      denied: ["/quality", "/inventory"],
    },
    {
      role: "QUALITY_ENGINEER",
      allowed: ["/quality", "/machines"],
      denied: ["/production", "/inventory"],
    },
    {
      role: "INVENTORY_MANAGER",
      allowed: ["/inventory", "/analytics"],
      denied: ["/production", "/quality"],
    },
    {
      role: "VIEWER",
      allowed: ["/dashboard", "/analytics", "/alerts"],
      denied: ["/production", "/quality", "/inventory", "/machines"],
    },
  ];

  const API_FOR: Record<string, string> = {
    "/production": "/production/summary",
    "/quality": "/quality/summary",
    "/inventory": "/inventory/summary",
    "/machines": "/machines/summary",
    "/analytics": "/analytics/oee",
    "/alerts": "/alerts/summary",
    "/maintenance": "/maintenance",
    "/dashboard": "/dashboard/summary",
  };

  for (const entry of MATRIX) {
    test(`${entry.role}: permitted pages load, forbidden ones are refused`, async ({ page }) => {
      await signIn(page, entry.role);

      for (const route of entry.allowed) {
        await page.goto(route);
        await waitForData(page);
        const text = await page.locator("main").innerText();
        expect(text, `${entry.role} should be able to use ${route}`).not.toMatch(
          /do not have access/i,
        );
      }

      for (const route of entry.denied) {
        // Direct URL access must not bypass anything: the page loads, and the
        // data region reports the refusal.
        await page.goto(route);
        await waitForData(page);
        await expect(
          page.locator("main"),
          `${entry.role} should be refused ${route} in the UI`,
        ).toContainText(/do not have access|not permit/i);

        // And the API refuses independently of anything the UI does.
        const response = await page.request.get(`${API()}${API_FOR[route]}`);
        expect(response.status(), `${entry.role} must get 403 from ${API_FOR[route]}`).toBe(403);
      }
    });
  }

  test("navigation hides what a role cannot use, without relying on it", async ({ page }) => {
    await signIn(page, "VIEWER");
    await page.goto("/dashboard");
    await waitForData(page);

    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Dashboard", exact: true })).toBeVisible();
    // Hidden as a courtesy...
    await expect(nav.getByRole("link", { name: "Production", exact: true })).toHaveCount(0);

    // ...but the backend is what actually enforces it.
    expect((await page.request.get(`${API()}/production/summary`)).status()).toBe(403);
  });
});

test.describe("rate limiting", () => {
  /*
   * A regression test for a defect this suite found the hard way.
   *
   * The RBAC tests below began failing with 429s that moved between roles from
   * run to run -- the signature of a shared bucket rather than a broken
   * assertion. The cause was that the rate limiter chose both its policy and
   * its bucket from `request.state.user_id`, which is set by a route dependency
   * and therefore does not exist yet when middleware runs. Every signed-in user
   * was counted against their IP address, and held to the unauthenticated
   * allowance.
   *
   * For a factory that is not a footnote: the terminals on a shop floor sit
   * behind one NAT, so the whole site would have shared a single 60-per-minute
   * budget -- roughly a dozen page loads a minute between everyone.
   *
   * The test drives one user past the limit and then asks whether a *different*
   * user, on the same address, is still served.
   */
  test("one user's traffic does not throttle another on the same address", async ({ browser }) => {
    const heavy = await browser.newContext();
    const other = await browser.newContext();

    try {
      const heavyPage = await heavy.newPage();
      const otherPage = await other.newPage();
      // Deliberately not ADMIN: the CSRF test above completes a real sign-out,
      // which revokes that session server-side, and every later ADMIN request
      // is answered 401. These two roles are only ever read from.
      await signIn(heavyPage, "PRODUCTION_SUPERVISOR");
      await signIn(otherPage, "INVENTORY_MANAGER");

      expect(
        (await otherPage.request.get(`${API()}/alerts/summary`)).status(),
        "the second user should start out able to reach the API",
      ).toBe(200);

      // Drive the first user into the limit. The cap is a safety net: the
      // point is that the limiter engages, not how long it takes.
      /*
       * Sent in batches rather than one at a time.
       *
       * Sequentially this took most of a minute and eventually tripped the test
       * timeout on a slower backend -- and the fix for that is not a longer
       * timeout, it is to stop testing a rate limiter with traffic no rate
       * limiter would ever need to stop. Concurrent bursts are what the control
       * exists for, and they reach the limit in a couple of seconds.
       *
       * The window is fixed rather than sliding, so a burst that straddles a
       * boundary gets a fresh allowance; the cap below is generous enough to
       * cross one and still finish.
       */
      let sawLimit = false;
      for (let batch = 0; batch < 20 && !sawLimit; batch += 1) {
        const statuses = await Promise.all(
          Array.from({ length: 25 }, () =>
            heavyPage.request.get(`${API()}/alerts/summary`).then((response) => response.status()),
          ),
        );
        for (const status of statuses) {
          if (status === 429) {
            sawLimit = true;
          } else {
            expect(status, "unexpected status while filling the bucket").toBe(200);
          }
        }
      }
      expect(sawLimit, "the rate limiter never engaged, so this proves nothing").toBe(true);

      // The second user has sent one request of their own.
      expect(
        (await otherPage.request.get(`${API()}/alerts/summary`)).status(),
        "a second user was throttled by someone else's traffic: the limiter is bucketing by IP",
      ).toBe(200);
    } finally {
      await heavy.close();
      await other.close();
    }
  });

  test("routine login-page traffic does not consume the sign-in allowance", async ({ page }) => {
    /*
     * The sign-in endpoints are the strictest thing in the API -- ten requests
     * a minute -- because they are unauthenticated and reach Google. That
     * allowance has to be spent by sign-in attempts and nothing else.
     *
     * It was not. The bucket was named after the third path segment, so
     * `/auth/status` and `/auth/google/login` shared one counter while being
     * held to 120 and 10 a minute. `/auth/status` is what the login page calls
     * on open, so a dozen reloads -- an ordinary thing to do when a sign-in has
     * just failed -- left the next real attempt refused with a 429. The
     * strictest limit in the system was the easiest to trip, by traffic that
     * was never meant to count against it.
     *
     * Well under the 120 the status endpoint is allowed, and comfortably over
     * the 10 that sign-in is.
     */
    await page.context().clearCookies();

    for (let i = 0; i < 15; i += 1) {
      const status = (await page.request.get(`${API()}/auth/status`)).status();
      expect(status, `/auth/status was throttled on call ${i + 1}`).toBe(200);
    }

    const signIn = await page.request.get(`${API()}/auth/google/login`, { maxRedirects: 0 });
    expect(
      signIn.status(),
      "sign-in was refused after ordinary login-page traffic: the buckets are shared again",
    ).toBe(302);
    expect(new URL(signIn.headers()["location"] ?? "").origin).toBe("https://accounts.google.com");
  });
});

test.describe("client-side secrets", () => {
  test("no token is stored in the browser and no secret is in the bundle", async ({ page }) => {
    await signIn(page, "ADMIN");
    await page.goto("/dashboard");
    await waitForData(page);

    const storage = await page.evaluate(() => ({
      local: Object.entries(localStorage).map(([k, v]) => `${k}=${String(v).slice(0, 40)}`),
      session: Object.entries(sessionStorage).map(([k, v]) => `${k}=${String(v).slice(0, 40)}`),
      cookie: document.cookie,
    }));

    // The session is HttpOnly, so JavaScript cannot see it — including an XSS
    // payload.
    expect(storage.cookie).not.toContain("acf_session");
    const jwtish = /eyJ[A-Za-z0-9_-]{10}/;
    expect(storage.local.join(" ")).not.toMatch(jwtish);
    expect(storage.session.join(" ")).not.toMatch(jwtish);
    expect(storage.cookie).not.toMatch(jwtish);

    // Nothing server-only leaked into the page or its scripts.
    const html = await page.content();
    for (const secret of [
      "SUPABASE_SERVICE_ROLE",
      "GOOGLE_CLIENT_SECRET",
      "JWT_SECRET",
      "postgresql://",
    ]) {
      expect(html, `${secret} appears in the page`).not.toContain(secret);
    }
  });

  test("the browser talks only to the app and its API", async ({ page }) => {
    await signIn(page, "ADMIN");

    const hosts = new Set<string>();
    page.on("request", (request) => hosts.add(new URL(request.url()).origin));

    await page.goto("/dashboard");
    await waitForData(page);

    const unexpected = [...hosts].filter(
      (origin) => origin !== "http://localhost:3000" && origin !== "http://localhost:8000",
    );
    // No CDN, no analytics, no icon service.
    expect(unexpected, "requests to unexpected origins").toEqual([]);
  });

  test("no JWT ever appears in a URL", async ({ page }) => {
    await signIn(page, "ADMIN");

    const urls: string[] = [];
    page.on("request", (request) => urls.push(request.url()));

    await page.goto("/dashboard");
    await waitForData(page);
    await page.goto("/production");
    await waitForData(page);

    const leaks = urls.filter((url) => /eyJ[A-Za-z0-9_-]{10}/.test(url));
    expect(leaks, "a token-shaped value appeared in a URL").toEqual([]);
  });
});
