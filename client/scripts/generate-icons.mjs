/**
 * Generate the bundled icon registry.
 *
 * WHY THIS EXISTS
 *
 * `@iconify/react` resolves an icon name by fetching it from
 * `api.iconify.design` at runtime, with fallbacks to two other public hosts.
 * That is convenient in a prototype and wrong for this application:
 *
 *   - it makes every icon on a factory dashboard depend on a third-party CDN
 *     being reachable, on a network that may well be segmented or offline;
 *   - it forces `connect-src https://api.iconify.design` (plus two fallback
 *     hosts) into the Content-Security-Policy, widening it for decoration;
 *   - it leaks the set of pages a user visits to a third party, since the
 *     icon requests are made per view.
 *
 * So the icons the application actually uses are extracted at build time and
 * committed as a plain data module. `@iconify/react` then finds every icon in
 * its local registry and never makes a network request. The two
 * `@iconify-json/*` packages stay devDependencies: their data is copied into
 * the generated file, and they are not part of the runtime bundle.
 *
 * USAGE
 *
 *   node scripts/generate-icons.mjs
 *
 * Run it after adding a new icon name to the source. The generated file lists
 * exactly the names found by scanning `components/`, `app/` and `lib/`, so an
 * icon that is no longer referenced drops out on the next run.
 */
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SCAN_DIRS = ["app", "components", "lib", "hooks"];
const OUTPUT = join(ROOT, "lib", "icons.generated.ts");

/** Every `"prefix:name"` string appearing in the source. */
function collectIconNames() {
  const names = new Set();
  const pattern = /"((?:mdi|logos):[a-z0-9-]+)"/g;

  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        walk(full);
      } else if ([".ts", ".tsx"].includes(extname(full))) {
        const content = readFileSync(full, "utf8");
        for (const match of content.matchAll(pattern)) {
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

/** Load an Iconify collection's raw JSON. */
function loadCollection(prefix) {
  const path = join(ROOT, "node_modules", `@iconify-json/${prefix}/icons.json`);
  return JSON.parse(readFileSync(path, "utf8"));
}

const names = collectIconNames();
const collections = new Map();
const icons = {};
const missing = [];

for (const name of names) {
  const [prefix, iconName] = name.split(":");
  if (!collections.has(prefix)) {
    collections.set(prefix, loadCollection(prefix));
  }
  const collection = collections.get(prefix);

  // Iconify aliases one name to another; resolve so the data is self-contained.
  const resolvedName = collection.aliases?.[iconName]?.parent ?? iconName;
  const data = collection.icons[resolvedName];

  if (!data) {
    missing.push(name);
    continue;
  }

  icons[name] = {
    body: data.body,
    width: data.width ?? collection.width ?? 24,
    height: data.height ?? collection.height ?? 24,
  };
}

if (missing.length > 0) {
  console.error(`Unknown icon names:\n  ${missing.join("\n  ")}`);
  process.exit(1);
}

const header = `/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Produced by \`node scripts/generate-icons.mjs\`, which extracts exactly the
 * icons referenced in the source from the \`@iconify-json/*\` devDependencies.
 *
 * This exists so the application makes no runtime request to
 * \`api.iconify.design\`: icons work offline, the Content-Security-Policy needs
 * no CDN exception for them, and no third party learns which pages are viewed.
 * See \`scripts/generate-icons.mjs\` for the full reasoning.
 *
 * ${names.length} icons.
 */

/** One icon's drawing data, in the shape \`@iconify/react\` expects. */
export interface BundledIcon {
  body: string;
  width: number;
  height: number;
}

export const BUNDLED_ICONS: Record<string, BundledIcon> = `;

writeFileSync(OUTPUT, `${header}${JSON.stringify(icons, null, 2)};\n`, "utf8");
console.log(`Wrote ${names.length} icons to lib/icons.generated.ts`);
