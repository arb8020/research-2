// <nn-fit>: watch a small MLP fit a function the reader draws, or classify a spiral.
// TensorFlow-Playground style. Self-contained: shadow DOM with its own styles, colours from page.css
// tokens (custom properties inherit into the shadow root), no ML dependencies.
//
// Initial config comes from attributes, all optional:
//   <nn-fit dataset="draw|spiral" activation="linear|relu|tanh|sigmoid" layers="0..4" width="1..16" lr="0.03">
// Read-only `stats` exposes the live numbers (tests and any host page can read them).
import { must } from "../../dom";
import type { Activation, Adam, Batch, Mlp, Task } from "./mlp";
import { ACTIVATIONS, evaluate, initMlp, makeAdam, paramCount, predictor, seeded, trainStep } from "./mlp";
import type { DrawBuffer, Point } from "./datasets";
import { INPUT_SCALE, columnX, drawSamples, fillExample, filledColumns, makeDrawBuffer, paintStroke, spiral } from "./datasets";

export type Dataset = "draw" | "spiral";
const DATASETS: readonly Dataset[] = ["draw", "spiral"];

export interface NnFitStats {
  readonly dataset: Dataset;
  readonly steps: number;
  readonly samples: number;
  readonly loss: number | null; // null with no data
  readonly accuracy: number | null; // spiral only
  readonly training: boolean; // the reader pressed Train (it may still be paused offscreen)
}

// Judgement calls (see the report): full-batch Adam, a few steps per animation frame, 160 draw columns,
// a spiral heatmap grid of one cell per HEAT_PX CSS px (capped at HEATMAP_MAX), learning rate 10^(-4 + k/4) for slider k in 0..16.
const STEPS_PER_FRAME = 8;
const COLUMNS = 160;
const HEAT_PX = 4;
const HEATMAP_MAX = 128;
const LR_STEPS = 16;
const lrAt = (k: number): number => 10 ** (-4 + k / 4);
const lrIndex = (lr: number): number => Math.min(LR_STEPS, Math.max(0, Math.round((Math.log10(lr) + 4) * 4)));
const Y_RANGE = 1.2; // draw view shows y in [-Y_RANGE, Y_RANGE]; drawn values are clamped to [-1, 1]
const SPIRAL_PER_CLASS = 100;
const SPIRAL_NOISE = 0.15;
const REDUCED_MOTION_MS = 250; // with prefers-reduced-motion, redraw at 4 Hz while training
const ARIA_MS = 1000;

const isActivation = (s: string): s is Activation => ACTIVATIONS.some((a) => a === s);
const isDataset = (s: string): s is Dataset => DATASETS.some((d) => d === s);

function intAttr(el: Element, name: string, lo: number, hi: number, fallback: number): number {
  const raw = el.getAttribute(name);
  if (raw === null) return fallback;
  const v = Number(raw);
  if (!Number.isInteger(v) || v < lo || v > hi) throw new Error(`<nn-fit ${name}="${raw}">: expected an integer in ${String(lo)}..${String(hi)}`);
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
.hint { position: absolute; inset: 0; display: grid; place-items: center; margin: 0; color: var(--muted); pointer-events: none; }
.hint[hidden] { display: none; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 6px 0 0; color: var(--muted); }
.legend span::before { content: ""; display: inline-block; width: 14px; height: 0; margin-right: 6px; vertical-align: middle;
                       border-top: 2.5px solid var(--swatch); }
.legend .dot::before { width: 8px; height: 8px; border: 0; border-radius: 50%; background: var(--swatch); }
.legend .square::before { width: 8px; height: 8px; border: 0; border-radius: 1px; background: var(--swatch); }
.legend [hidden] { display: none; }
.buttons { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0 10px; }
button { font: inherit; min-height: 30px; padding: 4px 12px; border: 1px solid var(--rule); border-radius: 4px;
         background: var(--bg); color: var(--fg); cursor: pointer; }
button:hover { background: var(--active, var(--code-bg)); }
button.train { min-width: 72px; border-color: var(--muted); }
button[hidden] { display: none; }
.controls { display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); gap: 8px 24px; }
.control { display: grid; grid-template-columns: 9.5em minmax(60px, 1fr) 3.5em; align-items: center; gap: 8px; color: var(--muted); white-space: nowrap; }
.control select { grid-column: 2 / 4; }
select { font: inherit; color: var(--fg); background: var(--code-bg); border: 1px solid var(--rule); border-radius: 4px; padding: 3px 4px; min-height: 28px; }
input[type="range"] { width: 100%; margin: 0; accent-color: var(--fg); }
input:disabled { opacity: 0.4; }
output { color: var(--fg); font-variant-numeric: tabular-nums; text-align: right; }
.readout { margin: 10px 0 0; color: var(--muted); font-variant-numeric: tabular-nums; }
.readout b { font-weight: 600; color: var(--fg); }
button:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid var(--fg); outline-offset: 2px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
@media (pointer: coarse) { button { min-height: 40px; } select { min-height: 36px; } }
`;

const TEMPLATE = `
<div class="stage">
  <canvas role="img"></canvas>
  <p class="hint" aria-hidden="true">draw a function here</p>
