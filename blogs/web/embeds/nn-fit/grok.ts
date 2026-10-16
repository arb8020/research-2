// <nn-fit>'s grokking dataset, the page side: the config grok_train.py trains from, the code sent to the
// kernel, parsing the lines it prints, and the accuracy-vs-step plot. Remote only: the model (a 1-layer
// transformer on a + b mod p) needs the connected session. The wire format is documented once, at the top of
// grok_train.py.
import source from "./grok_train.py"; // the program's text, bundled at build time (esbuild text loader)
import type { StopReason } from "./remote";
import { int, num, numOrNaN, reason, record, str } from "./remote";
import type { JsonObject } from "../../json";

export const GROK_P = 113; // Nanda et al. 2023's modulus
export const TRAIN_FRACTIONS: readonly number[] = [0.3, 0.4, 0.5]; // 0.3 is Nanda's; more pairs grok in fewer steps
export const GROK_TICK_SECONDS = 0.1; // at most this long between ticks (more come at log-spaced steps early on)
export const MAX_GROK_POINTS = 20_000; // plotted ticks kept; past it every other one is dropped
// The model's size (grok_train.py: D_MODEL, D_MLP), for the readout before the remote says it (and to check it).
const D_MODEL = 128;
const D_MLP = 512;

// Parameters of grok_train.py's model for modulus p: embed (p + 1 tokens), positions, qkv, out, MLP in/out
// with biases, unembed.
export function grokParams(p: number): number {
  return (p + 1) * D_MODEL + 3 * D_MODEL + 3 * D_MODEL * D_MODEL + D_MODEL * D_MODEL
    + D_MODEL * D_MLP + D_MLP + D_MLP * D_MODEL + D_MODEL + D_MODEL * p;
}

// Training pairs out of p^2 (grok_train.py: make_data rounds the same way).
export const grokTrainPairs = (p: number, fraction: number): number => Math.round(fraction * p * p);

export const GROK_MODEL = `1-layer transformer (d ${String(D_MODEL)}, 4 heads, MLP ${String(D_MLP)}) · AdamW lr 1e-3, weight decay 1`;

// The JSON grok_train.py parses (field names are its).
export interface GrokConfig {
  readonly run: string;
  readonly p: number;
  readonly train_fraction: number;
  readonly split_seed: number;
  readonly init_seed: number;
  readonly step: number;
  readonly seconds: number;
  readonly max_steps: number;
  readonly max_seconds: number;
  readonly tick_seconds: number;
}

// The Python the kernel runs: the program in its own namespace, then run(config, runs). `runs` is a kernel
// global the program keeps its weights in between Train presses (a run continues where it stopped).
export function grokCode(config: GrokConfig): string {
  return [
    `_nn_fit_grok_runs = globals().setdefault("_nn_fit_grok_runs", {})`,
    `_nn_fit = {"__name__": "nn_fit_grok"}`,
    `exec(compile(${JSON.stringify(source)}, "grok_train.py", "exec"), _nn_fit)`,
    `try:`,
    `    _nn_fit["run"](${JSON.stringify(JSON.stringify(config))}, _nn_fit_grok_runs)`,
    `finally:`,
    `    del _nn_fit`,
  ].join("\n");
}

// One point of the curve: the metrics after `step` steps.
export interface GrokPoint {
  readonly step: number;
  readonly seconds: number; // training time when it was measured
  readonly loss: number; // training pairs (NaN if it diverged)
  readonly accuracy: number;
  readonly testLoss: number; // the other pairs
  readonly testAccuracy: number;
}

export type GrokLine =
  | {
    readonly kind: "start"; readonly device: string; readonly deviceName: string; readonly torch: string;
    readonly params: number; readonly train: number; readonly test: number;
  }
  | ({ readonly kind: "tick" } & GrokPoint)
  | { readonly kind: "end"; readonly reason: StopReason; readonly step: number; readonly seconds: number };

function fraction(obj: JsonObject, key: string, where: string): number {
  const v = num(obj, key, where);
  if (v < 0 || v > 1) throw new Error(`${where}: ${key} must be in 0..1`);
  return v;
}

