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

const clientEnvSchema = z.object({
  NEXT_PUBLIC_API_BASE_URL: z
    .url({ message: "NEXT_PUBLIC_API_BASE_URL must be a valid absolute URL" })
    .refine((value) => !value.endsWith("/"), {
      message: "NEXT_PUBLIC_API_BASE_URL must not end with a trailing slash",
    }),

  NEXT_PUBLIC_API_TIMEOUT_MS: z.coerce.number().int().positive().max(120_000).default(15_000),

  NEXT_PUBLIC_APP_NAME: z.string().min(1).default("Automobile Component Factory"),

  NEXT_PUBLIC_APP_ENV: z.enum(["development", "staging", "production"]).default("development"),
});

export type ClientEnv = z.infer<typeof clientEnvSchema>;

function parseClientEnv(): ClientEnv {
  const result = clientEnvSchema.safeParse({
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
    NEXT_PUBLIC_API_TIMEOUT_MS: process.env.NEXT_PUBLIC_API_TIMEOUT_MS,
    NEXT_PUBLIC_APP_NAME: process.env.NEXT_PUBLIC_APP_NAME,
    NEXT_PUBLIC_APP_ENV: process.env.NEXT_PUBLIC_APP_ENV,
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
