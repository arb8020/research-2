/**
 * The Vega config half of the `paper` skin (DESIGN.md "Register > Skin").
 *
 * Vega renders into SVG *attributes*, not CSS-styled classes, so `var(--ink)`
 * on a `stroke` is simply ignored — a Vega config must hold literal values. So
 * this file READS the live CSS variables and spells them into Vega's config
 * keys. It holds no palette of its own: `src/theme.css` is the one writer of
 * the palette, and a literal here would be a second copy that drifts (it did:
 * `muted` was `#6b6f6b` here and `#777b75` there).
 *
 * `buildVegaTheme(tokens)` stays pure so tests can drive it with tokens they
 * name themselves; `resolveVegaTheme(root)` is the only production entry point.
 *
 * The CANVAS is CSS's, not Vega's: `background: "transparent"` and
 * `view.stroke: null` mean the panel's own `--surface` shows through, so there
 * is no third place that decides what color a chart's paper is.
 *
 * Hairlines, not boxes: no chart border, no tick marks, a single pale grid.
 */

import type { Config } from "vega-lite";

/** The CSS custom properties `resolveVegaTheme` reads, per token. */
const CSS_VARS = {
  ink: "--ink",
  grid: "--grid",
  muted: "--muted",
  sans: "--font-ui",
  mono: "--font-mono",
} as const;

/** The CSS variables holding the series palette, in assignment order. */
const CSS_SERIES_VARS = ["--blue", "--green", "--violet", "--amber", "--red"] as const;

export interface VegaTokens {
  readonly ink: string;
  readonly grid: string;
  readonly muted: string;
  readonly sans: string;
  readonly mono: string;
  /**
   * Series palette. Non-empty by construction so `series[0]` — the default
   * single-series color — needs no `!` and no "should never happen" fallback.
   */
  readonly series: readonly [string, ...string[]];
}

export function buildVegaTheme(tokens: VegaTokens): Config {
  const T = tokens;
  return {
    // CSS owns the canvas. A Vega background would paint over the panel's own
    // --surface and make the chart a box inside the paper.
    background: "transparent",
    font: T.sans,
    padding: 8,
    view: { stroke: null, continuousWidth: 320, continuousHeight: 160 },
    axis: {
      domain: false,
      ticks: false,
      labelPadding: 6,
      labelFont: T.mono,
      labelFontSize: 10,
      labelColor: T.muted,
      titleFont: T.sans,
      titleFontSize: 11,
      titleFontWeight: 500,
      titleColor: T.muted,
      titlePadding: 8,
      gridColor: T.grid,
      gridWidth: 1,
      tickCount: 5,
    },
    axisX: { grid: false },
    axisY: { grid: true },
    legend: {
      labelFont: T.sans,
      labelFontSize: 11,
      labelColor: T.ink,
      titleFont: T.sans,
      titleFontSize: 11,
      titleColor: T.muted,
      symbolType: "stroke",
      orient: "top-right",
      direction: "vertical",
    },
    title: {
      font: T.sans,
      fontSize: 12,
      fontWeight: 600,
      color: T.ink,
      anchor: "start",
    },
    line: { strokeWidth: 1.5, color: T.series[0] },
    point: { size: 18, filled: true, color: T.series[0] },
    rect: { color: T.series[0] },
    bar: { color: T.series[0] },
    area: { color: T.series[0], opacity: 0.2 },
    rule: { color: T.muted },
    range: { category: [...T.series], ordinal: [...T.series] },
  };
}

/**
 * The config with every token taken from `root`'s computed style.
 *
 * There is no literal fallback palette: a token the app has not defined reads
 * as the empty string, and Vega treats an empty color the way CSS does — as
 * "not set" — which is visibly wrong and therefore findable, unlike a
 * hardcoded paper value that looks right on a dark page. theme.css defines
 * them all; if it did not, that is the bug to fix.
 *
 * Read once per embed rather than watched: a theme switch remounts the view
 * slots (App's theme is part of their remount key), so each embed reads the
 * palette that is live at the moment it is built.
 */
export function resolveVegaTheme(root: Element): Config {
  const style = getComputedStyle(root);
  const read = (cssVar: string): string => style.getPropertyValue(cssVar).trim();
  const [head, ...tail] = CSS_SERIES_VARS;
  return buildVegaTheme({
    ink: read(CSS_VARS.ink),
    grid: read(CSS_VARS.grid),
    muted: read(CSS_VARS.muted),
    sans: read(CSS_VARS.sans),
    mono: read(CSS_VARS.mono),
    // Head-then-tail rather than `.map()`, because `.map()` widens the tuple to
    // `string[]` and loses the non-emptiness the type requires.
    series: [read(head), ...tail.map(read)],
  });
}
