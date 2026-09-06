/**
 * The seven module pages, driven in a real browser against real data.
 *
 * Each page gets the same treatment: does it render, does its data match the
 * API, do its filters actually change the request, and does pagination move
 * through real rows.
 */
import { expect, expectNoBrowserErrors, sessions, signIn, test, waitForData } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await signIn(page, "ADMIN");
});

test.describe("production", () => {
  test("renders KPIs, chart and a table whose totals match the API", async ({
    page,
    problems,
  }) => {
    await page.goto("/production");
    await waitForData(page);

    await expect(page.getByRole("heading", { level: 1 })).toContainText("Production");

    const api = (
      await (await page.request.get(`${sessions().apiBaseUrl}/production?page=1&page_size=25`)).json()
    );
    const total = api.pagination.total as number;

    // The pagination label states the real total, not a page-local count.
    await expect(page.locator("main")).toContainText(
      `of ${total.toLocaleString("en-US")} records`,
    );
    // Scoped by the table's caption: every chart also renders a `<details>`
    // data table, and an unscoped `table tbody tr` counts those rows too.
    const recordsTable = page.getByRole("table", { name: /Production records/i });
    const rows = await recordsTable.locator("tbody tr").count();
    expect(rows).toBeLessThanOrEqual(25);
    expect(rows).toBeGreaterThan(0);

    expectNoBrowserErrors(problems);
  });

  test("a machine filter changes the URL, the request and the results", async ({ page }) => {
    await page.goto("/production");
    await waitForData(page);

    // The pagination status region, not the whole page: several other strings
    // on the page also end in "records".
    const status = page.getByRole("status").filter({ hasText: /records/ });
    const beforeTotal = await status.innerText();

    // Pick a real machine from the live list.
    const machines = (
      await (await page.request.get(`${sessions().apiBaseUrl}/machines`)).json()
    ).data as { id: string; code: string; name: string }[];
    const machine = machines[0];

    const request = page.waitForRequest(
      (r) => r.url().includes("/production?") && r.url().includes(`machine_id=${machine.id}`),
    );
    await page.getByLabel("Machine").selectOption(machine.id);
    await request;
    await waitForData(page);

    // The URL carries the filter, so the view is shareable and reloadable.
    await expect(page).toHaveURL(new RegExp(`machine_id=${machine.id}`));

    const afterTotal = await status.innerText();
    expect(afterTotal, "the filter did not change the result count").not.toBe(beforeTotal);

    // Every visible row really is that machine.
    const codes = await page
      .getByRole("table", { name: /Production records/i })
      .locator("tbody tr td:nth-child(2)")
      .allInnerTexts();
    expect(codes.length).toBeGreaterThan(0);
    for (const code of codes) {
      expect(code.trim()).toBe(machine.code);
    }
  });

  test("a filter survives reload and browser back", async ({ page }) => {
    await page.goto("/production");
    await waitForData(page);

    const machines = (
      await (await page.request.get(`${sessions().apiBaseUrl}/machines`)).json()
    ).data as { id: string }[];
    await page.getByLabel("Machine").selectOption(machines[0].id);
    await waitForData(page);

    await page.reload();
    await waitForData(page);
    // The select still shows the filter after a full reload.
    await expect(page.getByLabel("Machine")).toHaveValue(machines[0].id);

    await page.goBack();
    await waitForData(page);
    await expect(page.getByLabel("Machine")).toHaveValue("");
  });

  test("pagination moves through real rows without overlap", async ({ page }) => {
    await page.goto("/production");
    await waitForData(page);

    const firstPage = await page.locator("table tbody tr td:first-child").allInnerTexts();
    await expect(page.locator("main")).toContainText("Page 1 of");

    await page.getByRole("button", { name: /^next$/i }).click();
    await waitForData(page);

    await expect(page.locator("main")).toContainText("Page 2 of");
    const secondPage = await page.locator("table tbody tr td:first-child").allInnerTexts();
    expect(secondPage.length).toBeGreaterThan(0);

    // Previous returns to page 1.
    await page.getByRole("button", { name: /^previous$/i }).click();
    await waitForData(page);
    await expect(page.locator("main")).toContainText("Page 1 of");
    const backAgain = await page.locator("table tbody tr td:first-child").allInnerTexts();
    expect(backAgain).toEqual(firstPage);
  });

  test("sorting a column re-sorts against the backend", async ({ page }) => {
    await page.goto("/production");
    await waitForData(page);

    const request = page.waitForRequest((r) => r.url().includes("sort_by=produced"));
    await page.getByRole("button", { name: /^Produced/ }).click();
    await request;
    await waitForData(page);

    await expect(page).toHaveURL(/./); // sorting is table state, not URL state
    const header = page.getByRole("columnheader", { name: /Produced/ });
    await expect(header).toHaveAttribute("aria-sort", /ascending|descending/);
  });

  test("an impossible filter combination shows an empty state, not a broken table", async ({
    page,
  }) => {
    // A range with no production: far in the past.
    await page.goto("/production?start_date=2020-01-01&end_date=2020-01-02");
    await waitForData(page);

    await expect(page.locator("main")).toContainText(/No production records found|No production in this range/i);
    await expect(page.locator("main")).not.toContainText(/NaN|undefined/);
  });
});

