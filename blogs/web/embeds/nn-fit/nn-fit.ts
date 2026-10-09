// <nn-fit>: watch a small MLP fit a hidden function from a few noisy samples, or classify a spiral.
// TensorFlow-Playground style. Self-contained: shadow DOM with its own styles, colours from page.css
// tokens (custom properties inherit into the shadow root), no ML dependencies.
//
// Initial config comes from attributes, all optional (values snap to the nearest slider stop):
//   dataset="draw|wave|spiral" activation="linear|relu|tanh|sigmoid" layers="0..4" width="1..16"
//   widths="8,4,..." lr="0.03" samples="4..512" noise="0..0.5" wiggles="1..20" roughness="0.5..3"
//   stages="1..4" seed="1" step-budget="2000" time-budget="5"
// Read-only `stats` exposes the live numbers (tests and any host page can read them).
//
// Backends: training runs in this browser (mlp.ts), or, while the page is connected (Connect, connect/kernel.ts),
// on the session's kernel: remote_train.py in torch, from the same weights on the same data, streaming ticks into
// the same plot.
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

export type Dataset = "draw" | "wave" | "spiral";
const DATASETS: readonly Dataset[] = ["draw", "wave", "spiral"];
export type Backend = "browser" | "remote";
const BROWSER = "this browser"; // what `device` says after a browser run
const connected = (): boolean => kernelState() === "idle" || kernelState() === "busy";

export interface NnFitStats {
  readonly dataset: Dataset;
  readonly sizes: readonly number[];
  readonly params: number;
  readonly samples: number; // training points (spiral: total over both classes)
  readonly loss: number | null; // training loss on the samples; null with no data
  readonly trueError: number | null; // draw/wave: MSE of the net against the whole clean curve
  readonly accuracy: number | null; // spiral: on the training points
  readonly heldOutAccuracy: number | null; // spiral: on a fresh sample from the same spiral
  readonly steps: number;
  readonly seconds: number; // training wall-clock time used
  readonly flops: number; // estimated: 6 * params * samples per step
  readonly stepBudget: number; // Infinity = off
  readonly timeBudget: number; // seconds, Infinity = off
  readonly training: boolean; // the reader pressed Train (it may still be paused offscreen); remote: a run is in flight
  readonly ready: boolean; // Train is enabled: something is drawn (or spiral) and budget remains
  readonly backend: Backend;
  readonly device: string; // what trained (or is training) the current weights: "this browser", "cuda · Tesla T4"
}

// A remote run in flight: its latest tick is what the plot and readout show until it ends.
interface RemoteRun {
  // The widget's counters when it started: ticks count on from them, and a failed run puts them back.
  readonly fromStep: number;
  readonly fromMs: number;
  readonly fromFlops: number;
  device: string | null; // from its "start" line
  tick: RemoteTick | null;
  end: Extract<RemoteLine, { kind: "end" }> | null;
  stopping: boolean; // the reader pressed Stop; the interrupt is sent
  failure: string | null; // a line that didn't parse, or the state that didn't load
}

