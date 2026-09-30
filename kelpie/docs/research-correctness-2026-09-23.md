# Research: correctness observers for kelpie (prior art, no design)

Date: 2026-09-23. Research only; nothing in the code changed. External clones (shallow, sparse, HEAD on 2026-09-23) are in
`/private/tmp/claude-501/-Users-chiraagbalu-research-2/7c590565-955e-4311-b0ba-fa12ccd50c23/scratchpad/{ext,ext2}/`.
Abbreviations: `CP=~/.claude/projects`, `CX=~/.codex/sessions/2026`.

The framing: each observer level defines its own meaning of "correct".

| Level | Meaning of "correct" | Blocking? |
|---|---|---|
| L0 | formal, graph level | no |
| L1 | kernel matches an upcast reference | no |
| L2 | kernel matches a same-dtype reference within an rtol/atol set per dtype | yes |
| L3 | model logits match a reference, checked like a kernel | yes |
| L4 | model behaves the same statistically | mostly |
| SD | spec decode: greedy spec == greedy no-spec; at T>0 the distributions are equal | — |

---

## 1. What we already decided in past sessions

### Observer / verifier ladder

**"L0-Lx" has meant three different ladders:**
1. The engine curriculum (08-25). It ran L0 "wire" up to L9 batch invariance and L10 spec decode, and was archived on 09-02.
2. The crucible verification levels L0-L6 (08-31, `CP/...-crucible/8c720d40`): smoke, dummy greedy, dummy allclose, fp64 budget, top-k logprob set, real-weight greedy, eval score. You said to build every level and "decide what we ship later".
3. The "L0-L5" comment in crucible's `fwd-02` task.toml.

**Five correctness layers** (09-02, `CP/...-crucible/243855f7`, a kelpie design session):
- the layers were "kernel layer / greedy full model layer / top k logits … for temp checks / hypothesis testing over actual benchmark runs like mmlu";
- benchmark accuracy was framed as "a regression alarm, never the definition".

**From ladder to observers** (09-03, `CX/09/03/rollout-...01a0686e`, about 19:00 UTC):
- You said: "the observer is the thing that defines if something is correct/close enough … simply report all and let the user write their own code to validate/gate … avoid making too many thin abstractions".

**Report shape** (09-04, `CX/09/04/rollout-...01a06ab1`, about 08:00):
- The report is a list of results, one per observer.
- Each result is `correct: bool` plus a `details[]` bag, with "the correct: function … passed as something that operates over the details bag".
- An observer that crashes raises; it does not return `correct=False`.
- **Agreed in conversation; no code exists.**

**Check function** (09-10):
- You said: "check fn should take in a pair and return a report, with parameterizable 'pass'", "a forward pass == a kernel", "dumbest thing that works".
- The plan was to copy crucible's `correctness.py` and `probe/check.py`.
- The check function for each rung is still marked "Open for you".

### Choice of reference

- **08-31:** "reference: hf transformers; comparison: greedy, top k logprob set equality, rtol/atol like our kernel benchmarks". A model forward is treated as an OpSpec, and random seeded weights are allowed.
- **09-02:** You asked "can we do fp64 above kernel level? wont it be p big". The resolution:
  - fp64 HF only for small synthetic configs;
  - real checkpoints are compared against a frozen fp32 corpus;
  - every backend is compared against HF, never against another backend.
  - You also said "not the depth of anti cheat".
- **09-09** (`kelpie-core/7128bde7`): rasbt teaching code with random weights is acceptable as the reference (for DSA/dsv4).
- **09-21** (`CP/-Users-chiraagbalu-research-2/c358631c`, about 19:00): you wanted references "ideally vendored from vllm/sgl/tkspeed/trtllm". Deploy should be "forced to hit a cache or run the tests". This produced `verify.py`, which `bind()` calls (see §2).

### Tolerances

- **08-28:** you proposed a hypothesis test "rather than a single flat tolerance". It became a self-budget: 2× the max error over 20 seeds.
- **09-04:** "one level below for setting the tolerance tighter, one level above for setting the tolerance looser".
- **09-05:** the task author must have the knobs: pinned dtype, atol, rtol.
- **09-21** (`c358631c`, 19:28): "rtol/atol … as a blocking and fp64 exactness can be warning". Implemented as:
  - BLOCK = FixedTolerance at native dtype;
  - WARN = fp64 budget.
  - Rope in bf16 then failed at 0.0078, so the BLOCK tolerance became dtype-aware.

### HF parity notes (09-02, `243855f7`)

- tiny gpt_oss error was 4e-7 against a 1.5e-5 band;
- TF32 is pinned off;
- dsv4 is compared on CPU, because HF's own CPU and CUDA runs differ by 0.085 on indexer top-k ties;
- the top-k check uses "values at oracle support", not membership or Jaccard. A top-20 Jaccard ≥ 0.9 test failed on a max diff of 0.0077.

### Batch invariance (09-03)

- You said: "ok with not using batch invariant kernels … important to know that we might want to check for it / relax constraints when we dont expect batch invariance".
- `decisions.md:54`: "Batch invariance is tested for, not assumed."
- **Status: a diagnostic, not a gate.**

### Spec decode

- 08-22: "spec decode is allowed but we should still report that logprobs are different".
- 09-08:
  - T>0 uses lossless rejection sampling with the drafter's real softmax;
  - greedy is tie-aware with an asserted band, plus a logit check on the verify rows;
  - 1-vs-8-row batch invariance is a non-fatal diagnostic.
