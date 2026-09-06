/**
 * Accessibility in a real browser (WCAG 2.2 AA target).
 *
 * Two halves, and both are needed.
 *
 * axe-core catches what a rule engine can: contrast against real computed
 * colours, missing names, broken ARIA. It runs against a live DOM, which is
 * what makes the contrast checks meaningful — jsdom has no colours to measure.
 *
 * The hand-written tests cover what no rule engine can decide: whether Tab
 * actually reaches a control, whether focus is visible, whether a dialog traps
 * and restores focus, and whether status is readable without colour. Those are
 * the things that make an interface usable rather than merely conformant.
 */
import AxeBuilder from "@axe-core/playwright";

import { expect, signIn, test, waitForData } from "./fixtures";

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

test.describe("axe-core audit", () => {
  for (const route of ROUTES) {
    test(`${route} has no WCAG 2.2 A/AA violations`, async ({ page }) => {
      await page.goto(route);
      await waitForData(page);

      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
        .analyze();

      const summary = results.violations.map(
        (violation) =>
          `${violation.id} (${violation.impact}): ${violation.help} ` +
          `[${violation.nodes.length} node(s)] e.g. ${violation.nodes[0]?.target.join(" ")}`,
      );

      expect(summary, `axe violations on ${route}`).toEqual([]);
    });
  }

  test("the login page has no violations either", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/login");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();

    expect(
      results.violations.map((v) => `${v.id}: ${v.help}`),
      "axe violations on /login",
    ).toEqual([]);
  });
});

test.describe("keyboard navigation", () => {
  test("the skip link is the first stop and jumps to the content", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    await page.keyboard.press("Tab");

    const focused = await page.evaluate(() => ({
      text: document.activeElement?.textContent?.trim(),
      href: (document.activeElement as HTMLAnchorElement)?.getAttribute("href"),
    }));
    expect(focused.text).toMatch(/skip to main content/i);
    expect(focused.href).toBe("#main-content");

    // And it becomes visible when focused, rather than staying screen-reader only.
    const visible = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement;
      const box = element.getBoundingClientRect();
      return box.width > 1 && box.height > 1;
    });
    expect(visible, "the skip link must be visible once focused").toBe(true);
  });

  test("every interactive control shows a visible focus ring", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    // Walk the first 25 stops and confirm each paints an outline.
    const withoutRing: string[] = [];
    for (let i = 0; i < 25; i += 1) {
      await page.keyboard.press("Tab");
      const info = await page.evaluate(() => {
        const element = document.activeElement as HTMLElement | null;
        if (!element || element === document.body) {
          return null;
        }
        const style = getComputedStyle(element);
        return {
          tag: element.tagName.toLowerCase(),
          label: (element.getAttribute("aria-label") ?? element.textContent ?? "").trim().slice(0, 40),
          outlineStyle: style.outlineStyle,
          outlineWidth: style.outlineWidth,
        };
      });
      if (!info) {
        continue;
      }
      if (info.outlineStyle === "none" || info.outlineWidth === "0px") {
        withoutRing.push(`${info.tag} "${info.label}"`);
      }
    }
    expect(withoutRing, "controls without a visible focus indicator").toEqual([]);
  });

  test("the sidebar is reachable and its links activate by keyboard", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const link = page
      .getByRole("navigation", { name: "Main" })
      .getByRole("link", { name: "Quality", exact: true });

    await link.focus();
    await page.keyboard.press("Enter");

    await page.waitForURL(/\/quality$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Quality");
  });

  test("the mobile drawer traps focus and restores it on close", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/dashboard");
    await waitForData(page);

    const trigger = page.getByRole("button", { name: /open navigation menu/i });
    await trigger.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // Tab many times; focus must never escape the dialog.
    for (let i = 0; i < 20; i += 1) {
      await page.keyboard.press("Tab");
      const inside = await page.evaluate(() => {
        const dialogElement = document.querySelector('[role="dialog"]');
        return dialogElement?.contains(document.activeElement) ?? false;
      });
      expect(inside, `focus escaped the drawer on Tab ${i + 1}`).toBe(true);
    }

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();

    // Focus returns to the control that opened it, not to the top of the page.
    const restored = await page.evaluate(
      () => document.activeElement?.getAttribute("aria-label") ?? "",
    );
    expect(restored).toMatch(/open navigation menu/i);
  });

  test("the account menu closes on Escape and returns focus", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const trigger = page.getByRole("button", { name: /account menu/i });
    await trigger.click();
    await expect(page.getByRole("menuitem", { name: /sign out/i })).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(page.getByRole("menuitem", { name: /sign out/i })).toBeHidden();

    const focused = await page.evaluate(
      () => document.activeElement?.textContent?.includes("Account menu") ?? false,
    );
    expect(focused, "focus should return to the account trigger").toBe(true);
  });
});

