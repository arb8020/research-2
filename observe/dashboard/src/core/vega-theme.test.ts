/**
 * The Vega theme's two claims:
 *
 *  1. CSS owns the canvas — the config paints no background and no view border,
 *     so a panel's own `--surface` is what shows through.
 *  2. There is ONE palette writer. This module holds no literal colors, so the
 *     `muted` drift (`#6b6f6b` here vs `#777b75` in theme.css) cannot recur.
 */

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { VegaTokens } from "./vega-theme.ts";
import { buildVegaTheme } from "./vega-theme.ts";

/** A palette a test names itself — `buildVegaTheme` is pure, so this is enough. */
const TOKENS: VegaTokens = {
  ink: "#111111",
  grid: "#222222",
  muted: "#333333",
  sans: "TestSans",
  mono: "TestMono",
  series: ["#aa0000", "#00bb00"],
};

describe("buildVegaTheme", () => {
  it("paints no canvas and no view border — CSS owns those", () => {
    const config = buildVegaTheme(TOKENS);
    expect(config.background).toBe("transparent");
    expect(config.view?.stroke).toBeNull();
  });

  it("threads the tokens it was given into Vega's config keys", () => {
    const config = buildVegaTheme(TOKENS);
    expect(config.axis?.gridColor).toBe("#222222");
    expect(config.axis?.labelColor).toBe("#333333");
    expect(config.axis?.labelFont).toBe("TestMono");
    expect(config.title?.color).toBe("#111111");
    expect(config.line).toMatchObject({ color: "#aa0000" });
    expect(config.range?.category).toEqual(["#aa0000", "#00bb00"]);
  });

  it("holds no hex literal of its own: theme.css is the one palette writer", () => {
    const source = readFileSync(new URL("./vega-theme.ts", import.meta.url), "utf8");
    // Comments are allowed to quote the old drifted values as history; code is not.
    const code = source
      .replaceAll(/\/\*[\s\S]*?\*\//g, "")
      .replaceAll(/\/\/.*$/gm, "");
    expect(code.match(/#[0-9a-fA-F]{3,8}\b/g)).toBeNull();
  });
});
