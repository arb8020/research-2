import type { Batch, Rng } from "./mlp";
import { get } from "./mlp";

export const INPUT_SCALE = 3;

// Two interleaved spirals, ported from TensorFlow Playground's classifySpiralData
// (github.com/tensorflow/playground, src/dataset.ts, Apache-2.0, Copyright 2016 Google Inc.).
// Changes: labels are 1/0 instead of 1/-1; `n` is the TOTAL point count with labels alternating 1, 0, 1, ...;
// each point sits at a random position u along its arm (the playground spaces them evenly, i/n), so few
// points means sparse random coverage rather than a coarse grid; the noise comes from a seeded rng; and
// coordinates are divided by SPIRAL_RADIUS so the points sit in [-1, 1]^2 (the playground plots them in
// [-6, 6]^2), then multiplied by INPUT_SCALE (the returned batch holds network inputs).
export const SPIRAL_RADIUS = 5;

export function spiral(n: number, jitterInSpiralUnits: number, rng: Rng): Batch {
  const x = new Float64Array(2 * n);
  const y = new Float64Array(n);
  for (let s = 0; s < n; s++) {
    const label = s % 2 === 0 ? 1 : 0;
    const u = rng();
    const r = u * SPIRAL_RADIUS;
    const t = 1.75 * u * 2 * Math.PI + (label === 1 ? 0 : Math.PI);
    const nx = (2 * rng() - 1) * jitterInSpiralUnits;
    const ny = (2 * rng() - 1) * jitterInSpiralUnits;
    x[2 * s] = ((r * Math.sin(t) + nx) / SPIRAL_RADIUS) * INPUT_SCALE;
    x[2 * s + 1] = ((r * Math.cos(t) + ny) / SPIRAL_RADIUS) * INPUT_SCALE;
    y[s] = label;
  }
  return { n, x, y };
}

export const SAMPLE_COUNTS: readonly number[] = [4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512];

export type DrawBuffer = Float64Array;

export const makeDrawBuffer = (columns: number): DrawBuffer => new Float64Array(columns).fill(NaN);

export const columnX = (columns: number, i: number): number => -1 + (2 * (i + 0.5)) / columns;

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

export function columnAt(columns: number, x: number): number {
  return clamp(Math.floor(((x + 1) / 2) * columns), 0, columns - 1);
}

export interface Point {
  readonly x: number;
  readonly y: number;
}

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

export const MAX_WIGGLES = 20;
export const MAX_STAGES = 4;

export interface WaveParams {
  readonly wiggles: number;
  readonly roughness: number;
  readonly stages: number;
  readonly seed: number;
}

export interface WaveStage {
  readonly amp: readonly number[];
  readonly phase: readonly number[];
  readonly lo: number;
  readonly hi: number;
}

const RANGE_SAMPLES = 4096;

function rawStage(amp: readonly number[], phase: readonly number[], u: number): number {
  let s = 0;
  for (let k = 0; k < amp.length; k++) s += (amp[k] ?? 0) * Math.sin(Math.PI * (k + 1) * u + (phase[k] ?? 0));
  return s;
}

export function stageAt(stage: WaveStage, u: number): number {
  const span = stage.hi - stage.lo;
  return span > 0 ? (2 * (rawStage(stage.amp, stage.phase, u) - stage.lo)) / span - 1 : 0;
}

export function waveStages(p: WaveParams, rng: (seed: number) => Rng): WaveStage[] {
  const random = rng(p.seed);
  const stages: WaveStage[] = [];
  for (let i = 0; i < MAX_STAGES; i++) {
    const amp: number[] = [];
    const phase: number[] = [];
    for (let k = 1; k <= MAX_WIGGLES; k++) {
      amp.push(random() / k ** p.roughness);
      phase.push(2 * Math.PI * random());
    }
    if (i >= p.stages) continue;
    const a = amp.slice(0, p.wiggles), ph = phase.slice(0, p.wiggles);
    let lo = Infinity, hi = -Infinity;
    for (let j = 0; j <= RANGE_SAMPLES; j++) {
      const v = rawStage(a, ph, -1 + (2 * j) / RANGE_SAMPLES);
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
    }
    stages.push({ amp: a, phase: ph, lo, hi });
  }
  return stages;
}

