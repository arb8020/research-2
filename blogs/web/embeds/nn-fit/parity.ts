// Browser side of the parity check (remote_train_test.py runs this under node, via `npm run test:nn-fit-remote`).
// Builds the widget's default datasets, trains each with mlp.ts for STEPS steps from a few weight seeds, and
// prints one JSON object: every case's remote config (what the page would send, same data and same initial
// weights) and mlp.ts's results: the training loss after every step (trace[k] = after k steps) and the final
// test metrics. The test then trains the same configs in torch and compares.
import type { Activation, Batch, Task } from "./mlp";
import { evaluate, initMlp, makeAdam, seeded, trainStep } from "./mlp";
import { completeCurve, curveSamples, drawSamples, fillWave, makeDrawBuffer, spiral, waveStages } from "./datasets";
import type { Dtype, RemoteConfig, RemoteData } from "./remote";
import { CURVE_POINTS, HEAT_GRID, curveGrid, heatGrid, remoteConfig } from "./remote";

const STEPS = 2000;
const SEEDS = [1, 2];
const LR = 0.03; // the widget's default (nearest slider stop to 0.03)
// The widget's defaults (nn-fit.ts: COLUMNS, HELD_OUT, HELD_OUT_SEED, sample seed 1, noise 0) and dl/neural-nets-fit.nnfit
// (wave, width 12): the page's default config. The spiral case uses the element's defaults (2 x 8, tanh).
const COLUMNS = 640;
const SAMPLES = 128;
const HELD_OUT = 500;
const HELD_OUT_SEED = 1000;

interface Case {
  readonly name: string;
  readonly task: Task;
  readonly activation: Activation;
  readonly sizes: readonly number[];
  readonly data: RemoteData;
}

function waveCase(): Case {
  const truth = makeDrawBuffer(COLUMNS);
  fillWave(truth, waveStages({ wiggles: 4, roughness: 1.5, stages: 1, seed: 1 }, seeded));
  const curve = completeCurve(truth);
  if (curve === null) throw new Error("the default wave is empty");
  return {
    name: "wave 1-12-12-1 tanh",
    task: "regression",
    activation: "tanh",
    sizes: [1, 12, 12, 1],
    data: { train: curveSamples(curve, SAMPLES, 0, seeded(1)), test: drawSamples(curve), grid: curveGrid(CURVE_POINTS) },
  };
}

function spiralCase(): Case {
  return {
    name: "spiral 2-8-8-1 tanh",
    task: "binary",
    activation: "tanh",
    sizes: [2, 8, 8, 1],
    data: { train: spiral(SAMPLES, 0, seeded(1)), test: spiral(HELD_OUT, 0, seeded(HELD_OUT_SEED)), grid: heatGrid(HEAT_GRID) },
  };
}

interface Result {
  readonly name: string;
  readonly seed: number;
  readonly config: Record<Dtype, RemoteConfig>;
  readonly browser: { readonly trace: number[]; readonly loss: number; readonly testLoss: number; readonly testAccuracy: number | null; readonly ms: number };
}

function run(c: Case, seed: number): Result {
  const net = initMlp(c.sizes, c.activation, seeded(seed));
  const opt = makeAdam(net);
  const config = (dtype: Dtype): RemoteConfig =>
    remoteConfig(net, opt, c.task, c.data, { lr: LR, dtype, step: 0, seconds: 0, stepBudget: STEPS, timeBudget: Infinity });
  const configs = { float32: config("float32"), float64: config("float64") }; // before training: the initial weights
  const train: Batch = c.data.train;
  const start = performance.now();
  const trace: number[] = [];
  for (let s = 0; s < STEPS; s++) trace.push(trainStep(net, c.task, train, opt, LR)); // the loss before the step
  const ms = performance.now() - start;
  const trained = evaluate(net, c.task, train);
  trace.push(trained.loss);
  const test = evaluate(net, c.task, c.data.test);
  return { name: c.name, seed, config: configs, browser: { trace, loss: trained.loss, testLoss: test.loss, testAccuracy: test.accuracy, ms } };
}

const cases = [waveCase(), spiralCase()];
console.log(JSON.stringify({ steps: STEPS, results: cases.flatMap((c) => SEEDS.map((seed) => run(c, seed))) }));