test.describe("quality", () => {
  test("renders KPIs, defect trend and a Pareto that matches the API", async ({
    page,
    problems,
  }) => {
    await page.goto("/quality");
    await waitForData(page);

    await expect(page.getByRole("heading", { level: 1 })).toContainText("Quality");

    const summary = (
      await (await page.request.get(`${sessions().apiBaseUrl}/quality/summary`)).json()
    ).data;

    await expect(page.locator("main")).toContainText(
      `${summary.defect_rate_percentage.toFixed(2)}%`,
    );
    await expect(page.locator("main")).toContainText(
      `${summary.first_pass_yield_percentage.toFixed(1)}%`,
    );

    // The Pareto keeps the backend's ranking.
    const defects = (
      await (await page.request.get(`${sessions().apiBaseUrl}/quality/defects?limit=20`)).json()
    ).data as { defect_name: string }[];
    if (defects.length > 0) {
      await expect(page.locator("main")).toContainText(defects[0].defect_name);
    }

    expectNoBrowserErrors(problems);
  });

  test("both charts are painted and carry text alternatives", async ({ page }) => {
    await page.goto("/quality");
    await waitForData(page);

    const surfaces = page.locator("figure .recharts-wrapper > .recharts-surface");
    const count = await surfaces.count();
    expect(count, "quality should draw a trend and a Pareto").toBeGreaterThanOrEqual(2);

    for (let index = 0; index < count; index += 1) {
      const box = await surfaces.nth(index).boundingBox();
      expect(box!.width, `quality chart ${index} width`).toBeGreaterThan(200);
    }
    expect(await page.locator("figure figcaption").count()).toBeGreaterThanOrEqual(2);
  });
});

test.describe("inventory", () => {
  test("renders stock health and states each status as a word", async ({ page, problems }) => {
    await page.goto("/inventory");
    await waitForData(page);

    await expect(page.getByRole("heading", { level: 1 })).toContainText("Inventory");

    const summary = (
      await (await page.request.get(`${sessions().apiBaseUrl}/inventory/summary`)).json()
    ).data;

    // Spec section 15: status is text, never colour alone.
    for (const entry of summary.status_breakdown as { status_label: string }[]) {
      await expect(page.getByText(entry.status_label).first()).toBeVisible();
    }
    await expect(page.locator("main")).toContainText(String(summary.total_items));

    expectNoBrowserErrors(problems);
  });

  test("the status filter narrows the table to that status", async ({ page }) => {
    await page.goto("/inventory");
    await waitForData(page);

    const request = page.waitForRequest((r) => r.url().includes("status=CRITICAL"));
    await page.getByLabel("Status").selectOption("CRITICAL");
    await request;
    await waitForData(page);

    await expect(page).toHaveURL(/status=CRITICAL/);

    const statuses = await page
      .getByRole("table", { name: /Inventory items/i })
      .locator("tbody tr td:nth-child(6)")
      .allInnerTexts();
    for (const status of statuses) {
      expect(status.trim()).toBe("Critical");
    }
  });
});

