# Tolerance prototype: old 2x rule vs BLAS gauge / GELU gauge / MCA test

**Run:** `./run_all.sh` (about 5 min on CPU).

**Setup:** inputs are N(μ∈{0.5,3}, s∈{0.1,1,10}), 5 seeds each. Truth is fp64 computed on the dtype-rounded inputs.

**Files:** `proto.py` (code), `results*.md` (per candidate), `scorecard.md`, `mde*.md`, `cost*.md`, `summary_mca.md` (K sweep).

## Headline
The new scheme beats 2x, but only after three fixes.

1. **Contraction rule as planned (fail if r > k, with u_out·|T| inside r) is wrong for fp16/bf16.**
   - k multiplies the output-rounding term, so fp16 accumulation is caught only ~55% of the time; MDE is 10% (fp16) and none (bf16).
   - **Fix:** fail if `|C−T| > k·u_acc·G + 2·u_out·(|T| + |A@B|)`. The `|A@B|` term accounts for the rounding before `+b`. Without it, correct fp16 `x@w + b` false-fails 13%.
   - With the fix: 0% false-fail, 100% detection, MDE 1.8e-3 in fp16 (2x gets 5.6e-4).
2. **MCA as an exact null false-fails correct code.**
   - The RMS-of-z null is very narrow (sd 0.005–0.05), and real kernels differ from the noise model by small factors: torch fp32 SDPA fails 70% (margin 1.26), `exp(x−logsumexp)` softmax fails 100% (margin ~5). Model mismatch, not α, sets the false-fail rate.
   - **Fix:** model sums as sequential (worst order) and fail above 2γ.
3. **The GELU gauge needs its floor.** Without one, correct fp32 GELU fails 50% (the `1+tanh` cancellation at x≪0). With floor u it passes, but fail=16 is loose (MDE 5.6e-6 vs 5.6e-8 for MCA). The subtle constant typos are caught 100% by MCA and 67–97% by the gauge.

## Scorecard
Each cell: false-fail on correct / subtle bugs detected / gross bugs detected.

| ops | dtype | old 2x | new (fixed) |
|---|---|---|---|
| linear, qk, pv | fp16 | 1% / 100% / 100% | 0% / 100% / 100% |
| LN, softmax, attn | fp32 | 1% / 60% / 100% | 0% / 67% / 100% |
| LN, softmax, attn | fp16 | **21%** / 65% / 95% | 2% / 3% / 97% |
| LN, softmax, attn | bf16 | **13%** / 31% / 89% | 0% / 0% / 83% |

## Where it fails / what in the plan looks wrong
- **In fp16/bf16, subtle bugs look the same as honest in-dtype code.**
  - Naive fp16 two-pass layernorm on μ=3, s=0.1 has about 1.5% error, which is as large as `unbiased_var` or `eps 1e-6`.
  - 2x "catches" them only by also failing 63–77% of correct fp16 layernorms.
  - This is a **contract choice**. With an fp32-opmath MCA (`--inner fp32`), subtle-bug detection reaches 80–100%, but every in-dtype implementation then fails.
- **σ depends on the assumed algorithm.**
  - Pairwise vs sequential summation moves layernorm fp16 MDE from 1.8% to 10%, and the lse-softmax margin from 5 to 1.6.
  - MCA encodes which implementations count as correct; it is not assumption-free.
- **Some "correct" variants should fail:**
  - One-pass variance (E[x²]−E[x]²) is 20–700× worse on offset inputs and NaN in bf16.
  - Global-max softmax underflows in fp16.
  - No-max-subtract softmax overflows in fp16.
- **Some bugs are invisible at low precision.**
  - Erf vs tanh GELU differs by ≤2e-4 relative, which is below fp16's u (4.9e-4).
  - The `1/sqrt(H+1)` scale bug is invisible in bf16.
  - Test these in fp32 only.
- **TRT-LLM-style θ/β is mostly decorative here.** θ is 0.02–0.39 RMS-z units, while the slack forced by model mismatch is about 1 unit.

## Constants I'd pick
- **Contractions:** u_acc = fp32 per the contract, with the split rule above.
  - Not measured: a √k warn tier in the split form.
- **Elementwise:** MCA (cheap). Otherwise the gauge `u(|T|+|x f'|+|x|)` with fail at 16.
- **Composite (MCA):**
  - u = test dtype, sequential sums
  - K=16: verdicts for the RMS statistic were identical from K=8 to K=128; the max statistic needs K≥16
  - statistic: RMS of z
  - threshold γ = mean + z₀.₉₉₉·sd·√(1+1/K), fail if above 2γ
- **Inputs:** always include μ=3 and s=0.1. The eps bugs are invisible at s=10.

## Cost
Truth takes 0.1–0.5 ms. MCA at K=64 (2K passes) takes 0.1–1.3 s (500–5700×); at K=16 it is ~150–1000×. Attention dominates.

## Uncertain
- c=2 was tuned on these same variants. It needs held-out implementations (flash/Triton kernels, a different BLAS).
- There is one shape per op, so how thresholds scale with k and N is untested.
- Only uniform relative noise was tried, not stochastic rounding.
- CPU fp16 matmul is not exactly fp32-accumulate-then-round (differences ≤1 ulp), so GPUs may behave differently.
