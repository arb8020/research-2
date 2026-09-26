# About correctness in kelpie

This page explains how kelpie decides that a kernel, a model forward, or an engine feature is correct, and why the design looks the way it does. For the file formats, schemas, and checker parameters, see [Correctness eval format](reference.md). For the prior art behind each choice, see [the 2026-09-23 correctness research](../research-correctness-2026-09-23.md).

## Correct means "passes the checks you chose"

Kelpie has no single definition of "correct". A bf16 attention kernel, a gpt-oss forward, and a DFlash speculative decoder each fail in different ways, and a number that is right for one is wrong for the others. So kelpie does not try to own the definition. You own it. You write a Grader: an ordered list of Checks, each with its own statistic and tolerance. Some Checks block and some only warn. A deployment is correct when every blocking Check in its Graders passes. A blocking Check can also return `inconclusive`, which means it could not judge. That is not a pass, but `kelpie serve` only warns on it, because refusing a deployment needs evidence that something is wrong.

This follows from how we want to work. A kernel or a model forward is a verifiable task. You can hand "write a faster `rms_norm`" or "port gpt-oss to kelpie" to an agent or to another person, because the Grader states in advance what done means. The person who does the work and the Grader that judges it never need to share a process, a machine, or a session. They share only the recorded outputs.

The blocking and warning split matters as much as the Checks themselves. A blocking Check is a claim you are willing to refuse a deployment over. A warning Check is a measurement you want to see on every build but would not stop a serve for.

## Record once, grade anywhere

Kelpie splits correctness into two steps. `kelpie record` runs a subject and writes its outputs to disk as a Run. `kelpie grade` reads files from disk and writes Grades. The two steps share nothing except the files.

Three things make the split worth its cost:

- **Recording is expensive and grading is cheap.** A model Run needs a GPU, often a rented one on Modal, and minutes of load time. A Check over the recorded logits takes seconds on a laptop with no GPU.
- **Runs are immutable.** A Run records its config hash, library versions, device, GPU architecture, seed, and deterministic flag. When a Grade changes, you know the Grader changed, because the Run cannot have.
- **Graders change more often than subjects.** You will tighten a tolerance, add a KL Check, or move a Check from warn to block many times. Each change re-grades the Runs already on disk. Nothing is re-recorded.

The vocabulary and the directory layout come from smevals, and the split between measuring and judging comes from loom. We rejected one loom pattern: grading inline in the live sandbox where the work ran. That pattern forces a Check to run where the GPU is, and it makes "change the Grader" mean "run the model again".

## A Check is a function over files

A Check in smevals usually inspects one Run: does the output contain this text, does the file parse. Most kelpie Checks need more than one set of outputs:

- a candidate kernel and a reference kernel
- the same engine at batch size 1 and at batch size N
- the same model at tensor parallel world size 1 and world size 2
- speculative decode and plain decode, both teacher-forced over the same tokens
- for the error budget, three sets: the candidate, the reference at native dtype, and the fp64 truth.

Other Checks need only the candidate, such as a scan for NaN or a floor on DFlash acceptance length. A benchmark score tested against a published score needs the candidate and one Pinned input.

So kelpie does not build "compare two Runs" into the API. A Checker is a pure function over named persisted inputs, `(inputs, params) -> Verdict`. Each Check in a Grader binds input names to selectors. `cand` is always the Run being graded. Other names, such as `ref`, `truth`, `null`, or `pinned`, are bound to selectors that pick other persisted outputs. Comparing two Runs is one way to use this, not a special case.

Everything a Check reads is persisted data with provenance. Running the op's `reference` function in fp64 or at native dtype, HF in fp32, or a null model is a Run like any other: `kelpie record` writes its outputs and its `run.yaml`. A golden, a set of calibration statistics, and a published benchmark score are persisted the same way. The Checker never computes a reference itself and never holds one as a hidden constant. That makes a Check a script over files. You can run it on any machine that has the files, and you can write one in any language.

Every input carries its `run.yaml`, with a `case_id` that hashes the case's inputs, a config hash, and versions. Before `kelpie grade` calls a Checker, it asserts three things. Every input exists on disk. Every input's `case_id` matches the candidate's. No two inputs are the same directory.

Each assertion stops a real failure. crucible's merged `fwd-*` tasks built `truth=None`, and `upcast_fp64` left an integer `input_ids` model in bf16, so the "truth" was the bf16 model itself. Every task passed, and the `task.toml` tolerances were never read. In kelpie the truth is a named input that must exist as its own Run, and its `run.yaml` shows which Config produced it. Kelpie's own `kelpie-models/kelpie_models/bench/compare.py` has a related bug today: an impl that is not registered falls back to `reference_impl()` and grades the reference against itself. Two inputs that resolve to the same directory are an error for that reason. The `case_id` match catches the quieter mistake: a golden recorded over a different corpus, or a truth recorded at different shapes. None of these cases is ever a silent pass, and no input ever falls back to another.