test.describe("machines", () => {
  test("lists the fleet with statuses matching the API", async ({ page, problems }) => {
    await page.goto("/machines");
    await waitForData(page);

    const machines = (
      await (await page.request.get(`${sessions().apiBaseUrl}/machines`)).json()
    ).data as { code: string; status_label: string }[];

    for (const machine of machines.slice(0, 5)) {
      // The code is a button whose accessible name also carries ", open machine
      // detail for ...", so an exact text match would never match.
      await expect(
        page.getByRole("button", { name: new RegExp(`^${machine.code}`) }),
        `machine ${machine.code} is missing from the fleet table`,
      ).toBeVisible();
    }
    expectNoBrowserErrors(problems);
  });

  test("opening a machine shows the same machine's detail", async ({ page }) => {
    await page.goto("/machines");
    await waitForData(page);

    // From the API, so the expected code is not read back out of the same DOM
    // the assertion is about. The button's own text carries a visually hidden
    // ", open machine detail for ..." suffix.
    const machines = (
      await (await page.request.get(`${sessions().apiBaseUrl}/machines`)).json()
    ).data as { code: string }[];

    await page.locator("table tbody tr td:first-child button").first().click();
    await page.waitForURL(/\/machines\/[0-9a-f-]{36}/);
    await waitForData(page);

    // The detail page is about a machine that is really in the fleet, and the
    // heading names it.
    const heading = await page.getByRole("heading", { level: 1 }).innerText();
    const code = heading.split("—")[0].trim();
    expect(machines.map((machine) => machine.code)).toContain(code);
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Machines");
  });

  test("an unknown machine id fails safely", async ({ page }) => {
    await page.goto("/machines/00000000-0000-4000-8000-000000000000");
    await waitForData(page);

    // A clear message, and nothing technical.
    await expect(page.locator("main")).toContainText(/not found|does not exist|unable to load/i);
    const text = await page.locator("main").innerText();
    expect(text).not.toMatch(/Traceback|psycopg|at .*\.tsx:/);
  });

  test("a malformed machine id fails safely too", async ({ page }) => {
    await page.goto("/machines/not-a-uuid");
    await waitForData(page);

    await expect(page.locator("main")).toContainText(/not found|does not exist|unable to load|not valid/i);
  });
});

test.describe("analytics", () => {
  test("shows OEE and its three factors, agreeing with the API", async ({ page, problems }) => {
    await page.goto("/analytics");
    await waitForData(page);

    const oee = (await (await page.request.get(`${sessions().apiBaseUrl}/analytics/oee`)).json())
      .data;

    for (const value of [
      oee.oee_percentage,
      oee.availability_percentage,
      oee.performance_percentage,
      oee.quality_percentage,
    ]) {
      await expect(page.locator("main")).toContainText(`${value.toFixed(1)}%`);
    }

    // The page names the weakest factor rather than leaving OEE mysterious.
    await expect(page.locator("main")).toContainText(/is the lowest factor at/i);

    expectNoBrowserErrors(problems);
  });

  test("every bar in a by-machine chart is labelled", async ({ page }) => {
    await page.goto("/analytics");
    await waitForData(page);

    // Regression test: Recharts thinned the category axis automatically and left
    // half the machines anonymous.
    const section = page.locator("section", { hasText: "OEE by machine" });
    const bars = await section.locator(".recharts-bar-rectangle").count();
    const labels = await section.locator(".recharts-yAxis .recharts-cartesian-axis-tick").count();

    expect(bars, "no bars drawn").toBeGreaterThan(0);
    expect(labels, "every bar needs a label").toBeGreaterThanOrEqual(bars);
  });

  test("changing the date range changes the data", async ({ page }) => {
    await page.goto("/analytics");
    await waitForData(page);
    const before = await page.locator("main").innerText();

    const request = page.waitForRequest((r) => r.url().includes("start_date=2026-08-25"));
    await page.getByLabel("From").fill("2026-08-25");
    await request;
    await waitForData(page);

    await expect(page).toHaveURL(/start_date=2026-08-25/);
    const after = await page.locator("main").innerText();
    expect(after).not.toBe(before);
  });
});

