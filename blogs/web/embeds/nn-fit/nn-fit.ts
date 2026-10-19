import { interrupt, kernelState, onKernelState, runCode } from "../../connect/kernel";
import type { RunResult } from "../../connect/kernel";
import { must } from "../../dom";
import type { Activation, Adam, Batch, Mlp, Task } from "./mlp";
import { ACTIVATIONS, evaluate, get, initMlp, makeAdam, paramCount, predictor, seeded, trainStep } from "./mlp";
import type { DrawBuffer, Point, WaveParams, WaveStage } from "./datasets";
import {
  INPUT_SCALE, MAX_STAGES, MAX_WIGGLES, SAMPLE_COUNTS, columnX, completeCurve, curveSamples, describeGaps, drawSamples, fillWave,
  gaps, makeDrawBuffer, paintStroke, spiral, waveFormula, waveStages,
} from "./datasets";
import type { RemoteLine, RemoteTick, StopReason } from "./remote";
import {
  CURVE_POINTS, HEAT_GRID, REMOTE_MAX_SECONDS, REMOTE_MAX_STEPS, curveGrid, heatGrid, loadState, parseLine, remoteCode, remoteConfig,
  splitLines,
} from "./remote";
import type { GrokLine, GrokPoint } from "./grok";
import {
  GROK_P, GROK_TICK_SECONDS, TRAIN_FRACTIONS, addPoint, grokCode, grokked, paintGrok, parseGrokLine,
} from "./grok";

export type Dataset = "draw" | "wave" | "spiral" | "grok";
const DATASETS: readonly Dataset[] = ["draw", "wave", "spiral", "grok"];
export type Backend = "browser" | "remote";
const BROWSER_DEVICE = "this browser";
const connected = (): boolean => kernelState() === "idle" || kernelState() === "busy";

export interface NnFitStats {
  readonly dataset: Dataset;
  readonly sizes: readonly number[];
  readonly params: number | null;
  readonly samples: number | null;
  readonly loss: number | null;
  readonly trueError: number | null;
  readonly accuracy: number | null;
  readonly heldOutAccuracy: number | null;
  readonly steps: number;
  readonly seconds: number;
  readonly flops: number | null;
  readonly stepBudget: number;
  readonly timeBudget: number;
  readonly training: boolean;
  readonly ready: boolean;
  readonly backend: Backend;
  readonly device: string;
  readonly grok: GrokStats | null;
}

export interface GrokStats {
  readonly p: number;
  readonly trainFraction: number;
  readonly testLoss: number | null;
  readonly points: number;
  readonly grokked: { readonly step: number; readonly seconds: number } | null;
  readonly run: string;
  readonly model: string | null;
}

type MlpStats = NnFitStats & { readonly params: number; readonly samples: number; readonly flops: number };

interface GrokRun {
  readonly id: string;
  readonly fractionK: number;
  readonly splitSeed: number;
  readonly initSeed: number;
  points: GrokPoint[];
  steps: number;
  ms: number;
  start: Extract<GrokLine, { kind: "start" }> | null;
  kernelOutOfSync: boolean;
}

interface GrokFlight {
  readonly run: GrokRun;
  stopping: boolean;
  end: Extract<GrokLine, { kind: "end" }> | null;
  failure: string | null;
}

const grokkedAt = (points: readonly GrokPoint[]): GrokStats["grokked"] => {
  const p = grokked(points);
  return p === null ? null : { step: p.step, seconds: p.seconds };
};

const newGrokRun = (fractionK: number, splitSeed: number, initSeed: number): GrokRun =>
  ({ id: `grok-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`, fractionK, splitSeed, initSeed, points: [], steps: 0, ms: 0, start: null, kernelOutOfSync: false });

interface RemoteRun {
  readonly fromStep: number;
  readonly fromMs: number;
  readonly fromFlops: number;
  device: string | null;
  tick: RemoteTick | null;
  end: Extract<RemoteLine, { kind: "end" }> | null;
  stopping: boolean;
  failure: string | null;
}

const MAX_STEPS_PER_FRAME = 8;
const MAX_TRAIN_MS_PER_FRAME = 12;
const COLUMNS = 640;
const MAX_LAYERS = 4;
const MAX_WIDTH = 16;
const HEAT_PX = 4;
const HEATMAP_MAX = 128;
const LRS = Array.from({ length: 17 }, (_, k) => 10 ** (-4 + k / 4));
const NOISE_SIGMAS = Array.from({ length: 11 }, (_, k) => k * 0.05);
const ROUGHNESSES = Array.from({ length: 11 }, (_, k) => 3 - k * 0.25);
const STEP_BUDGETS = [500, 1000, 2000, 5000, 10000, 20000, 50000, Infinity];
const TIME_BUDGETS = [1, 2, 5, 10, 20, 30, 60, Infinity];
const SPIRAL_JITTER_PER_SIGMA = 2;
const HELD_OUT = 500;
const HELD_OUT_SEED = 1000;
const Y_RANGE = 1.2;
const REDUCED_MOTION_PAINT_INTERVAL_MS = 250;
const ARIA_MS = 1000;
const MAX_COUNTED_FRAME_MS = 100;
const REMOTE_DTYPE = "float32";
const CURVE_X = curveGrid(CURVE_POINTS);
const HEAT_XY = heatGrid(HEAT_GRID);

const isActivation = (s: string): s is Activation => ACTIVATIONS.some((a) => a === s);
const isDataset = (s: string): s is Dataset => DATASETS.some((d) => d === s);
const nearest = (list: readonly number[], v: number): number =>
  list.reduce((best, x, i) => (Math.abs(x - v) < Math.abs((list[best] ?? Infinity) - v) ? i : best), 0);
const at = (list: readonly number[], i: number): number => {
  const v = list[i];
  if (v === undefined) throw new RangeError(`slider index ${String(i)} outside ${String(list.length)} stops`);
  return v;
};

function numAttr(el: Element, name: string): number | null {
  const raw = el.getAttribute(name);
  if (raw === null) return null;
  const v = raw === "off" ? Infinity : Number(raw);
  if (Number.isNaN(v)) throw new Error(`<nn-fit ${name}="${raw}">: expected a number`);
  return v;
}

function intAttr(el: Element, name: string, lo: number, hi: number, fallback: number): number {
  const v = numAttr(el, name);
  if (v === null) return fallback;
  if (!Number.isInteger(v) || v < lo || v > hi) throw new Error(`<nn-fit ${name}="${String(v)}">: expected an integer in ${String(lo)}..${String(hi)}`);
  return v;
}

