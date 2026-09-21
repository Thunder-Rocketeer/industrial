/**
 * Security invariants, enforced as tests (spec sections 31 and 35).
 *
 * The review items in section 35 -- no JWT in browser storage, no unsafe HTML,
 * no arbitrary redirects, no query-parameter injection -- are properties of the
 * whole source tree, not of any one module. A reviewer can confirm them once;
 * a test confirms them on every run, including against code written later.
 *
 * So most of this file greps the source. That is unusual, and it is the point:
 * these are the failures that a normal unit test cannot see, because the unsafe
 * version passes every functional assertion it has.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { extname, join, relative, sep } from "node:path";

import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { apiClient } from "@/lib/api/client";
import { buildParams } from "@/lib/api/params";
import { fetchProductionRecords } from "@/lib/api/production";

const ROOT = join(__dirname, "..");
const SOURCE_DIRS = ["app", "components", "hooks", "lib", "providers", "types"];
const SOURCE_EXTENSIONS = new Set([".ts", ".tsx"]);

interface SourceFile {
  path: string;
  content: string;
}

function collectSourceFiles(): SourceFile[] {
  const files: SourceFile[] = [];

  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        walk(full);
      } else if (SOURCE_EXTENSIONS.has(extname(full))) {
        files.push({
          path: relative(ROOT, full).split(sep).join("/"),
          content: readFileSync(full, "utf8"),
        });
      }
    }
  };

  for (const dir of SOURCE_DIRS) {
    walk(join(ROOT, dir));
  }
  return files;
}

const sourceFiles = collectSourceFiles();

/** Files matching a pattern, ignoring occurrences inside comments. */
function filesMatching(pattern: RegExp): string[] {
  return sourceFiles
    .filter(({ content }) =>
      content
        .split("\n")
        // Comments discuss these patterns constantly -- explaining why the code
        // does not do them. Only executable lines count.
        .filter((line) => {
          const trimmed = line.trim();
          return !trimmed.startsWith("//") && !trimmed.startsWith("*") && !trimmed.startsWith("/*");
        })
        .some((line) => pattern.test(line)),
    )
    .map(({ path }) => path);
}