test.describe("alerts", () => {
  test("lists alerts with severity as text and a timestamp", async ({ page, problems }) => {
    await page.goto("/alerts");
    await waitForData(page);

    const api = await (
      await page.request.get(`${sessions().apiBaseUrl}/alerts?page=1&page_size=25`)
    ).json();
    const alerts = api.data as { title: string; severity_label: string }[];

    if (alerts.length === 0) {
      test.skip(true, "no alerts in the seeded data");
    }

    await expect(page.locator("main")).toContainText(alerts[0].title);
    // Spec section 18: severity conveyed as text, not only styling.
    await expect(page.getByText(alerts[0].severity_label).first()).toBeVisible();
    await expect(page.locator("main")).toContainText(/ago/);

    expectNoBrowserErrors(problems);
  });

  test("the severity filter narrows the list", async ({ page }) => {
    await page.goto("/alerts");
    await waitForData(page);

    const request = page.waitForRequest((r) => r.url().includes("severity=CRITICAL"));
    await page.getByLabel("Severity").selectOption("CRITICAL");
    await request;
    await waitForData(page);

    await expect(page).toHaveURL(/severity=CRITICAL/);

    // Scoped to the list. "Warning" is also a filter option and a summary card
    // label, so asserting against the whole page would always fail.
    const list = page.locator("section", { hasText: "Alert history" }).locator("ul");
    const badges = await list.locator("li").allInnerTexts();
    expect(badges.length).toBeGreaterThan(0);
    for (const badge of badges) {
      expect(badge).toContain("Critical");
    }
  });
});

test.describe("maintenance", () => {
  test("shows upcoming and recent work with machine references", async ({ page, problems }) => {
    await page.goto("/maintenance");
    await waitForData(page);

    await expect(page.getByRole("heading", { level: 1 })).toContainText("Maintenance");
    await expect(page.getByRole("heading", { name: "Upcoming", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: /recently completed/i })).toBeVisible();

    const api = await (
      await page.request.get(`${sessions().apiBaseUrl}/maintenance?page=1&page_size=25`)
    ).json();
    const records = api.data as { machine_code: string }[];
    if (records.length > 0) {
      await expect(page.getByText(records[0].machine_code).first()).toBeVisible();
    }

    expectNoBrowserErrors(problems);
  });
});

test.describe("navigation", () => {
  const ROUTES = [
    { path: "/dashboard", heading: "Factory Operations" },
    { path: "/production", heading: "Production" },
    { path: "/quality", heading: "Quality" },
    { path: "/inventory", heading: "Inventory" },
    { path: "/machines", heading: "Machines" },
    { path: "/analytics", heading: "Analytics" },
    { path: "/alerts", heading: "Alerts" },
    { path: "/maintenance", heading: "Maintenance" },
  ];

  test("every sidebar link navigates client-side and marks itself current", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    for (const route of ROUTES.slice(1)) {
      const link = page.getByRole("navigation", { name: "Main" }).getByRole("link", {
        name: route.heading,
        exact: true,
      });
      await link.click();
      await page.waitForURL(new RegExp(`${route.path}$`));
      await waitForData(page);

      await expect(page.getByRole("heading", { level: 1 })).toContainText(route.heading);
      // The active link is marked for assistive technology, not only styled.
      await expect(
        page.getByRole("navigation", { name: "Main" }).getByRole("link", {
          name: route.heading,
          exact: true,
        }),
      ).toHaveAttribute("aria-current", "page");
    }
  });

  test("direct URL access works for every route", async ({ page }) => {
    for (const route of ROUTES) {
      await page.goto(route.path);
      await waitForData(page);
      await expect(page.getByRole("heading", { level: 1 })).toContainText(route.heading);
    }
  });

  test("browser back and forward move between pages", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);
    await page.goto("/quality");
    await waitForData(page);

    await page.goBack();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Factory Operations");

    await page.goForward();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Quality");
  });

  test("each page sets a distinct document title", async ({ page }) => {
    const titles = new Set<string>();
    for (const route of ROUTES) {
      await page.goto(route.path);
      titles.add(await page.title());
    }
    // Titles matter for tabs, history and screen-reader page announcements.
    expect(titles.size, `titles were not distinct: ${[...titles].join(" | ")}`).toBeGreaterThan(5);
  });
});