const STYLE = `
:host { display: block; margin: 1.6em 0; font-family: var(--font-mono, ui-monospace, monospace); font-size: 12px; color: var(--fg); }
* { box-sizing: border-box; }
.stage { position: relative; margin: 0 auto; }
.stage.spiral { max-width: 420px; }
canvas { display: block; width: 100%; aspect-ratio: 2 / 1; background: var(--code-bg); border: 1px solid var(--rule);
         border-radius: 6px; touch-action: none; cursor: crosshair; }
.stage.spiral canvas { aspect-ratio: 1 / 1; cursor: default; touch-action: auto; }
.hint { position: absolute; top: 50%; left: 50%; translate: -50% -50%; max-width: calc(100% - 32px); margin: 0; padding: 6px 12px;
        text-align: center; font-size: 13px; color: var(--fg); background: var(--code-bg); border: 1px solid var(--rule);
        border-radius: 4px; pointer-events: none; }
[hidden] { display: none !important; }
.need { margin: 6px 0 0; color: var(--muted); text-wrap: pretty; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 6px 0 0; color: var(--muted); }
.legend span::before { content: ""; display: inline-block; width: 14px; height: 0; margin-right: 6px; vertical-align: middle;
                       border-top: 2.5px solid var(--swatch); }
.legend .faint::before { opacity: 0.4; }
.legend .dot::before { width: 7px; height: 7px; border: 0; border-radius: 50%; background: var(--swatch); }
.legend .square::before { width: 7px; height: 7px; border: 0; border-radius: 1px; background: var(--swatch); }
.readout { margin: 8px 0 0; color: var(--muted); font-variant-numeric: tabular-nums; line-height: 1.6; }
.readout b { font-weight: 600; color: var(--fg); }
.buttons { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0 4px; }
button { font: inherit; min-height: 30px; padding: 4px 12px; border: 1px solid var(--rule); border-radius: 4px;
         background: var(--bg); color: var(--fg); cursor: pointer; }
button:hover { background: var(--active, var(--code-bg)); }
button.train { min-width: 72px; border-color: var(--muted); }
button[aria-disabled="true"] { opacity: 0.45; cursor: not-allowed; }
button[aria-disabled="true"]:hover { background: var(--bg); }
button:disabled { opacity: 0.45; cursor: not-allowed; }
button:disabled:hover { background: var(--bg); }
fieldset { margin: 10px 0 0; padding: 8px 0 0; border: 0; border-top: 1px solid var(--rule); min-width: 0; }
legend { padding: 0 8px 0 0; color: var(--muted); font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; }
.controls { display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); gap: 8px 24px; }
.control { display: grid; grid-template-columns: 9.5em minmax(60px, 1fr) 4em; align-items: center; gap: 8px; color: var(--muted); white-space: nowrap; }
.control select { grid-column: 2 / 4; }
select { font: inherit; color: var(--fg); background: var(--code-bg); border: 1px solid var(--rule); border-radius: 4px; padding: 3px 4px; min-height: 28px; }
input[type="range"] { width: 100%; margin: 0; accent-color: var(--fg); }
output { color: var(--fg); font-variant-numeric: tabular-nums; text-align: right; }
.widths { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 8px 24px; margin-top: 8px; }
.layer-width { display: grid; grid-template-columns: 9.5em 28px 3.2em 28px; align-items: center; gap: 4px; color: var(--muted); white-space: nowrap; }
.layer-width button { min-height: 28px; padding: 0; }
.layer-width input { font: inherit; width: 100%; min-height: 28px; text-align: center; color: var(--fg); background: var(--code-bg);
                     border: 1px solid var(--rule); border-radius: 4px; font-variant-numeric: tabular-nums; -moz-appearance: textfield; }
.layer-width input::-webkit-inner-spin-button, .layer-width input::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
details { margin-top: 8px; color: var(--muted); }
summary { cursor: pointer; width: fit-content; }
pre.formula { margin: 6px 0 0; padding: 8px 10px; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; font-size: 11.5px;
              line-height: 1.5; color: var(--fg); background: var(--code-bg); border: 1px solid var(--rule); border-radius: 4px; }
button:focus-visible, select:focus-visible, input:focus-visible, summary:focus-visible { outline: 2px solid var(--fg); outline-offset: 2px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
@media (pointer: coarse) { button, .layer-width button { min-height: 40px; } select, .layer-width input { min-height: 36px; }
                           .layer-width { grid-template-columns: 9.5em 40px 3.2em 40px; } }
`;

const range = (cls: string, label: string, max: number): string =>
  `<label class="control">${label} <input type="range" class="${cls}" min="0" max="${String(max)}" step="1"><output class="${cls}-out"></output></label>`;

const TEMPLATE = `
<div class="stage">
  <canvas role="img"></canvas>
  <p class="hint" id="hint"></p>
</div>
<p class="need" id="need"></p>
<p class="legend">
  <span class="curve-only faint" style="--swatch: var(--fg)">true curve</span>
  <span class="curve-only dot" style="--swatch: var(--fg)">training samples</span>
  <span class="curve-only" style="--swatch: var(--tok-number)">the network</span>
  <span class="spiral-only dot" style="--swatch: var(--tok-number)">class A</span>
  <span class="spiral-only square" style="--swatch: var(--tok-string)">class B</span>
  <span class="grok-only" style="--swatch: var(--fg)">train accuracy (the pairs it trains on)</span>
  <span class="grok-only" style="--swatch: var(--tok-number)">test accuracy (every other pair)</span>
</p>
<p class="readout"><span class="metrics"></span><br><span class="usage"></span></p>
<div class="buttons">
  <button type="button" class="train" aria-describedby="hint need">Train</button>
  <button type="button" class="reset">Reset weights</button>
  <button type="button" class="resample">New samples</button>
  <button type="button" class="new-wave wave-only">New random curve</button>
  <button type="button" class="clear curve-only">Clear drawing</button>
</div>
<fieldset class="data">
  <legend>Data</legend>
  <div class="controls">
    <label class="control">Data
      <select class="dataset"><option value="draw">Draw a function</option><option value="wave">Random wave</option><option value="spiral">Spiral</option><option value="grok">Modular arithmetic (grokking)</option></select></label>
    <div class="not-grok" style="display: contents">
      ${range("samples", "Samples", SAMPLE_COUNTS.length - 1)}
      ${range("noise", "Noise σ", NOISE_SIGMAS.length - 1)}
    </div>
    <div class="grok-only" style="display: contents">
      ${range("fraction", "Train fraction", TRAIN_FRACTIONS.length - 1)}
    </div>
    <div class="wave-only" style="display: contents">
      ${range("wiggles", "Wiggles K", MAX_WIGGLES - 1)}
      ${range("roughness", "Roughness α", ROUGHNESSES.length - 1)}
      ${range("stages", "Stages d", MAX_STAGES - 1)}
    </div>
  </div>
  <details class="wave-only"><summary>show formula</summary><pre class="formula"></pre></details>
</fieldset>
<fieldset class="network not-grok">
  <legend>Network</legend>
  <div class="controls">
    <label class="control">Activation
      <select class="activation">${ACTIVATIONS.map((a) => `<option value="${a}">${a}</option>`).join("")}</select></label>
    ${range("lr", "Learning rate", LRS.length - 1)}
    ${range("layers", "Hidden layers", MAX_LAYERS)}
  </div>
  <div class="widths"></div>
</fieldset>
<fieldset class="compute">
  <legend>Compute</legend>
  <div class="controls">
    <label class="control">Run on
      <select class="backend"><option value="browser">this browser</option><option value="remote">remote</option></select></label>
    ${range("step-budget", "Step budget", STEP_BUDGETS.length - 1)}
    ${range("time-budget", "Time budget", TIME_BUDGETS.length - 1)}
  </div>
</fieldset>
<p class="sr-only" role="status"></p>
`;

type Rgb = readonly [number, number, number];

interface Palette {
  readonly fg: string;
  readonly muted: string;
  readonly rule: string;
  readonly bg: string;
  readonly codeBg: string;
  readonly net: string;
  readonly classA: string;
  readonly classB: string;
  readonly bgRgb: Rgb;
  readonly aRgb: Rgb;
  readonly bRgb: Rgb;
}

const formatLr = (lr: number): string => (lr < 0.001 ? lr.toExponential(0) : String(Number(lr.toPrecision(2))));
const formatLoss = (loss: number): string => (loss < 1e-4 ? loss.toExponential(1) : loss.toPrecision(3));
const formatInt = (n: number): string => n.toLocaleString("en-US");
const formatPct = (a: number): string => `${(a * 100).toFixed(1)}%`;
function formatFlops(f: number): string {
  const units: readonly [number, string][] = [[1e12, "T"], [1e9, "G"], [1e6, "M"], [1e3, "k"]];
  for (const [scale, unit] of units) {
    const v = f / scale;
    if (v >= 1) return `${v >= 100 ? v.toFixed(0) : v.toPrecision(2)} ${unit}FLOP`;
  }
  return `${String(Math.round(f))} FLOP`;
}
const formatBudget = (v: number, unit: string): string => (v === Infinity ? "off" : `${formatInt(v)}${unit}`);

const EMPTY: Batch = { n: 0, x: new Float64Array(0), y: new Float64Array(0) };

const stopText = (reason: StopReason): string =>
  reason === "steps" ? "step budget used up" : reason === "time" ? "time budget used up" : "stopped";
const tracebackSummary = (error: string): string => error.trim().split("\n").at(-1) ?? error;

