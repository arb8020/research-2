// <nn-fit>'s remote backend, the page side: the config remote_train.py trains from, the code sent to the
// kernel, and parsing the JSON lines it prints. No DOM, so it runs under node too (parity.ts).
// The wire format is documented once, at the top of remote_train.py.
import source from "./remote_train.py"; // the program's text, bundled at build time (esbuild text loader)
import type { Activation, Adam, Batch, Grads, Mlp, Task } from "./mlp";
import { INPUT_SCALE } from "./datasets";

// Plot grids the remote predicts on. The curve: points evenly across the plot's x (the browser samples every
// 2 CSS px, ~320 points at full width). The spiral heatmap: a square raster, coarser than the browser's (up to
// 128) because every tick carries it: 64 x 64 predictions are ~25 KB of JSON.
export const CURVE_POINTS = 321;
export const HEAT_GRID = 64;
export const TICK_SECONDS = 0.1; // at most 10 ticks a second
// Remote runs always stop: "off" budgets become these (the widget shows them as the run's budget).
export const REMOTE_MAX_STEPS = 1_000_000;
export const REMOTE_MAX_SECONDS = 300;

export type Dtype = "float32" | "float64";

// x in plot coordinates [-1, 1], left to right, as network inputs.
export function curveGrid(points: number): Float64Array {
  return new Float64Array(points).map((_, i) => (-1 + (2 * i) / (points - 1)) * INPUT_SCALE);
}

// Pixel centres of a size x size raster, rows top to bottom, as (x, y) network inputs: the spiral heatmap.
export function heatGrid(size: number): Float64Array {
  const out = new Float64Array(2 * size * size);
  for (let j = 0; j < size; j++) {
    for (let i = 0; i < size; i++) {
      const o = 2 * (j * size + i);
      out[o] = (((i + 0.5) / size) * 2 - 1) * INPUT_SCALE;
      out[o + 1] = (1 - ((j + 0.5) / size) * 2) * INPUT_SCALE;
    }
  }
  return out;
}

interface WireLayer { readonly w: number[]; readonly b: number[] }
interface WireBatch { readonly x: number[]; readonly y: number[] }

// The JSON remote_train.py parses (field names are its).
export interface RemoteConfig {
  readonly task: Task;
  readonly activation: Activation;
  readonly sizes: readonly number[];
  readonly state: { readonly layers: WireLayer[]; readonly adam: { readonly m: WireLayer[]; readonly v: WireLayer[]; readonly t: number } };
  readonly lr: number;
  readonly dtype: Dtype;
  readonly train: WireBatch;
  readonly test: WireBatch;
  readonly grid: number[];
  readonly step: number;
  readonly seconds: number;
  readonly max_steps: number;
  readonly max_seconds: number;
  readonly tick_seconds: number;
}

// What to train on: the training sample, what the test metrics score against (the whole true curve, or the
// spiral's held-out sample), and where to predict for the plot.
export interface RemoteData {
  readonly train: Batch;
  readonly test: Batch;
  readonly grid: Float64Array;
}

// Where the run starts (the widget's counters) and its budgets (absolute, Infinity = off).
export interface RemoteSettings {
  readonly lr: number;
  readonly dtype: Dtype;
  readonly step: number;
  readonly seconds: number;
  readonly stepBudget: number;
  readonly timeBudget: number;
}

const wireBatch = (b: Batch): WireBatch => ({ x: Array.from(b.x), y: Array.from(b.y) });
const wireGrads = (g: Grads): WireLayer[] => g.w.map((w, l) => ({ w: Array.from(w), b: Array.from(g.b[l] ?? []) }));

export function remoteConfig(net: Mlp, opt: Adam, task: Task, data: RemoteData, run: RemoteSettings): RemoteConfig {
  return {
    task,
    activation: net.activation,
    sizes: net.sizes,
    state: {
      layers: net.layers.map((l) => ({ w: Array.from(l.w), b: Array.from(l.b) })),
      adam: { m: wireGrads(opt.m), v: wireGrads(opt.v), t: opt.t },
    },
    lr: run.lr,
    dtype: run.dtype,
    train: wireBatch(data.train),
    test: wireBatch(data.test),
    grid: Array.from(data.grid),
    step: run.step,
    seconds: run.seconds,
    max_steps: Math.min(run.stepBudget, REMOTE_MAX_STEPS),
    max_seconds: Math.min(run.timeBudget, REMOTE_MAX_SECONDS),
    tick_seconds: TICK_SECONDS,
  };
}

// The Python the kernel runs: the program in its own namespace (so its names don't land in the kernel's
// globals, and its `if __name__ == "__main__"` stays off), then run(config). A JSON string literal is also a
// valid Python string literal, so both are inlined with JSON.stringify.
export function remoteCode(config: RemoteConfig): string {
  return [
    `_nn_fit = {"__name__": "nn_fit_remote"}`,
    `exec(compile(${JSON.stringify(source)}, "remote_train.py", "exec"), _nn_fit)`,
    `try:`,
    `    _nn_fit["run"](${JSON.stringify(JSON.stringify(config))})`,
    `finally:`,
    `    del _nn_fit`,
  ].join("\n");
}

// --- the lines it prints ---

export interface NetState {
  readonly layers: readonly { readonly w: Float64Array; readonly b: Float64Array }[];
  readonly m: Grads;
  readonly v: Grads;
  readonly t: number;
}

export type StopReason = "steps" | "time" | "interrupted";

export type RemoteLine =
  | { readonly kind: "start"; readonly device: string; readonly deviceName: string; readonly torch: string; readonly dtype: string }
  | {
    readonly kind: "tick"; readonly step: number; readonly seconds: number; readonly loss: number; readonly accuracy: number | null;
    readonly testLoss: number; readonly testAccuracy: number | null; readonly pred: Float64Array;
  }
  | { readonly kind: "end"; readonly reason: StopReason; readonly step: number; readonly seconds: number; readonly state: NetState };

