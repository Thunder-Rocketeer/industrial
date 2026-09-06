import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/**
 * Vitest configuration for the frontend data layer (spec section 31).
 *
 * No Vite React plugin: nothing here needs Fast Refresh or the Babel pipeline,
 * and esbuild's automatic JSX runtime compiles the component tests on its own.
 * `tsconfig.json` sets `jsx: "preserve"` for Next.js, which esbuild would
 * otherwise carry through as raw JSX, so the transform is named explicitly.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  esbuild: {
    jsx: "automatic",
  },
  test: {
    // Node by default: booting jsdom costs about half a minute on this machine,
    // and most of these tests are pure functions and Axios calls that never
    // touch a DOM. The files that render components opt in with a
    // `@vitest-environment jsdom` docblock at the top.
    environment: "node",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    // Next.js's own build output and dependencies are not under test.
    exclude: ["node_modules/**", ".next/**"],
    restoreMocks: true,
  },
});