export const waveAt = (stages: readonly WaveStage[], x: number): number => stages.reduce((u, s) => stageAt(s, u), x);

export function fillWave(buf: DrawBuffer, stages: readonly WaveStage[]): void {
  for (let c = 0; c < buf.length; c++) buf[c] = waveAt(stages, columnX(buf.length, c));
  let lo = Infinity, hi = -Infinity;
  for (const v of buf) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  const span = hi - lo;
  buf.forEach((v, c) => { buf[c] = span > 0 ? (2 * (v - lo)) / span - 1 : 0; });
}

export function waveFormula(p: WaveParams, stages: readonly WaveStage[]): string {
  const n = (v: number): string => v.toFixed(2);
  const names = stages.map((_, i) => `s${String(i + 1)}`);
  const lines = [`f(x) = ${names.reduce((inner, name) => `${name}(${inner})`, "x")}`];
  stages.forEach((s, i) => {
    const terms = s.amp.map((a, k) => `${n(a)}·sin(${k === 0 ? "" : String(k + 1)}πu + ${n(s.phase[k] ?? 0)})`);
    lines.push(`${names[i] ?? ""}(u) = rescale[${n(s.lo)}, ${n(s.hi)}]( ${terms.join(" + ")} )`);
  });
  lines.push(`a_k = r / k^${String(p.roughness)},  φ_k = 2π r',  r, r' uniform in [0, 1), seed ${String(p.seed)}`);
  lines.push("rescale[lo, hi](v) = 2(v − lo)/(hi − lo) − 1, so each stage spans [−1, 1]");
  return lines.join("\n");
}

export function valueAt(buf: DrawBuffer, x: number): number {
  const p = clamp(((x + 1) / 2) * buf.length - 0.5, 0, buf.length - 1);
  const i = Math.min(buf.length - 2, Math.floor(p));
  const t = p - i;
  return get(buf, i) * (1 - t) + get(buf, i + 1) * t;
}

export function curveSamples(buf: DrawBuffer, n: number, sigma: number, rng: Rng): Batch {
  const x = new Float64Array(n);
  const y = new Float64Array(n);
  for (let s = 0; s < n; s++) {
    const xs = 2 * rng() - 1;
    const z = Math.sqrt(-2 * Math.log(1 - rng())) * Math.cos(2 * Math.PI * rng());
    x[s] = xs * INPUT_SCALE;
    y[s] = valueAt(buf, xs) + sigma * z;
  }
  return { n, x, y };
}

export function completeCurve(buf: DrawBuffer): DrawBuffer | null {
  const drawn: number[] = [];
  buf.forEach((y, c) => { if (!Number.isNaN(y)) drawn.push(c); });
  const first = drawn[0];
  const last = drawn[drawn.length - 1];
  if (first === undefined || last === undefined) return null;
  const out = Float64Array.from(buf);
  out.fill(get(buf, first), 0, first);
  out.fill(get(buf, last), last + 1);
  for (let i = 0; i + 1 < drawn.length; i++) {
    const a = drawn[i] ?? 0, b = drawn[i + 1] ?? 0;
    const ya = get(buf, a), yb = get(buf, b);
    for (let c = a + 1; c < b; c++) out[c] = ya + ((c - a) / (b - a)) * (yb - ya);
  }
  return out;
}

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

export function describeGaps(buf: DrawBuffer): string {
  const columns = buf.length;
  const lo = (c: number): string => String(Math.floor((c / columns) * 100 + 1e-9));
  const hi = (c: number): string => String(Math.ceil((c / columns) * 100 - 1e-9));
  const ranges = gaps(buf);
  if (ranges.length === 1 && ranges[0]?.from === 0 && ranges[0].to === columns - 1) return "everything";
  const named = ranges.slice(0, 3).map(({ from, to }) => {
    if (from === 0) return `left edge to ${hi(to + 1)}%`;
    if (to === columns - 1) return `${lo(from)}% to right edge`;
    return `${lo(from)}–${hi(to + 1)}%`;
  });
  if (ranges.length > 3) named.push(`${String(ranges.length - 3)} more`);
  return named.join(", ");
}