- 09-20 (`CP/-Users-chiraagbalu-research-2/0827da84`): `prove_dflash` was drafted as an **exact** token match plus acceptance length ≥ 1.5. **This contradicts the tie-aware ruling from 09-08.**

### Popcorn

- **Taken from it:** the three-way fp64/native/candidate budget, checking each override's signature against the reference, covering-array shapes.
- **Rejected:** its per-call dispatch, tuner and global registry.
- **Open:** depend on it or hand-roll (09-09: "most of what they do is hand-rollable?").

---

## 2. Local code: crucible and kelpie

### crucible

**`crucible/verification/kernels/correctness.py`:**
- Tolerance types: `ExactTolerance`, `BudgetTolerance(recheck_atol=1e-2, recheck_rtol=1e-2)`, `FixedTolerance(atol, rtol)` (lines 8-25).
- `DTYPE_FLOORS = {fp32: 2e-5, fp16: 1e-3, bf16: 2e-2}` (lines 27-31).
- `error_budget(truth, ref) = max(2·max|ref−truth|, floor·max|truth|)` (lines 34-50). The metric is global max-abs; there is no ULP or per-element relative check.
- `zip_leaves` walks nested outputs; integer outputs must match exactly.

**Driver** (`verify.py:414-456`): 3 correctness rounds (seed 41) plus probes (seed 7000). The timed recheck uses a fixed 1e-2 band.

**No written L0-L5 spec exists.** The ladder below is reconstructed from `model_logits.py`:

| Level | What it checks |
|---|---|
| L0 | static audit + registry |
| L1 | probes: `all_same`, `max_token_id`, `single_token_repeated`; any failure zeroes the score |
| L2 | dummy weights (`randn*1e-3`), budget against a separately built **fp64 HF model** |
| L3 | argmax equal, plus log-probs at the oracle's top-10, atol 1e-3 (`decision_match :745`) |
| L4 | 4-step rollout driven by the oracle's argmax, running L2 and L3 at every step |
| L5 | real weights, FixedTolerance calibrated per model; exists only on the unmerged branch `codex/model-ladder-verifier` |

L5 values on that branch:
- gpt2 fp32: 1e-4.
- qwen3 bf16: atol **1.25**, rtol 5e-2. Seed 8000 is dropped because of a genuine near-tie flip.
- gpt-oss: atol 0.75, decision atol 0.3.
- the others: 1e-2.

**Engine-tier design** (`benchmarks/engines/meta/docs/design.md:43-93`):
- C1: exact greedy string.
- C2: sampled log-prob within max(4× HF-at-dtype error, 0.02) of fp64, the other top-5 log-probs within max(8×, 0.06), and top-5 ids equal.
- C3: streamed == non-streamed.

**crucible bug:** the merged `fwd-*` tasks build `truth=None`, and `upcast_fp64` of an integer `input_ids` leaves the model in bf16. The "truth" is therefore the bf16 model itself, and the band collapses to `2e-2·max|logit|`. The `task.toml` atol/rtol/greedy_steps values are never read.

### kelpie, live code (this checkout)

**Copied from crucible:**
- `kelpie-models/kelpie_models/bench/correctness.py` is a verbatim copy of crucible's `correctness.py`.
- `bench/probe/*` is a verbatim copy of crucible's engine probe (upstream commit `84a510d`).

**`build(check=True)` path** (`sdk/run.py:108-148`) calls `bench/compare.py`, which does the three-way popcorn/crucible compare.
- At serve time, a recorded `fail` refuses to start and a missing verdict only warns (`sdk/cache.py:25-65`).
- `sample` is skipped. `distribution.kl_check` raises `NotImplementedError`.
- 7 ops have sample inputs: gelu, layer_norm, paged_attention, rms_norm, rope, silu, silu_mul. The other 7 (mla, dsa, gdn/kda, conv1d, mxfp4, …) produce no verdict.

**Weaknesses of `compare.py` compared with crucible:**
- one unseeded `randn` sample at tiny fixed shapes;
- no seed rounds and no probes;
- the verdict is copied to every bucket shape;
- an impl that isn't registered falls back to `reference_impl()`, so it grades the reference against itself.

**Model level** (`scripts/check_serve.py:89-135`) checks tokens and text only, never logits:
- gpt2: exact greedy string;
- smolvlm: ids == `hf.generate` fp32;
- gpt_oss_tiny: batched == solo.

**Other live checks:**
- `scripts/check_endpoint.py:219-244`: the TRT-LLM z-test with σ=50. Both rows are `NO_REFERENCE`, so it always passes.
- `sdk/checks/recurrent_batching.py`: batched == single at atol 1e-4.

**No live pytest suite exists.** `scripts/test` runs Zig tests, ruff and import checks.

### kelpie, archived (`archive/kelpie-models-tests/`)

- `check.py:120-205`: `Tol(atol | rel·max|oracle|)` plus argmax equality, against HF eager fp32.
- Model tolerances:
  - gpt2 1e-3, qwen3 2e-2, gpt_oss 5e-2 (`test_golden.py:25`, `oracle/test_corpus.py:15`);
  - chunked vs one-shot atol 1e-3, with KV cells within 1e-4.
- Other tests used an fp64-HF budget.
- `test_jax_corpus.py:128` has a **tie-aware greedy rule**: argmax may differ when the oracle's top-2 gap is below the band.
- `oracle/budget.py` adds a `floor_dtype` option to grade bf16 output against an fp32 reference.

### The 09-21 BLOCK/WARN verifier (not in this checkout)

