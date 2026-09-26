import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Two projects, because the environments differ on purpose.
 *
 * core/ and views/ are pure by contract (DESIGN.md: "Pure functions have no
 * React/DOM imports") and run in node, so an accidental `document` reference in
 * core/ fails the suite rather than passing under a DOM that happened to be
 * there. src/app/** is React chrome and needs jsdom — without it there was no
 * DOM test at all, which is why a blank dashboard shipped green.
 *
 * server/ tests run under `bun test` (bun run test:server): they exercise
 * Bun.serve, which does not exist in vitest's Node runtime.
 */
export default defineConfig({
  test: {
    projects: [
      {
        test: {
          name: "core",
          include: ["src/core/**/*.test.ts", "src/views/**/*.test.ts"],
          exclude: ["src/views/**/*.dom.test.ts"],
          environment: "node",
        },
      },
      {
        // Views are imperative surfaces, not React, but a surface still owns
        // DOM — so its DOM tests need jsdom while its pure logic stays in the
        // node project above. `*.dom.test.ts` is the marker.
        test: {
          name: "views-dom",
          include: ["src/views/**/*.dom.test.ts"],
          environment: "jsdom",
        },
      },
      {
        plugins: [react()],
        test: {
          name: "app",
          include: ["src/app/**/*.test.{ts,tsx}"],
          environment: "jsdom",
        },
      },
    ],
  },
});
