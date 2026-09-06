/**
 * Responsive behaviour at six real viewports.
 *
 * These are the tests jsdom structurally could not run: with no layout engine,
 * Phase 6's structural suite could not have detected horizontal overflow, a
 * clipped card, or a chart of zero width. Everything here measures real boxes
 * in Chromium.
 */
import { expect, horizontalOverflow, signIn, test, waitForData } from "./fixtures";

const VIEWPORTS = [
  { name: "375x812 (iPhone SE / small phone)", width: 375, height: 812, mobile: true },
  { name: "390x844 (iPhone 14)", width: 390, height: 844, mobile: true },
  { name: "768x1024 (tablet portrait)", width: 768, height: 1024, mobile: true },
  { name: "1024x768 (tablet landscape)", width: 1024, height: 768, mobile: true },
  { name: "1280x800 (laptop)", width: 1280, height: 800, mobile: false },
  { name: "1440x900 (desktop)", width: 1440, height: 900, mobile: false },
];

const ROUTES = [
  "/dashboard",
  "/production",
  "/quality",
  "/inventory",
  "/machines",
  "/analytics",
  "/alerts",
  "/maintenance",
];

test.beforeEach(async ({ page }) => {
  await signIn(page, "ADMIN");
});

for (const viewport of VIEWPORTS) {
  test.describe(viewport.name, () => {
    test(`no page scrolls horizontally at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });

      for (const route of ROUTES) {
        await page.goto(route);
        await waitForData(page);

        const overflow = await horizontalOverflow(page);
        expect(
          overflow.overflows,
          `${route} overflows at ${viewport.width}px: ` +
            `scrollWidth ${overflow.scrollWidth} > innerWidth ${overflow.innerWidth}. ` +
            `Widest elements: ${overflow.culprits.join("; ")}`,
        ).toBe(false);
      }
    });

    test(`the dashboard stays legible at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/dashboard");
      await waitForData(page);

      // The heading and at least one KPI value must be on screen and readable.
      const heading = page.getByRole("heading", { level: 1 });
      await expect(heading).toBeVisible();

      const kpiValues = page.locator("main p.text-2xl");
      expect(await kpiValues.count(), "no KPI values rendered").toBeGreaterThan(0);

      // Nothing is clipped to nothing.
      const box = await kpiValues.first().boundingBox();
      expect(box!.width).toBeGreaterThan(30);
      expect(box!.height).toBeGreaterThan(10);

      // Charts resize rather than keeping a desktop width.
      const surface = page.locator("figure .recharts-wrapper > .recharts-surface").first();
      const chartBox = await surface.boundingBox();
      expect(chartBox, "no chart drawn").not.toBeNull();
      expect(chartBox!.width).toBeGreaterThan(100);
      expect(
        chartBox!.width,
        `the chart is wider than the viewport at ${viewport.width}px`,
      ).toBeLessThanOrEqual(viewport.width);
    });

    test(`navigation is reachable at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/dashboard");
      await waitForData(page);

      if (viewport.width >= 1024) {
        // The persistent rail appears from `lg` (1024px) up.
        await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
      } else {
        // Below it, the rail is hidden and the drawer button takes over.
        const menuButton = page.getByRole("button", { name: /open navigation menu/i });
        await expect(menuButton).toBeVisible();

        await menuButton.click();
        const dialog = page.getByRole("dialog");
        await expect(dialog).toBeVisible();
        await expect(dialog.getByRole("link", { name: "Production", exact: true })).toBeVisible();

        // And it closes again without navigating.
        await page.keyboard.press("Escape");
        await expect(dialog).toBeHidden();
      }
    });
  });
}

test.describe("mobile interaction at 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the drawer navigates and closes itself", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    await page.getByRole("button", { name: /open navigation menu/i }).click();
    await page.getByRole("dialog").getByRole("link", { name: "Quality", exact: true }).click();

    await page.waitForURL(/\/quality$/);
    await waitForData(page);
    // Navigating closes the drawer rather than leaving it over the new page.
    await expect(page.getByRole("dialog")).toBeHidden();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Quality");
  });

  test("filters are usable on a phone", async ({ page }) => {
    await page.goto("/inventory");
    await waitForData(page);

    const select = page.getByLabel("Status");
    await expect(select).toBeVisible();

    // A touch target big enough to hit (WCAG 2.5.8 asks 24px; 36 is the design).
    const box = await select.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(24);

    await select.selectOption("LOW");
    await waitForData(page);
    await expect(page).toHaveURL(/status=LOW/);
  });

  test("a wide table scrolls inside its card, not the page", async ({ page }) => {
    await page.goto("/production");
    await waitForData(page);

    // The page itself must not scroll sideways...
    const overflow = await horizontalOverflow(page);
    expect(overflow.overflows).toBe(false);

    // ...but the table's own wrapper is allowed to, and must, so the columns
    // stay readable rather than being crushed.
    const scroller = page
      .getByRole("table", { name: /Production records/i })
      .locator("xpath=ancestor::div[contains(@class,'overflow-x-auto')][1]");
    const canScroll = await scroller.evaluate(
      (element) => element.scrollWidth > element.clientWidth,
    );
    expect(canScroll, "the records table should scroll within its card").toBe(true);
  });

  test("the account menu opens and offers sign out", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    await page.getByRole("button", { name: /account menu/i }).click();
    await expect(page.getByRole("menuitem", { name: /sign out/i })).toBeVisible();
  });
});