</div>
<p class="legend">
  <span class="draw-only" style="--swatch: var(--fg)">your curve</span>
  <span class="draw-only" style="--swatch: var(--tok-number)">the network</span>
  <span class="spiral-only dot" style="--swatch: var(--tok-number)">class A</span>
  <span class="spiral-only square" style="--swatch: var(--tok-string)">class B</span>
</p>
<div class="buttons">
  <button type="button" class="train">Train</button>
  <button type="button" class="reset">Reset weights</button>
  <button type="button" class="example draw-only">Example curve</button>
  <button type="button" class="clear draw-only">Clear drawing</button>
</div>
<div class="controls">
  <label class="control">Data
    <select class="dataset"><option value="draw">Draw a function</option><option value="spiral">Spiral</option></select></label>
  <label class="control">Activation
    <select class="activation">${ACTIVATIONS.map((a) => `<option value="${a}">${a}</option>`).join("")}</select></label>
  <label class="control">Hidden layers <input type="range" class="layers" min="0" max="4" step="1"><output class="layers-out"></output></label>
  <label class="control">Width <input type="range" class="width" min="1" max="16" step="1"><output class="width-out"></output></label>
  <label class="control">Learning rate <input type="range" class="lr" min="0" max="${String(LR_STEPS)}" step="1"><output class="lr-out"></output></label>
