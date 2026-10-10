# How assay decides an implementation is correct

You write `layer_norm` in `gpt2.py`, press Run, and a check answers pass or fail. This page explains why the checks work the way they do. The thresholds live in `checks/chNN.toml` and in the docstrings of the check functions. <!-- claude: checks/chNN.toml is not implemented yet; today the thresholds are constants in assay/ch01/suite.py (FLOORS, KL_MAX) -->

## Correct cannot mean equal

Floating-point arithmetic rounds after every operation, so two correct dot products that sum in different orders get different answers. A tiled matmul, a fused kernel, and plain torch all differ in the last bits, and none of them is wrong.

So a check must accept every reasonable evaluation order and still reject real bugs, even small ones such as an exact-erf GELU where GPT-2 uses the tanh approximation. Too tight a tolerance fails correct code. Too loose a tolerance passes bugs.

## Truth is the reference in fp64, on your device

Each check compares your output to truth: the reference op, run in fp64 on the same inputs. fp64 rounds about nine orders of magnitude finer than fp32, so the check measures your error, not the gap between two rounded answers.

Truth runs on your device, because a GPU and a CPU can disagree even in fp64. fp64 is slow on most GPUs (a T4's fp64 matmul is 43x slower than fp32), so truth is computed once per case and cached.

## The 2x rule worked until a correct model failed it

The first checks used the rule from FlashAttention's tests, which popcorn also uses:

```text
max|C - T| <= 2 * max|R - T| + floor[dtype]
```

C is your output, T is fp64 truth, and R is the reference run in your dtype: your error may be twice the reference's. The rule needs no analysis of the op, but it is only as strict as one reference. Worse, it compares two maxima over thousands of elements, each a noisy number, so two correct orders can land on either side of the line.

That noise is what broke it. A correct GPT-2 forward came in at 1.02x the budget on Linux and 0.98x on macOS. <!-- claude: from an agent's session report, not a file in the repo --> Its error against truth was 2.6x HF's own, only because it sums in a different order. <!-- claude: from an agent's session report, not a file in the repo --> Yet its per-position KL against fp64 truth was 5.3e-9: its output distribution matched truth to within rounding. <!-- claude: 5.3e-9 is vs fp64 truth, from an integration run (session report, not a file); RESULTS.md has 5.2e-10 for the correct forward, but that is vs HF fp32, a different baseline --> A gate that flips with the platform on correct code cannot be the gate. assay still records the 2x number for one chapter, and `run_checks ch01 --grade-only` regrades stored runs, so the two rules can be compared on the same runs.

## Most of the field picks tolerances by hand

A partial survey of how kernel test suites decide correctness: <!-- claude: rows carried over from the earlier draft; I confirmed the links resolve but did not re-check each project's rule against its source -->

| Project | Rule |
|---|---|
| [SOL-ExecBench](https://github.com/nvidia/sol-execbench) ([paper](https://arxiv.org/abs/2603.19173)) | Calibrated `atol` and `rtol` per problem; at least 99% of elements within them |
| [pygpubench](https://github.com/gpu-mode/pygpubench), [GPU MODE](https://github.com/gpu-mode/reference-kernels) | `allclose`, per-problem tolerances. Linear algebra problems: ‖R − QᵀA‖ ≤ 20·n·ε·‖A‖ |
| KernelBench | `allclose` at 1e-4 or 1e-2. All zeros passes 4 of 60 problems ([issue #165](https://github.com/ScalingIntelligence/KernelBench/issues/165)). [Measuring the Checker](https://arxiv.org/abs/2609.22220): tolerances 1 to 3 orders of magnitude too loose. See also [KernelBench-Verified](https://arxiv.org/abs/2607.16241) |
| FlashAttention, PyTorch Dynamo, [popcorn](https://github.com/tilde-research/popcorn) | The 2x rule above, or an RMSE variant (Dynamo) |
| CUTLASS | Small-integer inputs that make the product exact; bitwise compare |
| BLAS `dblat3` (`DMMCH`) | Per element, \|C − T\| / (ε · Σ\|a\|\|b\|) < 16 |
| [LAPACK test suite](https://github.com/Reference-LAPACK/lapack) | Normalized residuals < 30 |

Most projects loosen `atol` and `rtol` until known-good code passes, which is how all zeros passes KernelBench. Numerical linear algebra derives the shape of the bound from error analysis and picks only a small constant. assay does the same: the math sets the shape of each bound, and measurement sets the constants.

## Each kind of op gets the bound its math supports

Every op declares a kind: contraction, elementwise, composite, or model. <!-- claude: only kind="model" exists in assay/ch01/ops.py today; the other three kinds and their graders are not implemented --> A matmul's error grows with its inner dimension, a GELU's depends on how steep the function is, and a model is best judged by its output distribution. Before any numeric check, every op must also return the right dtype and shape, leave its inputs unchanged, and be deterministic.

### Contractions: a ratio from forward error analysis

For C = A·B with inner dimension k and unit roundoff u, the classic first-order bound is |C − T| ≤ k·u·(|A|·|B|) per element. assay turns it into a ratio:

```text
r = |C - T| / (u * (|A| @ |B|) + u * |T|)
```

The `u·|T|` term covers rounding into your dtype. The ratio is close to what `dblat3` checks and has no units, so one limit fits any inputs.

Rounding errors usually cancel in part, so Higham and Mary (2019) show growth like √k, not k, with high probability. But tensor cores truncate during accumulation, so their errors do not cancel (Fasi, Higham, Mikaitis, and Pranesh, 2021). So assay fails a contraction only when r exceeds k, which the worst-case bound rules out for any correct order. It warns above c·√k, with c = `[[PROTO: c for the contraction warning]]`. A warning means correct, but less accurate than a typical order.

### Elementwise ops: the condition number sets the scale

For y = f(x), the input carries a rounding error of about u·|x|. f scales it by f′(x), and rounding the result adds u·|T|:

```text
|C - T| <= m * (u * |x * f'(x)| + u * |T|) + floor
```

with m = `[[PROTO: m for elementwise ops]]` and floor = `[[PROTO: elementwise floor]]`. The first term is the condition number in absolute form: large where f is steep, small where it is flat. The bound is tight where a wrong formula shows and loose where rounding is all there is. <!-- claude: this bound is the drafting agent's own first-order derivation, not taken from a source; it ignores error inside f's own evaluation (e.g. tanh in GELU), which m has to absorb --> The floor covers the zeros of f.

### Composite ops: measure the spread, then test against it

A tight bound for a layer norm or an attention is easy to get wrong, so assay measures the spread of correct answers with Monte Carlo arithmetic (MCA). It runs the fp64 reference K = `[[PROTO: MCA run count K]]` times, adding noise the size of one rounding in your dtype after every primitive op. The per-element standard deviation σ of those runs is the noise of a correct answer. The runs are cached per case and cost `[[PROTO: MCA cost per op]]`.

The decision is a one-sided hypothesis test, as in [TensorRT-LLM's accuracy tests](https://github.com/NVIDIA/TensorRT-LLM/blob/main/tests/integration/defs/accuracy/README.md), defined by three numbers: α, how often a correct implementation may fail; β, how often a bug of size θ may pass; and θ, the smallest bug the test promises to catch. With n samples per side, that README gives the threshold γ and θ:

```text
γ = x̄ + Φ⁻¹(α) · √(2σ²/n)
θ = −(Φ⁻¹(α) + Φ⁻¹(β)) · √(2σ²/n)
```

Fix α, β, n, and the noise, and θ follows. If θ is bigger than the bugs you care about, you need more samples or less noise. assay uses α = `[[PROTO: α for composite ops]]` and β = `[[PROTO: β for composite ops]]`, which gives θ = `[[PROTO: θ per composite op]]`.

A check fails if any element is out of bounds, so the threshold must bound the maximum over all N elements. For Gaussian noise that maximum grows like √(2 ln N) standard deviations. <!-- claude: the drafting agent's own note; √(2 ln N) is the standard asymptotic for the max of N iid Gaussians, but the per-element errors here are neither independent nor exactly Gaussian -->

θ is a promise, so it needs evidence: `run_checks ch01 --selftest` checks that planted bugs such as `layer_norm_no_eps` and `attention_mask_off_by_one` fail, and by how much. Margins under the new rules: `[[PROTO: planted-bug margins under the new rules]]`.

### Model level: KL divergence on the next-token distribution

For `forward`, what matters is the next-token distribution at each position. The fp32 gate is the maximum over positions of KL(truth ‖ candidate), below 1e-7. For a small logit error δ and true distribution p,

```text
KL(p ‖ softmax(z + δ)) ≈ ½ · Var_p(δ)
```

Errors on likely tokens count, errors on unlikely ones barely do, and a shift of every logit by the same amount counts not at all. KL < 1e-7 means a probability-weighted logit error under about 4.5e-4. A correct forward measured 5.3e-9 against fp64 truth, and the exact-GELU bug measured 4e-5 against HF's fp32 model (`assay/ch01/RESULTS.md`), so the gate sits more than an order of magnitude from each. <!-- claude: the two numbers use different baselines (fp64 truth vs HF fp32); 5.3e-9 is from a session report, not a file. RESULTS.md has both vs HF fp32: correct 5.2e-10, GELU 4.0e-5. The GELU bug's KL vs fp64 truth was not measured that I know of -->

Token-level checks are smoke tests only: the exact-GELU bug kept all 64 greedy tokens on every prompt and passed vLLM's top-5 logprobs check. A token match says the model is not badly broken, not that it is right.

bf16 uses the same statistic with a limit of 0.1, about twice HF's own bf16 KL against fp32 (up to 0.046 in `RESULTS.md`).

## Inputs decide which bugs can show

A tolerance can catch only a bug that the inputs make visible.

- **Offset from zero.** Data centered at zero hides a missing mean subtraction in `layer_norm`.
- **Several magnitudes.** A missing `eps` shows only when the variance is comparable to `eps`, so layer norm cases include `eps=0.1` and rows of length 1, whose variance is 0. <!-- claude: carried over from the earlier draft; I did not find eps=0.1 in assay/ch01/ops.py -->
- **Long, varied prompts.** Attention over one token ignores the attention scale, so a 1-token prompt hides a wrong scale. On a 200-token repetitive prompt, the scale bug kept all 64 greedy tokens (`RESULTS.md`). The model prompts are 384 and 192 tokens of mixed prose, code, and Unicode.
- **Shapes that reach every code path.** Each op sweeps edge sizes such as 1, small primes, and tile size ± 1, and a `coverage` check fails if a line or branch of your function never ran.

## A chip that cannot test a dtype reports a visible skip

A T4 (sm_75) runs bf16 only in emulation, so a pass there says nothing about real bf16 kernels. `engine/capabilities.json` marks bf16 on sm_75 as not testable, and the verdict is `skip` with the reason attached. A skip is not a pass: it shows a gap in the evidence instead of hiding it.

## The check assumes the candidate might cheat

An agent rewarded for a pass can learn to read the expected answer instead of doing the work. So your code runs in an isolated child process that cannot reach the stored answers or the trusted code. The threat model, and what is still deferred, is in the "trust" row of `blogs/notes/ch01-design-2026-10-09.md`.

## Open questions

- **Does MCA noise model your rounding?** MCA perturbs the reference's own order, but an online softmax or Welford's variance rounds at different points. `[[PROTO: MCA spread vs alternative algorithms]]`.
- **Is θ small enough?** It must be below the smallest bug a reader actually writes, and the planted bugs are only the ones we thought of.
- **The bf16 limit is hand-picked.** 0.1 is the 2x rule again, in a different statistic.
