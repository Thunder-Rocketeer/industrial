/**
 * Validated public environment configuration.
 *
 * Spec section 39: only browser-safe values belong here. Next.js inlines
 * `NEXT_PUBLIC_*` variables into the client bundle at build time, so anything
 * referenced in this module is publicly readable by design.
 *
 * The schema is evaluated once at module load. A misconfigured deployment fails
 * immediately with an actionable message rather than surfacing later as a
 * confusing runtime error deep inside the Axios client.
 *
 * Note: `process.env.NEXT_PUBLIC_*` must be referenced by its full literal name
 * for the Next.js compiler to substitute the value. Dynamic access such as
 * `process.env[key]` is not replaced and resolves to `undefined` in the browser.
 */
import { z } from "zod";

/**
 * Turn off Zod's JIT validator compiler, because the CSP forbids `eval`.
 *
 * Zod 4 compiles a schema into a specialised validator with `new Function(...)`
 * the first time it parses. Under `script-src` without `'unsafe-eval'` that call
 * is blocked. Zod does guard it -- it probes with `Function("")` and falls back
 * to an interpreted path if the probe throws -- but the probe *is* the forbidden
 * operation, so it still trips the policy: Chromium reported two
 * `script-src blocked eval` violations on every page that parses a schema
 * (/dashboard, /production, /analytics), traced to columns 7626 and 39841 of the
 * shared chunk, which are Zod's probe and its `compile()`.
 *
 * `jitless` is Zod's documented setting for environments that disallow `eval`.
 * Setting it means the compiler is never reached and nothing has to be caught.
 * Validation behaviour is identical; only the interpretation strategy changes,
 * and this module parses five values once at load, so the JIT was never earning
 * anything here.
 *
 * The alternative -- adding `'unsafe-eval'` to the policy -- would have relaxed
 * the CSP to accommodate a probe whose failure is already handled. The fix
 * belongs on this side of the boundary.
 *
 * This is the only module in the client bundle that imports Zod, and it is
 * imported by the root layout, so configuring it here covers the application.
 */
z.config({ jitless: true });

const clientEnvSchema = z.object({
  /**
   * Either an absolute URL (`http://localhost:8000/api/v1`, the local
   * development case) or a root-relative path (`/api/v1`) for deployments where
   * the API is served from the same origin as the frontend -- on Vercel the
   * backend service is routed under `/api` of the same domain. A same-origin
   * path is what lets one value serve production and every preview URL, and
   * `apiOriginForCsp` already reduces it to `'self'`.
   */
  NEXT_PUBLIC_API_BASE_URL: z
    .string()
    // `//host/path` is protocol-relative, i.e. cross-origin; only a true path
    // counts as same-origin.
    .refine((value) => /^\/(?!\/)/.test(value) || z.url().safeParse(value).success, {
      message:
        "NEXT_PUBLIC_API_BASE_URL must be an absolute URL or a root-relative path such as /api/v1",
    })
    .refine((value) => !value.endsWith("/"), {
      message: "NEXT_PUBLIC_API_BASE_URL must not end with a trailing slash",
    }),

  NEXT_PUBLIC_API_TIMEOUT_MS: z.coerce.number().int().positive().max(120_000).default(15_000),

  NEXT_PUBLIC_APP_NAME: z.string().min(1).default("Automobile Component Factory"),

  NEXT_PUBLIC_APP_ENV: z.enum(["development", "staging", "production"]).default("development"),

  /**
   * Serve API responses from local fixtures instead of the backend.
   *
   * Development only, opt-in, and off by default. Spec section 30: mock data
   * must never stand in for production data silently. Two independent
   * conditions must hold before a fixture is served -- this flag, and a
   * non-production build -- and `lib/api/mock/install.ts` refuses to install
   * the adapter when either is missing.
   */
  NEXT_PUBLIC_ENABLE_API_MOCKS: z
    .enum(["true", "false"])
    .default("false")
    .transform((value) => value === "true"),
});

export type ClientEnv = z.infer<typeof clientEnvSchema>;

function parseClientEnv(): ClientEnv {
  const result = clientEnvSchema.safeParse({
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
    NEXT_PUBLIC_API_TIMEOUT_MS: process.env.NEXT_PUBLIC_API_TIMEOUT_MS,
    NEXT_PUBLIC_APP_NAME: process.env.NEXT_PUBLIC_APP_NAME,
    NEXT_PUBLIC_APP_ENV: process.env.NEXT_PUBLIC_APP_ENV,
    NEXT_PUBLIC_ENABLE_API_MOCKS: process.env.NEXT_PUBLIC_ENABLE_API_MOCKS,
  });

  if (!result.success) {
    const issues = result.error.issues
      .map((issue) => `  - ${issue.path.join(".") || "(root)"}: ${issue.message}`)
      .join("\n");

    throw new Error(
      `Invalid frontend environment configuration.\n${issues}\n\n` +
        `Copy .env.example to .env.local and fill in the required values.`,
    );
  }

  return result.data;
}

export const env: ClientEnv = parseClientEnv();

export const isProduction = env.NEXT_PUBLIC_APP_ENV === "production";
export const isDevelopment = env.NEXT_PUBLIC_APP_ENV === "development";

/**
 * Whether API mocking may be installed at all.
 *
 * Both conditions are required, and neither is sufficient. `NODE_ENV` is set by
 * the build (`next build` makes it "production") and cannot be flipped by an
 * environment variable at runtime, so a production bundle cannot serve fixtures
 * even if someone sets the flag by mistake -- and the mock module is
 * tree-shaken out of that bundle entirely.
 */
export const apiMocksEnabled =
  process.env.NODE_ENV !== "production" && !isProduction && env.NEXT_PUBLIC_ENABLE_API_MOCKS;