// Parse one line, or throw with what was wrong (the line crossed a network).
export function parseGrokLine(text: string): GrokLine {
  const where = `grok line ${text.length > 80 ? `${text.slice(0, 80)}…` : text}`;
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new Error(`${where}: not JSON`);
  }
  const obj = record(raw, where);
  switch (obj["kind"]) {
    case "start":
      return {
        kind: "start", device: str(obj, "device", where), deviceName: str(obj, "device_name", where), torch: str(obj, "torch", where),
        params: int(obj, "params", where), train: int(obj, "train", where), test: int(obj, "test", where),
      };
    case "tick":
      return {
        kind: "tick", step: int(obj, "step", where), seconds: num(obj, "seconds", where), loss: numOrNaN(obj["loss"], where),
        accuracy: fraction(obj, "accuracy", where), testLoss: numOrNaN(obj["test_loss"], where), testAccuracy: fraction(obj, "test_accuracy", where),
      };
    case "end":
      return { kind: "end", reason: reason(obj["reason"], where), step: int(obj, "step", where), seconds: num(obj, "seconds", where) };
    default:
      throw new Error(`${where}: unknown kind ${JSON.stringify(obj["kind"])}`);
  }
}

// Append a tick's point, keeping at most MAX_GROK_POINTS: when full, every other point goes (the first and the
// newest stay), so the curve keeps its shape at half the resolution.
export function addPoint(points: GrokPoint[], point: GrokPoint): GrokPoint[] {
  const last = points.at(-1);
  if (last !== undefined && point.step < last.step) throw new Error(`grok tick at step ${String(point.step)} after step ${String(last.step)}`);
  const kept = points.length < MAX_GROK_POINTS ? points : points.filter((_, i) => i % 2 === 0);
  kept.push(point);
  return kept;
}

export const GROKKED = 0.95; // test accuracy that counts as generalised

// The first point past GROKKED test accuracy, or null.
export const grokked = (points: readonly GrokPoint[]): GrokPoint | null => points.find((p) => p.testAccuracy > GROKKED) ?? null;

// --- the plot: train and test accuracy against step, log x ---

export interface GrokColors {
  readonly fg: string;
  readonly muted: string;
  readonly rule: string;
  readonly train: string;
  readonly test: string;
}

const MIN_DECADES = 3; // the x axis starts at 1..1000 steps and grows a decade at a time
const PAD = { left: 40, right: 12, top: 12, bottom: 24 }; // CSS px around the plot area, for the axis labels

const stepLabel = (decade: number): string => (decade >= 6 ? `${String(10 ** (decade - 6))}M` : decade >= 3 ? `${String(10 ** (decade - 3))}k` : String(10 ** decade));

// Decades on the x axis: enough to hold `maxStep`, at least MIN_DECADES.
export const grokDecades = (maxStep: number): number => Math.max(MIN_DECADES, Math.ceil(Math.log10(Math.max(1, maxStep))));

// Points at step 0 have no place on a log axis: the curve starts at step 1.
export function paintGrok(ctx: CanvasRenderingContext2D, w: number, h: number, points: readonly GrokPoint[], c: GrokColors): void {
  const decades = grokDecades(points.at(-1)?.step ?? 1);
  const plotW = w - PAD.left - PAD.right;
  const plotH = h - PAD.top - PAD.bottom;
  const px = (step: number): number => PAD.left + (Math.log10(step) / decades) * plotW;
  const py = (acc: number): number => PAD.top + (1 - acc) * plotH;

  ctx.lineWidth = 1;
  ctx.strokeStyle = c.rule;
  ctx.fillStyle = c.muted;
  ctx.font = "11px ui-monospace, monospace";
  ctx.beginPath();
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (const acc of [0, 0.5, 1]) {
    ctx.moveTo(PAD.left, py(acc)); ctx.lineTo(w - PAD.right, py(acc));
    ctx.fillText(`${String(acc * 100)}%`, PAD.left - 6, py(acc));
  }
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let d = 0; d <= decades; d++) {
    ctx.moveTo(px(10 ** d), PAD.top); ctx.lineTo(px(10 ** d), h - PAD.bottom);
    ctx.fillText(stepLabel(d), px(10 ** d), h - PAD.bottom + 6);
  }
  ctx.stroke();

  const plotted = points.filter((p) => p.step >= 1);
  for (const [key, colour] of [["accuracy", c.train], ["testAccuracy", c.test]] as const) {
    ctx.strokeStyle = colour;
    ctx.lineWidth = 2;
    ctx.beginPath();
    plotted.forEach((p, i) => {
      if (i === 0) ctx.moveTo(px(p.step), py(p[key])); else ctx.lineTo(px(p.step), py(p[key]));
    });
    ctx.stroke();
  }
}