// Judgement calls (see the report). Training: full-batch Adam, up to STEPS_PER_FRAME steps per animation
// frame (fewer if a frame's steps take FRAME_MS, or a step budget is about to run out).
const STEPS_PER_FRAME = 8;
const FRAME_MS = 12;
const COLUMNS = 640; // resolution of the true curve; 160 undersampled composed waves (see the report)
const MAX_LAYERS = 4;
const MAX_WIDTH = 16;
const HEAT_PX = 4;
const HEATMAP_MAX = 128;
const LRS = Array.from({ length: 17 }, (_, k) => 10 ** (-4 + k / 4)); // 1e-4 .. 1, log scale
const NOISES = Array.from({ length: 11 }, (_, k) => k * 0.05); // sigma 0 .. 0.5 in y units (curve spans [-1, 1])
const ROUGHNESSES = Array.from({ length: 11 }, (_, k) => 3 - k * 0.25); // alpha: 3 (smooth) .. 0.5 (rough)
const STEP_BUDGETS = [500, 1000, 2000, 5000, 10000, 20000, 50000, Infinity];
const TIME_BUDGETS = [1, 2, 5, 10, 20, 30, 60, Infinity];
const SPIRAL_JITTER = 2; // spiral jitter (playground units, arms reach radius 5) per unit of sigma
const HELD_OUT = 500;
const HELD_OUT_SEED = 1000;
const Y_RANGE = 1.2; // the curve view shows y in [-Y_RANGE, Y_RANGE]; drawn values are clamped to [-1, 1]
const REDUCED_MOTION_MS = 250; // with prefers-reduced-motion, redraw at 4 Hz while training
const ARIA_MS = 1000;
const MAX_FRAME_GAP_MS = 100; // wall-clock counted per frame is capped, so a stalled tab doesn't eat the budget
const REMOTE_DTYPE = "float32"; // what a GPU runs fast; parity with mlp.ts's float64: remote_train_test.py
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
      <select class="dataset"><option value="draw">Draw a function</option><option value="wave">Random wave</option><option value="spiral">Spiral</option></select></label>
    ${range("samples", "Samples", SAMPLE_COUNTS.length - 1)}
    ${range("noise", "Noise σ", NOISES.length - 1)}
    <div class="wave-only" style="display: contents">
      ${range("wiggles", "Wiggles K", MAX_WIGGLES - 1)}
      ${range("roughness", "Roughness α", ROUGHNESSES.length - 1)}
      ${range("stages", "Stages d", MAX_STAGES - 1)}
    </div>
  </div>
  <details class="wave-only"><summary>show formula</summary><pre class="formula"></pre></details>
</fieldset>
<fieldset class="network">
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

