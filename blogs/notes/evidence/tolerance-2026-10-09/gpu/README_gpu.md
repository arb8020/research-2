# Tolerance prototype on GPU (T4 sm_75, L4 sm_89)

**Run:** `modal run modal_run.py`, then `uv run summarize_gpu.py`. `proto_gpu.py` is a device-aware copy of `../proto.py`, which is unchanged. It uses the same inputs; truth, candidates and MCA run on cuda.

**Held-out implementations (GPU only):**
- torch.compile versions of the ops
- a Triton matmul
- SDPA backends: math, efficient, flash, cudnn
- bmm, and cuBLAS with reduced-precision reduction off
- liger-kernel 0.6.5
- fla-core 0.5.2

**Outputs:** `T4/`, `L4/` (the CPU tables), `scorecard_gpu.md`, `compare_cpu.md`, `heldout.md`, `xcheck.md`, `probe.md`.

## Does it hold on GPU?
Yes. Every CPU scorecard row reproduces within 1–2 points:
- Split gauge: 0% false-fail everywhere.
- MCA seq c=2, false-fail: 0% (fp32), 2% (fp16), 0% (bf16).
- TF32 under the fp32 contract is caught 100% on L4. T4 has no TF32.

## Does 2γ generalize?
**In-dtype contract:** 0% false-fail on held-out implementations, with two exceptions on L4 fp32 attention:
- **sdpa_efficient:** 37% false-fail, margin 1.35. The cause is unknown; the error is far too small to be TF32. Passing it would need c≈2.7.
- **fla parallel_attn:** fails 100%. It uses TF32 `tl.dot`, which is a real contract violation.

**`--inner fp32` contract:** held-out false-fail is 9–11%. Every fused attention kernel (SDPA flash, efficient and cudnn, and fla) fails about 30% in fp16/bf16, at margin about 3. They round P to the storage dtype before P·V. The fp32-inner model needs that one rounding added.

## Subtle bugs (MCA seq K16 c=2; T4 = L4)
| contract | fp32 | fp16 | bf16 |
|---|---|---|---|
| in-dtype: detect / false-fail | 67% / 0% | 3% / 2% | 0% / 0% |
| fp32-inner: detect / false-fail | 67% / 0% | 80% / 39% | 80% / 36% |

T4 notes: inductor skips bf16 compilation there, so compiled bf16 runs as eager. Triton bf16 kernels (liger, fla) did run on sm_75.

## MCA: is σ device-independent, and what does it cost?
**σ is device-independent:**
- σ_GPU/σ_CPU has median 0.99–1.00, with a 5–95% spread of 0.65–1.55. That equals the spread between two CPU seeds.
- Grading with σ computed on CPU gives the same verdict in 99.98% of cases (1 of about 5000 per GPU, a borderline gross bug).
- **So MCA can run on CPU and be cached.**

**Cost of seq K=16 on GPU vs the container CPU:**
- gelu: 30–37× faster
- attention: 6.6× faster (55 vs 365 ms)
- layernorm/softmax: 0.8× (slower), because the 256-step sequential sums are launch-bound

Pairwise K=64 on GPU takes 33–42 ms.

## Reduced-precision-reduction probe (L4)
- **The flag matters.** With the default `allow_*_reduced_precision_reduction=True`, cuBLAS uses output-dtype split-K. Error goes from about 1.0 to about 2.4 output ulps.
- **The einsum-ignores-the-flag hypothesis is not confirmed.** mm, F.linear, einsum (2-D and 3-D) and bmm all change bitwise when the flag flips, with or without `TORCH_BLAS_PREFER_CUBLASLT=1`.
- **Our rule can't see it.** With the proto's 4u|T| output term (no-bias form), the worst margin is 0.57. A strict 2u|T| form would false-fail default bf16 at 1024²×4096 (1.08).
- **If the contract forbids it, the harness must set the flag.**

## Recommended constants
**Unchanged:** split gauge; MCA RMS, sequential, K=16, fail above 2γ.

**Additions:**
- Cache MCA computed on CPU.
- Keep 4u|T| for contractions without bias.
- For fp32-inner attention, model P-rounding.
- Decide whether sdpa_efficient fp32 on sm80+ is correct. If it is, attention needs c≈3.

## Cost
About $0.50 (estimated from wall time × list price). That covers 2 smoke runs and 1 full run per GPU, plus 2 short L4 probe runs. No apps or containers are left running.

## Uncertain
- Cause of the sdpa_efficient fp32 failures.
- One shape per op (only the probe tests large K).
- No Hopper GPU.
- flash and cudnn SDPA ran on L4 only.