The inputs also get the same provenance as the candidate. If the reference was recorded on a different GPU or with different library versions, the Grade shows it.

## Pick the reference for the level

The right reference depends on what you check.

**Kernels** compare against the op's own `reference` function, run on inputs upcast to fp64. The fp64 run is as close to the mathematical answer as a torch composite gets, and it costs milliseconds at kernel shapes. Popcorn and crucible use the same scheme, and it is the only reference that lets you say how far the native-dtype reference itself is from the truth.

**Models** cannot use fp64. A 20B model in fp64 needs about 168 GB for weights alone, and the 2026-09-02 session settled on fp64 HF only for small synthetic configs. For real checkpoints the reference is HF transformers in fp32, or a golden: an HF fp32 Run recorded once and named in `eval.yaml`.

A golden is keyed by model, GPU architecture, and deterministic mode. The key is not paperwork. HF's own llama logits goldens differ by up to about 0.1 between CUDA capability 7 and 8, which is larger than HF's own tolerance. Megatron and torchtitan key their goldens by platform for the same reason. Megatron also keeps a deterministic mode, where exact equality is the test, apart from a tolerance mode.

Once Runs live on disk, goldens become the default reference for models. An HF fp32 forward of gpt-oss-20b needs about 84 GB of weights. You record it once on a large GPU and grade every later candidate against it on any machine. A golden also catches a second kind of bug: a kelpie change that moves the logits of a model that was already correct.

## Fixed tolerance and error budget catch different bugs

Kelpie has two ways to turn a distance into a pass or a fail.

A **fixed tolerance** compares the candidate with a same-dtype reference, element by element, with `atol` and `rtol` set per dtype. It is simple, it needs one input besides the candidate, and anyone can read the number.

An **error budget** measures the tolerance instead of choosing it. Popcorn and crucible run the op three times: the fp64 truth, the reference at native dtype, and the candidate. The candidate passes when `err(cand) <= max(2 * err(ref), floor * max|truth|)`, with floors of 2e-5 for fp32, 1e-3 for fp16, and 2e-2 for bf16. The rule says: a correct kernel may be twice as wrong as the reference already is in this precision.

Each rule misses a bug the other catches:

- The fixed tolerance misses a kernel that accumulates in bf16 instead of fp32. A bf16 `atol` of 2e-2 is loose enough that the worse accumulation stays inside the band. The budget catches it, because the reference accumulates in fp32 and sets a tighter bar.
- The budget false-fails when the reference lands almost exactly on the truth for one seed. Then `2 * err(ref)` is close to zero, and only the floor keeps an honest kernel from failing.

The 2026-09-21 decision was to make the fixed tolerance blocking and the budget a warning. We agree with it. A blocking Check has to be stable across seeds, and a measured bar that sometimes collapses is not. The budget still runs on every build, and a warning from it is exactly the signal for a bf16-accumulate bug. The choice is per op: set the budget to block for an op whose reference is well conditioned. The same session also showed that a fixed tolerance must depend on dtype, after `rope` in bf16 failed a shared band at 0.0078.

The budget has a third outcome. When the native reference is itself far from the truth, both pass and fail say more than you know. The torchtitan `kernel-numerics-verifier` skill returns `INCONCLUSIVE` when `err(ref) / max|truth|` exceeds 10%. Kelpie adopts that as a third verdict, `inconclusive`, for every Check whose reference can be too inaccurate to judge against.

## Teacher forcing checks every position

The common model-level test decodes greedily in two engines and compares the outputs. vLLM's `check_logprobs_close` walks both greedy sequences. At the first position where the tokens differ, it requires each token to be in the other side's top 5, and then it stops. Everything after the first divergence is unchecked, and the first divergence is often a harmless tie. A model can be badly wrong at position 40 and pass, because the two sequences split at position 12.

Kelpie teacher-forces instead. The Task supplies a fixed token corpus. Every Config runs one forward over the same tokens, and the Runs record logits at every position. Because every Run sees the same prefix, every position can be compared, and no divergence ever ends the test. TokenSpeed's `test_inkling_reference_parity.py` and crucible's oracle-driven rollout do the same thing for the same reason.

Teacher forcing also works on dummy weights. TokenSpeed notes that random weights make the logits almost flat, so the argmax is noise but the logprob values are still sharp. A Check on logprob values at forced positions keeps its meaning even when greedy tokens do not.

