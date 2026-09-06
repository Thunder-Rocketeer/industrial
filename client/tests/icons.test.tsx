/**
 * @vitest-environment jsdom
 */

/**
 * Icons resolve locally, with no network request (spec sections 33 and 41).
 *
 * This is the test that makes the Content-Security-Policy claim in
 * `docs/security-headers.md` true. `@iconify/react` falls back to fetching an
 * unknown name from `api.iconify.design`, so "we do not need `connect-src` for
 * Iconify" holds only for as long as *every* name used is in the local
 * registry. An icon added to a component without regenerating the registry
 * would silently reintroduce a runtime CDN dependency — and would still render
 * correctly on a developer's machine, which is exactly why it needs a test.
 */
import { getIcon } from "@iconify/react";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { extname, join } from "node:path";
import { describe, expect, it } from "vitest";

// Importing the component registers the bundled icons as a side effect.
import "@/components/ui/Icon";
import { BUNDLED_ICONS } from "@/lib/icons.generated";

const ROOT = join(__dirname, "..");
const SCAN_DIRS = ["app", "components", "lib", "hooks"];

/** Every `"prefix:name"` icon string appearing in the source. */
function iconNamesInSource(): string[] {
  const names = new Set<string>();
  const pattern = /"((?:mdi|logos):[a-z0-9-]+)"/g;

  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        walk(full);
      } else if ([".ts", ".tsx"].includes(extname(full))) {
        // The generated registry lists every name by definition; scanning it
        // would make this test tautological.
        if (full.endsWith("icons.generated.ts")) {
          continue;
        }
        for (const match of readFileSync(full, "utf8").matchAll(pattern)) {
          names.add(match[1]);
        }
      }
    }
  };

  for (const dir of SCAN_DIRS) {
    walk(join(ROOT, dir));
  }
  return [...names].sort();
}

describe("bundled icons", () => {
  it("registers every icon the source references", () => {
    const used = iconNamesInSource();
    expect(used.length).toBeGreaterThan(20);

    // `getIcon` returns null for a name Iconify would have to fetch.
    const unregistered = used.filter((name) => getIcon(name) === null);
    // A name here means `npm run icons` needs re-running; until then that icon
    // would be fetched from a CDN at runtime.
    expect(unregistered).toEqual([]);
  });

  it("has no registry entries that nothing uses", () => {
    const used = new Set(iconNamesInSource());
    const orphans = Object.keys(BUNDLED_ICONS).filter((name) => !used.has(name));
    expect(orphans).toEqual([]);
  });

  it("gives every icon drawing data and dimensions", () => {
    for (const [name, icon] of Object.entries(BUNDLED_ICONS)) {
      expect(icon.body.length, `${name} has no body`).toBeGreaterThan(0);
      expect(icon.width, `${name} has no width`).toBeGreaterThan(0);
      expect(icon.height, `${name} has no height`).toBeGreaterThan(0);
    }
  });

  it("renders without touching fetch", async () => {
    const { render } = await import("@testing-library/react");
    const { Icon } = await import("@/components/ui/Icon");

    // If any icon were unregistered, Iconify would call fetch here.
    const originalFetch = globalThis.fetch;
    let fetchCalls = 0;
    globalThis.fetch = (async (...args: Parameters<typeof fetch>) => {
      fetchCalls += 1;
      return originalFetch(...args);
    }) as typeof fetch;

    try {
      const { container } = render(
        <>
          {Object.keys(BUNDLED_ICONS).map((name) => (
            <Icon key={name} name={name} />
          ))}
        </>,
      );
      expect(container.querySelectorAll("svg").length).toBe(Object.keys(BUNDLED_ICONS).length);
      expect(fetchCalls).toBe(0);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