test.describe("semantics", () => {
  test("every page has exactly one h1 and no skipped heading levels", async ({ page }) => {
    for (const route of ROUTES) {
      await page.goto(route);
      await waitForData(page);

      const levels = await page.evaluate(() =>
        Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6")).map((element) =>
          Number(element.tagName[1]),
        ),
      );

      expect(levels.filter((level) => level === 1), `${route} h1 count`).toHaveLength(1);
      expect(levels[0], `${route} does not start at h1`).toBe(1);
      for (let index = 1; index < levels.length; index += 1) {
        expect(
          levels[index] - levels[index - 1],
          `${route} jumps from h${levels[index - 1]} to h${levels[index]}`,
        ).toBeLessThanOrEqual(1);
      }
    }
  });

  test("landmarks are present and labelled", async ({ page }) => {
    await page.goto("/production");
    await waitForData(page);

    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("search", { name: "Filters" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toBeVisible();
  });

  test("tables carry a caption and column headers", async ({ page }) => {
    await page.goto("/production");
    await waitForData(page);

    const table = page.getByRole("table", { name: /Production records/i });
    await expect(table).toBeVisible();

    const headers = table.locator("th[scope=col]");
    expect(await headers.count()).toBeGreaterThan(5);

    // A sortable header reports its state, not just a caret.
    const sorted = table.locator("th[aria-sort]");
    expect(await sorted.count()).toBeGreaterThan(0);
  });

  test("every form control has a label", async ({ page }) => {
    await page.goto("/production");
    await waitForData(page);

    const unlabelled = await page.evaluate(() =>
      Array.from(document.querySelectorAll<HTMLElement>("input, select, textarea"))
        .filter((element) => {
          if (element.getAttribute("aria-label")) return false;
          if (element.getAttribute("aria-labelledby")) return false;
          const id = element.getAttribute("id");
          if (id && document.querySelector(`label[for="${CSS.escape(id)}"]`)) return false;
          return !element.closest("label");
        })
        .map((element) => `${element.tagName.toLowerCase()}#${element.id || "(no id)"}`),
    );
    expect(unlabelled, "form controls without a label").toEqual([]);
  });

  test("status is conveyed as text, not by colour alone", async ({ page }) => {
    await page.goto("/machines");
    await waitForData(page);

    // Each status dot is decorative; the word beside it carries the meaning.
    const text = await page.locator("main").innerText();
    expect(text).toMatch(/Running|Idle|Maintenance|Offline/);

    const dots = page.locator('main span[aria-hidden="true"].rounded-full');
    const dotCount = await dots.count();
    expect(dotCount, "status dots should exist and be decorative").toBeGreaterThan(0);
  });

  test("decorative icons are hidden and named icons have names", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const unnamed = await page.evaluate(() =>
      Array.from(document.querySelectorAll("svg"))
        .filter((svg) => {
          const hidden = svg.getAttribute("aria-hidden") === "true";
          const named = svg.getAttribute("role") === "img" && svg.hasAttribute("aria-label");
          // Recharts' internals are inert graphics inside an aria-hidden box.
          const inChart = svg.closest('[aria-hidden="true"]') !== null;
          return !hidden && !named && !inChart;
        })
        .map((svg) => svg.getAttribute("class") ?? "(no class)"),
    );
    expect(unnamed, "svgs that are neither hidden nor named").toEqual([]);
  });
});

test.describe("charts", () => {
  test("each chart has a caption and a keyboard-reachable data table", async ({ page }) => {
    await page.goto("/analytics");
    await waitForData(page);

    const figures = page.locator("figure");
    const count = await figures.count();
    expect(count).toBeGreaterThan(0);

    for (let index = 0; index < count; index += 1) {
      const figure = figures.nth(index);
      const caption = await figure.locator("figcaption").innerText();
      expect(caption.length, `chart ${index} caption is too short`).toBeGreaterThan(20);

      // The <summary> is a real, focusable control.
      const summary = figure.locator("details > summary");
      await expect(summary).toHaveCount(1);
      await summary.focus();
      await page.keyboard.press("Enter");
      await expect(figure.locator("details table")).toBeVisible();
      await page.keyboard.press("Enter");
    }
  });
});

test.describe("reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("honours prefers-reduced-motion", async ({ page }) => {
    await page.goto("/dashboard");
    await waitForData(page);

    const animated = await page.evaluate(() =>
      Array.from(document.querySelectorAll<HTMLElement>("*"))
        .filter((element) => {
          const style = getComputedStyle(element);
          const duration = parseFloat(style.animationDuration) || 0;
          const transition = parseFloat(style.transitionDuration) || 0;
          return duration > 0.05 || transition > 0.05;
        })
        .slice(0, 5)
        .map((element) => element.tagName.toLowerCase()),
    );
    expect(animated, "animations should be suppressed under reduced motion").toEqual([]);
  });
});