// A canvas colour as numbers, for the heatmap's per-pixel mixing.
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
// A Python traceback's last line says what went wrong; the rest is in the browser console.
const lastLine = (error: string): string => error.trim().split("\n").at(-1) ?? error;

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

  // Settings (slider stops are indices into the lists above).
  #dataset: Dataset = "draw";
  #activation: Activation = "tanh";
  #layers = 2;
  #widths: number[] = Array.from({ length: MAX_LAYERS }, () => 8); // kept for layers that are removed and re-added
  #lrK = nearest(LRS, 0.03);
  #samplesK = SAMPLE_COUNTS.indexOf(128);
  #noiseK = 0;
  #wave = { wiggles: 4, roughnessK: nearest(ROUGHNESSES, 1.5), stages: 1, seed: 1 };
  #stepBudgetK = STEP_BUDGETS.length - 1;
  #timeBudgetK = TIME_BUDGETS.length - 1;
  #seed = 1; // weights
  #sampleSeed = 1;

  // Model and usage.
  #net: Mlp = initMlp([1, 8, 8, 1], "tanh", seeded(1));
  #opt: Adam = makeAdam(this.#net);
  #steps = 0;
  #trainMs = 0;
  #flops = 0;
  #backend: Backend = "browser";
  #remote: RemoteRun | null = null;
  #device = BROWSER;
  #remoteNote = ""; // why the last remote run failed; shown under the plot until the next run

  // Data: the true curve (drawn or generated), the training sample drawn from it, the spiral's held-out set.
  #truth: DrawBuffer = makeDrawBuffer(COLUMNS);
  #truthBatch: Batch = EMPTY;
  #curve: DrawBuffer | null = null; // the drawing with gaps filled (completeCurve); null when empty
  #train: Batch = EMPTY;
  #heldOut: Batch = EMPTY;
  #waveStages: WaveStage[] = [];
  #stroke: { pointer: number; last: Point } | null = null;

  // Loop: runs only while the reader wants training AND the widget is on screen AND the tab is visible.
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
    const metrics = this.#remote?.tick ? this.#tickMetrics(this.#remote.tick) : this.#metrics();
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
    };
  }

  // The four metrics, from the browser's net (the plot's net between runs and during browser runs).
  #metrics(): Pick<NnFitStats, "loss" | "trueError" | "accuracy" | "heldOutAccuracy"> {
    const task = this.#task();
    const train = this.#train.n > 0 ? evaluate(this.#net, task, this.#train) : null;
    const curve = this.#isCurve() && this.#truthBatch.n > 0 ? evaluate(this.#net, task, this.#truthBatch) : null;
    const held = !this.#isCurve() && this.#heldOut.n > 0 ? evaluate(this.#net, task, this.#heldOut) : null;
    return { loss: train?.loss ?? null, trueError: curve?.loss ?? null, accuracy: train?.accuracy ?? null, heldOutAccuracy: held?.accuracy ?? null };
  }

  // The same four, from a remote tick: its test set is the true curve (draw/wave) or the held-out sample (spiral).
  #tickMetrics(tick: RemoteTick): Pick<NnFitStats, "loss" | "trueError" | "accuracy" | "heldOutAccuracy"> {
    const curve = this.#isCurve();
    return { loss: tick.loss, trueError: curve ? tick.testLoss : null, accuracy: tick.accuracy, heldOutAccuracy: curve ? null : tick.testAccuracy };
  }

  // The curve the net is trained and scored against (the drawing with gaps filled), or null when empty.
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
    this.#stopRemote(); // a remote run doesn't outlive the widget that started it (e.g. a closed link card)
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
    this.#noiseK = pick("noise", NOISES, this.#noiseK);
    this.#stepBudgetK = pick("step-budget", STEP_BUDGETS, this.#stepBudgetK);
    this.#timeBudgetK = pick("time-budget", TIME_BUDGETS, this.#timeBudgetK);
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
      if (this.#remote) this.#stopRemote();
      else if (this.#backend === "remote") this.#startRemote();
      else this.#setTraining(!this.#training);
    });
    button("reset", () => {
      this.#seed++;
      this.#rebuildNet();
      this.#announce("Weights reset to new random values; step and time counters back to zero.");
    });
    button("resample", () => {
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
      this.#dataChanged(); // announces the pause if training was running
    });

    const select = this.#el("select.dataset", HTMLSelectElement);
    on(select, "change", () => {
      if (!isDataset(select.value)) return;
      const inputsBefore = this.#inputs();
      this.#dataset = select.value;
      this.#announce(
        select.value === "draw" ? "Draw a function on the plot, edge to edge."
          : select.value === "wave" ? "Random wave generated. You can draw over it to edit it."
            : "Spiral dataset: two classes.");
      if (this.#training && !this.#ready()) this.#setTraining(false);
      // draw <-> wave keeps the weights. Otherwise the net's input count changes: build it without painting,
      // since painting it on the old dataset's points reads past their end; the new data paints both.
      if (this.#inputs() !== inputsBefore) this.#makeNet();
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
      if (this.#training) this.#setTraining(false); // a browser run pauses; the select is disabled during a remote run
      this.#backend = backend.value;
      this.#announce(backend.value === "remote" ? "Train runs remotely, on the connected session." : "Train runs in this browser.");
      this.#syncControls();
      this.#paint();
    });
    // The page's session comes and goes (Connect / disconnect): remote is offered only while there is one.
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
    slider("lr", (v) => { this.#lrK = v; }, nothing); // keeps the weights: change the step size mid-run
    slider("layers", (v) => { this.#layers = v; }, () => { this.#rebuildNet(); });
    slider("samples", (v) => { this.#samplesK = v; }, () => { this.#resample(); }); // keeps the weights
    slider("noise", (v) => { this.#noiseK = v; }, () => { this.#resample(); });
    slider("wiggles", (v) => { this.#wave = { ...this.#wave, wiggles: v + 1 }; }, () => { this.#regenWave(); });
    slider("roughness", (v) => { this.#wave = { ...this.#wave, roughnessK: v }; }, () => { this.#regenWave(); });
    slider("stages", (v) => { this.#wave = { ...this.#wave, stages: v + 1 }; }, () => { this.#regenWave(); });
    slider("step-budget", (v) => { this.#stepBudgetK = v; }, nothing);
    slider("time-budget", (v) => { this.#timeBudgetK = v; }, nothing);

    // Per-layer widths: a number input per layer (the keyboard/AT control) flanked by -/+ buttons for pointers.
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

    // Drawing (draw and wave): one stroke per pointer, captured so it continues outside the canvas.
    on(canvas, "pointerdown", (e) => {
      if (!this.#isCurve() || this.#stroke || this.#remote) return; // the data is fixed while a remote run trains on it
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
    // Theme changes: the page flips data-scheme/data-theme on <html>, or the OS scheme changes.
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

  // --- model and data ---

  #isCurve(): boolean {
    return this.#dataset !== "spiral";
  }

  #task(): Task {
    return this.#isCurve() ? "regression" : "binary";
  }

  #inputs(): number {
    return this.#isCurve() ? 1 : 2;
  }

  // Budgets in force: a remote run always stops, so there "off" means the remote cap.
  #stepBudget(): number {
    const budget = at(STEP_BUDGETS, this.#stepBudgetK);
    return this.#backend === "remote" ? Math.min(budget, REMOTE_MAX_STEPS) : budget;
  }

  #timeBudget(): number {
    const budget = at(TIME_BUDGETS, this.#timeBudgetK);
    return this.#backend === "remote" ? Math.min(budget, REMOTE_MAX_SECONDS) : budget;
  }

  #budgetLeft(): boolean {
    return this.#steps < this.#stepBudget() && this.#trainMs < this.#timeBudget() * 1000;
  }

  // Train is enabled when the data is usable and budget remains.
  #dataReady(): boolean {
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

  // Fresh weights for the current settings, counters back to zero; no repaint.
  #makeNet(): void {
    const sizes = [this.#inputs(), ...this.#widths.slice(0, this.#layers), 1];
    this.#net = initMlp(sizes, this.#activation, seeded(this.#seed));
    this.#opt = makeAdam(this.#net);
    this.#steps = 0;
    this.#trainMs = 0;
    this.#flops = 0;
    this.#device = BROWSER;
  }

  // Regenerate the wave from its parameters (same seed: the slider changes reshape the same curve).
  #regenWave(): void {
    if (this.#dataset !== "wave") return;
    const params = this.#waveParams();
    this.#waveStages = waveStages(params, seeded);
    this.#truth = makeDrawBuffer(COLUMNS);
    fillWave(this.#truth, this.#waveStages);
    this.#el("pre.formula", HTMLPreElement).textContent = waveFormula(params, this.#waveStages);
    this.#dataChanged();
  }

  // The true curve changed (drawn, cleared, generated) or the dataset switched.
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

  // Training data from the current source, sample count, noise and sample seed. Keeps the weights.
  #resample(): void {
    const n = at(SAMPLE_COUNTS, this.#samplesK);
    const sigma = at(NOISES, this.#noiseK);
    if (this.#isCurve()) {
      this.#train = this.#curve === null ? EMPTY : curveSamples(this.#curve, n, sigma, seeded(this.#sampleSeed));
      this.#heldOut = EMPTY;
    } else {
      this.#train = spiral(n, sigma * SPIRAL_JITTER, seeded(this.#sampleSeed));
      this.#heldOut = spiral(HELD_OUT, sigma * SPIRAL_JITTER, seeded(HELD_OUT_SEED));
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
    for (const el of this.#root.querySelectorAll(".curve-only")) el.toggleAttribute("hidden", !isCurve);
    for (const el of this.#root.querySelectorAll(".spiral-only")) el.toggleAttribute("hidden", isCurve);
    for (const el of this.#root.querySelectorAll(".wave-only")) el.toggleAttribute("hidden", this.#dataset !== "wave");
    this.#el(".stage", HTMLDivElement).classList.toggle("spiral", !isCurve);

    const set = (cls: string, index: number, text: string): void => {
      const input = this.#el(`input.${cls}`, HTMLInputElement);
      input.value = String(index);
      input.setAttribute("aria-valuetext", text);
      this.#el(`output.${cls}-out`, HTMLOutputElement).value = text;
    };
    const n = at(SAMPLE_COUNTS, this.#samplesK);
    set("samples", this.#samplesK, String(n));
    set("noise", this.#noiseK, at(NOISES, this.#noiseK).toFixed(2));
    set("lr", this.#lrK, formatLr(at(LRS, this.#lrK)));
    set("layers", this.#layers, String(this.#layers));
    set("wiggles", this.#wave.wiggles - 1, String(this.#wave.wiggles));
    set("roughness", this.#wave.roughnessK, at(ROUGHNESSES, this.#wave.roughnessK).toFixed(2));
    set("stages", this.#wave.stages - 1, String(this.#wave.stages));
    // The sliders show the reader's setting; the readout shows what's in force (remote caps "off").
    set("step-budget", this.#stepBudgetK, formatBudget(at(STEP_BUDGETS, this.#stepBudgetK), ""));
    set("time-budget", this.#timeBudgetK, formatBudget(at(TIME_BUDGETS, this.#timeBudgetK), " s"));
    this.#renderWidths();

    const remote = this.#remote;
    const option = this.#el("select.backend option[value=remote]", HTMLOptionElement);
    option.disabled = !connected();
    option.textContent = connected() ? "remote (the connected session)" : "remote (Connect first)";
    this.#el("select.backend", HTMLSelectElement).value = this.#backend;
    // While a remote run trains, everything it was sent stays as it was: data, network, budgets, backend.
    for (const cls of ["data", "network", "compute"]) this.#el(`fieldset.${cls}`, HTMLFieldSetElement).disabled = remote !== null;
    for (const cls of ["reset", "resample", "new-wave", "clear"]) this.#el(`button.${cls}`, HTMLButtonElement).disabled = remote !== null;

    const train = this.#el("button.train", HTMLButtonElement);
    train.textContent = remote ? (remote.stopping ? "Stopping…" : "Stop") : this.#training ? "Pause" : "Train";
    // aria-disabled rather than disabled: the button stays focusable, so a screen reader still reaches
    // it and reads its description (the centred hint, then the note line) saying why it can't train.
    const ready = remote ? !remote.stopping : this.#ready() || this.#training;
    train.setAttribute("aria-disabled", String(!ready));
    // Hidden elements referenced by aria-describedby still count toward the description, so a hidden
    // message is also emptied.
    const empty = this.#isCurve() && this.#curve === null;
    const hint = this.#el(".hint", HTMLParagraphElement);
    hint.hidden = !empty;
    hint.textContent = !empty ? "" : this.#dataset === "wave" ? "draw a curve, or press New random curve" : "draw a curve, or pick Random wave";
    const filled = this.#isCurve() && this.#curve !== null ? gaps(this.#truth) : [];
    const note = [
      this.#remoteNote,
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

  // --- remote runs ---

  // Send the current weights, optimizer state and data to the connected session and stream its ticks in.
  // Everything a run depends on is fixed while it runs (the controls are disabled), so its end state lands
  // on the same net it started from.
  #startRemote(): void {
    if (!connected() || !this.#ready()) return;
    const isCurve = this.#isCurve();
    const config = remoteConfig(this.#net, this.#opt, this.#task(),
      { train: this.#train, test: isCurve ? this.#truthBatch : this.#heldOut, grid: isCurve ? CURVE_X : HEAT_XY },
      { lr: at(LRS, this.#lrK), dtype: REMOTE_DTYPE, step: this.#steps, seconds: this.#trainMs / 1000, stepBudget: this.#stepBudget(), timeBudget: this.#timeBudget() });
    const run: RemoteRun = { fromStep: this.#steps, fromMs: this.#trainMs, fromFlops: this.#flops, device: null, tick: null, end: null, stopping: false, failure: null };
    this.#remote = run;
    this.#training = true;
    this.#remoteNote = "";
    this.#announce("Training remotely, on the connected session.");
    this.#syncControls();
    let pending = "";
    const onStdout = (text: string): void => {
      const split = splitLines(pending, text);
      pending = split.pending;
      for (const line of split.lines) this.#onRemoteLine(run, line);
    };
    // stderr (library warnings) goes to the console, not the line parser: only the program's stdout is protocol.
    const onStderr = (text: string): void => { console.warn(`<nn-fit> remote stderr: ${text}`); };
    runCode(remoteCode(config), onStdout, onStderr).then(
      (result) => { this.#remoteDone(run, result); },
      (err: unknown) => { this.#remoteDone(run, { status: "aborted", reason: String(err) }); }, // runCode resolves its failures; this is a bug
    );
  }

  // Take a finished run's weights and counters; returns why not, if its state doesn't fit this net.
  #adoptRemote(run: RemoteRun, end: Extract<RemoteLine, { kind: "end" }> | null): string | null {
    if (end === null) return "the remote run ended without its final state";
    try {
      loadState(this.#net, this.#opt, end.state);
    } catch (err) {
      return err instanceof Error ? err.message : String(err);
    }
    this.#steps = end.step;
    this.#trainMs = end.seconds * 1000;
    this.#device = run.device ?? "remote";
    return null;
  }

  #stopRemote(): void {
    const run = this.#remote;
    if (run === null || run.stopping) return;
    run.stopping = true;
    this.#announce("Stopping the remote run.");
    this.#syncControls();
    interrupt().catch((err: unknown) => {
      if (this.#remote !== run) return;
      run.stopping = false; // still running: Stop can be pressed again
      this.#announce(`Couldn't stop the remote run: ${String(err)}`);
      this.#syncControls();
    });
  }

  // One line of the program's stdout. A line that doesn't parse stops the run: its output can't be trusted.
  #onRemoteLine(run: RemoteRun, text: string): void {
    if (this.#remote !== run || run.failure !== null) return;
    let line: RemoteLine;
    try {
      line = parseLine(text);
    } catch (err) {
      run.failure = err instanceof Error ? err.message : String(err);
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

  // The run's code finished (or never ran, or the session went away). Keep its final weights if it said them.
  #remoteDone(run: RemoteRun, result: RunResult): void {
    if (this.#remote !== run) return;
    const end = run.end;
    const failure = run.failure ?? runFailure(result) ?? this.#adoptRemote(run, end);
    if (failure !== null) { // the weights are still the ones it started from: so are the counters
      this.#steps = run.fromStep;
      this.#trainMs = run.fromMs;
      this.#flops = run.fromFlops;
    }
    this.#remote = null;
    this.#training = false;
    if (failure !== null) console.error(`<nn-fit> remote run failed:\n${failure}`);
    this.#remoteNote = failure === null ? "" : `Remote run failed: ${lastLine(failure)}`;
    this.#announce(failure === null && end !== null ? `Remote run stopped: ${stopText(end.reason)}.` : this.#remoteNote);
    this.#syncControls();
    this.#paint();
  }

  #announce(message: string): void {
    this.#el("[role=status]", HTMLParagraphElement).textContent = message;
    this.#lastAria = 0; // describe the new state right away
  }

  // --- loop ---

  #updateLoop(): void {
    const run = this.#training && this.#remote === null && this.#onScreen && !document.hidden;
    if (run && this.#frame === 0) this.#frame = requestAnimationFrame((t) => { this.#tick(t); });
    if (!run) this.#stopLoop();
  }

  #stopLoop(): void {
    if (this.#frame !== 0) cancelAnimationFrame(this.#frame);
    this.#frame = 0;
    this.#lastTick = null; // time offscreen or paused doesn't count against the time budget
  }

  #tick(now: number): void {
    if (this.#lastTick !== null) this.#trainMs += Math.min(MAX_FRAME_GAP_MS, now - this.#lastTick);
    this.#lastTick = now;
    const batch = this.#train;
    if (batch.n > 0 && this.#dataReady()) {
      const task = this.#task();
      const lr = at(LRS, this.#lrK);
      const flopsPerStep = 6 * paramCount(this.#net) * batch.n;
      const start = performance.now();
      for (let i = 0; i < STEPS_PER_FRAME && this.#steps < this.#stepBudget() && performance.now() - start < FRAME_MS; i++) {
        trainStep(this.#net, task, batch, this.#opt, lr);
        this.#steps++;
        this.#flops += flopsPerStep;
        this.#device = BROWSER;
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
    if (!this.#reducedMotion.matches || now - this.#lastPaint >= REDUCED_MOTION_MS) this.#paint(now);
    this.#frame = requestAnimationFrame((t) => { this.#tick(t); });
  }

  // --- rendering ---

  #resize(): void {
    const canvas = this.#el("canvas", HTMLCanvasElement);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(canvas.clientWidth * dpr));
    canvas.height = Math.max(1, Math.round(canvas.clientHeight * dpr));
    this.#paint();
  }

  // Pointer position -> plot coordinates (x, y in [-1, 1] for drawing; y is clamped by paintStroke).
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
    if (this.#isCurve()) this.#paintCurve(ctx, w, h);
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

    // The true curve, faint: one polyline per run of known columns.
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

    // Filled-in parts of the curve (completeCurve): dashed and muted, joined to the drawn ends.
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

    // The network's curve: the browser's net sampled every 2 CSS px across the whole width, or during a
    // remote run, its latest predictions (on CURVE_X).
    ctx.strokeStyle = c.net;
    ctx.lineWidth = 2;
    ctx.beginPath();
    this.#netCurve(w).forEach(([x, y], i) => {
      const sy = Math.max(-h, Math.min(2 * h, py(y)));
      if (i === 0) ctx.moveTo(px(x), sy); else ctx.lineTo(px(x), sy);
    });
    ctx.stroke();

    // Training samples on top.
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

  // (plot x, y-hat) points along the network's curve.
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

  // P(class A) on a grid x grid raster (row-major, top row first): the browser's net at about one cell per
  // HEAT_PX, or during a remote run, its latest predictions (on HEAT_XY).
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
    // Heatmap: P(class A) mixed from the background toward the winning class's colour by confidence, then
    // scaled up with smoothing.
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

    // Training points: class A circles, class B squares (shape as well as colour).
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
    const s = this.stats;
    const arch = `${s.sizes.join(" → ")} (${formatInt(s.params)} params)`;
    const b = (v: string): string => `<b>${v}</b>`;
    const metrics = this.#isCurve()
      ? [`train MSE ${s.loss === null ? "—" : b(formatLoss(s.loss))}`, `vs true curve ${s.trueError === null ? "—" : b(formatLoss(s.trueError))}`]
      : [`train loss ${s.loss === null ? "—" : b(formatLoss(s.loss))}`, `train accuracy ${b(formatPct(s.accuracy ?? 0))}`,
        `held-out accuracy ${b(formatPct(s.heldOutAccuracy ?? 0))}`];
    const of = (budget: number, unit: string): string => (budget === Infinity ? "" : ` / ${formatInt(budget)}${unit}`);
    const usage = [
      `step ${formatInt(s.steps)}${of(s.stepBudget, "")}`,
      `${s.seconds.toFixed(1)} s${of(s.timeBudget, " s")}`,
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
}

customElements.define("nn-fit", NnFit);
