import type { Activation, Batch, Task } from "./mlp";
import { evaluate, initMlp, makeAdam, seeded, trainStep } from "./mlp";
import { completeCurve, curveSamples, drawSamples, fillWave, makeDrawBuffer, spiral, waveStages } from "./datasets";
import type { Dtype, RemoteConfig, RemoteData } from "./remote";
import { CURVE_POINTS, HEAT_GRID, curveGrid, heatGrid, remoteConfig } from "./remote";

const STEPS = 2000;
const SEEDS = [1, 2];
const LR = 0.03;
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
  const initialConfigs = { float32: config("float32"), float64: config("float64") };
  const train: Batch = c.data.train;
  const start = performance.now();
  const lossAfterKSteps: number[] = [];
  for (let s = 0; s < STEPS; s++) lossAfterKSteps.push(trainStep(net, c.task, train, opt, LR));
  const ms = performance.now() - start;
  const trained = evaluate(net, c.task, train);
  lossAfterKSteps.push(trained.loss);
  const test = evaluate(net, c.task, c.data.test);
  return { name: c.name, seed, config: initialConfigs, browser: { trace: lossAfterKSteps, loss: trained.loss, testLoss: test.loss, testAccuracy: test.accuracy, ms } };
}

const cases = [waveCase(), spiralCase()];
console.log(JSON.stringify({ steps: STEPS, results: cases.flatMap((c) => SEEDS.map((seed) => run(c, seed))) }));
