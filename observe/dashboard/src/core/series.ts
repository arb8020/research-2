/**
 * Pure projections of metric events into plottable series.
 *
 * `step` is not first-class (DESIGN.md): the caller names the x-axis, either an
 * attr name like "step" or the literal "ts".
 *
 * Judo (2026-09-17): `ema`, `emaStep`, `nearestIndex` and `niceTicks` lived here
 * to serve the hand-rolled canvas chart. Vega-Lite owns smoothing, tick choice
 * and hit-testing now, so they were deleted rather than kept as a second,
 * unused answer to the same questions. `toSeries` survives because the golden
 * cross-language pin projects through it.
 */

import type { Metric } from "./events.ts";

export interface Point {
  readonly x: number;
  readonly y: number;
}

/** A metric that could not be plotted on the requested x-axis, and why. */
export interface Unplottable {
  readonly metric: Metric;
  readonly reason: string;
}

export interface SeriesResult {
  /** series name -> points, ascending in x. */
  readonly series: Map<string, Point[]>;
  /** Nothing is dropped silently — everything unplottable is reported here. */
  readonly unplottable: Unplottable[];
}

/** The x-axis selector: the literal timestamp, or the name of an attr. */
export const TS_AXIS = "ts";

/**
 * Resolve one metric's x value on the named axis.
 * Returns a reason string instead of a number when it cannot be plotted.
 */
function resolveX(metric: Metric, x: string): number | string {
  if (x === TS_AXIS) return metric.ts;
  const raw = metric.attrs[x];
  if (raw === undefined) return `missing attr \`${x}\``;
  if (typeof raw !== "number") return `attr \`${x}\` is not a number`;
  if (!Number.isFinite(raw)) return `attr \`${x}\` is not finite`;
  return raw;
}

/**
 * Group metrics by name into x/y point arrays.
 *
 * Points come out sorted ascending in x, so the chart's binary-search
 * tooltip lookup is valid even if events arrive out of order.
 */
export function toSeries(metrics: readonly Metric[], x: string): SeriesResult {
  const series = new Map<string, Point[]>();
  const unplottable: Unplottable[] = [];

  for (const metric of metrics) {
    const resolved = resolveX(metric, x);
    if (typeof resolved === "string") {
      unplottable.push({ metric, reason: resolved });
      continue;
    }
    let points = series.get(metric.name);
    if (points === undefined) {
      points = [];
      series.set(metric.name, points);
    }
    points.push({ x: resolved, y: metric.value });
  }

  for (const points of series.values()) {
    points.sort((a, b) => a.x - b.x);
  }

  return { series, unplottable };
}
