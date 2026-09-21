/**
 * The dashboard, against real data from Supabase.
 *
 * The most valuable assertions here are the cross-checks: read what the API
 * returned, read what the browser rendered, and require them to agree. A UI
 * that quietly rounds, rescales or relabels a KPI passes every "element is
 * visible" test ever written.
 */
import type { Page } from "@playwright/test";

import { expect, expectNoBrowserErrors, sessions, signIn, test, waitForData } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await signIn(page, "ADMIN");
});

test.describe("dashboard rendering", () => {
  test("renders every section with real data and no browser errors", async ({ page, problems }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    await expect(page.getByRole("heading", { level: 1 })).toContainText("Factory Operations");

    // Each section the spec's hierarchy calls for, by its heading.
    for (const heading of [
      "Production trend",
      "Active alerts",
      "Target vs actual",
      "Quality",
      "Top defect causes",
      "Machine status",
      "Inventory health",
      "Overall equipment effectiveness",
    ]) {
      await expect(
        page.getByRole("heading", { name: heading, exact: false }),
        `section "${heading}" is missing`,
      ).toBeVisible();
    }

    expectNoBrowserErrors(problems);
  });

  test("KPI cards show real values, not placeholders", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const response = await page.request.get(`${sessions().apiBaseUrl}/dashboard/summary`);
    const kpis = (await response.json()).data.kpis as {
      label: string;
      status_label: string;
    }[];
    expect(kpis.length, "the API returned no KPIs").toBeGreaterThan(0);

    for (const kpi of kpis) {
      // The label and the status word must both be on screen: spec section 4
      // forbids conveying status by colour alone.
      await expect(page.getByText(kpi.label, { exact: true }).first()).toBeVisible();
      await expect(page.getByText(kpi.status_label).first()).toBeVisible();
    }
  });

  test("shows no NaN, undefined, null or Infinity anywhere on the page", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const text = await page.locator("main").innerText();
    // The classic symptoms of a formatter meeting a value it did not expect.
    expect(text).not.toMatch(/\bNaN\b/);
    expect(text).not.toMatch(/\bundefined\b/);
    expect(text).not.toMatch(/\bInfinity\b/);
    expect(text).not.toMatch(/\[object Object\]/);
    expect(text).not.toMatch(/\bnull\b/);
  });

  test("reports no negative percentages where none are possible", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const text = await page.locator("main").innerText();
    // A trend may legitimately fall, and its sign is shown separately. What
    // must never appear is a negative *rate* such as "-4.2%" attached to a KPI
    // value, which would mean a formatter or a divisor went wrong.
    const kpiValues = await page.locator("main p.text-2xl").allInnerTexts();
    for (const value of kpiValues) {
      expect(value, `KPI value "${value}" is negative`).not.toMatch(/^-/);
    }
    expect(text).not.toMatch(/-\d+\.\d+% of target/);
  });

  test("says when the data was last updated, without claiming to be live", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const meta = page.getByText(/Updated|Refreshing/).first();
    await expect(meta).toBeVisible();
    // Spec section 3: the wording must not overstate a 30-second poll.
    await expect(page.locator("main")).toContainText(/Refreshes every 30 seconds/i);
    await expect(page.locator("main")).not.toContainText(/\blive\b/i);
  });

  test("charts carry a text alternative and a data table", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const figures = page.locator("figure");
    const count = await figures.count();
    expect(count, "no charts rendered").toBeGreaterThan(0);

    for (let index = 0; index < count; index += 1) {
      const figure = figures.nth(index);
      // WCAG 1.1.1: a chart is a non-text element and needs an equivalent.
      const caption = figure.locator("figcaption");
      await expect(caption).toHaveCount(1);
      expect((await caption.innerText()).length).toBeGreaterThan(20);

      // And the numbers themselves, reachable without reading the picture.
      await expect(figure.locator("details table")).toHaveCount(1);
    }
  });

  test("an SVG chart is actually painted, not an empty box", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    /*
     * The regression test for the blank-chart bug.
     *
     * jsdom could never have caught it: with no layout engine, a chart of zero
     * width is indistinguishable from a working one, which is how a
     * `max-width: 100%` in `globals.css` blanked every chart for two phases
     * while every structural test stayed green.
     *
     * The locator has to be the wrapper's *direct* child: Recharts gives its
     * legend icons the `.recharts-surface` class too, and those are
     * legitimately 10px squares.
     */
    const surfaces = page.locator("figure .recharts-wrapper > .recharts-surface");
    const count = await surfaces.count();
    expect(count, "no chart surfaces rendered").toBeGreaterThan(0);

    for (let index = 0; index < count; index += 1) {
      const box = await surfaces.nth(index).boundingBox();
      expect(box, `chart surface ${index} has no layout box`).not.toBeNull();
      expect(box!.width, `chart surface ${index} width`).toBeGreaterThan(200);
      expect(box!.height, `chart surface ${index} height`).toBeGreaterThan(100);
    }

    // And it actually drew something, not just an empty canvas.
    expect(await page.locator("figure .recharts-surface path").count()).toBeGreaterThan(0);
  });
});

