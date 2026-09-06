/**
 * Test environment setup.
 *
 * The public environment variables are set before any module loads, because
 * `lib/env.ts` validates them at import time and throws on a missing base URL.
 * Vitest evaluates setup files before the modules under test, which is what
 * makes this work.
 *
 * The values are deliberately not real: the Axios mock adapter intercepts every
 * request, so nothing here should ever reach a network.
 */
process.env.NEXT_PUBLIC_API_BASE_URL ??= "http://localhost:8000/api/v1";
process.env.NEXT_PUBLIC_API_TIMEOUT_MS ??= "15000";
process.env.NEXT_PUBLIC_APP_NAME ??= "Automobile Component Factory (test)";
process.env.NEXT_PUBLIC_APP_ENV ??= "development";
// Mocking is a development affordance, not a test mechanism: tests stub the
// Axios adapter directly so they control every response.
process.env.NEXT_PUBLIC_ENABLE_API_MOCKS = "false";
