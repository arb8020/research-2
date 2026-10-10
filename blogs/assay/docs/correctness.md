# How assay decides an implementation is correct

A reader writes `layer_norm` in `gpt2.py` and presses Run. `run_checks ch01 --op layer_norm` answers pass or fail. This page explains what that answer means and why the checks are built the way they are. It does not list thresholds. For exact values, read `checks/chNN.toml` (`run_checks rules chNN` prints it as tables) and the docstrings of the check functions.

## Correct cannot mean equal

Floating-point arithmetic rounds after every operation, and addition is not associative. Two correct implementations of a dot product that sum in different orders get different answers. A tiled matmul, a fused kernel, and the reference in plain torch all differ in the last bits, and none of them is wrong.

So a check has two jobs that pull against each other. It must accept every reasonable evaluation order, including ones the reference does not use. It must also reject real bugs, including small ones such as an exact-erf GELU where GPT-2 uses the tanh approximation. A tolerance that is too tight fails correct code. One that is too loose passes bugs. Everything below is about choosing a tolerance that has a reason behind it.

## Truth is the reference in fp64, on the candidate's device

Each check compares the candidate to truth: the reference op (the body of the `@op` function in `assay/ch01/ops.py`) run in fp64 on the same inputs. fp64 has about 2^-53 relative rounding error, nine orders of magnitude below fp32's 2^-24. Against an fp32 or bf16 candidate, the fp64 result is exact for practical purposes. The check then measures the candidate's error, not the difference between two rounded answers.

Truth runs on the candidate's device. A GPU and a CPU can disagree in fp64 too, because their libraries pick different algorithms. Computing truth on the same device keeps that disagreement out of the measurement. fp64 is slow on consumer and inference GPUs (on a T4, fp64 matmul is 43x slower than fp32, per `blogs/engine/capabilities.json`). So the trusted parent computes truth once per case and caches it in the store, keyed by a fingerprint of the reference code, the case, and the environment. Editing `ops.py` changes the key and recomputes truth. Editing a grader does not.

## The 2x rule and where it breaks

The first version of the checks used the rule from FlashAttention's tests, also used by popcorn:

```
max|C - T| <= 2 * max|R - T| + floor[dtype]
```

Here C is the candidate, T is fp64 truth, and R is the reference run in the candidate's dtype. In words: a correct candidate may be twice as far from truth as the reference is. PyTorch Dynamo's accuracy checker uses a variant that compares root-mean-square errors instead of maxima.

The rule is simple and needs no analysis of the op. It has three weaknesses.

1. It is only as strict as one reference. If the reference happens to be accurate on a case, the budget shrinks and a correct candidate with a different order fails. If the reference is sloppy, the budget grows and bugs pass.
2. It compares two worst cases. Each side is a maximum over thousands or millions of elements, and the maximum of many noisy values is itself a noisy number. Two runs that differ only in summation order can land on either side of a fixed ratio.
3. At model level it rejected a correct GPT-2 forward. The worst logit error was 1.02x the budget on Linux and 0.98x on macOS. That forward's error against truth was 2.6x HF's own error, only because it evaluates in a different order. Its per-position KL against truth was 5e-9, which says the two output distributions agree to within rounding.

