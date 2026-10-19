import type { Activation, Batch, Mlp, Rng, Task } from "./mlp";
import { ACTIVATIONS, evaluate, get, initMlp, lossAndGrad, makeAdam, seeded, trainStep } from "./mlp";
import type { WaveParams } from "./datasets";
import {
  INPUT_SCALE, columnAt, completeCurve, curveSamples, describeGaps, drawSamples, fillWave, filledColumns, gaps, makeDrawBuffer, paintStroke,
  spiral, valueAt, waveAt, waveStages,
} from "./datasets";

function check(ok: boolean, message: string): void {
  if (!ok) throw new Error(`FAIL ${message}`);
  console.log(`ok   ${message}`);
}

function moveBiasesOffTheReluKink(net: Mlp, rng: Rng): void {
  for (const layer of net.layers) layer.b.forEach((_, i) => { layer.b[i] = 0.1 * (2 * rng() - 1); });
}

function gradCheck(activation: Activation, task: Task): number {
  const rng = seeded(7);
  const net = initMlp([2, 4, 3, 1], activation, rng);
  const n = 6;
  const batch: Batch = {
    n,
    x: new Float64Array(2 * n).map(() => 2 * rng() - 1),
    y: new Float64Array(n).map(() => (task === "binary" ? (rng() < 0.5 ? 0 : 1) : 2 * rng() - 1)),
  };
  moveBiasesOffTheReluKink(net, rng);
  const { grads } = lossAndGrad(net, task, batch);
  const h = 1e-6;
  let worst = 0;
  const probe = (params: Float64Array, analytic: Float64Array): void => {
    for (let i = 0; i < params.length; i++) {
      const saved = get(params, i);
      params[i] = saved + h;
      const up = evaluate(net, task, batch).loss;
      params[i] = saved - h;
      const down = evaluate(net, task, batch).loss;
      params[i] = saved;
      const numeric = (up - down) / (2 * h);
      const a = get(analytic, i);
      worst = Math.max(worst, Math.abs(a - numeric) / Math.max(1e-8, Math.abs(a) + Math.abs(numeric)));
    }
  };
  net.layers.forEach((layer, l) => {
    const gw = grads.w[l], gb = grads.b[l];
    if (!gw || !gb) throw new Error("missing grads");
    probe(layer.w, gw);
    probe(layer.b, gb);
  });
  return worst;
}

for (const task of ["regression", "binary"] as const) {
  for (const activation of ACTIVATIONS) {
    const worst = gradCheck(activation, task);
    check(worst < 1e-5, `grad check ${task.padEnd(10)} ${activation.padEnd(7)} worst relative error ${worst.toExponential(2)}`);
  }
}

{
  const buf = makeDrawBuffer(100);
  paintStroke(buf, { x: -0.9, y: -1 }, { x: 0.9, y: 1 });
  const first = columnAt(100, -0.9), last = columnAt(100, 0.9);
  check(filledColumns(buf) === last - first + 1, `fast stroke fills every column it crosses (${String(filledColumns(buf))})`);
  const mid = get(buf, columnAt(100, 0));
  check(Math.abs(mid) < 0.03, `stroke is interpolated linearly (y at x=0 is ${mid.toFixed(3)})`);
  paintStroke(buf, null, { x: 0, y: 0.5 });
  check(get(buf, columnAt(100, 0)) === 0.5 && filledColumns(buf) === last - first + 1, "drawing over a column overwrites it");
  check(drawSamples(buf).n === filledColumns(buf), "one sample per drawn column");
  check(describeGaps(buf) === "left edge to 4%, 96% to right edge" && gaps(buf).length === 2, `gaps at both edges: "${describeGaps(buf)}"`);
  buf.fill(NaN, 40, 55);
  check(describeGaps(buf) === "left edge to 4%, 40–55%, 96% to right edge", `gap in the middle: "${describeGaps(buf)}"`);
  check(describeGaps(makeDrawBuffer(100)) === "everything", "empty buffer: everything is missing");
  const full = makeDrawBuffer(100);
  paintStroke(full, { x: -1, y: 0 }, { x: 1, y: 0 });
  check(gaps(full).length === 0, "a stroke from edge to edge leaves no gaps");
}

{
  const buf = makeDrawBuffer(640).fill(0);
  for (const c of [0, 320, 639]) buf[c] = NaN;
  check(describeGaps(buf) === "left edge to 1%, 50–51%, 99% to right edge", `a one-column gap never reads as 0% or empty: "${describeGaps(buf)}"`);
}

{
  const buf = makeDrawBuffer(10);
  buf[2] = 0.5; buf[3] = 0.4; buf[7] = -0.2;
  const done = completeCurve(buf);
  const want = [0.5, 0.5, 0.5, 0.4, 0.25, 0.1, -0.05, -0.2, -0.2, -0.2];
  check(done !== null && want.every((v, i) => Math.abs(v - get(done, i)) < 1e-12),
    `completeCurve: flat ends, linear interior [${done === null ? "null" : Array.from(done, (v) => v.toFixed(2)).join(", ")}]`);
  check(Number.isNaN(get(buf, 0)), "completeCurve returns a new buffer (the drawing keeps its gaps)");
  check(completeCurve(makeDrawBuffer(10)) === null, "completeCurve of an empty drawing is null");
  const one = makeDrawBuffer(5); one[4] = 0.3;
  check(completeCurve(one)?.every((v) => v === 0.3) ?? false, "completeCurve of a single column is flat");
}