function runFailure(result: RunResult): string | null {
  switch (result.status) {
    case "ok": return null;
    case "error": return result.traceback === "" ? `${result.ename}: ${result.evalue}` : result.traceback;
    case "aborted": return result.reason;
  }
}

export class NnFit extends HTMLElement {
  #root = this.attachShadow({ mode: "open" });
  #ctx: CanvasRenderingContext2D | null = null;

  #dataset: Dataset = "draw";
  #activation: Activation = "tanh";
  #layers = 2;
  #widths: number[] = Array.from({ length: MAX_LAYERS }, () => 8);
  #lrK = nearest(LRS, 0.03);
  #samplesK = SAMPLE_COUNTS.indexOf(128);
  #noiseK = 0;
  #wave = { wiggles: 4, roughnessK: nearest(ROUGHNESSES, 1.5), stages: 1, seed: 1 };
  #stepBudgetK = STEP_BUDGETS.length - 1;
  #timeBudgetK = TIME_BUDGETS.length - 1;
  #weightSeed = 1;
  #sampleSeed = 1;

  #net: Mlp = initMlp([1, 8, 8, 1], "tanh", seeded(1));
  #opt: Adam = makeAdam(this.#net);
  #steps = 0;
  #trainMs = 0;
  #flops = 0;
  #backend: Backend = "browser";
  #remote: RemoteRun | null = null;
  #device = BROWSER_DEVICE;
  #remoteFailureNote = "";
  #grok: GrokRun = newGrokRun(TRAIN_FRACTIONS.indexOf(0.3), 1, 1);
  #grokFlight: GrokFlight | null = null;

  #truth: DrawBuffer = makeDrawBuffer(COLUMNS);
  #truthBatch: Batch = EMPTY;
  #curve: DrawBuffer | null = null;
  #train: Batch = EMPTY;
  #heldOut: Batch = EMPTY;
  #waveStages: WaveStage[] = [];
  #stroke: { pointer: number; last: Point } | null = null;

  #training = false;
  #onScreen = false;
  #frame = 0;
  #lastTick: number | null = null;
  #lastPaint = 0;
  #lastAria = 0;
  #reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  #darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
  #palette: Palette | null = null;
  #heat = document.createElement("canvas");
  #cleanup: (() => void)[] = [];
  #built = false;

  get stats(): NnFitStats {
    return this.#dataset === "grok" ? this.#grokStats() : this.#mlpStats();
  }

  #mlpStats(): MlpStats {
    const metrics = this.#remote?.tick ? this.#tickMetrics(this.#remote.tick) : this.#browserMetrics();
    return {
      dataset: this.#dataset,
      sizes: this.#net.sizes,
      params: paramCount(this.#net),
      samples: this.#train.n,
      ...metrics,
      steps: this.#steps,
      seconds: this.#trainMs / 1000,
      flops: this.#flops,
      stepBudget: this.#stepBudget(),
      timeBudget: this.#timeBudget(),
      training: this.#training,
      ready: this.#ready(),
      backend: this.#backend,
      device: this.#remote ? this.#remote.device ?? "remote (starting)" : this.#device,
      grok: null,
    };
  }

  #grokStats(): NnFitStats {
    const g = this.#grok;
    const last = g.points.at(-1);
    const fraction = at(TRAIN_FRACTIONS, g.fractionK);
    const start = g.start;
    const device = start === null ? null : start.device === "cpu" ? "cpu (remote)" : `${start.device} · ${start.deviceName}`;
    return {
      dataset: "grok", sizes: [], params: start?.params ?? null, samples: start?.train ?? null,
      loss: last?.loss ?? null, trueError: null, accuracy: last?.accuracy ?? null, heldOutAccuracy: last?.testAccuracy ?? null,
      steps: g.steps, seconds: g.ms / 1000, flops: start === null ? null : 6 * start.params * start.train * g.steps,
      stepBudget: this.#stepBudget(), timeBudget: this.#timeBudget(), training: this.#training, ready: this.#ready(),
      backend: "remote", device: device ?? (this.#grokFlight ? "remote (starting)" : "not trained yet"),
      grok: { p: GROK_P, trainFraction: fraction, testLoss: last?.testLoss ?? null, points: g.points.length, run: g.id, grokked: grokkedAt(g.points), model: start?.model ?? null },
    };
  }