test.describe("rendered values match the API", () => {
  /**
   * Read a number out of the page by its visible label.
   *
   * Deliberately reads the DOM rather than recomputing anything: the point is
   * to catch the frontend changing a business meaning, so the test must not
   * perform the same calculation itself.
   */
  async function statUnder(page: Page, label: string) {
    const value = page
      .locator("dt", { hasText: new RegExp(`^${label}$`, "i") })
      .locator("xpath=following-sibling::dd[1]");
    /*
     * The first line only.
     *
     * A `Stat` renders its figure and its hint as two block elements inside the
     * one `<dd>` -- "64.3%" then "Running machines as a share of the fleet". The
     * hint used to sit outside as a sibling `<p>`, which is what axe-core
     * flagged as `definition-list`: a `<dl>` group may contain only `<dt>` and
     * `<dd>`, and a stray `<p>` breaks the term-description association a screen
     * reader relies on.
     *
     * So the hint belongs where it now is, and this reads the figure rather than
     * the figure plus its explanation.
     */
    return (await value.first().innerText()).trim().split("\n")[0].trim();
  }

  test("total production, defect rate, FPY, availability and OEE all agree", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const summary = (
      await (await page.request.get(`${sessions().apiBaseUrl}/dashboard/summary`)).json()
    ).data;

    // 1. Quality: inspected units.
    const inspected = await statUnder(page, "Inspected");
    expect(inspected.replace(/,/g, "")).toBe(String(summary.quality.total_inspected));

    // 2. Quality: rejected units.
    const rejected = await statUnder(page, "Rejected");
    expect(rejected.replace(/,/g, "")).toBe(String(summary.quality.total_rejected));

    // 3. Defect rate, to the two decimals the UI formats it with.
    const defectRate = await statUnder(page, "Defect rate");
    expect(defectRate).toBe(`${summary.quality.defect_rate_percentage.toFixed(2)}%`);

    // 4. First-pass yield.
    const fpy = await statUnder(page, "First-pass yield");
    expect(fpy).toBe(`${summary.quality.first_pass_yield_percentage.toFixed(1)}%`);

    // 5. Machine availability.
    const availability = await statUnder(page, "Availability");
    expect(availability).toBe(`${summary.machines.availability_percentage.toFixed(1)}%`);

    // 6. OEE, the headline composite.
    await expect(
      page.getByText(`${summary.oee.oee_percentage.toFixed(1)}%`, { exact: true }).first(),
    ).toBeVisible();
  });

  test("target vs actual reports the backend's achievement, not a recomputed one", async ({
    page,
  }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const summary = (
      await (await page.request.get(`${sessions().apiBaseUrl}/dashboard/summary`)).json()
    ).data;

    if (!summary.production.has_data) {
      test.skip(true, "no production on the current business date");
    }

    const produced = summary.production.total_produced as number;
    await expect(page.locator("main")).toContainText(produced.toLocaleString("en-US"));

    const achievement = page
      .locator("dt", { hasText: /^Achievement vs target$/ })
      .locator("xpath=following-sibling::dd[1]");
    const shown = (await achievement.first().innerText()).trim();

    if (summary.production.target_quantity === 0) {
      // The backend suppresses the target when it does not apply; "0%" would
      // read as total failure.
      expect(shown).toBe("Not applicable");
    } else {
      expect(shown).toBe(`${summary.production.achievement_percentage.toFixed(1)}%`);
    }
  });

  test("machine and inventory counts match the fleet and stock summaries", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const summary = (
      await (await page.request.get(`${sessions().apiBaseUrl}/dashboard/summary`)).json()
    ).data;

    // Every status the backend reports must be on screen as a word.
    for (const entry of summary.machines.status_breakdown as {
      status_label: string;
      count: number;
    }[]) {
      await expect(page.getByText(entry.status_label).first()).toBeVisible();
    }
    for (const entry of summary.inventory.status_breakdown as {
      status_label: string;
      count: number;
    }[]) {
      await expect(page.getByText(entry.status_label).first()).toBeVisible();
    }

    const attention = await statUnder(page, "Needs attention");
    expect(attention.replace(/,/g, "")).toBe(String(summary.inventory.items_requiring_attention));
  });
});

test.describe("refresh behaviour", () => {
  test("a manual refresh keeps the content on screen rather than blanking it", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const before = await page.locator("main").innerText();
    expect(before.length).toBeGreaterThan(200);

    await page.getByRole("button", { name: /^refresh$/i }).click();

    // Spec section 16: a refetch must not replace the screen. The heading and
    // the KPI grid stay mounted throughout.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("Key performance indicators")).toHaveCount(1);
    await waitForData(page);

    const after = await page.locator("main").innerText();
    expect(after.length).toBeGreaterThan(200);
  });
});