It exists only in `~/research-2/worktrees/spec-decode/kelpie`, in commit `e7b046e` "Replay lost session c358631c edits (from transcript)".

**Files:**
- `kelpie-models/kelpie_models/kernels/verify.py` (472 LoC);
- `kelpie-engine/kelpie_engine/sdk/verify.py` (108 LoC).

**What it checks:**
- BLOCK = FixedTolerance at native dtype, with defaults:

  | dtype | atol | rtol |
  |---|---|---|
  | fp32 | 2e-5 | 1e-5 |
  | fp16 | 1e-3 | 1e-3 |
  | bf16 | 2e-2 | 2e-2 |

- WARN = fp64 budget.

**How it runs:** 3 rounds from seed 41, plus `PAD_POISON = 8192.0`. Results are cached by fingerprint and device arch.

**TODO list in the file:**
- jaxtyping dims to generate the case grid;
- tolerance functions per op (GEMM √K);
- region-aware dispatch;
- unified JIT + verify cache;
- test cases for every op;
- a sweep over several dtypes.

---

## 3. External prior art

### Kernel level (L1/L2)

**popcorn** (`tilde-research/popcorn` @e497398):
- **Runs:** truth = the reference with inputs cast to fp64; budget = the same reference at native dtype; the candidate is the third run.
- **Pass rule:** `err ≤ max(2·budget_err, FLOOR[dtype]·max|truth|)` (`bench/model.py:66-71`), where FLOORS are fp64 1e-10 / fp32 2e-5 / fp16 1e-3 / bf16 2e-2 (`compare.py:14`). The floor used is the loosest across the inputs.
- **Gradients:** checked with fp64 cotangents.
- **Trials:** 10 seeds.
- **Record key:** `(op, impl, device, case_id, grad, torch_version, backend_version)`, where `case_id = sha1(json(dims, batch, dtype, args, optionals))[:12]`. `ref_hash` and `impl_hash` are stored next to the record and gate whether it is stale.
- **AST fingerprint** (`core/fingerprint.py:163-202`):
  - SHA-256 of the AST dump with docstrings and decorators removed, so comments and formatting don't change it;
  - follows names recursively, but only inside the `popcorn.kernels.` and `popcorn.impls.` scopes;
  - hashes a sibling `.cu` file byte for byte;
  - keeps the first 12 hex characters.

**flash-attention:**
- The truth is fp32 (fp64 in FA4). The "pt" baseline is the same-dtype reference with reordered ops.
- **FA2:** `max|out−ref| ≤ 2·max|pt−ref|` (3× for dq/dk/dv).
- **FA3:** adds a rounding atol: `2·|ref+0.3−0.3−ref|`.
- **FA4:** also requires mean error ≤ 2× the eager error plus rounding.

**Other per-dtype conventions:**

| Source | Reference | fp32 | fp16 | bf16 | fp8 | Notes |
|---|---|---|---|---|---|---|
| KernelBench (`eval.py:83-102`) | same dtype | 1e-4 | 1e-2 | 1e-2 | — | allclose with atol = rtol; 5 trials; v0 used fp32 1e-2 |
| gpu-mode | same dtype | 1e-5 rtol / 1e-8 atol default | — | — | — | per-problem 1e-3…1e-1; linalg uses a `k·n·eps32` residual; secret seed |
| FlashInfer (`trace/template.py:99-118`) | often its own kernel or an fp16 reference | 1e-5 | 1e-3 | 1e-2 | 1e-1 | fp4 1.0; also mismatch-% and cos-sim |
| torch.testing (rtol/atol) | — | 1.3e-6 / 1e-5 | 1e-3 / 1e-5 | 1.6e-2 / 1e-5 | 0/0 (exact) | fp8 silently means exact |
| TransformerEngine (rtol/atol) | varies | — | — | — | e4m3 .125/.0675; e5m2 .25/.125 | — |
| xformers/MSLK (fwd rtol/atol) | fp32 | 2e-5 / 3e-4 | 4e-4 / 4e-3 | 5e-3 / 2e-2 | — | also requires bit-identical reruns |
| Liger | HF module, same dtype | — | — | — | — | loose: bf16 RMSNorm atol 0.2, SwiGLU 1e4 (TODO) |

FlashInfer sampling tests are statistical: 5M draws, cos(freq, p) > 0.99.

**ULP-based checks:** no source uses them. The closest are eps-scaled rules.

### Model level (L3/L4)

**vLLM:**
- `check_outputs_equal`: exact ids and text.
- `check_logprobs_close` (`tests/models/utils.py:90-270`):
  - walks the greedy tokens;
  - at the first divergence, each side's token must be in the other side's top-5;
  - then `break`;
  - **logprob values are never compared**.
- Typical run: 8 prompts × 32 tokens in the checkpoint's dtype, against HF with fp32 log_softmax. CUDA graphs are on and `max_num_seqs=2`.
- lm-eval CI: gsm8k with 250 questions, `measured ≥ gt·(1−0.08)`.
- `tests/evals/gsm8k`: `≥ thr − 0.08` absolute.

**SGLang** (`runners.py:936-982`):
- top-5 logprob values compared by absolute difference:
  - prefill < 5e-2;
  - decode < 6e-2 (7-8e-2 for some models);
- plus ROUGE-L = 1 (identical text);
- in fp16, 32 tokens;
- the logprob asserts are skipped when the input is longer than 100 tokens.
- GSM8K CI threshold = measured − 5 points.