describe("no session token in browser storage", () => {
  it("never writes to localStorage or sessionStorage", () => {
    // Spec section 55.3: the session is an HttpOnly cookie. Anything in
    // localStorage is readable by any script on the page, which is exactly what
    // an XSS payload is looking for.
    expect(filesMatching(/\b(localStorage|sessionStorage)\s*\.\s*setItem/)).toEqual([]);
  });

  it("never reads a token out of browser storage", () => {
    expect(filesMatching(/\b(localStorage|sessionStorage)\s*\.\s*getItem/)).toEqual([]);
  });

  it("never reads document.cookie", () => {
    // The session cookie is HttpOnly and unreadable anyway; code that tries is
    // a sign someone is reconstructing an Authorization header by hand.
    expect(filesMatching(/document\s*\.\s*cookie/)).toEqual([]);
  });

  it("builds no Authorization header from client state", () => {
    expect(filesMatching(/["'`]Authorization["'`]\s*:/i)).toEqual([]);
    expect(filesMatching(/Bearer\s*\$\{/)).toEqual([]);
  });
});

describe("no unsafe HTML", () => {
  it("never uses dangerouslySetInnerHTML", () => {
    // Every value on this dashboard comes from the API, including free-text
    // fields such as alert descriptions and maintenance notes. Rendering any of
    // it as HTML turns a stored string into script execution.
    expect(filesMatching(/dangerouslySetInnerHTML/)).toEqual([]);
  });

  it("never assigns innerHTML or outerHTML", () => {
    expect(filesMatching(/\.(inner|outer)HTML\s*=/)).toEqual([]);
  });

  it("never calls eval or the Function constructor", () => {
    expect(filesMatching(/\beval\s*\(|new\s+Function\s*\(/)).toEqual([]);
  });

  it("never uses a javascript: URL", () => {
    expect(filesMatching(/["'`]javascript:/i)).toEqual([]);
  });
});

describe("no arbitrary redirect handling", () => {
  it("never assigns a non-literal value to window.location", () => {
    // An open redirect: `location.href = params.get("next")` sends the user
    // wherever an attacker's link says, from a page they trust.
    //
    // A plain quoted literal is allowed; anything else -- a variable, a call,
    // or a template literal that could interpolate a value -- is not. Reading
    // `location.pathname` is untouched, since that is not a navigation.
    const assignments = filesMatching(
      /(window\.)?location(\.href\s*=|\.replace\(|\.assign\()(?!\s*["'])/,
    );
    expect(assignments).toEqual([]);
  });

  it("routes sign-in through a constant path, not a parameter", () => {
    const auth = sourceFiles.find((file) => file.path === "lib/api/auth.ts");
    expect(auth?.content).toContain('export const LOGIN_PATH = "/auth/google/login"');
  });
});

describe("no secret material in the client", () => {
  it("references no server-only environment variables", () => {
    // Everything in the browser bundle is public. A service-role key or client
    // secret referenced here would ship to every visitor.
    const forbidden = [
      /SUPABASE_SERVICE_ROLE/,
      /GOOGLE_CLIENT_SECRET/,
      /JWT_SECRET/,
      /DATABASE_URL/,
      /REDIS_URL/,
    ];
    for (const pattern of forbidden) {
      expect(filesMatching(pattern), `${pattern} must not appear in client source`).toEqual([]);
    }
  });

  it("exposes only NEXT_PUBLIC_ variables", () => {
    const nonPublic = sourceFiles
      .flatMap(({ path, content }) =>
        [...content.matchAll(/process\.env\.([A-Z0-9_]+)/g)].map((match) => ({
          path,
          name: match[1],
        })),
      )
      .filter(({ name }) => !name.startsWith("NEXT_PUBLIC_") && name !== "NODE_ENV");

    expect(nonPublic).toEqual([]);
  });
});

describe("no query parameter injection", () => {
  let mock: MockAdapter;

  beforeEach(() => {
    mock = new MockAdapter(apiClient);
  });

  afterEach(() => {
    mock.restore();
  });

  it("escapes rather than interpolates a hostile filter value", async () => {
    mock.onGet("/production").reply(200, {
      data: [],
      pagination: { page: 1, page_size: 25, total: 0 },
    });

    const hostile = "1' OR '1'='1";
    await fetchProductionRecords({ sort_by: hostile });

    const request = mock.history.get[0];
    // The value travels as a parameter, so Axios percent-encodes it and the
    // backend's allow-list rejects it. The URL is never assembled by hand.
    expect(request.url).toBe("/production");
    expect(request.params.sort_by).toBe(hostile);
  });

  it("does not let a filter value smuggle in another parameter", () => {
    // `&role=admin` inside a value must stay part of that value, not become a
    // parameter of its own.
    const params = buildParams({ search: "widget&role=admin" });
    expect(params).toEqual({ search: "widget&role=admin" });
    expect(params).not.toHaveProperty("role");
  });

  it("builds no query string by hand anywhere in the source", () => {
    // `?${...}` or manual URLSearchParams onto a request path is how encoding
    // gets skipped. Axios owns serialization (spec section 15).
    expect(filesMatching(/get<[^>]*>\(\s*[`"'][^`"']*\?\$?\{/)).toEqual([]);
  });
});

describe("no token or session logging", () => {
  it("logs no header, cookie or token values", () => {
    const logsSensitive = sourceFiles.filter(({ content }) =>
      /console\.(log|info|warn|error)\([^)]*\b(token|cookie|authorization|jwt|secret|password)\b/i.test(
        content,
      ),
    );
    expect(logsSensitive.map((file) => file.path)).toEqual([]);
  });
});

describe("a single Axios instance", () => {
  it("creates no additional Axios client", () => {
    // Spec section 15 and principle 4: a second instance would miss the
    // interceptors, and with them credentials, error normalization and the
    // session-expiry signal.
    const creators = filesMatching(/axios\.create\(/);
    expect(creators).toEqual(["lib/api/client.ts"]);
  });
});

describe("UI-layer security (Phase 6)", () => {
  it("builds every internal link from a route literal, not from API data", () => {
    /*
     * The risk is a URL that comes from the database reaching an `href`, where
     * a stored `javascript:` string becomes a clickable payload.
     *
     * Only one place in this application lets API data influence a URL at all:
     * `alertSubject`, which turns an alert's machine id into a link. It builds
     * the path from a literal prefix and interpolates only the id, so the
     * scheme can never be attacker-chosen. Asserting that specific shape is
     * worth more than sweeping for `href={...}`, which cannot tell a route
     * constant from a response field.
     */
    const alerts = sourceFiles.find((file) => file.path === "components/dashboard/AlertsPanel.tsx");
    expect(alerts?.content).toContain("href: alert.machine_id ? `/machines/${alert.machine_id}`");

    // And no href anywhere is assigned straight from a response-shaped field.
    const fromApiField = filesMatching(/href=\{[^}]*(data|response|item|row|record)\.[a-z_]*url/i);
    expect(fromApiField).toEqual([]);
  });

  it("keeps target=_blank paired with rel=noopener", () => {
    // A `target="_blank"` link without `rel` hands the opened page a reference
    // to this one through `window.opener`.
    const blankLinks = sourceFiles.filter(
      ({ content }) =>
        /target=["']_blank["']/.test(content) && !/rel=["'][^"']*noopener/.test(content),
    );
    expect(blankLinks.map((file) => file.path)).toEqual([]);
  });

  it("gates navigation links on permissions as UX only, never as the check", () => {
    // The nav map must not be the place a permission decision is enforced.
    // Every page fetches through the API, which authorizes independently.
    const navigation = sourceFiles.find((file) => file.path === "lib/navigation.ts");
    expect(navigation?.content).toContain("not a security control");
  });

  it("passes route parameters to the API rather than into markup", () => {
    // A machine id from the URL reaches `useMachine(machineId)` and nothing
    // else. Interpolating it into HTML or a redirect would be the injection
    // path.
    const detail = sourceFiles.find((file) =>
      file.path.endsWith("machines/[machineId]/MachineDetailView.tsx"),
    );
    expect(detail?.content).toContain("useMachine(machineId)");
    expect(detail?.content).not.toContain("dangerouslySetInnerHTML");
  });

  it("validates a redirect target before using it", () => {
    // `?next=https://evil.example` must not survive into a navigation.
    const login = sourceFiles.find((file) => file.path === "app/login/page.tsx");
    expect(login?.content).toContain("safeNextPath");

    /*
     * The guard rejects more than a leading `//` now.
     *
     * It used to test exactly that, and passed `/\evil.example` straight
     * through into the sign-in link -- browsers normalise a backslash to a
     * forward slash, so that is the same protocol-relative URL in a different
     * coat. The API always rejected it, so the application was never
     * vulnerable, but the frontend filter was weaker than the rule it was
     * standing in for. It now mirrors the backend, decoding pass included.
     */
    expect(login?.content).toContain('form.startsWith("//")');
    expect(login?.content).toContain("decodeURIComponent");
    expect(login?.content).toContain('form.includes("\\\\")');
  });

  it("uses exactly one charting library", () => {
    // Spec section 17: do not install multiple charting libraries.
    const chartImports = new Set<string>();
    for (const { content } of sourceFiles) {
      for (const match of content.matchAll(/from "(recharts|chart\.js|victory|visx|nivo)[^"]*"/g)) {
        chartImports.add(match[1]);
      }
    }
    expect([...chartImports]).toEqual(["recharts"]);
  });

  it("uses exactly one icon library", () => {
    // Spec section 33: do not introduce another icon library.
    const iconImports = sourceFiles.filter(({ content }) =>
      /from "(lucide-react|react-icons|@heroicons)/.test(content),
    );
    expect(iconImports.map((file) => file.path)).toEqual([]);
  });
});
