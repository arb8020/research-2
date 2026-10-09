// A small fully connected network with hand-written backprop and Adam. Pure: no DOM, no globals,
// so it runs (and is gradient-checked) under node as well as in the page.
//
// Shapes: layer l maps nIn -> nOut with w[o * nIn + i] and b[o]. Hidden layers use `activation`;
// the output layer is always one linear unit. What that unit means depends on the Task:
//   regression  output is y-hat, loss is mean squared error
//   binary      output is a logit z, p = sigmoid(z), loss is mean binary cross-entropy (from the logit)

export type Activation = "linear" | "relu" | "tanh" | "sigmoid";
export const ACTIVATIONS: readonly Activation[] = ["linear", "relu", "tanh", "sigmoid"];
export type Task = "regression" | "binary";

export interface Layer {
  readonly nIn: number;
  readonly nOut: number;
  readonly w: Float64Array;
  readonly b: Float64Array;
}

export interface Mlp {
  readonly sizes: readonly number[]; // [inputs, ...hidden widths, 1]
  readonly activation: Activation;
  readonly layers: readonly Layer[];
}

// n samples, row-major inputs (n * inputs) and one target each (a value, or a 0/1 label).
export interface Batch {
  readonly n: number;
  readonly x: Float64Array;
  readonly y: Float64Array;
}

export interface Grads {
  readonly w: readonly Float64Array[];
  readonly b: readonly Float64Array[];
}

export interface Adam {
  readonly m: Grads;
  readonly v: Grads;
  t: number;
}

export type Rng = () => number; // uniform in [0, 1)

// Bounds-checked read: noUncheckedIndexedAccess makes a[i] `number | undefined`, and an out-of-range
// index here is a bug, so it throws rather than computing with NaN.
export function get(a: Float64Array, i: number): number {
  const v = a[i];
  if (v === undefined) throw new RangeError(`index ${String(i)} outside length ${String(a.length)}`);
  return v;
}