**HF transformers:**
- Pins a logits slice per device at bf16 1e-2.
- Eager vs SDPA: bf16 atol 1e-2 (3e-2·max|logit|). The test passes if ≥80% of batch rows match.

**llama.cpp `--kl-divergence`:**
- Reports full-vocab KL(base‖Q) as mean and percentiles, Δp of the correct token, and a "same top p" %.
- Calibration: Llama-3-8B bf16 vs fp16 gives mean KLD 2.5e-5, max 0.012, same-top 99.74%.

**TRT-LLM** (`accuracy_core.py:86-111`):
- Formulas: `scale = √(2σ²/n)`, `γ = ref + Φ⁻¹(α)·scale`, `θ = −(Φ⁻¹(α)+Φ⁻¹(β))·scale`.

  | Task | α | β | σ | n | θ | γ − ref |
  |---|---|---|---|---|---|---|
  | MMLU | 0.05 | 0.2 | 50 | 4096 | 2.75 | −1.82 |
  | GSM8K | 0.05 | 0.2 | 50 | 1319 | 4.84 | −3.20 |
  | CNN-DM | 0.002 | 0.2 | 11.06 | 512 | 2.57 | −1.99 |

- References are keyed by (model, dtype, quant, kv-quant, spec_dec_algo).

**MLPerf:** the score must reach ≥99% or ≥99.9% of an fp32/fp16 reference score, with a tokens-per-sample band.

**Thinking Machines** (batch invariance), on Qwen3-235B:
- 1000 temperature-0 completions produced 80 unique outputs by default and 1 with batch-invariant kernels.
- **Cost** (Qwen3-8B): 26 s by default vs 42 s batch-invariant (+62%).
- In RL, the KL between sampler and trainer stays exactly 0.
- **vLLM `VLLM_BATCH_INVARIANT=1`:**
  - logprobs at bs=1 vs bs=N must be `torch.equal`;
  - a "needle" test places one prompt in batches of 64-128;
  - "beta", no published cost.

### Spec decode

- **vLLM:** greedy spec vs no-spec is **not exact**:
  - EAGLE needs ≥60% of prompts identical, MTP 80%, draft+LoRA 90%;
  - plus a GSM8K floor and acceptance-length and per-position acceptance thresholds.
- **vLLM rejection sampler:** V=10, k=2, up to 100k samples. The L2 distance to the target PMF must shrink ≥20× more than to random PMFs. This is a heuristic, not a formal test.
- **SGLang `SpecParityKit`:** **exact** greedy equality, but only under `--enable-deterministic-inference` with page size 1 (4 prompts × 48 tokens).
- **kelpie `spec-decode-survey.md:80-86`:** all four engines surveyed make greedy bitwise-equal by construction. vLLM's tests show this does not hold end to end without deterministic mode.

---

## 4. Summary by observer level

| Level | Prior art | Reference | Statistic / tolerance | Test shape | Cost |
|---|---|---|---|---|---|
| L0 formal | nothing concrete. popcorn's AST fingerprint is provenance, not proof. gpu-mode linalg property checks and crucible's static audit are the nearest | — | — | — | — |
| L1 upcast | popcorn, crucible, kelpie `bench/compare.py`, flash-attn | fp64 (fp32 in FA2/3) truth plus the native reference as budget | `max|err| ≤ max(2·budget, floor·max|truth|)`, floors 2e-5/1e-3/2e-2 | randn, 3-10 seeds, shape grid | 3 runs per trial including fp64, ~ms per op; fp64 OOMs on big shapes |
| L2 same dtype | KernelBench, gpu-mode, FlashInfer, torch.testing, TE, xformers, kelpie spec-decode worktree BLOCK | reference at native dtype, sometimes fp32 | allclose: fp32 1e-5…1e-4; fp16 1e-3…1e-2; bf16 1e-2…2e-2; fp8 4e-2…1.25e-1; fp4 up to 1.0; plus mismatch-% or cos-sim | param grids, 1-5 trials | 2 runs, cheap |
| L3 logits | SGLang (values), vLLM (top-k membership), crucible L3/L4, kelpie archive | HF at dtype (fp32 log_softmax), or fp64 HF on tiny configs | SGLang: \|Δ top-5 logprob\| < 5e-2/6e-2. vLLM: token ∈ other's top-5 until the first divergence. crucible: argmax equal plus top-10 atol 1e-3, rollout of 4. HF: 1e-2 slice | 5-8 prompts × 32 tokens | 2 model loads, seconds to minutes |
| L4 statistical | TRT-LLM, vLLM/SGLang gsm8k, MLPerf, llama.cpp KLD | pinned score (from HF or the reference engine) or saved base logits | one-sided z-test γ = ref + Φ⁻¹(α)√(2σ²/n); or ≥ gt·(1−0.08); or ≥99% of ref; or KLD percentiles and same-top % | MMLU 4096, GSM8K 1319/250, wikitext | minutes to hours per model |
| Batch invariance | Thinking Machines, vLLM BI mode, xformers rerun | same engine at BS=1 | bitwise (`torch.equal`), unique-count = 1 | 1000×1000 tokens, or 16 tokens bs1-vs-N | +62% runtime when enforced |
| SD greedy | SGLang (exact, deterministic mode), vLLM (≥60-90% of prompts identical) | same engine without spec | exact, or a fraction exact | 4-8 prompts × 10-48 tokens | 2 engine loads |
| SD T>0 | vLLM rejection-sampler PMF test, FlashInfer sampling | analytic target PMF | L2 convergence ratio > 20×; cos > 0.99 | V=10, 100k-5M draws | no model, seconds |