Speculative decode uses the same idea. Record the spec-decode engine and the `K=0` engine over the same forced corpus, and compare the target logits at every position. That tests the verify rows directly, instead of hoping that two free-running greedy decodes stay in step.

## Ties make exact greedy a bad default gate

In bf16, two logits often round to the same value or to values one step apart. When the top two candidates tie, the argmax depends on reduction order, batch composition, and kernel choice, none of which change the model's meaning.

This is not hypothetical. In kelpie's DFlash work, a `K=0` baseline, with no drafter at all, picked different tokens across two identical Runs. An exact greedy Check would have failed a correct engine against itself. So exact greedy equality cannot be a default gate. The 2026-09-20 `prove_dflash` draft used exact token match, which contradicts the tie-aware ruling of 2026-09-08. Kelpie follows the 2026-09-08 ruling.

The default token Check is tie-aware. At every forced position, the candidate's argmax must be within a few bf16 steps of the reference's top logit. A near-tie can flip without a fail, and a real disagreement still fails.

Batch invariance is a separate question with a separate Check. It asks whether one engine gives bit-identical outputs at batch size 1 and batch size N. `docs/decisions.md` says batch invariance is tested for, not assumed, and it is a diagnostic, not a gate. Keep that Check apart from the reference comparison. When it passes, exact Checks elsewhere become safe to block on. When it fails, the tie-aware Check still gives a stable verdict.

## Four additions from training codebases and TokenSpeed

Inference engines test less carefully than training codebases do, because a training run notices drift over thousands of steps. Four ideas from Megatron, torchtitan, and TokenSpeed shape kelpie's Checks.

**Error relative to a null model.** Megatron's checkpoint converter compares output logits by MSE against the source model, and also against a model with different random weights. It passes when `mse_real < 0.05 * mse_fake`. The ratio has no units and no dtype table, and a loose `atol` cannot hide a wrong model behind it. Kelpie reports this ratio as a warning Check on model forwards. The null model is a Run like any other, recorded from random weights.

**Per-layer drill-down on failure.** TokenSpeed's `test_inkling_activation_parity.py` compares hidden states after every decoder layer and reports the first layer that diverges. A failed end-to-end Check tells you that the model is wrong. The drill-down tells you where. Kelpie runs it only after a blocking Check fails, reads the `resid_post` taps that the Runs recorded, and never lets it block.

**A third verdict.** The torchtitan kernel skill's `INCONCLUSIVE` result, described earlier, becomes kelpie's `inconclusive`. It keeps an ill-conditioned reference from producing a confident answer in either direction.

**Where each tolerance came from.** Megatron recommends tolerances from N reruns with a 1.5x margin. TokenSpeed's eval thresholds cite the run-to-run spread they observed. The torchtitan skill forbids widening a tolerance after a failure. Kelpie records a `tolerance_source` on every Check. The next section explains the four values.

## A tolerance should say where it came from

Every tolerance is a number someone picked. The `tolerance_source` on a Check says how:

- **`calibrated`**: measured from kelpie's own Runs, with a margin.
- **`derived`**: follows from the math. The error budget, bitwise equality, and the `z_test` bound are derived.
- **`vendored`**: copied from another project's test suite, with a pin to the exact commit, file, and symbol.
- **`guessed`**: none of the above.

Most tolerances today are guessed, and the Grade says so. A guessed number is the one to distrust first when a Check fails.

Vendored beats guessed for two reasons. First, someone else calibrated it. SGLang runs its prefill bar of 5e-2 against HF for every model in its generation test list. That is more evidence than one of us picking a round number. Second, the pin gives the number an upgrade path. When SGLang changes the bar, a diff of the pinned file at a newer commit shows it, and the Check's pin says which file to diff. A guessed number has no upstream to check against, so it only changes after it causes a false pass or a false fail. The pin also shows when a vendored bar was set for a different setting, such as a different dtype or model size, so you can see that it does not transfer.

## A calibrated tolerance must trace back to an independent reference

Calibration sounds like the rigorous choice. It has a trap. Suppose you set the spec-decode tolerance from the variation between kelpie's own `K=0` Runs at batch size 1 and batch size 8. If `K=0` batching has a bug, the bug shows up as variation. The band widens to fit it, and the Check that should catch the bug passes. A band calibrated only from our own engine absorbs the bugs of that engine.

This is not hypothetical either. On the `core/option2` branch (`NOTES-core-option2.md`), the teacher-forced spec gate used a guessed bar of 8 bf16 steps. It failed one of four identical batched runs, at 11 steps on the "Translate to Spanish" row. A control run with no drafter, `K=0` batched, moved a neighbouring position by 5 steps. Was 11 steps a spec bug or batching noise at a known three-way tie? The guessed bar could not say. A band calibrated from `K=0` batching could, but only if the `K=0` batching itself is known to be right.