// mulberry32: a tiny seeded PRNG, so weights and datasets are reproducible.
export function seeded(seed: number): Rng {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// He-uniform for relu (keeps activations from halving each layer), Glorot-uniform otherwise. Biases start at 0.
export function initMlp(sizes: readonly number[], activation: Activation, rng: Rng): Mlp {
  if (sizes.length < 2 || sizes.some((s) => !Number.isInteger(s) || s < 1)) {
    throw new Error(`initMlp: sizes must be >= 2 positive integers, got [${sizes.join(", ")}]`);
  }
  const layers: Layer[] = [];
  for (let l = 0; l + 1 < sizes.length; l++) {
    const nIn = sizes[l] ?? 0;
    const nOut = sizes[l + 1] ?? 0;
    const hidden = l + 2 < sizes.length;
    const limit = hidden && activation === "relu" ? Math.sqrt(6 / nIn) : Math.sqrt(6 / (nIn + nOut));
    const w = new Float64Array(nIn * nOut).map(() => (2 * rng() - 1) * limit);
    layers.push({ nIn, nOut, w, b: new Float64Array(nOut) });
  }
  return { sizes: [...sizes], activation, layers };
}

export function paramCount(net: Mlp): number {
  return net.layers.reduce((sum, l) => sum + l.w.length + l.b.length, 0);
}

function act(kind: Activation, z: number): number {
  switch (kind) {
    case "linear": return z;
    case "relu": return z > 0 ? z : 0;
    case "tanh": return Math.tanh(z);
    case "sigmoid": return 1 / (1 + Math.exp(-z));
  }
}

// d act / dz, written in terms of z and a = act(z) (whichever is cheaper).
function dAct(kind: Activation, z: number, a: number): number {
  switch (kind) {
    case "linear": return 1;
    case "relu": return z > 0 ? 1 : 0;
    case "tanh": return 1 - a * a;
    case "sigmoid": return a * (1 - a);
  }
}

const sigmoid = (z: number): number => 1 / (1 + Math.exp(-z));
// log(1 + e^z) without overflow.
const softplus = (z: number): number => (z > 0 ? z + Math.log1p(Math.exp(-z)) : Math.log1p(Math.exp(z)));

// Per-layer buffers for one sample: pre-activations z and activations a (a[0] is the input).
interface Trace {
  readonly z: Float64Array[];
  readonly a: Float64Array[];
}

function makeTrace(net: Mlp): Trace {
  return {
    z: net.layers.map((l) => new Float64Array(l.nOut)),
    a: [new Float64Array(net.sizes[0] ?? 0), ...net.layers.map((l) => new Float64Array(l.nOut))],
  };
}

// Forward one sample (input = x[offset .. offset + inputs)) into `trace`. Returns the raw output unit.
function forwardInto(net: Mlp, x: Float64Array, offset: number, trace: Trace): number {
  const input = trace.a[0];
  if (!input) throw new Error("trace has no input layer");
  for (let i = 0; i < input.length; i++) input[i] = get(x, offset + i);
  const last = net.layers.length - 1;
  net.layers.forEach((layer, l) => {
    const a = trace.a[l];
    const z = trace.z[l];
    const out = trace.a[l + 1];
    if (!a || !z || !out) throw new Error(`trace is missing layer ${String(l)}`);
    for (let o = 0; o < layer.nOut; o++) {
      let s = get(layer.b, o);
      const row = o * layer.nIn;
      for (let i = 0; i < layer.nIn; i++) s += get(layer.w, row + i) * get(a, i);
      z[o] = s;
      out[o] = l === last ? s : act(net.activation, s);
    }
  });
  return get(trace.a[trace.a.length - 1] ?? new Float64Array(0), 0);
}

// Raw output for one input vector: y-hat for regression, the logit for binary.
export function forward(net: Mlp, input: Float64Array): number {
  return forwardInto(net, input, 0, makeTrace(net));
}

// What the reader sees: y-hat for regression, P(label = 1) for binary.
export function predict(net: Mlp, task: Task, input: Float64Array): number {
  const out = forward(net, input);
  return task === "binary" ? sigmoid(out) : out;
}

// A reusable predictor for many calls (the heatmap): one trace, no allocation per call.
export function predictor(net: Mlp, task: Task): (input: Float64Array) => number {
  const trace = makeTrace(net);
  return (input) => {
    const out = forwardInto(net, input, 0, trace);
    return task === "binary" ? sigmoid(out) : out;
  };
}

function sampleLoss(task: Task, out: number, target: number): number {
  switch (task) {
    case "regression": return (out - target) ** 2;
    case "binary": return softplus(out) - target * out; // BCE(sigmoid(out), target)
  }
}

// d sampleLoss / d out.
function dLoss(task: Task, out: number, target: number): number {
  switch (task) {
    case "regression": return 2 * (out - target);
    case "binary": return sigmoid(out) - target;
  }
}

export function zeroGrads(net: Mlp): Grads {
  return { w: net.layers.map((l) => new Float64Array(l.w.length)), b: net.layers.map((l) => new Float64Array(l.b.length)) };
}

export interface Eval {
  readonly loss: number; // mean over the batch
  readonly accuracy: number | null; // binary only: fraction with (p > 0.5) === label
}

export function evaluate(net: Mlp, task: Task, batch: Batch): Eval {
  if (batch.n === 0) throw new Error("evaluate: empty batch");
  const trace = makeTrace(net);
  const inputs = net.sizes[0] ?? 0;
  let loss = 0;
  let correct = 0;
  for (let s = 0; s < batch.n; s++) {
    const out = forwardInto(net, batch.x, s * inputs, trace);
    const target = get(batch.y, s);
    loss += sampleLoss(task, out, target);
    if ((out > 0 ? 1 : 0) === target) correct++;
  }
  return { loss: loss / batch.n, accuracy: task === "binary" ? correct / batch.n : null };
}

// Mean loss over the batch and its gradient with respect to every weight and bias (full-batch backprop).
export function lossAndGrad(net: Mlp, task: Task, batch: Batch): { loss: number; grads: Grads } {
  if (batch.n === 0) throw new Error("lossAndGrad: empty batch");
  const grads = zeroGrads(net);
  const trace = makeTrace(net);
  const delta = net.layers.map((l) => new Float64Array(l.nOut)); // dLoss/dz per layer
  const inputs = net.sizes[0] ?? 0;
  const last = net.layers.length - 1;
  let loss = 0;
  for (let s = 0; s < batch.n; s++) {
    const out = forwardInto(net, batch.x, s * inputs, trace);
    const target = get(batch.y, s);
    loss += sampleLoss(task, out, target);
    const top = delta[last];
    if (!top) throw new Error("no output layer");
    top[0] = dLoss(task, out, target) / batch.n;
    for (let l = last; l >= 0; l--) {
      const layer = net.layers[l];
      const d = delta[l];
      const aIn = trace.a[l];
      const gw = grads.w[l];
      const gb = grads.b[l];
      if (!layer || !d || !aIn || !gw || !gb) throw new Error(`missing buffers for layer ${String(l)}`);
      for (let o = 0; o < layer.nOut; o++) {
        const dz = get(d, o);
        gb[o] = get(gb, o) + dz;
        const row = o * layer.nIn;
        for (let i = 0; i < layer.nIn; i++) gw[row + i] = get(gw, row + i) + dz * get(aIn, i);
      }
      if (l === 0) break;
      // delta for layer l-1: (W^T d) * act'(z_{l-1})
      const below = delta[l - 1];
      const zBelow = trace.z[l - 1];
      if (!below || !zBelow) throw new Error(`missing buffers for layer ${String(l - 1)}`);
      for (let i = 0; i < layer.nIn; i++) {
        let s2 = 0;
        for (let o = 0; o < layer.nOut; o++) s2 += get(layer.w, o * layer.nIn + i) * get(d, o);
        below[i] = s2 * dAct(net.activation, get(zBelow, i), get(aIn, i));
      }
    }
  }
  return { loss: loss / batch.n, grads };
}

export function makeAdam(net: Mlp): Adam {
  return { m: zeroGrads(net), v: zeroGrads(net), t: 0 };
}

const BETA1 = 0.9;
const BETA2 = 0.999;
const EPS = 1e-8;

// One Adam update in place (Kingma & Ba 2015, with bias correction).
export function adamStep(net: Mlp, grads: Grads, opt: Adam, lr: number): void {
  opt.t += 1;
  const c1 = 1 - BETA1 ** opt.t;
  const c2 = 1 - BETA2 ** opt.t;
  const update = (p: Float64Array, g: Float64Array, m: Float64Array, v: Float64Array): void => {
    for (let i = 0; i < p.length; i++) {
      const gi = get(g, i);
      const mi = BETA1 * get(m, i) + (1 - BETA1) * gi;
      const vi = BETA2 * get(v, i) + (1 - BETA2) * gi * gi;
      m[i] = mi;
      v[i] = vi;
      p[i] = get(p, i) - (lr * (mi / c1)) / (Math.sqrt(vi / c2) + EPS);
    }
  };
  net.layers.forEach((layer, l) => {
    const gw = grads.w[l], gb = grads.b[l], mw = opt.m.w[l], mb = opt.m.b[l], vw = opt.v.w[l], vb = opt.v.b[l];
    if (!gw || !gb || !mw || !mb || !vw || !vb) throw new Error(`adamStep: missing state for layer ${String(l)}`);
    update(layer.w, gw, mw, vw);
    update(layer.b, gb, mb, vb);
  });
}

// One training step: gradient on the full batch, then Adam. Returns the loss before the step.
export function trainStep(net: Mlp, task: Task, batch: Batch, opt: Adam, lr: number): number {
  const { loss, grads } = lossAndGrad(net, task, batch);
  adamStep(net, grads, opt, lr);
  return loss;
}