{
  const wave = (p: Partial<WaveParams>): Float64Array => {
    const buf = makeDrawBuffer(640);
    fillWave(buf, waveStages({ wiggles: 6, roughness: 1.5, stages: 2, seed: 5, ...p }, seeded));
    return buf;
  };
  const same = (a: Float64Array, b: Float64Array): boolean => a.every((v, i) => v === b[i]);
  check(same(wave({}), wave({})), "wave: same params and seed give the identical curve");
  check(!same(wave({}), wave({ seed: 6 })), "wave: a different seed gives a different curve");
  let lo = Infinity, hi = -Infinity, worstStage = 0;
  for (const seed of [1, 2, 3, 4, 5]) for (const stages of [1, 2, 3, 4]) for (const wiggles of [1, 7, 20]) {
    const buf = wave({ seed, stages, wiggles });
    for (const v of buf) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    const st = waveStages({ wiggles, roughness: 0.5, stages, seed }, seeded);
    for (let j = 0; j <= 5000; j++) worstStage = Math.max(worstStage, Math.abs(waveAt(st, -1 + j / 2500)));
  }
  check(lo === -1 && hi === 1, `wave: every filled buffer spans exactly [-1, 1] (60 configs: min ${String(lo)}, max ${String(hi)})`);
  check(worstStage < 1.001, `wave: composed stages stay in [-1, 1] off the range grid too (max |f| ${worstStage.toFixed(5)})`);
  const k4 = waveStages({ wiggles: 4, roughness: 1.5, stages: 3, seed: 9 }, seeded);
  const k9 = waveStages({ wiggles: 9, roughness: 1.5, stages: 3, seed: 9 }, seeded);
  check(k4.every((st, i) => {
    const longer = k9[i];
    return longer !== undefined && st.amp.every((a, k) => a === longer.amp[k] && st.phase[k] === longer.phase[k]);
  }),
    "wave: raising K keeps the seed (the first K terms of every stage are unchanged)");
  const d1 = waveStages({ wiggles: 4, roughness: 1.5, stages: 1, seed: 9 }, seeded);
  check(d1[0]?.amp.every((a, k) => a === k4[0]?.amp[k]) === true, "wave: raising d keeps the earlier stages");
}

{
  const buf = makeDrawBuffer(640);
  fillWave(buf, waveStages({ wiggles: 4, roughness: 1.5, stages: 1, seed: 1 }, seeded));
  const a = curveSamples(buf, 8, 0, seeded(3)), b = curveSamples(buf, 64, 0, seeded(3));
  check(a.x.every((x, i) => x === b.x[i]) && a.y.every((y, i) => y === b.y[i]), "samples: n=8 is a prefix of n=64 for one seed");
  check(a.y.every((y, i) => Math.abs(y - valueAt(buf, get(a.x, i) / INPUT_SCALE)) < 1e-12), "samples: with sigma 0, y = f(x)");
  const n1 = curveSamples(buf, 64, 0.1, seeded(3)), n2 = curveSamples(buf, 64, 0.3, seeded(3));
  check(n1.y.every((y, i) => Math.abs((get(n2.y, i) - get(b.y, i)) - 3 * (y - get(b.y, i))) < 1e-12), "samples: noise 0.3 is exactly 3x the noise-0.1 draw");
  const s8 = spiral(8, 0.2, seeded(4)), s64 = spiral(64, 0.2, seeded(4));
  check(s8.x.every((x, i) => x === s64.x[i]) && s64.y.reduce((n, y) => n + y, 0) === 32, "spiral: n=8 is a prefix of n=64, classes alternate (32/32)");
}

function train(net: Mlp, task: Task, batch: Batch, steps: number, lr: number): { before: number; after: number; accuracy: number | null } {
  const opt = makeAdam(net);
  const before = evaluate(net, task, batch).loss;
  for (let i = 0; i < steps; i++) trainStep(net, task, batch, opt, lr);
  const after = evaluate(net, task, batch);
  return { before, after: after.loss, accuracy: after.accuracy };
}
function bestLineMse(b: Batch): number {
  let sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (let i = 0; i < b.n; i++) {
    const x = get(b.x, i), y = get(b.y, i);
    sx += x; sy += y; sxx += x * x; sxy += x * y;
  }
  const slope = (b.n * sxy - sx * sy) / (b.n * sxx - sx * sx);
  const icept = (sy - slope * sx) / b.n;
  let mse = 0;
  for (let i = 0; i < b.n; i++) mse += (get(b.y, i) - (slope * get(b.x, i) + icept)) ** 2;
  return mse / b.n;
}
{
  const buf = makeDrawBuffer(640);
  fillWave(buf, waveStages({ wiggles: 4, roughness: 1.5, stages: 1, seed: 2 }, seeded));
  const data = curveSamples(buf, 128, 0, seeded(1));
  const tanh = train(initMlp([1, 8, 8, 1], "tanh", seeded(1)), "regression", data, 1500, 0.03);
  check(tanh.after < tanh.before / 20, `wave K=4, tanh 2x8: MSE ${tanh.before.toFixed(4)} -> ${tanh.after.toFixed(4)} in 1500 steps at lr 0.03`);
  const linear = train(initMlp([1, 8, 8, 8, 1], "linear", seeded(1)), "regression", data, 1500, 0.03);
  const line = bestLineMse(data);
  check(Math.abs(linear.after - line) < 1e-3, `wave K=4, linear 3x8: MSE ${linear.after.toFixed(4)}, the best straight line's is ${line.toFixed(4)}`);
  const points = spiral(200, 0.15, seeded(3));
  for (const activation of ["tanh", "relu"] as const) {
    const s = train(initMlp([2, 8, 8, 8, 1], activation, seeded(2)), "binary", points, 3000, 0.03);
    check((s.accuracy ?? 0) > 0.9, `spiral (200 points), ${activation} 3x8: accuracy ${((s.accuracy ?? 0) * 100).toFixed(1)}%, loss ${s.after.toFixed(3)} in 3000 steps`);
  }
}