  #browserMetrics(): Pick<NnFitStats, "loss" | "trueError" | "accuracy" | "heldOutAccuracy"> {
    const task = this.#task();
    const train = this.#train.n > 0 ? evaluate(this.#net, task, this.#train) : null;
    const curve = this.#isCurve() && this.#truthBatch.n > 0 ? evaluate(this.#net, task, this.#truthBatch) : null;
    const held = !this.#isCurve() && this.#heldOut.n > 0 ? evaluate(this.#net, task, this.#heldOut) : null;
    return { loss: train?.loss ?? null, trueError: curve?.loss ?? null, accuracy: train?.accuracy ?? null, heldOutAccuracy: held?.accuracy ?? null };
  }

  #tickMetrics(tick: RemoteTick): Pick<NnFitStats, "loss" | "trueError" | "accuracy" | "heldOutAccuracy"> {
    const curve = this.#isCurve();
    return { loss: tick.loss, trueError: curve ? tick.testLoss : null, accuracy: tick.accuracy, heldOutAccuracy: curve ? null : tick.testAccuracy };
  }

  get curve(): Float64Array | null {
    return this.#curve === null ? null : Float64Array.from(this.#curve);
  }

  connectedCallback(): void {
    if (!this.#built) this.#build();
    this.#listen();
    this.#paint();
  }

  disconnectedCallback(): void {
    for (const undo of this.#cleanup) undo();
    this.#cleanup = [];
    this.#stopLoop();
    this.#stopRemote();
  }

  #el<T extends Element>(selector: string, type: new () => T): T {
    return must(this.#root, selector, type);
  }

  #build(): void {
    this.#built = true;
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(STYLE);
    this.#root.adoptedStyleSheets = [sheet];
    this.#root.innerHTML = TEMPLATE;

    const dataset = this.getAttribute("dataset") ?? "draw";
    if (!isDataset(dataset)) throw new Error(`<nn-fit dataset="${dataset}">: expected ${DATASETS.join(", ")}`);
    const activation = this.getAttribute("activation") ?? "tanh";
    if (!isActivation(activation)) throw new Error(`<nn-fit activation="${activation}">: expected ${ACTIVATIONS.join(", ")}`);
    this.#dataset = dataset;
    this.#activation = activation;
    this.#layers = intAttr(this, "layers", 0, MAX_LAYERS, 2);
    const width = intAttr(this, "width", 1, MAX_WIDTH, 8);
    this.#widths.fill(width);
    const widths = this.getAttribute("widths");
    if (widths !== null) {
      widths.split(",").forEach((w, i) => {
        const v = Number(w);
        if (!Number.isInteger(v) || v < 1 || v > MAX_WIDTH || i >= MAX_LAYERS) throw new Error(`<nn-fit widths="${widths}">: expected up to ${String(MAX_LAYERS)} integers in 1..${String(MAX_WIDTH)}`);
        this.#widths[i] = v;
      });
      if (!this.hasAttribute("layers")) this.#layers = widths.split(",").length;
    }
    const pick = (name: string, list: readonly number[], fallback: number): number => {
      const v = numAttr(this, name);
      return v === null ? fallback : nearest(list, v);
    };
    this.#lrK = pick("lr", LRS, this.#lrK);
    this.#samplesK = pick("samples", SAMPLE_COUNTS, this.#samplesK);
    this.#noiseK = pick("noise", NOISE_SIGMAS, this.#noiseK);
    this.#stepBudgetK = pick("step-budget", STEP_BUDGETS, this.#stepBudgetK);
    this.#timeBudgetK = pick("time-budget", TIME_BUDGETS, this.#timeBudgetK);
    this.#grok = newGrokRun(pick("train-fraction", TRAIN_FRACTIONS, this.#grok.fractionK), 1, 1);
    this.#wave = {
      wiggles: intAttr(this, "wiggles", 1, MAX_WIGGLES, this.#wave.wiggles),
      roughnessK: pick("roughness", ROUGHNESSES, this.#wave.roughnessK),
      stages: intAttr(this, "stages", 1, MAX_STAGES, this.#wave.stages),
      seed: intAttr(this, "seed", 0, 2 ** 31, this.#wave.seed),
    };

    this.#el("select.dataset", HTMLSelectElement).value = this.#dataset;
    this.#el("select.activation", HTMLSelectElement).value = this.#activation;
    this.#ctx = this.#el("canvas", HTMLCanvasElement).getContext("2d");
    if (this.#dataset === "wave") this.#regenWave();
    this.#rebuildNet();
    this.#dataChanged();
  }

  #listen(): void {
    const on = <K extends keyof HTMLElementEventMap>(target: HTMLElement, type: K, fn: (e: HTMLElementEventMap[K]) => void): void => {
      target.addEventListener(type, fn);
      this.#cleanup.push(() => { target.removeEventListener(type, fn); });
    };
    const button = (cls: string, fn: () => void): void => { on(this.#el(`button.${cls}`, HTMLButtonElement), "click", fn); };
    const canvas = this.#el("canvas", HTMLCanvasElement);

    button("train", () => {
      if (this.#remote ?? this.#grokFlight) this.#stopRemote();
      else if (this.#dataset === "grok") this.#startGrok();
      else if (this.#backend === "remote") this.#startRemote();
      else this.#setTraining(!this.#training);
    });
    button("reset", () => {
      if (this.#dataset === "grok") {
        this.#newGrokRun({ initSeed: this.#grok.initSeed + 1 }, "Weights reset to new random values; the curve starts over.");
        return;
      }
      this.#weightSeed++;
      this.#rebuildNet();
      this.#announce("Weights reset to new random values; step and time counters back to zero.");
    });
    button("resample", () => {
      if (this.#dataset === "grok") {
        this.#newGrokRun({ splitSeed: this.#grok.splitSeed + 1 }, "A new random split of the pairs, and new weights; the curve starts over.");
        return;
      }
      this.#sampleSeed++;
      this.#resample();
      this.#announce(`New random sample of ${String(this.#train.n)} training points.`);
    });
    button("new-wave", () => {
      this.#wave = { ...this.#wave, seed: this.#wave.seed + 1 };
      this.#announce(`New random curve, seed ${String(this.#wave.seed)}.`);
      this.#regenWave();
    });
    button("clear", () => {
      this.#truth = makeDrawBuffer(COLUMNS);
      this.#announce("Drawing cleared.");
      this.#dataChanged();
    });

    const select = this.#el("select.dataset", HTMLSelectElement);
    on(select, "change", () => {
      if (!isDataset(select.value)) return;
      this.#dataset = select.value;
      this.#announce(
        select.value === "draw" ? "Draw a function on the plot, edge to edge."
          : select.value === "wave" ? "Random wave generated. You can draw over it to edit it."
            : select.value === "spiral" ? "Spiral dataset: two classes."
              : "Modular arithmetic: a plus b mod 113, trained remotely. The plot shows train and test accuracy against step.");
      if (this.#training && (this.#dataset === "grok" || !this.#ready())) this.#setTraining(false);
      if (this.#dataset !== "grok" && this.#net.sizes[0] !== this.#inputs()) this.#makeNet();
      if (select.value === "wave") this.#regenWave();
      else this.#dataChanged();
    });
    const activation = this.#el("select.activation", HTMLSelectElement);
    on(activation, "change", () => {
      if (!isActivation(activation.value)) return;
      this.#activation = activation.value;
      this.#rebuildNet();
    });

    const backend = this.#el("select.backend", HTMLSelectElement);
    on(backend, "change", () => {
      if (backend.value !== "browser" && backend.value !== "remote") return;
      if (this.#training) this.#setTraining(false);
      this.#backend = backend.value;
      this.#announce(backend.value === "remote" ? "Train runs remotely, on the connected session." : "Train runs in this browser.");
      this.#syncControls();
      this.#paint();
    });
    this.#cleanup.push(onKernelState(() => {
      if (!connected() && this.#backend === "remote" && this.#remote === null) {
        this.#backend = "browser";
        this.#announce("The remote session went away; Train runs in this browser.");
      }
      this.#syncControls();
    }));

    const slider = (cls: string, set: (v: number) => void, after: () => void): void => {
      const input = this.#el(`input.${cls}`, HTMLInputElement);
      on(input, "input", () => {
        set(input.valueAsNumber);
        after();
        this.#syncControls();
        this.#paint();
      });
    };
    const nothing = (): void => undefined;
    slider("lr", (v) => { this.#lrK = v; }, nothing);
    slider("layers", (v) => { this.#layers = v; }, () => { this.#rebuildNet(); });
    slider("samples", (v) => { this.#samplesK = v; }, () => { this.#resample(); });
    slider("noise", (v) => { this.#noiseK = v; }, () => { this.#resample(); });
    slider("wiggles", (v) => { this.#wave = { ...this.#wave, wiggles: v + 1 }; }, () => { this.#regenWave(); });
    slider("roughness", (v) => { this.#wave = { ...this.#wave, roughnessK: v }; }, () => { this.#regenWave(); });
    slider("stages", (v) => { this.#wave = { ...this.#wave, stages: v + 1 }; }, () => { this.#regenWave(); });
    slider("fraction", (v) => { this.#grok = newGrokRun(v, this.#grok.splitSeed, this.#grok.initSeed); }, nothing);
    slider("step-budget", (v) => { this.#stepBudgetK = v; }, nothing);
    slider("time-budget", (v) => { this.#timeBudgetK = v; }, nothing);

    const widths = this.#el(".widths", HTMLDivElement);
    const setWidth = (layer: number, w: number): void => {
      const v = Math.min(MAX_WIDTH, Math.max(1, Math.round(w)));
      if (Number.isNaN(v) || this.#widths[layer] === v) { this.#syncControls(); return; }
      this.#widths[layer] = v;
      this.#rebuildNet();
      this.#syncControls();
    };
    on(widths, "click", (e) => {
      const t = e.target;
      if (!(t instanceof HTMLButtonElement)) return;
      const layer = Number(t.dataset["layer"]);
      setWidth(layer, (this.#widths[layer] ?? 1) + Number(t.dataset["delta"]));
    });
    on(widths, "change", (e) => {
      const t = e.target;
      if (t instanceof HTMLInputElement) setWidth(Number(t.dataset["layer"]), t.valueAsNumber);
    });

    on(canvas, "pointerdown", (e) => {
      if (!this.#isCurve() || this.#stroke || this.#remote) return;
      canvas.setPointerCapture(e.pointerId);
      const p = this.#toPlot(e);
      paintStroke(this.#truth, null, p);
      this.#stroke = { pointer: e.pointerId, last: p };
      this.#dataChanged();
    });
    on(canvas, "pointermove", (e) => {
      if (this.#stroke?.pointer !== e.pointerId) return;
      const p = this.#toPlot(e);
      paintStroke(this.#truth, this.#stroke.last, p);
      this.#stroke = { pointer: e.pointerId, last: p };
      this.#dataChanged();
    });
    const end = (e: PointerEvent): void => {
      if (this.#stroke?.pointer === e.pointerId) this.#stroke = null;
    };
    on(canvas, "pointerup", end);
    on(canvas, "pointercancel", end);

    const resize = new ResizeObserver(() => { this.#resize(); });
    resize.observe(canvas);
    const visible = new IntersectionObserver((entries) => {
      this.#onScreen = entries.some((e) => e.isIntersecting);
      this.#updateLoop();
    });
    visible.observe(this);
    const tab = (): void => { this.#updateLoop(); };
    document.addEventListener("visibilitychange", tab);
    const retheme = (): void => { this.#palette = null; this.#paint(); };
    const themes = new MutationObserver(retheme);
    themes.observe(document.documentElement, { attributes: true, attributeFilter: ["data-scheme", "data-theme", "style", "class"] });
    this.#darkQuery.addEventListener("change", retheme);
    this.#cleanup.push(() => {
      resize.disconnect();
      visible.disconnect();
      themes.disconnect();
      document.removeEventListener("visibilitychange", tab);
      this.#darkQuery.removeEventListener("change", retheme);
    });
  }

  #isCurve(): boolean {
    return this.#dataset === "draw" || this.#dataset === "wave";
  }

  #runsRemote(): boolean {
    return this.#dataset === "grok" || this.#backend === "remote";
  }

  #task(): Task {
    return this.#isCurve() ? "regression" : "binary";
  }

  #inputs(): number {
    return this.#dataset === "spiral" ? 2 : 1;
  }

  #stepBudget(): number {
    const budget = at(STEP_BUDGETS, this.#stepBudgetK);
    return this.#runsRemote() ? Math.min(budget, REMOTE_MAX_STEPS) : budget;
  }

  #timeBudget(): number {
    const budget = at(TIME_BUDGETS, this.#timeBudgetK);
    return this.#runsRemote() ? Math.min(budget, REMOTE_MAX_SECONDS) : budget;
  }

  #budgetText(): { steps: string; seconds: string } {
    const of = (inForce: number, setting: number, unit: string): string =>
      (inForce === Infinity ? "" : ` / ${formatInt(inForce)}${unit}${inForce < setting ? " (cap)" : ""}`);
    return {
      steps: of(this.#stepBudget(), at(STEP_BUDGETS, this.#stepBudgetK), ""),
      seconds: of(this.#timeBudget(), at(TIME_BUDGETS, this.#timeBudgetK), " s"),
    };
  }

  #budgetLeft(): boolean {
    const [steps, ms] = this.#dataset === "grok" ? [this.#grok.steps, this.#grok.ms] : [this.#steps, this.#trainMs];
    return steps < this.#stepBudget() && ms < this.#timeBudget() * 1000;
  }

  #dataReady(): boolean {
    if (this.#dataset === "grok") return connected();
    return !this.#isCurve() || this.#curve !== null;
  }

  #ready(): boolean {
    return this.#dataReady() && this.#budgetLeft();
  }

  #waveParams(): WaveParams {
    return { wiggles: this.#wave.wiggles, roughness: at(ROUGHNESSES, this.#wave.roughnessK), stages: this.#wave.stages, seed: this.#wave.seed };
  }

  #rebuildNet(): void {
    this.#makeNet();
    this.#syncControls();
    this.#paint();
  }

  #makeNet(): void {
    const sizes = [this.#inputs(), ...this.#widths.slice(0, this.#layers), 1];
    this.#net = initMlp(sizes, this.#activation, seeded(this.#weightSeed));
    this.#opt = makeAdam(this.#net);
    this.#steps = 0;
    this.#trainMs = 0;
    this.#flops = 0;
    this.#device = BROWSER_DEVICE;
  }

  #regenWave(): void {
    if (this.#dataset !== "wave") return;
    const params = this.#waveParams();
    this.#waveStages = waveStages(params, seeded);
    this.#truth = makeDrawBuffer(COLUMNS);
    fillWave(this.#truth, this.#waveStages);
    this.#el("pre.formula", HTMLPreElement).textContent = waveFormula(params, this.#waveStages);
    this.#dataChanged();
  }

  #dataChanged(): void {
    const had = this.#curve !== null;
    this.#curve = completeCurve(this.#truth);
    this.#truthBatch = this.#curve === null ? EMPTY : drawSamples(this.#curve);
    if (this.#isCurve() && this.#curve !== null && !had && this.#dataset === "draw") this.#announce("Train is ready. Gaps in the drawing are filled in.");
    if (this.#isCurve() && this.#curve === null && this.#training) {
      this.#setTraining(false);
      this.#announce("Paused: the drawing is empty.");
    }
    this.#resample();
  }

  #resample(): void {
    const n = at(SAMPLE_COUNTS, this.#samplesK);
    const sigma = at(NOISE_SIGMAS, this.#noiseK);
    if (this.#isCurve()) {
      this.#train = this.#curve === null ? EMPTY : curveSamples(this.#curve, n, sigma, seeded(this.#sampleSeed));
      this.#heldOut = EMPTY;
    } else {
      this.#train = spiral(n, sigma * SPIRAL_JITTER_PER_SIGMA, seeded(this.#sampleSeed));
      this.#heldOut = spiral(HELD_OUT, sigma * SPIRAL_JITTER_PER_SIGMA, seeded(HELD_OUT_SEED));
    }
    this.#syncControls();
    this.#paint();
  }

  #renderWidths(): void {
    const box = this.#el(".widths", HTMLDivElement);
    const groups = Array.from({ length: this.#layers }, (_, l) => {
      const name = `layer ${String(l + 1)} width`;
      return `<div class="layer-width"><label for="w${String(l)}">${name}</label>`
        + `<button type="button" tabindex="-1" aria-hidden="true" data-layer="${String(l)}" data-delta="-1">−</button>`
        + `<input id="w${String(l)}" type="number" min="1" max="${String(MAX_WIDTH)}" step="1" inputmode="numeric" data-layer="${String(l)}">`
        + `<button type="button" tabindex="-1" aria-hidden="true" data-layer="${String(l)}" data-delta="1">+</button></div>`;
    });
    if (box.children.length !== this.#layers) box.innerHTML = groups.join("");
    box.querySelectorAll("input").forEach((input, l) => {
      const v = String(this.#widths[l] ?? 1);
      if (input.value !== v) input.value = v;
    });
  }

  #syncControls(): void {
    const isCurve = this.#isCurve();
    const grok = this.#dataset === "grok";
    for (const el of this.#root.querySelectorAll(".curve-only")) el.toggleAttribute("hidden", !isCurve);
    for (const el of this.#root.querySelectorAll(".spiral-only")) el.toggleAttribute("hidden", this.#dataset !== "spiral");
    for (const el of this.#root.querySelectorAll(".wave-only")) el.toggleAttribute("hidden", this.#dataset !== "wave");
    for (const el of this.#root.querySelectorAll(".grok-only")) el.toggleAttribute("hidden", !grok);
    for (const el of this.#root.querySelectorAll(".not-grok")) el.toggleAttribute("hidden", grok);
    this.#el(".stage", HTMLDivElement).classList.toggle("spiral", this.#dataset === "spiral");

    const set = (cls: string, index: number, text: string): void => {
      const input = this.#el(`input.${cls}`, HTMLInputElement);
      input.value = String(index);
      input.setAttribute("aria-valuetext", text);
      this.#el(`output.${cls}-out`, HTMLOutputElement).value = text;
    };
    const n = at(SAMPLE_COUNTS, this.#samplesK);
    set("samples", this.#samplesK, String(n));
    set("noise", this.#noiseK, at(NOISE_SIGMAS, this.#noiseK).toFixed(2));
    set("lr", this.#lrK, formatLr(at(LRS, this.#lrK)));
    set("layers", this.#layers, String(this.#layers));
    set("wiggles", this.#wave.wiggles - 1, String(this.#wave.wiggles));
    set("roughness", this.#wave.roughnessK, at(ROUGHNESSES, this.#wave.roughnessK).toFixed(2));
    set("stages", this.#wave.stages - 1, String(this.#wave.stages));
    set("fraction", this.#grok.fractionK, formatPct(at(TRAIN_FRACTIONS, this.#grok.fractionK)).replace(".0%", "%"));
    set("step-budget", this.#stepBudgetK, formatBudget(at(STEP_BUDGETS, this.#stepBudgetK), ""));
    set("time-budget", this.#timeBudgetK, formatBudget(at(TIME_BUDGETS, this.#timeBudgetK), " s"));
    this.#renderWidths();

    const remote = this.#remote ?? this.#grokFlight;
    const option = this.#el("select.backend option[value=remote]", HTMLOptionElement);
    option.disabled = !connected();
    option.textContent = connected() ? "remote (the connected session)" : "remote (Connect first)";
    const backend = this.#el("select.backend", HTMLSelectElement);
    backend.value = grok ? "remote" : this.#backend;
    backend.disabled = grok;
    const grokOption = this.#el("select.dataset option[value=grok]", HTMLOptionElement);
    grokOption.disabled = !connected() && !grok;
    grokOption.textContent = connected() ? "Modular arithmetic (grokking)" : "Modular arithmetic (grokking): Connect first";
    for (const cls of ["data", "network", "compute"]) this.#el(`fieldset.${cls}`, HTMLFieldSetElement).disabled = remote !== null;
    for (const cls of ["reset", "resample", "new-wave", "clear"]) this.#el(`button.${cls}`, HTMLButtonElement).disabled = remote !== null;

    const train = this.#el("button.train", HTMLButtonElement);
    train.textContent = remote ? (remote.stopping ? "Stopping…" : "Stop") : this.#training ? "Pause" : "Train";
    const ready = remote ? !remote.stopping : this.#ready() || this.#training;
    train.setAttribute("aria-disabled", String(!ready));
    const empty = this.#isCurve() && this.#curve === null;
    const offline = grok && !connected();
    const hint = this.#el(".hint", HTMLParagraphElement);
    hint.hidden = !empty && !offline;
    hint.textContent = offline ? "Connect (top right) to train this one: it runs on the session's GPU"
      : !empty ? "" : this.#dataset === "wave" ? "draw a curve, or press New random curve" : "draw a curve, or pick Random wave";
    const filled = this.#isCurve() && this.#curve !== null ? gaps(this.#truth) : [];
    const note = [
      this.#remoteFailureNote,
      grok && this.#grok.kernelOutOfSync && remote === null ? "Train starts a new run." : "",
      this.#budgetLeft() ? "" : "Budget used up. Raise a budget or reset the weights to train again.",
      filled.length > 0 ? `Dashed parts were filled in: ${describeGaps(this.#truth)}.` : "",
    ].filter((m) => m !== "").join(" ");
    const need = this.#el(".need", HTMLParagraphElement);
    need.hidden = note === "";
    need.textContent = note;
  }

  #setTraining(on: boolean): void {
    if (on && !this.#ready()) return;
    this.#training = on;
    this.#lastTick = null;
    this.#syncControls();
    this.#announce(on ? "Training." : "Paused.");
    this.#updateLoop();
  }

  #startRemote(): void {
    if (!connected() || !this.#ready()) return;
    const isCurve = this.#isCurve();
    const config = remoteConfig(this.#net, this.#opt, this.#task(),
      { train: this.#train, test: isCurve ? this.#truthBatch : this.#heldOut, grid: isCurve ? CURVE_X : HEAT_XY },
      { lr: at(LRS, this.#lrK), dtype: REMOTE_DTYPE, step: this.#steps, seconds: this.#trainMs / 1000, stepBudget: this.#stepBudget(), timeBudget: this.#timeBudget() });
    const run: RemoteRun = { fromStep: this.#steps, fromMs: this.#trainMs, fromFlops: this.#flops, device: null, tick: null, end: null, stopping: false, failure: null };
    this.#remote = run;
    this.#training = true;
    this.#remoteFailureNote = "";
    this.#announce("Training remotely, on the connected session.");
    this.#syncControls();
    let pending = "";
    const onStdout = (text: string): void => {
      const split = splitLines(pending, text);
      pending = split.pending;
      for (const line of split.lines) this.#onRemoteLine(run, line);
    };
    const onStderr = (text: string): void => { console.warn(`<nn-fit> remote stderr: ${text}`); };
    runCode(remoteCode(config), onStdout, onStderr).then(
      (result) => { this.#remoteDone(run, result); },
      (cause: unknown) => { this.#remoteDone(run, { status: "aborted", reason: String(cause) }); },
    );
  }

  #adoptRemote(run: RemoteRun, end: Extract<RemoteLine, { kind: "end" }> | null): string | null {
    if (end === null) return "the remote run ended without its final state";
    try {
      loadState(this.#net, this.#opt, end.state);
    } catch (cause) {
      return cause instanceof Error ? cause.message : String(cause);
    }
    this.#steps = end.step;
    this.#trainMs = end.seconds * 1000;
    this.#device = run.device ?? "remote";
    return null;
  }

  #stopRemote(): void {
    const run = this.#remote ?? this.#grokFlight;
    if (run === null || run.stopping) return;
    run.stopping = true;
    this.#announce("Stopping the remote run.");
    this.#syncControls();
    interrupt().catch((cause: unknown) => {
      if (this.#remote !== run && this.#grokFlight !== run) return;
      run.stopping = false;
      this.#announce(`Couldn't stop the remote run: ${String(cause)}`);
      this.#syncControls();
    });
  }

  #onRemoteLine(run: RemoteRun, text: string): void {
    if (this.#remote !== run || run.failure !== null) return;
    let line: RemoteLine;
    try {
      line = parseLine(text);
    } catch (cause) {
      run.failure = cause instanceof Error ? cause.message : String(cause);
      this.#stopRemote();
      return;
    }
    switch (line.kind) {
      case "start":
        run.device = line.device === "cpu" ? "cpu (remote)" : `${line.device} · ${line.deviceName}`;
        break;
      case "tick":
        run.tick = line;
        this.#steps = line.step;
        this.#trainMs = line.seconds * 1000;
        this.#flops = run.fromFlops + (line.step - run.fromStep) * 6 * paramCount(this.#net) * this.#train.n;
        break;
      case "end":
        run.end = line;
        break;
    }
    this.#paint();
  }

  #remoteDone(run: RemoteRun, result: RunResult): void {
    if (this.#remote !== run) return;
    const end = run.end;
    const failure = run.failure ?? runFailure(result) ?? this.#adoptRemote(run, end);
    if (failure !== null) {
      this.#steps = run.fromStep;
      this.#trainMs = run.fromMs;
      this.#flops = run.fromFlops;
    }
    this.#remote = null;
    this.#training = false;
    if (failure !== null) console.error(`<nn-fit> remote run failed:\n${failure}`);
    this.#remoteFailureNote = failure === null ? "" : `Remote run failed: ${tracebackSummary(failure)}`;
    this.#announce(failure === null && end !== null ? `Remote run stopped: ${stopText(end.reason)}.` : this.#remoteFailureNote);
    this.#syncControls();
    this.#paint();
  }

  #newGrokRun(change: { splitSeed?: number; initSeed?: number }, message: string): void {
    const g = this.#grok;
    this.#grok = newGrokRun(g.fractionK, change.splitSeed ?? g.splitSeed, change.initSeed ?? g.initSeed);
    this.#remoteFailureNote = "";
    this.#announce(message);
    this.#syncControls();
    this.#paint();
  }

  #startGrok(): void {
    if (!connected() || !this.#ready()) return;
    if (this.#grok.kernelOutOfSync) this.#grok = newGrokRun(this.#grok.fractionK, this.#grok.splitSeed, this.#grok.initSeed);
    const run = this.#grok;
    const code = grokCode({
      run: run.id, p: GROK_P, train_fraction: at(TRAIN_FRACTIONS, run.fractionK), split_seed: run.splitSeed, init_seed: run.initSeed,
      step: run.steps, seconds: run.ms / 1000, max_steps: this.#stepBudget(), max_seconds: this.#timeBudget(), tick_seconds: GROK_TICK_SECONDS,
    });
    const flight: GrokFlight = { run, stopping: false, end: null, failure: null };
    this.#grokFlight = flight;
    this.#training = true;
    this.#remoteFailureNote = "";
    this.#announce("Training remotely, on the connected session.");
    this.#syncControls();
    let pending = "";
    const onStdout = (text: string): void => {
      const split = splitLines(pending, text);
      pending = split.pending;
      for (const line of split.lines) this.#onGrokLine(flight, line);
    };
    const onStderr = (text: string): void => { console.warn(`<nn-fit> remote stderr: ${text}`); };
    runCode(code, onStdout, onStderr).then(
      (result) => { this.#grokDone(flight, result); },
      (cause: unknown) => { this.#grokDone(flight, { status: "aborted", reason: String(cause) }); },
    );
  }

  #onGrokLine(flight: GrokFlight, text: string): void {
    if (this.#grokFlight !== flight || flight.failure !== null) return;
    const run = flight.run;
    try {
      const line = parseGrokLine(text);
      switch (line.kind) {
        case "start":
          run.start = line;
          break;
        case "tick":
          run.points = addPoint(run.points, { step: line.step, seconds: line.seconds, loss: line.loss, accuracy: line.accuracy, testLoss: line.testLoss, testAccuracy: line.testAccuracy });
          run.steps = line.step;
          run.ms = line.seconds * 1000;
          break;
        case "end":
          flight.end = line;
          break;
      }
    } catch (cause) {
      flight.failure = cause instanceof Error ? cause.message : String(cause);
      this.#stopRemote();
      return;
    }
    this.#paint();
  }

  #grokDone(flight: GrokFlight, result: RunResult): void {
    if (this.#grokFlight !== flight) return;
    const end = flight.end;
    const failure = flight.failure ?? runFailure(result) ?? (end === null ? "the remote run ended without saying why" : null);
    flight.run.kernelOutOfSync = failure !== null;
    this.#grokFlight = null;
    this.#training = false;
    if (failure !== null) console.error(`<nn-fit> remote run failed:\n${failure}`);
    this.#remoteFailureNote = failure === null ? "" : `Remote run failed: ${tracebackSummary(failure)}`;
    this.#announce(failure === null && end !== null ? `Remote run stopped: ${stopText(end.reason)}.` : this.#remoteFailureNote);
    this.#syncControls();
    this.#paint();
  }

  #announce(message: string): void {
    this.#el("[role=status]", HTMLParagraphElement).textContent = message;
    this.#lastAria = 0;
  }

  #updateLoop(): void {
    const run = this.#training && this.#remote === null && this.#grokFlight === null && this.#onScreen && !document.hidden;
    if (run && this.#frame === 0) this.#frame = requestAnimationFrame((t) => { this.#tick(t); });
    if (!run) this.#stopLoop();
  }

  #stopLoop(): void {
    if (this.#frame !== 0) cancelAnimationFrame(this.#frame);
    this.#frame = 0;
    this.#lastTick = null;
  }

  #tick(now: number): void {
    if (this.#lastTick !== null) this.#trainMs += Math.min(MAX_COUNTED_FRAME_MS, now - this.#lastTick);
    this.#lastTick = now;
    const batch = this.#train;
    if (batch.n > 0 && this.#dataReady()) {
      const task = this.#task();
      const lr = at(LRS, this.#lrK);
      const flopsPerStep = 6 * paramCount(this.#net) * batch.n;
      const start = performance.now();
      for (let i = 0; i < MAX_STEPS_PER_FRAME && this.#steps < this.#stepBudget() && performance.now() - start < MAX_TRAIN_MS_PER_FRAME; i++) {
        trainStep(this.#net, task, batch, this.#opt, lr);
        this.#steps++;
        this.#flops += flopsPerStep;
        this.#device = BROWSER_DEVICE;
      }
    }
    if (!this.#budgetLeft()) {
      const which = this.#steps >= this.#stepBudget() ? `step budget (${formatInt(this.#stepBudget())} steps)` : `time budget (${String(this.#timeBudget())} s)`;
      this.#frame = 0;
      this.#setTraining(false);
      this.#announce(`Stopped: ${which} used up.`);
      this.#paint(now);
      return;
    }
    if (!this.#reducedMotion.matches || now - this.#lastPaint >= REDUCED_MOTION_PAINT_INTERVAL_MS) this.#paint(now);
    this.#frame = requestAnimationFrame((t) => { this.#tick(t); });
  }

  #resize(): void {
    const canvas = this.#el("canvas", HTMLCanvasElement);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(canvas.clientWidth * dpr));
    canvas.height = Math.max(1, Math.round(canvas.clientHeight * dpr));
    this.#paint();
  }

  #toPlot(e: PointerEvent): Point {
    const rect = this.#el("canvas", HTMLCanvasElement).getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const y = (1 - ((e.clientY - rect.top) / rect.height) * 2) * Y_RANGE;
    return { x, y };
  }

  #colors(): Palette {
    if (this.#palette) return this.#palette;
    const style = getComputedStyle(this);
    const token = (name: string, fallback: string): string => style.getPropertyValue(name).trim() || fallback;
    const probe = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
    const rgb = (color: string): Rgb => {
      if (!probe) return [128, 128, 128];
      probe.clearRect(0, 0, 1, 1);
      probe.fillStyle = color;
      probe.fillRect(0, 0, 1, 1);
      const [r = 0, g = 0, b = 0] = probe.getImageData(0, 0, 1, 1).data;
      return [r, g, b];
    };
    const codeBg = token("--code-bg", "Canvas");
    const classA = token("--tok-number", "LinkText");
    const classB = token("--tok-string", "VisitedText");
    this.#palette = {
      fg: token("--fg", "CanvasText"),
      muted: token("--muted", "GrayText"),
      rule: token("--rule", "GrayText"),
      bg: token("--bg", "Canvas"),
      codeBg,
      net: classA,
      classA,
      classB,
      bgRgb: rgb(codeBg),
      aRgb: rgb(classA),
      bRgb: rgb(classB),
    };
    return this.#palette;
  }

  #paint(now = performance.now()): void {
    const ctx = this.#ctx;
    if (!ctx || !this.#built) return;
    this.#lastPaint = now;
    const canvas = ctx.canvas;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (this.#dataset === "grok") {
      const c = this.#colors();
      paintGrok(ctx, w, h, this.#grok.points, { fg: c.fg, muted: c.muted, rule: c.rule, train: c.fg, test: c.net });
    } else if (this.#isCurve()) this.#paintCurve(ctx, w, h);
    else this.#paintSpiral(ctx, w, h);
    this.#paintReadout(now);
  }

  #paintCurve(ctx: CanvasRenderingContext2D, w: number, h: number): void {
    const c = this.#colors();
    const px = (x: number): number => ((x + 1) / 2) * w;
    const py = (y: number): number => (1 - (y / Y_RANGE + 1) / 2) * h;
    ctx.lineWidth = 1;
    ctx.strokeStyle = c.rule;
    ctx.beginPath();
    ctx.moveTo(0, py(0)); ctx.lineTo(w, py(0));
    ctx.moveTo(px(0), 0); ctx.lineTo(px(0), h);
    ctx.stroke();

    ctx.save();
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.strokeStyle = c.fg;
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 3;
    let run = 0;
    ctx.beginPath();
    this.#truth.forEach((y, i) => {
      if (Number.isNaN(y)) { run = 0; return; }
      const x = px(columnX(COLUMNS, i));
      if (run === 0) ctx.moveTo(x, py(y)); else ctx.lineTo(x, py(y));
      const next = this.#truth[i + 1];
      if (run === 0 && (next === undefined || Number.isNaN(next))) ctx.arc(x, py(y), 1.5, 0, 2 * Math.PI);
      run++;
    });
    ctx.stroke();
    ctx.restore();

    const curve = this.#curve;
    if (curve !== null) {
      ctx.save();
      ctx.strokeStyle = c.muted;
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 4]);
      for (const { from, to } of gaps(this.#truth)) {
        ctx.beginPath();
        for (let i = Math.max(0, from - 1); i <= Math.min(COLUMNS - 1, to + 1); i++) {
          const x = i === 0 ? 0 : i === COLUMNS - 1 ? w : px(columnX(COLUMNS, i));
          const y = py(curve[i] ?? 0);
          if (i === Math.max(0, from - 1)) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      ctx.restore();
    }

    ctx.strokeStyle = c.net;
    ctx.lineWidth = 2;
    ctx.beginPath();
    this.#netCurve(w).forEach(([x, y], i) => {
      const sy = Math.max(-h, Math.min(2 * h, py(y)));
      if (i === 0) ctx.moveTo(px(x), sy); else ctx.lineTo(px(x), sy);
    });
    ctx.stroke();

    const r = this.#train.n > 128 ? 2.25 : 3.25;
    ctx.fillStyle = c.fg;
    ctx.strokeStyle = c.codeBg;
    ctx.lineWidth = 1;
    for (let s = 0; s < this.#train.n; s++) {
      ctx.beginPath();
      ctx.arc(px((this.#train.x[s] ?? 0) / INPUT_SCALE), py(this.#train.y[s] ?? 0), r, 0, 2 * Math.PI);
      ctx.fill();
      ctx.stroke();
    }
  }

  #netCurve(w: number): [number, number][] {
    const tick = this.#remote?.tick;
    if (tick) return Array.from(tick.pred, (y, i) => [get(CURVE_X, i) / INPUT_SCALE, y]);
    const f = predictor(this.#net, "regression");
    const input = new Float64Array(1);
    const points: [number, number][] = [];
    for (let sx = 0; sx <= w; sx += 2) {
      const x = (sx / w) * 2 - 1;
      input[0] = x * INPUT_SCALE;
      points.push([x, f(input)]);
    }
    return points;
  }

  #heatValues(w: number): { grid: number; p: Float64Array } {
    const tick = this.#remote?.tick;
    if (tick) return { grid: HEAT_GRID, p: tick.pred };
    const f = predictor(this.#net, "binary");
    const input = new Float64Array(2);
    const grid = Math.min(HEATMAP_MAX, Math.max(16, Math.ceil(w / HEAT_PX)));
    const p = new Float64Array(grid * grid);
    for (let j = 0; j < grid; j++) {
      for (let i = 0; i < grid; i++) {
        input[0] = (((i + 0.5) / grid) * 2 - 1) * INPUT_SCALE;
        input[1] = (1 - ((j + 0.5) / grid) * 2) * INPUT_SCALE;
        p[j * grid + i] = f(input);
      }
    }
    return { grid, p };
  }

  #paintSpiral(ctx: CanvasRenderingContext2D, w: number, h: number): void {
    const c = this.#colors();
    const { grid, p: heat } = this.#heatValues(w);
    this.#heat.width = grid;
    this.#heat.height = grid;
    const hctx = this.#heat.getContext("2d");
    if (!hctx) return;
    const img = hctx.createImageData(grid, grid);
    for (let j = 0; j < grid; j++) {
      for (let i = 0; i < grid; i++) {
        const p = get(heat, j * grid + i);
        const toward = p >= 0.5 ? c.aRgb : c.bRgb;
        const t = Math.abs(2 * p - 1) * 0.45;
        const o = 4 * (j * grid + i);
        for (let k = 0; k < 3; k++) img.data[o + k] = Math.round((c.bgRgb[k] ?? 0) * (1 - t) + (toward[k] ?? 0) * t);
        img.data[o + 3] = 255;
      }
    }
    hctx.putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(this.#heat, 0, 0, w, h);

    const px = (x: number): number => ((x / INPUT_SCALE + 1) / 2) * w;
    const py = (y: number): number => (1 - (y / INPUT_SCALE + 1) / 2) * h;
    const r = Math.max(2.5, w / 120);
    ctx.lineWidth = 1;
    ctx.strokeStyle = c.bg;
    const pts = this.#train;
    for (let s = 0; s < pts.n; s++) {
      const x = px(pts.x[2 * s] ?? 0);
      const y = py(pts.x[2 * s + 1] ?? 0);
      ctx.beginPath();
      if (pts.y[s] === 1) {
        ctx.fillStyle = c.classA;
        ctx.arc(x, y, r, 0, 2 * Math.PI);
      } else {
        ctx.fillStyle = c.classB;
        ctx.rect(x - r, y - r, 2 * r, 2 * r);
      }
      ctx.fill();
      ctx.stroke();
    }
  }

  #paintReadout(now: number): void {
    if (this.#dataset === "grok") { this.#paintGrokReadout(now); return; }
    const s = this.#mlpStats();
    const arch = `${s.sizes.join(" → ")} (${formatInt(s.params)} params)`;
    const b = (v: string): string => `<b>${v}</b>`;
    const metrics = this.#isCurve()
      ? [`train MSE ${s.loss === null ? "—" : b(formatLoss(s.loss))}`, `vs true curve ${s.trueError === null ? "—" : b(formatLoss(s.trueError))}`]
      : [`train loss ${s.loss === null ? "—" : b(formatLoss(s.loss))}`, `train accuracy ${b(formatPct(s.accuracy ?? 0))}`,
        `held-out accuracy ${b(formatPct(s.heldOutAccuracy ?? 0))}`];
    const budget = this.#budgetText();
    const usage = [
      `step ${formatInt(s.steps)}${budget.steps}`,
      `${s.seconds.toFixed(1)} s${budget.seconds}`,
      `~${formatFlops(s.flops)}`,
      arch,
      `on ${s.device}`,
    ];
    this.#el(".metrics", HTMLSpanElement).innerHTML = metrics.join(" · ");
    this.#el(".usage", HTMLSpanElement).innerHTML = usage.join(" · ");

    if (now - this.#lastAria < ARIA_MS && this.#frame !== 0) return;
    this.#lastAria = now;
    const lossText = s.loss === null ? "no loss yet" : `training loss ${formatLoss(s.loss)}`;
    const net = `a ${s.sizes.join("-")} network with ${this.#activation} hidden units, ${lossText} after ${String(s.steps)} steps`;
    const label = this.#isCurve()
      ? this.#curve === null
        ? `Empty drawing area. Draw a curve with a pointer, or choose Random wave. The plot shows ${net}.`
        : `${this.#dataset === "wave" ? "A random wave" : "Your drawn function"} (faint${gaps(this.#truth).length > 0 ? `; filled in, dashed: ${describeGaps(this.#truth)}` : ""}), ${String(s.samples)} training samples as dots, and the fit of ${net}${s.trueError === null ? "" : `; error against the true curve ${formatLoss(s.trueError)}`}.`
      : `Spiral of ${String(s.samples)} training points in two classes, background shaded by the prediction of ${net}, training accuracy ${formatPct(s.accuracy ?? 0)}, held-out accuracy ${formatPct(s.heldOutAccuracy ?? 0)}.`;
    this.#el("canvas", HTMLCanvasElement).setAttribute("aria-label", label);
  }

  #paintGrokReadout(now: number): void {
    const s = this.stats;
    const g = s.grok;
    if (g === null) throw new Error("grok stats outside the grok dataset");
    const b = (v: string): string => `<b>${v}</b>`;
    const pct = (a: number | null): string => (a === null ? "—" : b(formatPct(a)));
    const loss = (l: number | null): string => (l === null ? "—" : b(formatLoss(l)));
    const budget = this.#budgetText();
    const pairs = `a + b mod ${String(g.p)}: trains on ${s.samples === null ? "—" : formatInt(s.samples)} of ${formatInt(g.p * g.p)} pairs`;
    this.#el(".metrics", HTMLSpanElement).innerHTML = [`train accuracy ${pct(s.accuracy)}`, `test accuracy ${pct(s.heldOutAccuracy)}`,
      `train loss ${loss(s.loss)}`, `test loss ${loss(g.testLoss)}`,
      ...(g.grokked === null ? [] : [`test past 95% at step ${b(formatInt(g.grokked.step))} (${g.grokked.seconds.toFixed(1)} s)`])].join(" · ");
    this.#el(".usage", HTMLSpanElement).innerHTML = [`step ${formatInt(s.steps)}${budget.steps}`, `${s.seconds.toFixed(1)} s${budget.seconds}`,
      s.flops === null ? "—" : `~${formatFlops(s.flops)}`, pairs, g.model === null || s.params === null ? "—" : `${g.model} (${formatInt(s.params)} params)`,
      `on ${s.device}`].join(" · ");

    if (now - this.#lastAria < ARIA_MS && this.#grokFlight !== null) return;
    this.#lastAria = now;
    const state = s.steps === 0 ? "Not trained yet." : `After ${String(s.steps)} steps: train accuracy ${formatPct(s.accuracy ?? 0)}, test accuracy ${formatPct(s.heldOutAccuracy ?? 0)}.`;
    this.#el("canvas", HTMLCanvasElement).setAttribute("aria-label",
      `Train and test accuracy against training step (log scale) for a 1-layer transformer learning ${pairs}. ${state}`);
  }
}

customElements.define("nn-fit", NnFit);
