/**
 * Evidence capture.
 *
 * Not assertions -- these produce the screenshots referenced by
 * `docs/browser-e2e.md`. Kept in the suite so the evidence is regenerated from
 * the real application rather than pasted in once and left to rot.
 */
import { signIn, test, waitForData } from "./fixtures";

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

const PAGES: { path: string; name: string }[] = [
  { path: "/dashboard", name: "03-dashboard-desktop" },
  { path: "/production", name: "04-production" },
  { path: "/quality", name: "05-quality" },
  { path: "/inventory", name: "06-inventory" },
  { path: "/machines", name: "07-machines" },
  { path: "/analytics", name: "08-analytics" },
  { path: "/alerts", name: "09-alerts" },
  { path: "/maintenance", name: "10-maintenance" },
];

test.describe("evidence", () => {
  for (const target of PAGES) {
    test(`capture ${target.name}`, async ({ page }) => {
      await signIn(page, "ADMIN");
      await page.setViewportSize(DESKTOP);
      await page.goto(target.path);
      await waitForData(page);
      // Charts animate their first paint even with animation disabled; a beat
      // here keeps the evidence from catching a half-drawn axis.
      await page.waitForTimeout(600);
      await page.screenshot({
        path: `../artifacts/e2e/${target.name}.png`,
        fullPage: true,
      });
    });
  }

  test("capture 11-dashboard-mobile", async ({ page }) => {
    await signIn(page, "ADMIN");
    await page.setViewportSize(MOBILE);
    await page.goto("/dashboard");
    await waitForData(page);
    await page.waitForTimeout(600);
    await page.screenshot({ path: "../artifacts/e2e/11-dashboard-mobile.png", fullPage: true });
  });

  test("capture 12-mobile-drawer-open", async ({ page }) => {
    await signIn(page, "ADMIN");
    await page.setViewportSize(MOBILE);
    await page.goto("/dashboard");
    await waitForData(page);
    await page.getByRole("button", { name: /open navigation menu/i }).click();
    await page.getByRole("dialog").waitFor();
    await page.screenshot({ path: "../artifacts/e2e/12-mobile-drawer-open.png" });
  });
});