export type RemoteTick = Extract<RemoteLine, { kind: "tick" }>;

// Split stdout chunks into whole lines; `pending` is the unterminated tail carried to the next chunk.
export function splitLines(pending: string, chunk: string): { lines: string[]; pending: string } {
  const parts = (pending + chunk).split("\n");
  const rest = parts.pop() ?? "";
  return { lines: parts.filter((l) => l.trim() !== ""), pending: rest };
}

// Parse one line, or throw with what was wrong (the line crossed a network). Non-finite numbers arrive as
// null (JSON has no NaN) and become NaN again here.
export function parseLine(text: string): RemoteLine {
  const where = `remote line ${text.length > 80 ? `${text.slice(0, 80)}…` : text}`;
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new Error(`${where}: not JSON`);
  }
  const obj = record(raw, where);
  switch (obj["kind"]) {
    case "start":
      return { kind: "start", device: str(obj, "device", where), deviceName: str(obj, "device_name", where), torch: str(obj, "torch", where), dtype: str(obj, "dtype", where) };
    case "tick":
      return {
        kind: "tick", step: int(obj, "step", where), seconds: num(obj, "seconds", where), loss: numOrNaN(obj["loss"], where),
        accuracy: optional(obj, "accuracy", where), testLoss: numOrNaN(obj["test_loss"], where), testAccuracy: optional(obj, "test_accuracy", where),
        pred: floats(obj["pred"], `${where}: pred`),
      };
    case "end":
      return { kind: "end", reason: reason(obj["reason"], where), step: int(obj, "step", where), seconds: num(obj, "seconds", where), state: netState(obj["state"], where) };
    default:
      throw new Error(`${where}: unknown kind ${JSON.stringify(obj["kind"])}`);
  }
}

// Copy a remote state into the browser's net and optimizer (same shapes, checked), so training continues from it.
export function loadState(net: Mlp, opt: Adam, state: NetState): void {
  const copy = (into: Float64Array, from: Float64Array | undefined, what: string): void => {
    if (from?.length !== into.length) throw new Error(`remote state: ${what} has ${String(from?.length)} values, expected ${String(into.length)}`);
    into.set(from);
  };
  if (state.layers.length !== net.layers.length) throw new Error(`remote state: ${String(state.layers.length)} layers, expected ${String(net.layers.length)}`);
  net.layers.forEach((layer, l) => {
    const name = `layer ${String(l)}`;
    copy(layer.w, state.layers[l]?.w, `${name} w`);
    copy(layer.b, state.layers[l]?.b, `${name} b`);
    for (const [mine, theirs, which] of [[opt.m, state.m, "m"], [opt.v, state.v, "v"]] as const) {
      const w = mine.w[l], b = mine.b[l];
      if (!w || !b) throw new Error(`optimizer has no ${name}`);
      copy(w, theirs.w[l], `adam ${which} ${name} w`);
      copy(b, theirs.b[l], `adam ${which} ${name} b`);
    }
  });
  opt.t = state.t;
}

// Parsing helpers, shared with grok.ts (its lines cross the same network).
const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

export function record(v: unknown, where: string): Record<string, unknown> {
  if (!isRecord(v)) throw new Error(`${where}: expected an object`);
  return v;
}

export function str(obj: Record<string, unknown>, key: string, where: string): string {
  const v = obj[key];
  if (typeof v !== "string") throw new Error(`${where}: ${key} must be a string`);
  return v;
}

export function num(obj: Record<string, unknown>, key: string, where: string): number {
  const v = obj[key];
  if (typeof v !== "number") throw new Error(`${where}: ${key} must be a number`);
  return v;
}

export function int(obj: Record<string, unknown>, key: string, where: string): number {
  const v = num(obj, key, where);
  if (!Number.isInteger(v) || v < 0) throw new Error(`${where}: ${key} must be a non-negative integer`);
  return v;
}

export function numOrNaN(v: unknown, where: string): number {
  if (v === null) return NaN;
  if (typeof v !== "number") throw new Error(`${where}: expected a number or null, got ${JSON.stringify(v)}`);
  return v;
}

function optional(obj: Record<string, unknown>, key: string, where: string): number | null {
  return obj[key] === null ? null : num(obj, key, where);
}

function floats(v: unknown, where: string): Float64Array {
  if (!Array.isArray(v)) throw new Error(`${where}: expected a list of numbers`);
  return Float64Array.from(v, (x) => numOrNaN(x, where));
}

export function reason(v: unknown, where: string): StopReason {
  if (v === "steps" || v === "time" || v === "interrupted") return v;
  throw new Error(`${where}: unknown stop reason ${JSON.stringify(v)}`);
}

function layers(v: unknown, where: string): { w: Float64Array; b: Float64Array }[] {
  if (!Array.isArray(v)) throw new Error(`${where}: expected a list of layers`);
  return v.map((layer: unknown, l) => {
    const obj = record(layer, `${where}[${String(l)}]`);
    return { w: floats(obj["w"], `${where}[${String(l)}].w`), b: floats(obj["b"], `${where}[${String(l)}].b`) };
  });
}

function netState(v: unknown, where: string): NetState {
  const obj = record(v, `${where}: state`);
  const adam = record(obj["adam"], `${where}: state.adam`);
  const grads = (key: string): Grads => {
    const ls = layers(adam[key], `${where}: state.adam.${key}`);
    return { w: ls.map((l) => l.w), b: ls.map((l) => l.b) };
  };
  return { layers: layers(obj["layers"], `${where}: state.layers`), m: grads("m"), v: grads("v"), t: int(adam, "t", where) };
}