---

## 5. Open questions to argue about

1. **What is the reference, per level?**
   - Kernel: fp64 of the same torch reference (popcorn), fp32 (FA), or same dtype (KernelBench)?
   - Model: HF at dtype, HF fp32, fp64 HF on tiny random configs, or a frozen corpus?
   - Vendored engine code (vllm/sgl) as the reference, as you asked for on 09-21?
   - Does "reference" at L2 mean the **same-dtype reference kernel**, the torch composite, or a trusted library (FlashInfer)? FlashInfer tests often compare the library against itself.
2. **Should L1 vs L2 be inverted?**
   - Today's code (09-21) makes the fixed same-dtype tolerance BLOCK and the fp64 budget WARN.
   - Popcorn and crucible gate on the budget.
   - Which of the two better catches "different algorithm" vs "worse accumulation"?
   - The budget is measured, so it adapts to shape; a fixed tolerance needs a table.
3. **How to set L2 tolerances:**
   - adopt one table (torch.testing? FlashInfer's `default_tolerances`?) or derive from eps;
   - tolerance functions per op (GEMM √K, attention ~ seq_len);
   - global max-abs vs elementwise isclose vs mismatch-% vs cos-sim.
   - Max-abs scaled by max|truth| hides relative error on small values.
4. **Budgets per op vs end to end.** Does passing every kernel imply the model passes L3 at some tolerance, or is L3 calibrated on its own?
   - Crucible's real-weight atol of 1.25 for qwen3 bf16 suggests an end-to-end tolerance ends up far from anything composed out of per-kernel ones.
5. **L3 statistic:**
   - SGLang-style logprob values (atol about 5e-2);
   - vLLM-style top-k membership that stops at divergence;
   - crucible-style argmax + top-10 values + oracle-driven rollout (teacher forcing avoids divergence entirely);
   - full-vocab KL (llama.cpp);
   - how to handle ties: the tie-aware band from `test_jax_corpus`.
6. **L4 details:**
   - which benchmarks;
   - where the reference score comes from (HF run vs published);
   - α/β/n;
   - is it gating or an alarm ("regression alarm, never the definition", 09-02)?
   - Cost per model is minutes to hours on a GPU.
7. **Where batch invariance fits:**
   - as its own observer (bitwise bs1 vs bsN, which is cheap to state);
   - as a precondition that makes exact spec-decode and SOLO checks valid;
   - or only a diagnostic, as ruled on 09-03.
   - Without it, the exact checks (`check_serve` SOLO, `prove_dflash`) can flake.
8. **Spec decode greedy: exact or tie-aware/fractional?** The 09-08 ruling (tie-aware) and the 09-20 draft (exact) conflict. Prior art splits: SGLang is exact only in deterministic mode; vLLM uses fractions. For T>0:
   - should the rejection sampler be tested in isolation against an analytic PMF (cheap);
   - or end to end on distributions (expensive and flaky)?
9. **Cases and seeds:**
   - kelpie's `compare` uses one unseeded sample at a toy shape and copies the verdict to every bucket.
   - Should verdicts be keyed by shape (popcorn `case_id`)?
   - Should kelpie add paged/stepped/recurrent case types (neither popcorn nor crucible has them)?
   - Add probes and PAD_POISON?
10. **Popcorn:** depend on it, vendor its compare+fingerprint, or hand-roll? And how deep should anti-cheat go (09-02 "not the depth" vs 09-10 "subprocess if agent-developed")?
11. **Observer report shape:** implement the agreed `correct(details)` design (09-04) once, shared across L1-L4 and SD?

---

## Uncertainties

- The crucible ladder is reconstructed from code; there is no written L0-L5 spec.
- The Thinking Machines numbers come from a summarized WebFetch, not the raw post.
- I did not check how vLLM pairs dtypes for fp32 checkpoints.
- FlashInfer's `trace/default_check` may only be used by newer tests.
- The TRT-LLM README calls σ "p(1−p)", but the code treats it as a standard deviation. The numbers agree because σ=0.5.
- The 09-21 verifier exists only in the spec-decode worktree, recreated from a transcript. It is unclear whether it is the intended mainline.

## Papercuts

- **"L0-Lx" is overloaded** across three different ladders. Worth renaming the observers.
- **Kelpie docs are stale:**
  - `decisions.md:124-127` says "popcorn as pip dep";
  - `model-contract.md:182-188` points at the archived `tests/oracle/`.
- **Codex rollouts duplicate parent history.** There are about 100 copies on 09-09 and 4 GB of sessions in total.
- **Design work is filed under the wrong project:** kelpie design sits under the crucible project dir (`243855f7`).
- **Lost-session edits were replayed from transcripts** into worktrees (`e7b046e`, `26e7221`).
- **A gcloud OAuth code was pasted in plain text** in `CP/...-crucible/243855f7` (09-02 07:02). Consider rotating it.

---

## 7. Training codebases + TokenSpeed (2026-09-23)

Shallow blobless clones at HEAD on 2026-09-23 (all deleted afterwards): tokenspeed `bf66451`, Megatron-LM `8dded20`, torchtitan `847f98a`, transformers `f324707`, TransformerEngine `965b5dc`. NeMo was not checked; its HF<->Megatron conversion lives in Megatron-Bridge, which I did not clone.

### TokenSpeed (`lightseekorg/tokenspeed`)

- **Kernel harness** `tokenspeed-kernel/python/tokenspeed_kernel/numerics/`:
  - `verify.py:verify_kernel` looks up a registered kernel, then finds a *reference kernel* in the same registry (`solution="reference"`, a plain torch impl in `numerics/reference/gemm.py`) with a compatible format signature. It runs both on seeded (42) generated inputs over per-family standard shapes.
  - `comparison.py:compare_outputs` upcasts both sides to fp32. An element fails if `|d| > atol AND |d|/(|e|+1e-12) > rtol`, which is `max(atol, rtol·|e|)`, not allclose's sum. NaN/Inf on either side always fail. It passes only with **zero** mismatches. The `ComparisonResult` reports max_abs, max_rel, mean_abs, mismatch count/fraction and the top-10 worst indices with their values. That is close to the "correct: bool + details" shape.
  - Tolerances are registered per *family* (`tolerance.py:set_family_tolerance`) as a function of (dtype, shape, inputs):
    - **gemm** (`gemm.py:62`): base atol = rtol = fp32 1e-5, fp16/bf16 1.5e-2, fp8 5e-3. fp32 scales by √(K/128). bf16/fp16 is independent of K (the output cast dominates). fp8 scales as max(5e-3·K/128, 1.5e-2). ×8 if the accumulator is not fp32.
    - **quantize:** 0.2/0.2 (one e4m3 ulp plus margin).
    - **moe routing** (int32): exact.
  - It runs in CI: `test/ci/ut/ut-tokenspeed-kernel.yaml` runs `test_numerics.py` per commit. The other kernel tests use ad-hoc `assert_close`. The most common values are `0/0` (about 145 sites) and `2e-2/2e-2` (about 100).
- **Model level**, three styles:
  1. **Independent-reference parity** (`test/runtime/test_inkling_reference_parity.py`):
     - Dummy weights with deterministic per-parameter init, so an in-process replica holds identical weights.
     - A hand-written pure-torch forward is the reference (fp32 default dtype, "fp32-accum").
     - The engine runs bf16 greedy with logprobs. One reference forward over prompt + engine trajectory is compared against the chosen-token logprob: `max |ref − engine| < 2e-2`. Token ids must match.
     - The docstring notes that dummy weights make logits near-flat, so the **argmax is noise but the logprob values are sharp**.
     - The layerwise variant (`test_inkling_activation_parity.py`) compares hidden states after every decoder layer, for prefill and each decode step, with `max|Δ| < 5e-3`. It fails at the **first diverging layer/phase** and prints the whole report so far.
     - Both are registered in the CI `runtime-1gpu` suite, Blackwell only.
  2. **Smoke** (`test/runtime/models/test_generation_models.py`): the SGLang-derived `ModelCase` still carries `prefill_tolerance=5e-2` / `decode_tolerance=5e-2`, but **nothing reads them**. The HF-logit comparison is gone, and the test only checks substrings ("Paris", "4", "Jupiter").
  3. **Eval gates** (`test/ci/eval/*.yaml`): an `evalscope` run at T=0 against a pinned `score_threshold` (GSM8K 0.86-0.96, AIME 0.69-0.9). The triggers are per-commit / nightly / slurm. Comments show thresholds set from observed run-to-run spread, e.g. "two seed-42 runs scored 0.933 and 0.900". Spec-decode/DP refactors use bitwise `assert_close(rtol=0, atol=0)` against the legacy path (`test_dp_sampling_logits_verify.py`).

### Megatron-LM / Megatron-Core

- **Golden-value functional tests** (`tests/functional_tests/python_test_utils/common.py:pipeline`, thresholds in `test_pretraining_regular_pipeline.py:CHECK_THRESHOLDS`):
  - Per-iteration TensorBoard scalars (`lm loss`, `num-zeros`, `mtp_* loss`, `logprobs`, `generated_tokens`, `iteration-time`, `mem-*`) are compared with a **pinned JSON golden per (environment × platform)**: `golden_values_{dev,lts}_{dgx_a100,dgx_h100,dgx_gb200}.json`, about 930 files.
  - **Two modes:**
    - `DeterministicTest`: exact at full precision. Used when `NVTE_ALLOW_NONDETERMINISTIC_ALGO=0` and `--deterministic-mode`.
    - `ApproximateTest`: `np.isclose` after rounding to 5 decimals. Loss rtol is 0.05, num-zeros 0.20, and iteration-time/memory 0.05 on the median of a steady window.
  - The approximate mode tolerates `min(max(n//100, 1), 50)` failing steps.
  - **Resume test:** run 2 (restarted from a checkpoint at `train_iters/2`) must match run 1.
  - **Tolerance calibration:** `compute_golden_statistics.py --recommend-tolerances` runs N copies of a job and recommends `max(max_rel_variance × 1.5, 0.001)`.
  - **Scope:** about 57 cases per MR and about 62 nightly, from `tests/test_utils/recipes/h100/gpt.yaml`.
- **Inference goldens** (`test_inference_regular_pipeline.py`):
  - generated tokens: exact;
  - logprobs: `math.isclose(abs_tol=1e-3)` per token;
  - generated text: prefix-equal;
  - MoE routing indices: exact after sorting.
  - Example: the `gpt_static_inference_tp1_pp1_583m_logitsmatch` config (deterministic mode, top_k=1).
- **Error-analysis bound for grads** (`test_optimizer_grads_match.py:assert_grads_close`):
  - Compares optimizer `exp_avg` across checkpoints from different parallel configs.
  - Statistic: `‖ĝ−g‖_F/‖g‖_F ≤ k·C^(L+1−l)·eps_mch`, with k=4, C=1.03, L=32, l=0 → ≈8.3e-2 for bf16. fp8 uses the bf16 eps. It cites arXiv 2506.09280 thm 5.3.
  - On failure it also computes the error against `torch.roll(ref, 1)` as a **null baseline** and runs `assert_close` for diagnostics.
- **Checkpoint converter** (`test_cases/common/ckpt_converter/__main__.py`):
  - Converts a checkpoint, reloads it, and compares output logits by MSE against the source model. It also loads a **fake** (differently initialized) model.
  - Pass rule: `mse_real < 0.05 · mse_fake`, a relative-to-null criterion.
  - The recipe currently marks it `mr-broken` / `nightly-broken`, i.e. disabled.

### torchtitan

- **Loss goldens, bitwise** (`scripts/loss_compare.py:assert_losses_equal`):
  - Always runs with `--debug.deterministic --debug.seed=42` plus a seed checkpoint (the model is created on 1 GPU, then parallelized).
  - Per-step loss is compared with `assertEqual` on floats, i.e. **bitwise**. It compares either commit A against commit B, or a run against a pinned golden `tests/assets/losses/{fake_pg,real_pg}/{gpu_arch}/<model>.txt`.
  - Wired into integration tests via `golden_numerics_path`. The golden is chosen per GPU arch (A10G in CI). Same for RL: `scripts/rl/loss_compare.py --import-result tests/assets/losses/rl_grpo_cuda.txt --assert-equal`, on push and every 12 h.
- **Close but not bitwise:** graph_trainer/AutoParallel vs eager (`experiments/graph_trainer/tests/test_numerics.py`) uses `math.isclose(rtol=1e-4, atol=1e-5)` per step (5e-4 for DSv3 autoparallel), because the collective ordering legitimately differs. `test_bitwise_deterministic.py` requires eager == traced bitwise, on losses and on gradient/model hashes.
- **RL generator vs trainer** (`tests/unit_tests/rl/test_bitwise_parity.py`, `torchtitan/rl/docs/bitwise_parity.md`): `torch.equal` on logprobs between vLLM-generator and trainer forwards. This relies on batch-invariant mode:
  - TM `batch_invariant_ops` for mm/addmm/log_softmax/mean;
  - FA3 `num_splits=1`;
  - single-channel tree NCCL;
  - no TF32 and no reduced-precision reductions.
- **HF conversion** (`scripts/checkpoint_conversion/numerical_tests_*.py`):
  - A manual script, not CI. It runs 100 random 8-token prompts, takes last-token logits, and computes KL between HF and titan.
  - The Llama example has **no threshold** and uses `F.kl_div(reduction="mean")`, which divides by V, a pitfall. It also includes a *negative control* checkpoint converted without the RoPE permute.
  - The Kimi version uses KL(sum) < 1e-3 as the pass rule, and prints top1-agree, cos and max_diff as diagnostics.
- **float8 / MXFP8** (`tests/unit_tests/gpu/test_float8_linear.py:107`, `test_mxfp8_linear.py:395`): the second implementation is torchao's `Float8Linear`/MX path, compared **exactly** (`rtol=0, atol=0`) on output, input grad and weight grad. There is no fp32 comparison at the unit level.
- **Agent skills in-repo:**
  - `.claude/skills/kernel-numerics-verifier`:
    - Uses the popcorn/FA scheme: fp64 golden, same-dtype eager reference, target. Pass rule: `err_t ≤ 2·err_ref + max(atol, rounding_floor)`.
    - Adds a **conditioning pre-check**: if `err_ref/max|golden| > 10%`, the result is `INCONCLUSIVE`, not pass/fail.
    - Checks √T vs T error growth to tell noise from bias, and reports the outcome as `PASS WITH LIMITATIONS`.
  - `.claude/skills/numerics_debugging`: per-op activation capture via `DebugMode`. It diffs by (shape, fp64 L1-norm hash) and flags a relative hash difference > 1e-8.

### TransformerEngine / HF transformers (brief)

- **TE** `tests/pytorch/test_numerics.py`:
  - Compares TE modules against hand-written `Torch*` modules (`TorchLayerNormMLP`, `TorchMHA`, …) at the **same dtype**, with copied weights.
  - Base tolerances come from `utils.py:dtype_tols` (torch.testing defaults; fp4 0.25/0.125).
  - The GPT e2e output uses atol fp32 5e-3 / fp16 5e-2 / bf16 1e-1; grads use rtol 1e-2.
  - fp8 uses 0.125/0.0675. The `test_float8_*_exact.py` files require **exact** agreement with Python reference quantizers/GEMMs in `tests/pytorch/references/`.
- **HF** `tests/models/llama/test_modeling_llama.py:test_model_7b_logits_bf16` (`@slow`, nightly only):
  - A pinned 8-token prompt. Checks the per-position logit mean and `logits[0,0,:15]` with `allclose(atol=1e-2, rtol=1e-2)`.
  - The goldens are **per-device** `Expectations` keyed by (`cuda`,7) / (`cuda`,8) / (`rocm`,(9,4)) / (`xpu`,3). The values differ by up to about 0.1 between keys, which is bigger than the tolerance.
  - Generation tests check exact expected text.

### Summary table

| Source | Level | Reference | Statistic / tolerance | Golden vs 2nd impl vs upcast | CI? |
|---|---|---|---|---|---|
| TokenSpeed `numerics/verify_kernel` | L2 | registered torch "reference" kernel, same storage dtype | 0 elements with `\|d\|>atol ∧ rel>rtol`; gemm bf16 1.5e-2, fp8 5e-3·K/128 (≥1.5e-2), fp32 1e-5·√(K/128); NaN always fails | 2nd impl | per-commit |
| TokenSpeed inkling parity | L3 | independent pure-torch fp32 forward, same dummy weights | chosen-token logprob max\|Δ\| < 2e-2; layerwise hidden max\|Δ\| < 5e-3, stop at first layer | 2nd impl (upcast) | per-commit, Blackwell |
| TokenSpeed eval yamls | L4 | pinned score | GSM8K ≥ 0.86-0.96, AIME ≥ 0.69-0.9 at T=0 | golden | per-commit / nightly |
| Megatron functional | training L3/L4 | pinned JSON per env × GPU | deterministic: exact; else isclose rtol 5e-2 (num-zeros 0.2) on 5-dp rounding, ≤1% of steps may fail | golden | MR + nightly |
| Megatron inference goldens | L3 | pinned JSON | tokens exact, logprob abs 1e-3, routing exact | golden | MR |
| Megatron grads match | training | other parallel config | ‖Δ‖_F/‖g‖_F ≤ 4·1.03^33·eps_bf16 ≈ 8.3e-2; roll(ref) null baseline in diagnostics | 2nd config | MR |
| Megatron ckpt converter | conversion | source model (real) vs random model (fake) | MSE_real < 0.05·MSE_fake | 2nd impl + null | disabled ("broken") |
| torchtitan loss_compare | training | pinned losses per GPU arch, or another commit | bitwise per-step loss, deterministic + seed ckpt | golden | integration CI |
| torchtitan graph_trainer | training | eager FSDP2 | isclose rtol 1e-4 (5e-4), atol 1e-5; bitwise for eager-vs-traced | 2nd impl | CI (experiments) |
| torchtitan RL parity | L3 | trainer forward vs vLLM generator | `torch.equal` logprobs (batch-invariant mode) | 2nd impl | push + 12 h |
| torchtitan HF conversion | L3 | HF model | KL(sum) < 1e-3 (Kimi); Llama example prints mean-KL with no threshold, has no-permute negative control | 2nd impl | manual |
| torchtitan fp8/MX | L2 | torchao | exact | 2nd impl | PR |
| torchtitan kernel skill | L1 | fp64 golden + native reference | 2×ref_err + rounding floor; INCONCLUSIVE if ref rel-err > 10% | upcast | agent-run |
| TE test_numerics | L2/L3 | pure-torch modules, same dtype | torch.testing tols; GPT e2e atol bf16 1e-1; fp8 .125/.0675; *_exact: 0 | 2nd impl | CI |
| HF test_modeling | L3 | pinned logits slice per device | allclose 1e-2/1e-2 on mean + first 15 logits | golden | nightly `@slow` |

### Implications for kelpie's model-level observer

1. **Two references, not one: an independent reference plus a null reference.**
   - TokenSpeed's inkling test gets a sharp L3 check without HF: identical deterministic dummy weights, plus a separate pure-torch forward in fp32.
   - Megatron's converter and torchtitan's no-permute control add a *null* comparison (random-init model, or `roll(ref)`), so "close" is measured relative to "obviously wrong".
   - For kelpie the observer could report `err_vs_ref`, `err_vs_null` and their ratio as details. The ratio is scale-free and hard to game with a loose atol.
2. **Compare logprob values along the engine's own trajectory, not argmax.** Several sources converge on the same scheme: TokenSpeed (Δlogprob < 2e-2), Megatron (1e-3 abs in deterministic mode), torchtitan RL (bitwise).
   - Decode greedily in the engine.
   - Run **one** teacher-forced reference forward over prompt + trajectory.
   - Compare the chosen-token logprob at each position.
   - This avoids the "first divergence ends the test" problem that vLLM/crucible have, and works even on dummy weights, where argmax is noise.
3. **Localize: run layerwise on fail, not always.** TokenSpeed's activation-parity variant and torchtitan's `numerics_debugging` both exist to answer "where did it diverge". The model observer's details could name the first layer/phase that exceeds tolerance. This is cheap if the reference already exposes per-layer hidden states. A natural split is a blocking end-to-end check plus a warn-only, on-failure layerwise drill-down.
4. **Split goldens by hardware and determinism mode, and make "exact" its own mode.**
   - Every golden-file system keys goldens by platform: Megatron by env × GPU, torchtitan by gpu_arch, HF by (device, capability). HF's cuda7 vs cuda8 values differ by more than its own atol.
   - Megatron and torchtitan both keep a **deterministic ⇒ exact** mode separate from a tolerance mode.
   - Kelpie could store `(model, gpu_arch, deterministic)` → golden and pick `exact` vs `tol` from the config. That fits the block/warn split: exact under deterministic mode is a good block, tolerance mode a warn.
5. **Record where the tolerances came from.** Megatron calibrates tolerances from N reruns (×1.5 margin), TokenSpeed eval thresholds cite observed run spreads, and the torchtitan kernel skill forbids widening a tolerance after a failure and returns `INCONCLUSIVE` when the reference itself is ill-conditioned. A kelpie observer could store `tolerance_source` (calibrated / derived / guessed) in details and allow a third verdict besides pass/fail.

Uncertainties for this section:
- I did not check which torchtitan workflow runs the per-arch golden integration tests on PRs versus only on main.
- The Megatron MR/nightly counts come from the h100 `gpt.yaml` recipe only.
- TokenSpeed's `RTRunner` may still compute logits that nothing compares; I did not read `test/runners.py`.
