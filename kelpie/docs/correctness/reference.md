# Correctness eval format

This page specifies code that does not exist yet: `kelpie record`, `kelpie grade`, and the files they read and write. For the reasons behind the design, see [About correctness in kelpie](about.md).

## Vocabulary

The terms come from [smevals](https://github.com/prime-radiant-inc/smevals). Kelpie adds Case, Persisted, Pinned, Golden, Verdict, input selector, tolerance source, and Calibration.

| Term | Meaning in kelpie |
|---|---|
| Eval | Every Grade for one deployment, across all subjects. Described by `eval.yaml`. Folded into the build manifest (`kelpie-models/kelpie_models/sdk/manifest.py`). |
| Task | A set of Cases for one subject. The subject is an op (Cases are shapes, dtypes, and seeds), a model (Cases are rows of a teacher-forced token corpus), an engine (Cases are prompts, or rows of a token corpus), or a benchmark (one Case per question set). |
| Case | One element of a Task. Identified by `case_id`, a hash of the Case's input parameters. |
| Config | What produces outputs. Either a deployment (the kernels and model build from a `kelpie.toml`) or a reference (the op's `reference` function in fp64 or at native dtype, or HF transformers). |
| Runner | `kelpie record`. Runs one Task under one Config and writes one Run. |
| Persisted | A directory that holds `run.yaml` and `outputs.safetensors`. Every Check input is a Persisted. |
| Run | A Persisted that `kelpie record` wrote (`kind: recorded`). Immutable. |
| Pinned | A Persisted written by hand or by a tool (`kind: pinned`): a published benchmark score or calibration statistics. |
| Golden | A Persisted that `eval.yaml` names as a reference for a (model, GPU architecture, deterministic mode) key. Usually a Run of an HF fp32 Config. |
| Check | One entry in a Grader: a Checker, its named inputs, its parameters, a severity (`block` or `warn`), and a tolerance source. |
| Checker | The function that a Check calls. A built-in name, or the path of an executable that follows the [CLI checker contract](#cli-checker-contract). |
| Input selector | A string in a Check's `inputs:` map that resolves to one Persisted. |
| Tolerance source | Where a Check's tolerance came from: `calibrated`, `derived`, `vendored`, or `guessed`. See [Tolerance source](#tolerance-source). |
| Calibration | A tolerance value measured from Runs, with a ceiling and a lineage. Declared in `eval.yaml`, written by `kelpie calibrate` to `calibrations/<name>.yaml`. See [Calibration](#calibration). |
| Verdict | The result of one Check on one Case: `pass`, `fail`, or `inconclusive`, plus details. |
| Grader | An ordered list of Checks. Its Grade verdict follows the [combine rule](#combine-rule). |
| Grade | The result of one Grader on one Run: `grades/<grader>/grade.yaml` inside the Run directory. |

The existing `kelpie_models.bench.compare.Verdict` is an older type with a string field. It is not the `Verdict` on this page.

## File layout

An Eval is a directory under `kelpie/evals/`:

```
kelpie/evals/<eval>/
├── eval.yaml                       # name, deployment, graded tasks, goldens
├── tasks/<task>.yaml               # one file per Task
├── tasks/data/                     # corpus files that Tasks name
├── configs/<config>.yaml           # one file per Config
├── graders/<grader>.yaml           # one file per Grader
├── checkers/<checker>              # CLI Checker executables
├── calibrations/<name>.yaml        # written by kelpie calibrate
├── pinned/<name>/                  # Pinned data
│   ├── run.yaml
│   └── outputs.safetensors
└── runs/<task>/<config>/<timestamp>/
    ├── run.yaml                    # written last; its presence marks a complete Run
    ├── outputs.safetensors
    └── grades/<grader>/
        ├── grade.yaml
        ├── grader.yaml             # byte copy of the Grader file used
        └── ...                     # files that CLI Checkers wrote
```

- `<timestamp>` is UTC in the form `2026-09-23T101500Z`.
- The run ID is `<task>/<config>/<timestamp>`.
- `kelpie grade` writes only under `grades/`. Nothing else in a Run directory changes after `run.yaml` exists.

## `eval.yaml`

```yaml
name: gpt-oss-h100                  # required; matches the directory name
description: >-                     # optional
  Kernels, forward, and DFlash for gpt-oss-20b on one H100.
deployment: ../../examples/h100-gpt-oss/kelpie.toml   # required; relative to this file
grade:                              # required; the Grades that make up the Eval
  - task: rms_norm                  # Task name
    config: deployment              # Config of the Run to grade
    grader: kernel                  # Grader name
goldens:                            # optional; name -> list of keyed entries
  hf-fp32:
    - model: openai/gpt-oss-20b     # matched against the candidate's run.yaml `model`
      gpu_arch: sm_90               # matched against `gpu_arch`, or `any`
      deterministic: any            # true, false, or any
      path: runs/gpt-oss-math-tf/hf-fp32/2026-09-23T101500Z   # relative to the eval directory
calibrations:                       # optional; name -> Calibration declaration
  k0-batch-noise:
    task: gpt-oss-dflash-tf         # Task of the source Runs
    config: dflash-k0-b8            # Config of the source Runs
    grader: k0-batch                # measurement Grader, already run on the source Runs
    check: logprobs                 # measurement Check in that Grader
    statistic: max_abs              # key in the Check's per-Case details
    upstream: k0-vs-hf              # Grader that every trusted Run must pass
    ceiling: 1.0e-1                 # the calibrated value must not exceed this
    ceiling_source: derived         # derived | "vendored: <pin>"
    ceiling_note: 2 x the vendored atol in k0-vs-hf/logprobs
```

For each `grade` entry, `kelpie grade` grades the newest complete Run of that Task and Config.

## Task

```yaml
name: rms_norm                      # required; matches the file name
subject:                            # required
  kind: op                          # op | model | engine | benchmark
  op: rms_norm                      # kind: op. The name of a kelpie Op
  model: openai/gpt-oss-20b         # kind: model, engine, or benchmark. HF model ID
  benchmark: gsm8k                  # kind: benchmark. Benchmark name
cases:                              # required; one of the two forms below
  grid:                             # form 1 (op): Cartesian product of every list
    dtype: [bf16, fp16, fp32]
    dims:
      - {tokens: 1, hidden: 2880}
      - {tokens: 64, hidden: 2880}
  seeds: [41, 42, 43]               # multiplies the grid
  # rows: all                       # form 2 (model, engine): one Case per corpus row, or a list of row indices
corpus: data/math-16x512.safetensors   # model and engine only; relative to tasks/
mode: teacher_forced                # engine only: teacher_forced | free
record:                             # model and engine only
  topk: 20                          # entries per position in topk_ids and topk_logits
  logits: none                      # none | full. full adds the `logits` output
  taps: [resid_post]                # records the `resid_post` output (sites from kelpie_models.sdk.taps.SITES)
outputs: [out]                      # required; output names every Run of this Task must contain
```

### Cases and `case_id`

`case_id` is `sha1(canonical_json(params))[:12]`, where `canonical_json` is `json.dumps(obj, sort_keys=True, separators=(",", ":"))`.

| Subject | `params` |
|---|---|
| op | `{op, dtype, dims, seed}` |
| model | `{model, corpus_sha256, row}` |
| engine | `{model, corpus_sha256, row, mode}`, or `{model, prompt_sha256}` for `mode: free` |
| benchmark | `{benchmark, questions_sha256, n}` |

`params` never contains a Config field. Runs of one Task under different Configs therefore have the same `case_id` values. A Pinned benchmark score uses the benchmark `params`, so its `case_id` matches a benchmark Run over the same questions.

### Op inputs

`kelpie record` builds the inputs of an op Case with `torch.manual_seed(seed)` followed by `Op.sample_args(device, dtype, **dims)`. Today `Op.samples` registers a function of `(device, dtype)` only. This spec adds the `dims` keyword arguments.

A Config with `reference: op_fp64` builds the inputs at the Case's `dtype` and then upcasts floating-point tensors to fp64. The inputs are therefore identical before the upcast.

### Corpus file

A corpus is a safetensors file with two tensors:

| Tensor | Shape | Dtype | Meaning |
|---|---|---|---|
| `tokens` | `[N, T]` | int32 | Token IDs. Row `i` is Case `row: i`. |
| `prompt_len` | `[N]` | int32 | Number of prompt tokens in each row. |

Under `mode: teacher_forced`, the engine decodes from `tokens[i, :prompt_len[i]]`, and the sampler output at each step is replaced by the next corpus token.

### Outputs by subject

Op Runs store each output of the op under its name. A single tensor output is named `out`.

Model and engine Runs store these outputs per Case. `P` is the number of positions in the row, `k` is `record.topk`, `V` is the vocabulary size, `L` is the number of layers, and `H` is the hidden size.

| Output | Shape | Dtype | Present when |
|---|---|---|---|
| `topk_ids` | `[P, k]` | int32 | always |
| `topk_logits` | `[P, k]` | fp32 | always |
| `lse` | `[P]` | fp32 | always. `logsumexp` of the logits at each position |
| `target_lp` | `[P - 1]` | fp32 | always. Logprob of `tokens[t + 1]` at position `t` |
| `logits` | `[P, V]` | fp32 | `record.logits: full` |
| `resid_post` | `[L, P, H]` | compute dtype of the forward | `record.taps` contains `resid_post` |
| `accept_len` | `[S]` | int32 | engine with a `spec` Config. Tokens committed at each of `S` verify steps: accepted drafts plus one |
| `score` | `[]` | fp64 | benchmark Tasks. Accuracy in percent |
| `n` | `[]` | int64 | benchmark Tasks. Number of questions |

A logprob is `topk_logits - lse[:, None]`. For `reference: hf`, `kelpie record` takes `resid_post[l]` from the output of decoder layer `l` with a forward hook. It does not use HF `hidden_states`, because the last entry of `hidden_states` comes after the final norm.

`logits: full` costs `V * 4` bytes per position. For gpt-oss (`V = 201088`) that is 804,352 bytes per position.

## Config

```yaml
name: deployment                    # required; matches the file name
kind: deployment                    # required; deployment | reference

# kind: deployment
deployment: ../../examples/h100-gpt-oss/kelpie.toml   # default: eval.yaml `deployment`
spec:                               # optional; engine only
  drafter: z-lab/gpt-oss-20b-DFlash
  k: 7                              # drafts per step. 0 runs the engine without drafts

# kind: reference
reference: op_fp64                  # op_fp64 | op_native | hf
dtype: fp32                         # reference: hf only
weights: checkpoint                 # reference: hf only. checkpoint | random
weights_seed: 0                     # weights: random only

# both kinds
batch_size: 1                       # Cases per forward. Default 1
world_size: 1                       # tensor parallel ranks. Default 1
deterministic: false                # torch.use_deterministic_algorithms and backend determinism flags
seed: 41                            # process seed for everything that is not a Case input
```

- `op_fp64` runs the op's `reference` function on inputs upcast to fp64.
- `op_native` runs the op's `reference` function at the Case's `dtype`.
- `hf` runs the HF transformers model for the Task's `subject.model` in `dtype`, with TF32 off.
- `kelpie.toml` has no `spec` section today. A `spec` block in a Config is the only way to set a drafter in this spec.

### Config hash

`config_hash` is `sha256(canonical_json(x))`, where `x` holds:

- the parsed Config YAML
- the sha256 of the `deployment` file bytes, for `kind: deployment`
- `{op: fingerprint(op, impl)}` for every bound op, from `kelpie_models.kernels.fingerprint.fingerprint`
- the resolved revision of every HF checkpoint the Config loads.

## `run.yaml`

```yaml
kind: recorded                      # recorded | pinned
run_id: rms_norm/deployment/2026-09-23T101500Z
task: rms_norm
task_sha256: 9b1d...                # sha256 of the Task file bytes
config: deployment                  # Config name, or `pinned`
config_hash: 5e0c...
fingerprints:                       # bound ops only
  rms_norm: 3f2a9c01b7de
model: openai/gpt-oss-20b           # model and engine subjects only
cases:
  - case_id: a41c09e2f7b3
    params: {op: rms_norm, dtype: bf16, dims: {tokens: 64, hidden: 2880}, seed: 41}
device: cuda
device_name: NVIDIA H100 80GB HBM3
gpu_arch: sm_90
world_size: 1
batch_size: 1
seed: 41
deterministic: false
versions:                           # keys present only for installed packages
  kelpie: f0dfb27                   # git commit
  python: 3.12.4
  torch: 2.13.0
  triton: 3.6.0
  cuda: "12.8"
  flashinfer: 0.6.3
  transformers: 4.58.0
recorded_at: 2026-09-23T10:15:00Z
record_seconds: 12.4
outputs:                            # key in outputs.safetensors -> dtype and shape
  a41c09e2f7b3/out: {dtype: bf16, shape: [64, 2880]}
source: null                        # pinned only: where the data came from (URL or run ID)
```

Keys in `outputs.safetensors` are `<case_id>/<output>`.

A Pinned `run.yaml` sets `kind: pinned`, `config: pinned`, and `source`. Its `config_hash` is the sha256 of `source`. Device fields may be `null`.

### Record key

`kelpie record` does not write a new Run when an existing complete Run of the same Task and Config matches this key for every Case:

```
(task, case_id, config_hash, device, gpu_arch, versions)
```

`kelpie record --force` writes a new Run regardless.

## Grader

```yaml
name: kernel                        # required; matches the file name
checks:                             # required; runs in order
  - name: fixed                     # required; unique in this Grader
    checker: fixed_tol              # required; built-in name, or a path relative to this file
    inputs:                         # required; input name -> input selector
      cand: run
      ref: config:op-native
    severity: block                 # block | warn. Default: the Checker default
    when: always                    # always | on_fail. Default: the Checker default
    params: {}                      # Checker parameters. Omitted keys take the Checker default
    tolerance_source: guessed       # calibrated | derived | guessed | "vendored: <pin>". Default: the Checker default
    tolerance_note: 09-21 verifier table   # optional free text
    calibration:                    # required when tolerance_source is calibrated; forbidden otherwise
      name: k0-batch-noise          # key in eval.yaml `calibrations`
      param: atol                   # the params key that the calibration sets
      factor: 2                     # params[param] = factor * calibrated value. Default 1
```

- A Grader must have at least one `block` Check.
- Every built-in Checker defaults to `severity: block` and `when: always`, except where its section says otherwise. A CLI Checker defaults to `block` and `always`.
- `when: on_fail` runs the Check only if the combined verdict of an earlier `block` Check in the same Grader is `fail`. Otherwise the Check is recorded as skipped, with verdict `null`. A skipped Check takes no part in the combine rule.
- `layer_drilldown` must have `severity: warn`. A Grader that sets it to `block` fails to load.
- A Check with `calibration` must not set `calibration.param` in `params`.

### Tolerance source

`tolerance_source` takes one of four values:

| Value | Meaning |
|---|---|
| `calibrated` | Measured from Runs by a [Calibration](#calibration). The Check must set `calibration`. |
| `derived` | Follows from the statistic itself, such as the error budget, bitwise equality, or a bound computed from other non-guessed tolerances. |
| `vendored: <pin>` | Copied from another project's tests. `<pin>` identifies the exact source. |
| `guessed` | None of the above. |

A pin has the form `<repo>@<git hash> <path>:<symbol or line>`:

```yaml
tolerance_source: "vendored: sglang@c3e9852 test/registered/e2e/models/test_generation_models.py:ModelCase.prefill_tolerance"
```

- `<repo>` is a short repository name. `tolerance_note` may give the URL.
- `<git hash>` is 7 to 40 lowercase hex characters.
- `<path>` is relative to the repository root at that commit.
- `<symbol or line>` is a dotted symbol name, or a line number `L<n>`.

A Grader fails to load when a `tolerance_source` does not match `^(calibrated|derived|guessed|vendored: [A-Za-z0-9_.-]+@[0-9a-f]{7,40} \S+:\S+)$`. `kelpie grade` does not fetch the pinned file.

### Calibration

A Calibration turns the details of a measurement Check into a tolerance value. `kelpie calibrate EVAL NAME` computes the Calibration declared at `eval.yaml` `calibrations.<name>` and writes `calibrations/<name>.yaml`.

Terms used in this section:

- **Source Runs**: every complete Run of the declaration's `task` and `config`.
- **Measurement inputs**: for each source Run, the Persisted that the measurement Check resolved for each of its inputs, as recorded in the Run's `grades/<grader>/grade.yaml`.
- **Trusted Runs**: every measurement input whose `kind` is `recorded` and whose Config has `kind: deployment`. Runs of `kind: reference` Configs, goldens, and Pinned data are independent and need no upstream Grade.
- **Qualifying Check**: a Check with `severity: block` that satisfies at least one of the following: every input other than `cand` resolves to a Run of a `kind: reference` Config or to a golden, or its `tolerance_source` is `derived` or `vendored`.

`kelpie calibrate` refuses to write the file, and exits non-zero, when any of these holds:

1. The `upstream` Grader has no qualifying Check.
2. The `upstream` Grader contains a Check that uses this Calibration, directly or through another Calibration.
3. A source Run has no `grades/<grader>/grade.yaml`, or that file does not contain `check`.
4. A trusted Run has no `grades/<upstream>/grade.yaml`, or its verdict is not `pass`.
5. A trusted Run's upstream Grade has a different `grader_sha256` from the current `upstream` Grader file.

Otherwise it computes `value`, the maximum of `details[statistic]` over every Case of every source Run. The measurement Check's own verdict does not affect `value`. The Calibration verdict is `pass` when `value <= ceiling`, and `fail` otherwise. `kelpie calibrate` writes the file in both cases, and exits non-zero on `fail`.

`ceiling` is required. `ceiling_source` must be `derived` or a `vendored: <pin>` value.

`calibrations/<name>.yaml`:

```yaml
name: k0-batch-noise
declaration_sha256: 41d0...         # sha256(canonical_json(eval.yaml calibrations.<name>))
calibrated_at: 2026-09-23T12:40:00Z
verdict: pass                       # pass | fail
statistic: max_abs
value: 3.1e-2
ceiling: 1.0e-1
ceiling_source: derived
measurement:
  grader: k0-batch
  grader_sha256: 77ab...
  check: logprobs
upstream:
  grader: k0-vs-hf
  grader_sha256: c519...
sources:                            # one entry per source Run
  - run_id: gpt-oss-dflash-tf/dflash-k0-b8/2026-09-23T120000Z
    value: 3.1e-2                   # max of details[statistic] over this Run's Cases
    inputs:                         # the measurement Check's resolved inputs
      cand: gpt-oss-dflash-tf/dflash-k0-b8/2026-09-23T120000Z
      ref: gpt-oss-dflash-tf/dflash-k0/2026-09-23T113000Z
trusted:                            # one entry per trusted Run
  - run_id: gpt-oss-dflash-tf/dflash-k0/2026-09-23T113000Z
    upstream_verdict: pass
    upstream_inputs:                # the upstream Grade's resolved inputs, per qualifying Check
      logprobs: {ref: gpt-oss-dflash-tf/hf-fp32/2026-09-23T101500Z}
  - run_id: gpt-oss-dflash-tf/dflash-k0-b8/2026-09-23T120000Z
    upstream_verdict: pass
    upstream_inputs:
      logprobs: {ref: gpt-oss-dflash-tf/hf-fp32/2026-09-23T101500Z}
```

#### Using a Calibration

For a Check with `tolerance_source: calibrated`, `kelpie grade` reads `calibrations/<calibration.name>.yaml` and sets `params[calibration.param] = calibration.factor * value`. Before each grading, it checks the Calibration's status. The status is not cached.

| Status | Condition | Check verdict |
|---|---|---|
| `valid` | none of the conditions below | computed by the Checker |
| `over_ceiling` | the file's `verdict` is `fail` | `fail` for every Case. The Checker is not called. |
| `invalid` | the file is missing. Or `declaration_sha256` differs from the current declaration. Or a `measurement` or `upstream` `grader_sha256` differs from the current Grader file. Or a trusted Run's upstream Grade is now missing, or its verdict is not `pass`. Or the newest complete Run of any trusted Run's Task and Config has no `pass` Grade from the `upstream` Grader. | `inconclusive` for every Case. The Checker is not called. |

A new `kelpie calibrate` run is the only way to make an `invalid` Calibration `valid` again.

### Input selectors

| Selector | Resolves to |
|---|---|
| `run` | The Run being graded. |
| `config:<name>` | The newest complete Run of the same Task under Config `<name>`. |
| `repeat` | The newest complete Run of the same Task and Config as the Run being graded, other than that Run. |
| `golden:<name>` | The first entry of `eval.yaml` `goldens.<name>` whose `model`, `gpu_arch`, and `deterministic` match the Run being graded. |
| `path:<dir>` | The Persisted at `<dir>`, relative to the eval directory. |

The input named `cand` must use the selector `run`.

### Input assertions

Before it calls a Checker on a Case, `kelpie grade` asserts all of the following. A failed assertion is a grading error, not a Verdict.

1. Every selector resolves to a directory that contains `run.yaml` and `outputs.safetensors`.
2. Every input's `run.yaml` lists the Case's `case_id`.
3. No two inputs resolve to the same directory.
4. For a built-in Checker, the inputs include every input the Checker requires, and nothing the Checker does not accept. A CLI Checker receives every input the Check binds, and checks its own inputs.
5. For a built-in Checker, every output the Checker reads exists for the Case in every input that it reads from.

### Combine rule

A Check's verdict over all Cases:

1. `fail` if any Case is `fail`.
2. Otherwise `inconclusive` if any Case is `inconclusive`.
3. Otherwise `pass`.

The Grade verdict:

1. `fail` if any `block` Check is `fail`.
2. Otherwise `inconclusive` if any `block` Check is `inconclusive`.
3. Otherwise `pass`.

`warn` Checks never change the Grade verdict. The Grade lists every `warn` Check that ran and whose verdict is not `pass` under `warnings`.

A Checker that raises, and a CLI Checker that breaks its contract, stop the Grader. `kelpie grade` writes no `grade.yaml` for that Grader and exits non-zero.

## `grade.yaml`

```yaml
grader: kernel
grader_sha256: 0c7e...              # sha256 of the Grader file bytes
run_id: rms_norm/deployment/2026-09-23T101500Z
verdict: pass                       # pass | fail | inconclusive
warnings: [budget]                  # warn Checks whose verdict is not pass
graded_at: 2026-09-23T11:02:10Z
checks:
  - name: fixed
    checker: fixed_tol
    checker_version: 1              # built-in version, or sha256 of the executable
    severity: block
    tolerance_source: guessed
    calibration: null               # calibrated Checks only. See below
    inputs:                         # input name -> resolved run ID or path
      cand: rms_norm/deployment/2026-09-23T101500Z
      ref: rms_norm/op-native/2026-09-23T100900Z
    params: {atol: {bf16: 2.0e-2, fp16: 1.0e-3, fp32: 2.0e-5}, rtol: {bf16: 2.0e-2, fp16: 1.0e-3, fp32: 1.0e-5}}
    verdict: pass
    skipped: false
    cases:
      a41c09e2f7b3:
        verdict: pass
        key: 7d3b...                # cache key
        details: {max_abs: 0.0039, max_rel: 0.0071, mismatch_count: 0, mismatch_frac: 0.0}
        notes: null
```

For a Check with `tolerance_source: calibrated`, `calibration` holds the lineage:

```yaml
    calibration:
      name: k0-batch-noise
      sha256: 9e41...               # sha256 of calibrations/<name>.yaml bytes
      status: valid                 # valid | over_ceiling | invalid
      value: 3.1e-2
      param: atol
      factor: 2
      resolved: 6.2e-2              # factor * value, the params value used
      measurement: {grader: k0-batch, check: logprobs}
      upstream: {grader: k0-vs-hf}
      sources: [gpt-oss-dflash-tf/dflash-k0-b8/2026-09-23T120000Z]
      trusted: [gpt-oss-dflash-tf/dflash-k0/2026-09-23T113000Z, gpt-oss-dflash-tf/dflash-k0-b8/2026-09-23T120000Z]
      reasons: []                   # the conditions that made the status over_ceiling or invalid
```

### Cache key

Each Case result stores a cache key. `kelpie grade` reuses a stored result when the key matches, and recomputes it otherwise. `kelpie grade --regrade` recomputes every result.

The key is `sha256(canonical_json(x))`, where `x` holds:

- `case_id`
- the `config_hash` of every input
- the run ID or path of every input
- the Checker name, the Checker version, and the resolved `params`
- the `versions` of every input
- for a calibrated Check, the sha256 of the Calibration file.

## Python types

```python
VerdictValue = Literal["pass", "fail", "inconclusive"]
Severity = Literal["block", "warn"]
When = Literal["always", "on_fail"]
ToleranceSource = str                     # "calibrated" | "derived" | "guessed" | "vendored: <pin>"
CalibrationStatus = Literal["valid", "over_ceiling", "invalid"]


@dataclass(frozen=True)
class Case:
	case_id: str                          # sha1(canonical_json(params))[:12]
	params: Mapping[str, Any]


@dataclass(frozen=True)
class Persisted:
	"""A directory with run.yaml and outputs.safetensors. A Run is a Persisted with kind "recorded"."""
	path: Path
	run_id: str
	kind: Literal["recorded", "pinned"]
	task: str
	config: str
	config_hash: str
	cases: tuple[Case, ...]
	versions: Mapping[str, str]
	model: str | None
	device: str | None
	gpu_arch: str | None
	seed: int | None
	deterministic: bool | None

	def outputs(self, case_id: str) -> Mapping[str, torch.Tensor]: ...
	def select(self, case_id: str) -> "Persisted": ...   # the same Persisted, restricted to one Case


@dataclass(frozen=True)
class Check:
	name: str
	checker: str                          # built-in name or executable path
	inputs: Mapping[str, str]             # input name -> input selector
	severity: Severity | None = None      # None: the Checker default
	when: When | None = None              # None: the Checker default
	params: Mapping[str, Any] = field(default_factory=dict)
	tolerance_source: ToleranceSource | None = None   # None: the Checker default
	tolerance_note: str | None = None
	calibration: "CalibrationRef | None" = None


@dataclass(frozen=True)
class CalibrationRef:
	name: str                             # key in eval.yaml calibrations
	param: str
	factor: float = 1.0


@dataclass(frozen=True)
class Verdict:
	correct: bool
	inconclusive: bool = False            # __post_init__ asserts not (correct and inconclusive)
	details: Mapping[str, Any] = field(default_factory=dict)
	notes: str | None = None

	@property
	def value(self) -> VerdictValue: ...  # "pass" if correct, else "inconclusive" or "fail"


@dataclass(frozen=True)
class CheckResult:
	check: Check
	inputs: Mapping[str, str]             # input name -> resolved run ID or path
	cases: Mapping[str, Verdict]          # case_id -> Verdict
	keys: Mapping[str, str]               # case_id -> cache key
	verdict: VerdictValue | None          # combined over Cases. None when skipped
	skipped: bool = False


@dataclass(frozen=True)
class Grade:
	grader: str
	grader_sha256: str
	run_id: str
	verdict: VerdictValue
	warnings: tuple[str, ...]
	checks: tuple[CheckResult, ...]


class Checker(Protocol):
	name: str
	version: str
	required_inputs: frozenset[str]       # for example {"cand", "ref"}
	optional_inputs: frozenset[str]
	default_severity: Severity
	default_when: When

	def __call__(self, inputs: Mapping[str, Persisted], params: Mapping[str, Any]) -> Verdict: ...
```

`kelpie grade` calls a Checker once per Case. Every Persisted in `inputs` is restricted to that Case with `Persisted.select`.

## Built-in Checkers

Every built-in Checker compares tensors in fp32 or wider. Unless a Checker says otherwise, it reads every output named in the Task's `outputs`, and integer outputs must be equal. Every Checker fails a Case whose inputs differ in output shape.

`dtype` in a default table is the dtype of the `ref` output.

### `fixed_tol`

Elementwise tolerance against one reference.

- **Inputs:** `cand`, `ref`.
- **Statistic:** an element mismatches when `|cand - ref| > atol + rtol * |ref|`, computed in `torch.promote_types(ref.dtype, torch.float32)`. NaN or Inf in either tensor is a mismatch.
- **Pass:** the mismatch count is 0, and the two outputs have the same dtype.
- **Details:** `max_abs`, `max_rel`, `mismatch_count`, `mismatch_frac`, and `worst`: the 10 largest mismatches as `[index, cand, ref]`.
- **Default `tolerance_source`:** `guessed`.

| Parameter | Default |
|---|---|
| `atol` | fp32 `2e-5`, fp16 `1e-3`, bf16 `2e-2` |
| `rtol` | fp32 `1e-5`, fp16 `1e-3`, bf16 `2e-2` |

`atol` and `rtol` take a number or a map from dtype to number.

### `budget`

Error budget against an fp64 truth, as in popcorn and crucible.

- **Inputs:** `cand`, `ref` (reference at native dtype), `truth` (reference in fp64).
- **Statistic:** `err(x) = max|x - truth|` over all elements, in fp64. `band = max(factor * err(ref), floor[dtype] * max|truth|)`.
- **Inconclusive:** `err(ref) / max|truth| > inconclusive_rel`.
- **Pass:** `err(cand)` is finite and `err(cand) <= band`.
- **Details:** `err`, `ref_err`, `band`, `ref_rel_err`.
- **Default `tolerance_source`:** `derived`.

| Parameter | Default |
|---|---|
| `factor` | `2` |
| `floor` | fp64 `1e-10`, fp32 `2e-5`, fp16 `1e-3`, bf16 `2e-2` |
| `inconclusive_rel` | `0.1` |

### `tie_greedy`

Tie-aware greedy agreement at every teacher-forced position.

- **Inputs:** `cand`, `ref`.
- **Reads:** `topk_ids`, `topk_logits`.
- **Statistic:** at position `t`, let `c = cand.topk_ids[t, 0]` and `m = ref.topk_logits[t, 0]`. Let `step(x) = 2 ** (floor(log2(|x|)) - 7)`, the bf16 spacing at `x`, with `step(0) = 2 ** -133`. Position `t` passes when `c` is in `ref.topk_ids[t]` and its reference logit is at least `m - n_steps * step(m)`.
- **Pass:** every position passes.
- **Details:** `positions`, `exact` (positions with equal argmax), `ties` (positions that pass with a different argmax), `first_fail`.
- **Default `tolerance_source`:** `guessed`.

| Parameter | Default |
|---|---|
| `n_steps` | `2` |

### `topk_logprob`

Logprob values at the reference's top-k tokens.

- **Inputs:** `cand`, `ref`.
- **Reads:** `topk_ids`, `topk_logits`, `lse`.
- **Statistic:** for each position `t` and each of the first `k` IDs in `ref.topk_ids[t]`, `|lp_cand - lp_ref|`, where `lp = topk_logits - lse`. An ID that is absent from `cand.topk_ids[t]` counts as missing.
- **Pass:** no ID is missing, and the maximum difference is at most `atol`.
- **Details:** `max_abs`, `mean_abs`, `p99_abs`, `worst_position`, `missing`.
- **Default `tolerance_source`:** `vendored: sglang@c3e9852 test/registered/e2e/models/test_generation_models.py:ModelCase.prefill_tolerance`.

| Parameter | Default |
|---|---|
| `k` | `5` |
| `atol` | `5e-2` |

`k` must not exceed the Task's `record.topk`.

### `kl`

Full-softmax KL divergence at every position.

- **Inputs:** `cand`, `ref`.
- **Reads:** `logits`.
- **Statistic:** `KL(ref || cand)[t] = sum_v p_ref[t, v] * (log p_ref[t, v] - log p_cand[t, v])`, in fp64, summed over the vocabulary.
- **Pass:** `mean(KL) <= mean_tol` and `max(KL) <= max_tol`.
- **Details:** `mean`, `p99`, `max`, `worst_position`.
- **Default `tolerance_source`:** `guessed`.

| Parameter | Default |
|---|---|
| `mean_tol` | `1e-3` |
| `max_tol` | `5e-2` |

### `null_ratio`

Error relative to a null model, as in Megatron's checkpoint converter.

- **Inputs:** `cand`, `ref`, `null`.
- **Reads:** the output named by `output`.
- **Statistic:** `ratio = err(cand) / err(null)`, where `err(x) = mean((x - ref) ** 2)`. The `null` input is a Run of a null model, such as a Config with `weights: random`.
- **Inconclusive:** `err(null) == 0`.
- **Pass:** `ratio <= max_ratio`.
- **Details:** `err`, `null_err`, `ratio`.
- **Default `tolerance_source`:** `guessed`. The default `max_ratio` is Megatron's.

| Parameter | Default |
|---|---|
| `output` | `target_lp` |
| `max_ratio` | `0.05` |

### `bitwise`

Bit-identical outputs.

- **Inputs:** `cand`, `ref`.
- **Statistic:** `torch.equal` on every output.
- **Pass:** every output is equal.
- **Details:** `n_diff`, `first_diff` (output name and index), `max_abs`.
- **Default `tolerance_source`:** `derived`.
- **Parameters:** none.

### `layer_drilldown`

The first layer where hidden states diverge. Always `severity: warn`.

- **Inputs:** `cand`, `ref`.
- **Reads:** `resid_post`.
- **Statistic:** `d[l] = max|cand.resid_post[l] - ref.resid_post[l]|` in fp32, for each layer `l`.
- **Pass:** `d[l] <= atol` for every layer.
- **Details:** `first_layer` (the lowest `l` with `d[l] > atol`, or `null`), `per_layer` (the list `d`).
- **Default `tolerance_source`:** `guessed`. The default `atol` is TokenSpeed's.
- **Default `severity`:** `warn`.
- **Default `when`:** `on_fail`.

| Parameter | Default |
|---|---|
| `atol` | `5e-3` |

### `z_test`

One-sided hypothesis test on a benchmark score, from TensorRT-LLM `accuracy_core.py`.

- **Inputs:** `cand`, `pinned`.
- **Reads:** `score`, `n`.
- **Statistic:** `scale = sqrt(2 * sigma**2 / n)`, `gamma = pinned.score + Φ⁻¹(alpha) * scale`, and `theta = -(Φ⁻¹(alpha) + Φ⁻¹(beta)) * scale`. `sigma` is a standard deviation in score percent.
- **Pass:** `cand.score >= gamma`, and `cand.n == pinned.n`.
- **Details:** `score`, `ref_score`, `gamma`, `theta`, `n`.
- **Default `tolerance_source`:** `derived`.

| Parameter | Default |
|---|---|
| `alpha` | `0.05` |
| `beta` | `0.2` |
| `sigma` | `50` |

## CLI checker contract

A Check whose `checker` is a path runs that executable once per Case. The contract follows smevals and loom's `script_scorer`, with one change: the exit code does not carry the verdict.

`kelpie grade` runs the executable with no arguments. The working directory is `grades/<grader>/` of the Run being graded. Files written there are kept with the Grade. The environment contains:

| Variable | Value |
|---|---|
| `KELPIE_INPUT_<NAME>` | Absolute path of each input's Persisted directory. `<NAME>` is the input name in upper case, for example `KELPIE_INPUT_CAND`. |
| `KELPIE_INPUTS` | JSON object: input name -> absolute path. |
| `KELPIE_CASE_ID` | The Case's `case_id`. |
| `KELPIE_TASK` | The Task name. |
| `KELPIE_CHECK` | The whole Check entry as JSON, with selectors resolved to paths. |
| `KELPIE_CHECK_<KEY>` | Each scalar key in `params`, upper case. |
| `KELPIE_EVAL_DIR` | Absolute path of the eval directory. |

The executable prints one JSON object on standard output:

```json
{"verdict": "pass", "metrics": {"mean_accept_len": 2.31}, "notes": "64 rows"}
```

| Key | Required | Meaning |
|---|---|---|
| `verdict` | yes | `pass`, `fail`, or `inconclusive`. |
| `metrics` | no | Object of numbers and booleans. `kelpie grade` stores it as `Verdict.details`. |
| `notes` | no | String. Stored as `Verdict.notes`. |

- Exit code 0 with a valid object: the object is the Verdict.
- A non-zero exit code, invalid JSON, a missing `verdict`, or a timeout: the Checker broke its contract, and grading stops.
- `timeout_s` is a reserved key in `params`. The default is 600.
- The Checker version in the cache key is the sha256 of the executable's bytes.

## Eval in the build manifest

`Manifest` in `kelpie-models/kelpie_models/sdk/manifest.py` gains one field, and `SCHEMA` becomes 2:

```python
@dataclass(frozen=True)
class EvalGrade:
	task: str
	config: str
	grader: str
	run_id: str
	verdict: VerdictValue
	warnings: tuple[str, ...]


@dataclass(frozen=True)
class EvalRecord:
	name: str
	graded_at: str
	grades: tuple[EvalGrade, ...]


# Manifest
eval: EvalRecord | None = None
```

`kelpie serve` refuses to start when any `EvalGrade.verdict` is `fail`. It warns when a verdict is `inconclusive`, and when a Grade listed in `eval.yaml` is missing. This matches the current rule in `kelpie-models/kelpie_models/sdk/cache.py`: a recorded `fail` refuses, and a missing verdict warns.

This spec does not define how `EvalRecord` relates to the existing per-op `Entry.verdict`, `Entry.err`, and `Entry.budget`.

## Commands

```
kelpie record EVAL --task TASK --config CONFIG [--force]
kelpie grade EVAL [--grader GRADER] [--regrade]
kelpie calibrate EVAL NAME
```

- `kelpie record` writes one Run, subject to the [record key](#record-key).
- `kelpie grade` without `--grader` grades every entry in `eval.yaml` `grade`, then writes `EvalRecord` into the deployment's manifest.
- `kelpie grade` needs no GPU.
- `kelpie calibrate` writes one file under `calibrations/`, subject to the rules in [Calibration](#calibration). It needs no GPU.

## Worked examples

All three examples belong to one Eval, `kelpie/evals/gpt-oss-h100/`. The deployment file `kelpie/examples/h100-gpt-oss/kelpie.toml` does not exist yet.

### `eval.yaml`

```yaml
name: gpt-oss-h100
description: Kernels, forward, and DFlash for gpt-oss-20b on one H100.
deployment: ../../examples/h100-gpt-oss/kelpie.toml
grade:
  - {task: rms_norm, config: deployment, grader: kernel}
  - {task: gpt-oss-math-tf, config: deployment, grader: model-forward}
  - {task: gpt-oss-dflash-tf, config: dflash-k0, grader: k0-vs-hf}
  - {task: gpt-oss-dflash-tf, config: dflash-k0-b8, grader: k0-vs-hf}
  - {task: gpt-oss-dflash-tf, config: dflash-k0-b8, grader: k0-batch}
  - {task: gpt-oss-dflash-tf, config: dflash-k7, grader: spec-parity}
goldens:
  hf-fp32:
    - model: openai/gpt-oss-20b
      gpu_arch: sm_90
      deterministic: any
      path: runs/gpt-oss-math-tf/hf-fp32/2026-09-23T101500Z
calibrations:
  k0-batch-noise:
    task: gpt-oss-dflash-tf
    config: dflash-k0-b8
    grader: k0-batch
    check: logprobs
    statistic: max_abs
    upstream: k0-vs-hf
    ceiling: 1.0e-1
    ceiling_source: derived
    ceiling_note: 2 x the vendored atol in k0-vs-hf/logprobs
```

### Configs

```yaml
# configs/deployment.yaml
name: deployment
kind: deployment

# configs/op-fp64.yaml
name: op-fp64
kind: reference
reference: op_fp64

# configs/op-native.yaml
name: op-native
kind: reference
reference: op_native

# configs/hf-fp32.yaml. Recorded once on an H200: fp32 weights need about 84 GB.
name: hf-fp32
kind: reference
reference: hf
dtype: fp32
deterministic: true

# configs/hf-random.yaml. The null model for null_ratio.
name: hf-random
kind: reference
reference: hf
dtype: fp32
weights: random
weights_seed: 0

# configs/dflash-k7.yaml
name: dflash-k7
kind: deployment
spec: {drafter: z-lab/gpt-oss-20b-DFlash, k: 7}
batch_size: 8

# configs/dflash-k0.yaml
name: dflash-k0
kind: deployment
spec: {drafter: z-lab/gpt-oss-20b-DFlash, k: 0}

# configs/dflash-k0-b8.yaml
name: dflash-k0-b8
kind: deployment
spec: {drafter: z-lab/gpt-oss-20b-DFlash, k: 0}
batch_size: 8
```

### Kernel: `rms_norm`

```yaml
# tasks/rms_norm.yaml
name: rms_norm
subject: {kind: op, op: rms_norm}
cases:
  grid:
    dtype: [bf16, fp16, fp32]
    dims:
      - {tokens: 1, hidden: 2880}
      - {tokens: 64, hidden: 2880}
      - {tokens: 4096, hidden: 2880}
  seeds: [41, 42, 43]
outputs: [out]
```

```yaml
# graders/kernel.yaml
name: kernel
checks:
  - name: fixed
    checker: fixed_tol
    inputs: {cand: run, ref: config:op-native}
    severity: block
    tolerance_source: guessed
    tolerance_note: 09-21 verifier table
  - name: budget
    checker: budget
    inputs: {cand: run, ref: config:op-native, truth: config:op-fp64}
    severity: warn
```

Record and grade:

```
kelpie record gpt-oss-h100 --task rms_norm --config op-fp64
kelpie record gpt-oss-h100 --task rms_norm --config op-native
kelpie record gpt-oss-h100 --task rms_norm --config deployment
kelpie grade gpt-oss-h100 --grader kernel
```

The Task has 27 Cases: 3 dtypes, 3 shapes, and 3 seeds.

### Model forward: gpt-oss, teacher-forced against the HF fp32 golden

```yaml
# tasks/gpt-oss-math-tf.yaml
name: gpt-oss-math-tf
subject: {kind: model, model: openai/gpt-oss-20b}
corpus: data/math-16x512.safetensors   # 16 rows of 512 tokens
cases: {rows: all}
record:
  topk: 20
  logits: none
  taps: [resid_post]
outputs: [topk_ids, topk_logits, lse, target_lp, resid_post]
```

```yaml
# graders/model-forward.yaml
name: model-forward
checks:
  - name: greedy
    checker: tie_greedy
    inputs: {cand: run, ref: golden:hf-fp32}
    severity: block
    params: {n_steps: 2}
  - name: logprobs
    checker: topk_logprob
    inputs: {cand: run, ref: golden:hf-fp32}
    severity: block
    params: {k: 5, atol: 5.0e-2}
    tolerance_note: SGLang prefill bar
  - name: null
    checker: null_ratio
    inputs: {cand: run, ref: golden:hf-fp32, null: config:hf-random}
    severity: warn
    params: {output: target_lp, max_ratio: 0.05}
    tolerance_note: Megatron ckpt_converter
  - name: drilldown
    checker: layer_drilldown
    inputs: {cand: run, ref: golden:hf-fp32}
    severity: warn
    when: on_fail
    params: {atol: 5.0e-3}
```

Record and grade:

```
kelpie record gpt-oss-h100 --task gpt-oss-math-tf --config hf-random
kelpie record gpt-oss-h100 --task gpt-oss-math-tf --config deployment
kelpie grade gpt-oss-h100 --grader model-forward
```

The golden already exists, so this example records no `hf-fp32` Run.

### Speculative decode: DFlash, a calibrated chain against `K=0`

All four engine Configs run over the same corpus under `mode: teacher_forced`. The `K=7` Run takes its logits from the verify rows. The `K=0` Runs take them from plain decode rows. The HF fp32 reference is recorded on this Task too, because an engine `case_id` includes `mode` and does not match the model golden's.

The example is a three-link chain:

1. `k0-vs-hf` grades `dflash-k0` and `dflash-k0-b8` against `hf-fp32`, with vendored tolerances.
2. `k0-batch` measures `dflash-k0-b8` against `dflash-k0`. The Calibration `k0-batch-noise` takes the largest logprob difference as the batching noise. Its ceiling is twice the vendored `atol` from link 1.
3. `spec-parity` grades `dflash-k7` against `dflash-k0` with `atol` set to twice the calibrated noise.

```yaml
# tasks/gpt-oss-dflash-tf.yaml
name: gpt-oss-dflash-tf
subject: {kind: engine, model: openai/gpt-oss-20b}
corpus: data/math-16x512.safetensors
cases: {rows: all}
mode: teacher_forced
record: {topk: 20, logits: none, taps: []}
outputs: [topk_ids, topk_logits, lse, target_lp]
```

```yaml
# graders/k0-vs-hf.yaml. Link 1: the independent anchor.
name: k0-vs-hf
checks:
  - name: greedy
    checker: tie_greedy
    inputs: {cand: run, ref: config:hf-fp32}
    severity: block
  - name: logprobs
    checker: topk_logprob
    inputs: {cand: run, ref: config:hf-fp32}
    severity: block
    params: {atol: 5.0e-2}
    tolerance_source: "vendored: sglang@c3e9852 test/registered/e2e/models/test_generation_models.py:ModelCase.prefill_tolerance"
```

```yaml
# graders/k0-batch.yaml. Link 2: the measurement for k0-batch-noise.
name: k0-batch
checks:
  - name: logprobs
    checker: topk_logprob
    inputs: {cand: run, ref: config:dflash-k0}
    severity: block
    params: {atol: 1.0e-1}
    tolerance_source: derived
    tolerance_note: the k0-batch-noise ceiling
  - name: bitwise
    checker: bitwise
    inputs: {cand: run, ref: config:dflash-k0}
    severity: warn
```

```yaml
# graders/spec-parity.yaml. Link 3.
name: spec-parity
checks:
  - name: greedy
    checker: tie_greedy
    inputs: {cand: run, ref: config:dflash-k0}
    severity: block
  - name: logprobs
    checker: topk_logprob
    inputs: {cand: run, ref: config:dflash-k0}
    severity: block
    tolerance_source: calibrated
    calibration: {name: k0-batch-noise, param: atol, factor: 2}
  - name: accept
    checker: ../checkers/accept_len
    inputs: {cand: run}
    severity: block
    params: {min_mean: 1.5}
    tolerance_source: guessed
    tolerance_note: prove_dflash draft, 2026-09-20
  - name: bitwise-k0
    checker: bitwise
    inputs: {cand: run, ref: config:dflash-k0}
    severity: warn
  - name: repeat
    checker: bitwise
    inputs: {cand: run, ref: repeat}
    severity: warn
```

```python
#!/usr/bin/env python3
# checkers/accept_len
import json, os
from safetensors.torch import load_file

case = os.environ["KELPIE_CASE_ID"]
outputs = load_file(os.path.join(os.environ["KELPIE_INPUT_CAND"], "outputs.safetensors"))
accept = outputs[f"{case}/accept_len"].double()
mean = accept.mean().item()
floor = float(os.environ["KELPIE_CHECK_MIN_MEAN"])
print(json.dumps({
	"verdict": "pass" if mean >= floor else "fail",
	"metrics": {"mean_accept_len": mean, "steps": accept.numel()},
}))
```

Record and grade:

```
kelpie record gpt-oss-h100 --task gpt-oss-dflash-tf --config hf-fp32
kelpie record gpt-oss-h100 --task gpt-oss-dflash-tf --config dflash-k0
kelpie record gpt-oss-h100 --task gpt-oss-dflash-tf --config dflash-k0-b8
kelpie grade gpt-oss-h100 --grader k0-vs-hf
kelpie grade gpt-oss-h100 --grader k0-batch
kelpie calibrate gpt-oss-h100 k0-batch-noise
kelpie record gpt-oss-h100 --task gpt-oss-dflash-tf --config dflash-k7
kelpie record gpt-oss-h100 --task gpt-oss-dflash-tf --config dflash-k7 --force
kelpie grade gpt-oss-h100 --grader spec-parity
```

The second `dflash-k7` Run exists for the `repeat` Check. The `repeat` selector resolves to the older of the two Runs when `kelpie grade` grades the newer one.

If a later `dflash-k0` Run fails `k0-vs-hf`, `k0-batch-noise` becomes `invalid`, and the `logprobs` Check in `spec-parity` returns `inconclusive` until `kelpie calibrate` runs again on passing Runs. If `dflash-k0-b8` drifts past `1.0e-1` from `dflash-k0`, `kelpie calibrate` writes `verdict: fail`, and the same Check returns `fail`.