The third point settled it. A rule that flips on the platform for code that is plainly correct cannot be the gate. The 2x number is still recorded as a metric (`err` and `budget` in a verdict's metrics) for one chapter, so the old and new rules can be compared.

## Most of the field picks tolerances by hand

The table below is a partial survey of how other kernel test suites and benchmarks decide correctness.

| Project | Rule |
|---|---|
| SOL-ExecBench | Calibrated `atol` and `rtol` per problem, and at least 99% of elements within them |
| pygpubench, GPU MODE | `allclose` with per-problem tolerances. GPU MODE's linear algebra problems instead use a LAPACK-style residual: ‖R − QᵀA‖ ≤ 20·n·ε·‖A‖ |
| KernelBench | `allclose` with tolerances of 1e-4 and 1e-2. Known false passes: an all-zeros output passes 4 of 60 problems (issue #165). "Measuring the Checker" (arXiv 2609.22220) finds the tolerances 1 to 3 orders of magnitude too loose |
| FlashAttention, Dynamo, popcorn | The 2x-reference rule above, or an RMSE variant of it |
| CUTLASS | Small-integer inputs that make the product exact, then a bitwise compare |
| BLAS `dblat3` (`DMMCH`) | Per element, max\|C − T\| / (ε · Σ\|a\|\|b\|) < 16 |
| LAPACK test suite | Normalized residuals < 30 |

Two groups stand out. Most projects pick `atol` and `rtol` by hand and tune them until known-good code passes. That is how KernelBench ends up passing all zeros. Numerical linear algebra does something different. It derives the shape of the bound from error analysis, so the bound scales with the inputs and the problem size, and then picks a small constant for the slack. CUTLASS avoids the question by choosing inputs where every order gives the same answer, which works for a GEMM but not for `gelu` or `softmax`.

assay follows the numerical linear algebra approach. The shape of each bound comes from what the op does. The constants are measured.

## Each kind of op gets the bound its math supports

Every op declares a kind (`@op(..., kind=...)`), and `checks/chNN.toml` has a grader per kind: contraction, elementwise, composite, and model. The kinds exist because one formula does not fit all ops. A matmul's error grows with its inner dimension. A GELU's error depends on how sensitive the function is at each input. A layer norm mixes both. The error of a whole model is best judged on its output distribution.

Every grader starts with the same fixed safety checks, defined in core and not configurable: `returned`, `dtype_shape`, `inputs_unchanged`, and `deterministic`. The numeric check comes after.

### Contractions: a per-element ratio from forward error analysis

For C = A·B with inner dimension k, forward error analysis bounds each element:

```
|C - T| <= k * u * (|A| @ |B|)        (to first order)
```

u is the unit roundoff of the dtype and `|A| @ |B|` is the matrix product of absolute values. assay turns the bound into a ratio per element:

```
r = |C - T| / (u * (|A| @ |B|) + u * |T|)
```

The `u·|T|` term covers the final rounding into the output dtype. The ratio is nearly the quantity `dblat3` tests. It is scale-free, so one limit works for small and large inputs and for any k.

The worst case grows like k. In practice, rounding errors partly cancel, and Higham and Mary (2019) show that with high probability the error grows like √k. A √k limit would be much tighter than k. But tensor cores do not round like the model assumes. Fasi, Higham, Mikaitis, and Pranesh (2021) found that NVIDIA tensor cores truncate during accumulation, so their errors do not cancel and a correct kernel can exceed √k. So assay fails a contraction only above k, which the worst-case bound says no correct order exceeds. It warns above c·√k, with c = [[PROTO: c for the contraction warning]]. A warning tells the reader that the kernel is correct but less accurate than a typical order.

### Elementwise ops: the condition number sets the scale

For y = f(x) applied per element, the input itself carries a rounding error of about u·|x|. The function scales that error by f′(x), so it reaches the output as u·|x·f′(x)|. Rounding the result adds u·|T|. The bound per element is a multiple of their sum:

```
|C - T| <= m * (u * |x * f'(x)| + u * |T|) + floor
```

m = [[PROTO: m for elementwise ops]]. Near a zero of f, both terms vanish and any absolute error looks infinite in relative terms. The floor, [[PROTO: elementwise floor]], handles those points. The first term is the textbook condition number written in absolute form. It is large where the function is steep and small where it is flat, so the bound is tight where a wrong formula shows and loose where rounding is all there is.

### Composite ops: measure the spread of correct answers, then test against it

A layer norm or an attention is a chain of reductions, divisions, square roots, and exponentials. Deriving a tight bound for each is possible but slow and easy to get wrong. assay measures the spread instead, with Monte Carlo arithmetic (MCA). It runs the fp64 reference K = [[PROTO: MCA run count K]] times. In each run, after every primitive op, it adds random noise the size of one rounding in the candidate's dtype. The runs differ the way different correct implementations differ. Their per-element standard deviation σ is the noise scale of a correct answer.

The decision is a one-sided hypothesis test, in the style of TensorRT-LLM's accuracy tests (`tests/integration/defs/accuracy/README.md`). Those tests fix three numbers:

- α, the false-fail rate: how often a correct implementation may fail.
- β, the miss rate: how often a bug of size θ may pass.
- θ, the minimum detectable effect: the smallest bug the test promises to catch at rate 1 − β.

With n samples per side and noise σ, the TensorRT-LLM README gives the threshold and the detectable effect:

```
γ = x̄ + Φ⁻¹(α) · √(2σ²/n)
θ = −(Φ⁻¹(α) + Φ⁻¹(β)) · √(2σ²/n)
```

Φ⁻¹ is the inverse of the standard normal distribution function. The point is that α, β, and θ cannot all be chosen freely. Pick α and the noise, and θ follows. If θ is larger than the bugs you care about, you need more samples or less noise. assay uses α = [[PROTO: α for composite ops]] and β = [[PROTO: β for composite ops]], which gives θ = [[PROTO: θ per composite op]].

One wrinkle changes the arithmetic. A check does not test one number. It tests every element of the output, and fails if any one is out of bounds. With a million elements and a per-element false-fail rate of 1%, a correct candidate fails almost every time. This is the multiple comparisons problem. The per-element threshold must be set so that the maximum over all elements stays under it with probability 1 − α. For Gaussian noise, the maximum of N values grows like √(2 ln N) standard deviations, so the threshold grows slowly with output size. It is also the reason the 2x rule was noisy: it compared two such maxima without accounting for either.

θ is a promise, and a promise needs evidence. Each composite op has planted bugs (one-line mistakes such as `layer_norm_no_eps` or `attention_mask_off_by_one`), and `run_checks ch01 --selftest` checks that each one fails for its stated reason. The selftest also measures how far over the threshold each bug lands, which tests θ directly instead of trusting the formula. Margins under the new rules: [[PROTO: planted-bug margins under the new rules]].

### Model level: KL divergence on the next-token distribution

For `forward`, the output is a [T, V] matrix of logits, and what matters is the distribution they define at each position. The gate is per-position KL(truth ‖ candidate), with a maximum over positions below 1e-7 in fp32.

The number 1e-7 has a meaning. Let δ be the candidate's logit error at one position and p the true distribution. For small δ, a second-order expansion gives

```
KL(p ‖ softmax(z + δ)) ≈ ½ · Var_p(δ)
```

The variance is weighted by p, so errors on likely tokens count and errors on tokens with probability near zero do not. A shift of every logit by the same amount changes nothing, and the variance correctly ignores it. KL < 1e-7 means Var_p(δ) < 2e-7, so the probability-weighted logit wobble is under about 4.5e-4. A correct forward measured 5e-9 against truth. The exact-GELU bug measured 4e-5. The gate sits between them with more than an order of magnitude on each side.

Token-level checks are smoke tests only. The exact-GELU bug produced identical greedy continuations (64 of 64 tokens on every prompt), 100% top-1 agreement, and passed vLLM's top-5 logprobs check on all 6 prompts (`assay/ch01/RESULTS.md`). A token match tells you the model is not badly broken. It cannot tell you the model is right.

At low precision, a bf16 or fp16 forward is compared on the same KL statistic with a much looser limit, about 0.1. That limit is about twice HF's own bf16 KL against fp32, which `RESULTS.md` measured at up to 0.046. It is a hand-picked number, and the open questions below say so.

## Inputs decide which bugs can show

A tolerance can only catch a bug that the inputs make visible. assay's inputs are chosen to expose them.

- **Offset from zero.** Data centered at zero hides a missing mean subtraction in `layer_norm`. Data near zero makes every relative bound meaningless. Inputs carry an offset.
- **Several magnitudes.** A missing `eps` only shows when the variance is comparable to `eps`. The layer norm cases use `eps=0.1` and rows of length 1, where the variance is exactly 0, for this reason.
- **Long, non-repetitive prompts.** `RESULTS.md` shows why. On a 1-token prompt, the attention-scale bug and the mask bug produce the same logits as the correct model, because attention over one token ignores both. On a 200-token repetitive prompt, the attention-scale bug kept 64 of 64 greedy tokens and passed the logprobs check. The model prompts are 384 and 192 tokens of mixed prose, code, and Unicode (`PROMPTS` in `ops.py`).
- **Shapes that cover code paths.** Each op declares edge sizes per dim: 1, small primes, tile size ± 1, and the largest size that matters. Past 64 cases, the sweep uses a pairwise covering array plus the all-smallest and all-largest corners. A separate `coverage` check fails if some line or branch of the reader's function never ran on any case, because a branch no case reaches is a branch nobody checked.

## A chip that cannot test a dtype reports a visible skip

A T4 (sm_75) runs bf16 code, but only in emulation. `torch.cuda.is_bf16_supported(including_emulation=False)` is False there, and bf16 matmul runs at 3.8 TFLOP/s, slower than fp32. A pass on a T4 would say nothing about the bf16 kernels that a bf16 chip (sm_80 or newer) runs. So the capability table (`blogs/engine/capabilities.json`, mirrored in `suite.py`) marks bf16 on sm_75 as not testable, and the verdict is `skip` with the reason attached. The cell can still pass on its other dtypes. A skip is not a pass. It records a gap in the evidence instead of hiding it.

## The check is built for a candidate that might cheat

The reader is often an agent, and an agent that is rewarded for a pass can learn to produce one without doing the work. It can read the expected answer, edit the grader, or return a cached tensor. So the candidate's code runs in an isolated child process. When the parent runs as root, the child drops to an unprivileged user before it imports the reader's file. The store with the expected answers is root-only. The trusted code is checked against a sha256 manifest before every check. This is threat A in the design note: only the candidate file is untrusted. Threat B, where the reader's scratch cells also run code with privileges, is deferred. The "trust" row of `blogs/notes/ch01-design-2026-10-09.md` has the details.

The core also separates running from judging. A Run is an immutable store entry with the candidate's facts (errors, reductions, and fingerprints of everything the result depends on). A Grade applies a grader to a stored Run and is keyed by the Run and the grader's fingerprint. Changing a threshold in `checks/chNN.toml` changes only the grader fingerprint, so `run_checks ch01 --grade-only` regrades every stored Run without executing candidate code again. That property is what makes it cheap to tune tolerances against the evidence, and it lets the 2x rule and the new rules be compared on the same Runs. The module docstring of `assay/core.py` describes the store and grading.

## Open questions

- **Does MCA noise model the candidate's rounding?** MCA perturbs the reference's own evaluation order. A candidate with a different algorithm, such as an online softmax or Welford's variance, rounds at different points. The assumption is that the spread of correct answers does not depend much on the algorithm. The prototype tests that assumption. Results: [[PROTO: MCA spread vs alternative algorithms]].
- **What does MCA cost?** K runs of the fp64 reference per case are paid once and cached, but they are paid on the slowest dtype on the chip. Cost: [[PROTO: MCA cost per op]].
- **Is c·√k a useful warning on tensor cores?** If truncating accumulators routinely exceed it, the warning is noise and should be calibrated per chip.
- **Is θ small enough?** θ is only meaningful if it is below the smallest bug a reader actually writes. The planted bugs are the bugs we thought of. Readers will write others.
- **The low-precision KL limit is hand-picked.** 0.1 comes from about 2x HF's measured bf16 KL, which is the 2x rule again in a different statistic. It needs the same treatment as fp32.
- **When does the 2x metric go away?** It stays reported for one chapter. Removing it needs a comparison on stored Runs that shows the new rules never miss a bug the old rule caught.

## Sources

- Design decisions: `blogs/notes/ch01-design-2026-10-09.md` (rows "tolerances", "check config", "matrix", "trust", "expected").
- Historical measurements: `blogs/assay/assay/ch01/RESULTS.md`.
- Check core and graders: `blogs/assay/assay/core.py`, `blogs/assay/assay/cli.py`, `blogs/assay/assay/ch01/ops.py`, `blogs/assay/assay/ch01/run.py`, `blogs/assay/assay/ch01/suite.py`.
- Capability table: `blogs/engine/capabilities.json`.
- TensorRT-LLM accuracy tests: <https://github.com/NVIDIA/TensorRT-LLM/blob/main/tests/integration/defs/accuracy/README.md>.
- FlashAttention tests: <https://github.com/Dao-AILab/flash-attention> (`tests/`).
- KernelBench and issue #165: <https://github.com/ScalingIntelligence/KernelBench/issues/165>.
- "Measuring the Checker": arXiv 2609.22220.
- GPU MODE reference kernels: <https://github.com/gpu-mode/reference-kernels>.
- SOL-ExecBench, pygpubench, popcorn: [[PROTO: links]].
- CUTLASS: <https://github.com/NVIDIA/cutlass>.
- BLAS level 3 tests (`dblat3.f`, `DMMCH`): <https://www.netlib.org/blas/>. LAPACK test suite: <https://www.netlib.org/lapack/>.
- N. J. Higham and T. Mary, "A New Approach to Probabilistic Rounding Error Analysis", SIAM J. Sci. Comput., 2019.
- M. Fasi, N. J. Higham, M. Mikaitis, and S. Pranesh, "Numerical Behavior of NVIDIA Tensor Cores", PeerJ Computer Science, 2021.
- PyTorch Dynamo accuracy comparison: `torch/_dynamo/utils.py` (`same`).