</div>
<p class="readout"></p>
<p class="sr-only" role="status"></p>
`;

// A canvas colour as numbers, for the heatmap's per-pixel mixing.
type Rgb = readonly [number, number, number];

interface Palette {
  readonly fg: string;
  readonly muted: string;
  readonly rule: string;
  readonly bg: string;
  readonly net: string;
  readonly classA: string;
  readonly classB: string;
  readonly bgRgb: Rgb;
  readonly aRgb: Rgb;
  readonly bRgb: Rgb;
}

const formatLr = (lr: number): string => (lr < 0.001 ? lr.toExponential(0) : String(Number(lr.toPrecision(2))));
const formatLoss = (loss: number): string => (loss < 1e-4 ? loss.toExponential(1) : loss.toPrecision(3));

export class NnFit extends HTMLElement {
  #root = this.attachShadow({ mode: "open" });
  #ctx: CanvasRenderingContext2D | null = null;

  // Model state.
  #dataset: Dataset = "draw";
  #activation: Activation = "tanh";
  #layers = 2;
  #width = 8;
  #lrK = lrIndex(0.03);
  #seed = 1;
  #net: Mlp = initMlp([1, 8, 8, 1], "tanh", seeded(1));
  #opt: Adam = makeAdam(this.#net);
  #steps = 0;

  // Data.
  #drawing: DrawBuffer = makeDrawBuffer(COLUMNS);
  #drawBatch: Batch = drawSamples(this.#drawing);
  #spiral: Batch = spiral(SPIRAL_PER_CLASS, SPIRAL_NOISE, seeded(3));
  #stroke: { pointer: number; last: Point } | null = null;

  // Loop: runs only while the reader wants training AND the widget is on screen AND the tab is visible.
  #training = false;
  #onScreen = false;
  #frame = 0;
  #lastPaint = 0;
  #lastAria = 0;
  #reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  #darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
  #palette: Palette | null = null;
  #heat = document.createElement("canvas");
  #cleanup: (() => void)[] = [];
  #built = false;

  get stats(): NnFitStats {
    const batch = this.#batch();
    const result = batch.n > 0 ? evaluate(this.#net, this.#task(), batch) : null;
    return {
      dataset: this.#dataset,
      steps: this.#steps,
      samples: batch.n,
      loss: result?.loss ?? null,
      accuracy: result?.accuracy ?? null,
      training: this.#training,
    };
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
    if (!isDataset(dataset)) throw new Error(`<nn-fit dataset="${dataset}">: expected draw or spiral`);
    const activation = this.getAttribute("activation") ?? "tanh";
    if (!isActivation(activation)) throw new Error(`<nn-fit activation="${activation}">: expected ${ACTIVATIONS.join(", ")}`);
    const lr = Number(this.getAttribute("lr") ?? "0.03");
    if (!(lr > 0)) throw new Error(`<nn-fit lr="${String(this.getAttribute("lr"))}">: expected a positive number`);
    this.#dataset = dataset;
    this.#activation = activation;
    this.#layers = intAttr(this, "layers", 0, 4, 2);
    this.#width = intAttr(this, "width", 1, 16, 8);
    this.#lrK = lrIndex(lr);

    this.#el("select.dataset", HTMLSelectElement).value = this.#dataset;
    this.#el("select.activation", HTMLSelectElement).value = this.#activation;
    this.#el("input.layers", HTMLInputElement).value = String(this.#layers);
    this.#el("input.width", HTMLInputElement).value = String(this.#width);
    this.#el("input.lr", HTMLInputElement).value = String(this.#lrK);
    this.#ctx = this.#el("canvas", HTMLCanvasElement).getContext("2d");
    this.#rebuildNet();
    this.#syncControls();
  }

  #listen(): void {
    const on = <K extends keyof HTMLElementEventMap>(target: HTMLElement, type: K, fn: (e: HTMLElementEventMap[K]) => void): void => {
      target.addEventListener(type, fn);
      this.#cleanup.push(() => { target.removeEventListener(type, fn); });
    };
    const canvas = this.#el("canvas", HTMLCanvasElement);

    on(this.#el("button.train", HTMLButtonElement), "click", () => { this.#setTraining(!this.#training); });
    on(this.#el("button.reset", HTMLButtonElement), "click", () => {
      this.#seed++;
      this.#rebuildNet();
      this.#announce("Weights reset to new random values.");
    });
    on(this.#el("button.example", HTMLButtonElement), "click", () => {
      fillExample(this.#drawing);
      this.#dataChanged();
      this.#announce("Example curve drawn.");
    });
    on(this.#el("button.clear", HTMLButtonElement), "click", () => {
      this.#drawing = makeDrawBuffer(COLUMNS);
      this.#dataChanged();
      this.#announce("Drawing cleared.");
    });
    const select = this.#el("select.dataset", HTMLSelectElement);
    on(select, "change", () => {
      if (!isDataset(select.value)) return;
      this.#dataset = select.value;
      this.#rebuildNet();
      this.#syncControls();
      this.#announce(select.value === "draw" ? "Draw a function on the plot." : "Spiral dataset: two classes.");
    });
    const activation = this.#el("select.activation", HTMLSelectElement);
    on(activation, "change", () => {
      if (!isActivation(activation.value)) return;
      this.#activation = activation.value;
      this.#rebuildNet();
    });
    const range = (cls: string, set: (v: number) => void, rebuild: boolean): void => {
      const input = this.#el(`input.${cls}`, HTMLInputElement);
      on(input, "input", () => {
        set(input.valueAsNumber);
        if (rebuild) this.#rebuildNet();
        this.#syncControls();
        this.#paint();
      });
    };
    range("layers", (v) => { this.#layers = v; }, true);
    range("width", (v) => { this.#width = v; }, true);
    range("lr", (v) => { this.#lrK = v; }, false); // keeps the weights: change the step size mid-run

    // Drawing: one stroke per pointer, captured so it continues outside the canvas.
    on(canvas, "pointerdown", (e) => {
      if (this.#dataset !== "draw" || this.#stroke) return;
      canvas.setPointerCapture(e.pointerId);
      const p = this.#toPlot(e);
      paintStroke(this.#drawing, null, p);
      this.#stroke = { pointer: e.pointerId, last: p };
      this.#dataChanged();
    });
    on(canvas, "pointermove", (e) => {
      if (this.#stroke?.pointer !== e.pointerId) return;
      const p = this.#toPlot(e);
      paintStroke(this.#drawing, this.#stroke.last, p);
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

  #task(): Task {
    return this.#dataset === "draw" ? "regression" : "binary";
  }

  #batch(): Batch {
    return this.#dataset === "draw" ? this.#drawBatch : this.#spiral;
  }

  #lr(): number {
    return lrAt(this.#lrK);
  }

  #rebuildNet(): void {
    const inputs = this.#dataset === "draw" ? 1 : 2;
    const sizes = [inputs, ...Array.from({ length: this.#layers }, () => this.#width), 1];
    this.#net = initMlp(sizes, this.#activation, seeded(this.#seed));
    this.#opt = makeAdam(this.#net);
    this.#steps = 0;
    this.#paint();
  }

  #dataChanged(): void {
    this.#drawBatch = drawSamples(this.#drawing);
    this.#paint();
  }

  #syncControls(): void {
    const isDraw = this.#dataset === "draw";
    for (const el of this.#root.querySelectorAll(".draw-only")) el.toggleAttribute("hidden", !isDraw);
    for (const el of this.#root.querySelectorAll(".spiral-only")) el.toggleAttribute("hidden", isDraw);
    this.#el(".stage", HTMLDivElement).classList.toggle("spiral", !isDraw);
    this.#el("input.width", HTMLInputElement).disabled = this.#layers === 0;
    this.#el("output.layers-out", HTMLOutputElement).value = String(this.#layers);
    this.#el("output.width-out", HTMLOutputElement).value = String(this.#width);
    const lr = formatLr(this.#lr());
    this.#el("output.lr-out", HTMLOutputElement).value = lr;
    this.#el("input.lr", HTMLInputElement).setAttribute("aria-valuetext", lr);
    const train = this.#el("button.train", HTMLButtonElement);
    train.textContent = this.#training ? "Pause" : "Train";
  }

  #setTraining(on: boolean): void {
    this.#training = on;
    this.#syncControls();
    this.#announce(on ? "Training." : "Paused.");
    this.#updateLoop();
  }

  #announce(message: string): void {
    this.#el("[role=status]", HTMLParagraphElement).textContent = message;
    this.#lastAria = 0; // describe the new state right away
  }

  // --- loop ---

  #updateLoop(): void {
    const run = this.#training && this.#onScreen && !document.hidden;
    if (run && this.#frame === 0) this.#frame = requestAnimationFrame((t) => { this.#tick(t); });
    if (!run) this.#stopLoop();
  }

  #stopLoop(): void {
    if (this.#frame !== 0) cancelAnimationFrame(this.#frame);
    this.#frame = 0;
  }

  #tick(now: number): void {
    const batch = this.#batch();
    if (batch.n > 0) {
      const task = this.#task();
      for (let i = 0; i < STEPS_PER_FRAME; i++) trainStep(this.#net, task, batch, this.#opt, this.#lr());
      this.#steps += STEPS_PER_FRAME;
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
    const bg = token("--code-bg", "Canvas");
    const classA = token("--tok-number", "LinkText");
    const classB = token("--tok-string", "VisitedText");
    this.#palette = {
      fg: token("--fg", "CanvasText"),
      muted: token("--muted", "GrayText"),
      rule: token("--rule", "GrayText"),
      bg: token("--bg", "Canvas"),
      net: classA,
      classA,
      classB,
      bgRgb: rgb(bg),
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
    this.#el(".hint", HTMLParagraphElement).hidden = this.#dataset !== "draw" || this.#drawBatch.n > 0;
    if (this.#dataset === "draw") this.#paintDraw(ctx, w, h);
    else this.#paintSpiral(ctx, w, h);
    this.#paintReadout(now);
  }

  #paintDraw(ctx: CanvasRenderingContext2D, w: number, h: number): void {
    const c = this.#colors();
    const px = (x: number): number => ((x + 1) / 2) * w;
    const py = (y: number): number => (1 - (y / Y_RANGE + 1) / 2) * h;
    ctx.lineWidth = 1;
    ctx.strokeStyle = c.rule;
    ctx.beginPath();
    ctx.moveTo(0, py(0)); ctx.lineTo(w, py(0));
    ctx.moveTo(px(0), 0); ctx.lineTo(px(0), h);
    ctx.stroke();

    // The reader's curve: one polyline per run of drawn columns, a dot for a lone column.
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.strokeStyle = c.fg;
    ctx.fillStyle = c.fg;
    ctx.lineWidth = 3;
    let run = 0;
    ctx.beginPath();
    this.#drawing.forEach((y, i) => {
      if (Number.isNaN(y)) { run = 0; return; }
      const x = px(columnX(COLUMNS, i));
      if (run === 0) ctx.moveTo(x, py(y)); else ctx.lineTo(x, py(y));
      const next = this.#drawing[i + 1];
      if (run === 0 && (next === undefined || Number.isNaN(next))) ctx.arc(x, py(y), 1.5, 0, 2 * Math.PI);
      run++;
    });
    ctx.stroke();

    // The network's curve, sampled every 2 CSS px across the whole width.
    const f = predictor(this.#net, "regression");
    const input = new Float64Array(1);
    ctx.strokeStyle = c.net;
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let sx = 0; sx <= w; sx += 2) {
      input[0] = ((sx / w) * 2 - 1) * INPUT_SCALE;
      const sy = Math.max(-h, Math.min(2 * h, py(f(input))));
      if (sx === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
    }
    ctx.stroke();
  }

  #paintSpiral(ctx: CanvasRenderingContext2D, w: number, h: number): void {
    const c = this.#colors();
    // Heatmap: P(class A) on a grid x grid raster, mixed from the background toward the winning
    // class's colour by confidence, then scaled up with smoothing.
    const f = predictor(this.#net, "binary");
    const input = new Float64Array(2);
    const grid = Math.min(HEATMAP_MAX, Math.max(16, Math.ceil(w / HEAT_PX)));
    this.#heat.width = grid;
    this.#heat.height = grid;
    const hctx = this.#heat.getContext("2d");
    if (!hctx) return;
    const img = hctx.createImageData(grid, grid);
    for (let j = 0; j < grid; j++) {
      for (let i = 0; i < grid; i++) {
        input[0] = (((i + 0.5) / grid) * 2 - 1) * INPUT_SCALE;
        input[1] = (1 - ((j + 0.5) / grid) * 2) * INPUT_SCALE;
        const p = f(input);
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

    // Points: class A circles, class B squares (shape as well as colour).
    const px = (x: number): number => ((x / INPUT_SCALE + 1) / 2) * w;
    const py = (y: number): number => (1 - (y / INPUT_SCALE + 1) / 2) * h;
    const r = Math.max(2.5, w / 120);
    ctx.lineWidth = 1;
    ctx.strokeStyle = c.bg;
    const pts = this.#spiral;
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
    const { loss, accuracy, samples } = this.stats;
    const arch = this.#net.sizes.join(" → ");
    const params = paramCount(this.#net);
    const parts: string[] = [];
    if (loss === null) parts.push("loss —");
    else parts.push(`${this.#dataset === "draw" ? "MSE" : "loss"} <b>${formatLoss(loss)}</b>`);
    if (accuracy !== null) parts.push(`accuracy <b>${(accuracy * 100).toFixed(1)}%</b>`);
    parts.push(`step ${this.#steps.toLocaleString("en-US")}`);
    parts.push(`${arch} (${String(params)} params)`);
    this.#el(".readout", HTMLParagraphElement).innerHTML = parts.join(" · ");

    if (now - this.#lastAria < ARIA_MS && this.#frame !== 0) return;
    this.#lastAria = now;
    const lossText = loss === null ? "no loss yet" : `loss ${formatLoss(loss)}`;
    const net = `a ${arch} network with ${this.#activation} hidden units, ${lossText} after ${String(this.#steps)} training steps`;
    const label = this.#dataset === "draw"
      ? samples === 0
        ? `Empty drawing area. Draw a function with a pointer, or press Example curve. The plot shows ${net}.`
        : `Your drawn function (${String(filledColumns(this.#drawing))} of ${String(COLUMNS)} columns) and the fit of ${net}.`
      : `Spiral of ${String(samples)} points in two classes, background shaded by the prediction of ${net}${accuracy === null ? "" : `, accuracy ${(accuracy * 100).toFixed(0)}%`}.`;
    this.#el("canvas", HTMLCanvasElement).setAttribute("aria-label", label);
  }
}

customElements.define("nn-fit", NnFit);