So kelpie puts four rules on a `calibrated` tolerance:

1. **Calibrate only from trusted Runs.** Every Run the calibration reads must already pass a blocking Check against an independent reference. An independent reference is one that kelpie's engine did not produce: an HF fp32 golden, an fp64 truth, or a vendored or derived bound.
2. **Give the calibration a ceiling.** The calibrated value must stay under a vendored or derived bound. Without a ceiling, a calibration can never fail. It only grows.
3. **Record the lineage.** Every calibrated tolerance lists the source Runs, the Grader each one passed, and the reference that Grader used. The Grade copies that list, so you can read the chain from any Grade.
4. **Invalidate downstream.** If an upstream Check stops passing, every calibration that depends on it is invalid, and so is every Check that uses it.

For spec decode the chain has three links:

1. `K=0` at batch size 1 against HF fp32, teacher-forced. The tolerance is vendored or derived. This link is the independent anchor.
2. `K=0` at batch size 8 against `K=0` at batch size 1. The distance between them is the batching noise, and it becomes a calibrated tolerance. Its ceiling comes from link 1: if both Runs are within a bar of HF, they are within twice that bar of each other.
3. Spec decode against `K=0`, teacher-forced, within twice the calibrated noise.

Each link is checked against something the previous link has already made trustworthy. A bug in `K=0` batching now breaks link 1 or the ceiling in link 2, instead of widening the band in link 3.

The cost is more Runs and a stricter order. You cannot calibrate link 2 until link 1 passes, and a regression in link 1 turns link 3 inconclusive until you re-calibrate. We think that is the right cost. A tolerance that cannot fail is not a Check.

## What kelpie took from each source

Each source below contributed one idea. Some also contributed a warning.

- **vLLM.** The shape of a model test: a few prompts, a few dozen tokens, compared against HF with an fp32 `log_softmax`. Its stop-at-first-divergence walk is the reason kelpie teacher-forces. Its batch-invariant mode defines the bitwise batch Check.
- **SGLang.** Compare logprob values, not only top-k membership. Its bars of 5e-2 at prefill and 6e-2 at decode are the starting point for kelpie's `topk_logprob` Checker. Its spec-decode parity kit is exact only under deterministic inference, which supports keeping exact Checks behind batch invariance.
- **TensorRT-LLM.** A one-sided hypothesis test for benchmark scores, instead of a fixed percentage drop. The candidate passes when its score is at least `ref + Φ⁻¹(α) * sqrt(2σ²/n)`. Kelpie's `z_test` Checker is that rule, for accuracy on benchmarks such as GSM8K and MMLU.
- **popcorn.** The three-Run error budget, the per-dtype floors, and a record key built from op, impl, device, `case_id`, and versions. Kelpie keys cached Runs and Grades the same way.
- **crucible.** The ladder of Checks from smoke test to real-weight greedy, and the per-model tolerances on its `codex/model-ladder-verifier` branch. Also the `truth=None` bug, which is why an unresolved reference is an error.
- **TokenSpeed.** Teacher-forced logprob parity against an independent fp32 forward, the layerwise drill-down, and a fixed-tolerance report that lists the worst elements, not only a boolean.
- **Megatron.** The null-model ratio, goldens keyed by platform, and the split between a deterministic exact mode and a tolerance mode.
- **torchtitan.** Bitwise loss goldens per GPU architecture, the `inconclusive` verdict, and a caution: its Llama conversion test uses `F.kl_div(reduction="mean")`, which divides by the vocabulary size and hides real divergence. Kelpie's `kl` Checker sums over the vocabulary.
- **smevals.** The vocabulary: Eval, Task, Config, Run, Runner, Grader, Grade, Check, and Checker. Also the on-disk layout, and a Checker that is either built in or any executable that prints JSON.
- **loom.** The split between measuring and judging. An loom Scorer emits metrics and a Rubric turns them into a Grade, so a Rubric change never re-runs a Scorer. Kelpie's Checks and Graders follow that split. Kelpie also adopts loom's `script_scorer` contract, which is itself the smevals Checker contract: context in environment variables, JSON on stdout.

## What this design does not settle

Some questions remain open, and the design leaves room for them:

- which benchmarks, if any, run at the statistical level, and whether a `z_test` Check ever blocks
- whether kelpie depends on popcorn or keeps its own copy of the budget code
- how tolerances for a whole model relate to the tolerances of its kernels. crucible's calibrated `atol` of 1.25 for qwen3 in bf16 suggests that the two are far apart.
