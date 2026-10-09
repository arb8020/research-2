// The two datasets: a spiral (2D, two classes) and a reader-drawn function (1D regression). No DOM.
//
// Points live in plot coordinates, [-1, 1] on every axis. The network sees inputs multiplied by
// INPUT_SCALE: with inputs in [-1, 1], Adam often sat on the best straight line for hundreds of steps
// before bending (see the sweep in the nn-fit report); [-3, 3] fits both datasets quickly at lr 0.03.
import type { Batch, Rng } from "./mlp";
import { get } from "./mlp";

export const INPUT_SCALE = 3;

// Two interleaved spirals, ported from TensorFlow Playground's classifySpiralData
// (github.com/tensorflow/playground, src/dataset.ts, Apache-2.0, Copyright 2016 Google Inc.).
// Changes: labels are 1/0 instead of 1/-1, the noise comes from a seeded rng, and coordinates are
// divided by SPIRAL_RADIUS so the points sit in [-1, 1]^2 (the playground plots them in [-6, 6]^2),
// then multiplied by INPUT_SCALE (the returned batch holds network inputs).
export const SPIRAL_RADIUS = 5;

export function spiral(perClass: number, noise: number, rng: Rng): Batch {
  const x = new Float64Array(2 * perClass * 2);
  const y = new Float64Array(2 * perClass);
  const uniform = (): number => 2 * rng() - 1;
  let s = 0;
  for (const [deltaT, label] of [[0, 1], [Math.PI, 0]] as const) {
    for (let i = 0; i < perClass; i++) {
      const r = (i / perClass) * SPIRAL_RADIUS;
      const t = ((1.75 * i) / perClass) * 2 * Math.PI + deltaT;
      x[2 * s] = ((r * Math.sin(t) + uniform() * noise) / SPIRAL_RADIUS) * INPUT_SCALE;
      x[2 * s + 1] = ((r * Math.cos(t) + uniform() * noise) / SPIRAL_RADIUS) * INPUT_SCALE;
      y[s] = label;
      s++;
    }
  }
  return { n: s, x, y };
}

// A drawn function y(x) on x, y in [-1, 1]: one y per x column, NaN where nothing is drawn yet.
// One y per column is what makes the drawing a function: drawing over a column overwrites it.
export type DrawBuffer = Float64Array;

export const makeDrawBuffer = (columns: number): DrawBuffer => new Float64Array(columns).fill(NaN);

// Centre of column i, in [-1, 1].
export const columnX = (columns: number, i: number): number => -1 + (2 * (i + 0.5)) / columns;

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

export function columnAt(columns: number, x: number): number {
  return clamp(Math.floor(((x + 1) / 2) * columns), 0, columns - 1);
}

export interface Point {
  readonly x: number;
  readonly y: number;
}

// Paint the stroke segment from -> to into `buf` (in place). Every column the segment crosses gets a y,
// linearly interpolated between the two ends, so a fast stroke with far-apart pointer samples still
// leaves no gaps. `from` null means the stroke starts at `to`.
export function paintStroke(buf: DrawBuffer, from: Point | null, to: Point): void {
  const columns = buf.length;
  const start = from ?? to;
  const c0 = columnAt(columns, start.x);
  const c1 = columnAt(columns, to.x);
  const y0 = clamp(start.y, -1, 1);
  const y1 = clamp(to.y, -1, 1);
  const step = c1 >= c0 ? 1 : -1;
  for (let c = c0; ; c += step) {
    const t = c1 === c0 ? 1 : (c - c0) / (c1 - c0);
    buf[c] = y0 + t * (y1 - y0);
    if (c === c1) break;
  }
}

export function filledColumns(buf: DrawBuffer): number {
  return buf.reduce((n, y) => (Number.isNaN(y) ? n : n + 1), 0);
}

// Training samples: one (x * INPUT_SCALE, y) per drawn column.
export function drawSamples(buf: DrawBuffer): Batch {
  const n = filledColumns(buf);
  const x = new Float64Array(n);
  const y = new Float64Array(n);
  let s = 0;
  for (let c = 0; c < buf.length; c++) {
    const v = get(buf, c);
    if (Number.isNaN(v)) continue;
    x[s] = columnX(buf.length, c) * INPUT_SCALE;
    y[s] = v;
    s++;
  }
  return { n, x, y };
}

// A wiggly example curve, so keyboard and first-time readers have something to fit without drawing.
export function fillExample(buf: DrawBuffer): void {
  for (let c = 0; c < buf.length; c++) {
    const x = columnX(buf.length, c);
    buf[c] = 0.55 * Math.sin(2.5 * Math.PI * x) + 0.25 * x;
  }
}

// Undrawn column ranges [from, to] (inclusive), left to right. Training needs none: the drawn
// function must span the whole x axis, otherwise the net is free to do anything over a gap.
export function gaps(buf: DrawBuffer): { from: number; to: number }[] {
  const out: { from: number; to: number }[] = [];
  let start = -1;
  buf.forEach((y, c) => {
    const empty = Number.isNaN(y);
    if (empty && start < 0) start = c;
    if (!empty && start >= 0) { out.push({ from: start, to: c - 1 }); start = -1; }
  });
  if (start >= 0) out.push({ from: start, to: buf.length - 1 });
  return out;
}

// "left edge to 40%, 55–70%, 90% to right edge": short, for the hint line. At most 3 ranges named.
export function describeGaps(buf: DrawBuffer): string {
  const columns = buf.length;
  const num = (c: number): string => String(Math.round((c / columns) * 100));
  const pct = (c: number): string => `${num(c)}%`;
  const ranges = gaps(buf);
  if (ranges.length === 1 && ranges[0]?.from === 0 && ranges[0].to === columns - 1) return "everything";
  const named = ranges.slice(0, 3).map(({ from, to }) => {
    if (from === 0) return `left edge to ${pct(to + 1)}`;
    if (to === columns - 1) return `${pct(from)} to right edge`;
    return `${num(from)}–${pct(to + 1)}`;
  });
  if (ranges.length > 3) named.push(`${String(ranges.length - 3)} more`);
  return named.join(", ");
}
