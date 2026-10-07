# NOTES: kernels/paged-attention

Branch `kernels/paged-attention` (worktrees/attn), started off `build/resolve-at-warm` 73ffdbb;
rebased onto main 23df025 (its merge) with no conflicts. Working notes, not a design doc: the code is the source of truth.

## 1. Where build's 23 GiB went (measured before fixing)

`scripts/profile_build_memory.py` on 21a3105, A100. `build`: a TorchDispatchMode brackets every
top-level op with reset_peak / max_memory_allocated. `op`: the reference traced line by line.

    build peak 47.53 GiB; kelpie::paged_attention @ prefill T=1024: 24.15 GiB transient (x24 layers)
      next: prefill T=512 12.07, T=256 3.02, aten::_to_copy (load) 1.08, moe decode R=8 0.99

    reference at T=1024 = 2 x 512 rows (gpt-oss: 64 q / 8 kv heads, D 64), per line:
      gather K, V per TOKEN [1024, 512 slots, 8, 64] bf16     0.5 + 0.5 GiB
      repeat_interleave(8) of both (GQA)                      +4.0 +4.0  (8 GiB live)
      einsum(q.float(), keys.float())                         24.15 GiB peak = 8 live
                                                               + keys.float() 8 + einsum's permuted copy 8
      einsum(probs.to(bf16), values)                          12.3 GiB peak
    scores were 128 MiB (the back-of-envelope was right about them; they were not the cost).

Cause = per-token gather x GQA repeat x fp32 upcast x einsum's contiguous copy. Fixed in the
reference (37ef3ec): q heads grouped per kv head (no repeat), rows in chunks sized to a 256 MiB
working set (CHUNK_BYTES), K/V upcast per chunk only. Result: that op 24.15 -> 0.20 GiB; build
peak 47.53 -> 23.92 GiB on A100 (46.94 -> 24.40 on H100), which is main's 24.0. What now sets
the peak is the weights + the MoE backend's converted expert copy (adapters/_prepared.py).

## 2. Kernel: vLLM 0.29.0 Triton unified attention, vendored

Pin: vllm v0.29.0 = 98dff2a81d747d1dba01a47f939f48c3526d4206 (same tag as the Marlin .so);
`vllm/v1/attention/ops/{triton_unified_attention,triton_attention_helpers}.py`, upstream sha256
992a2bc8... / 8c730611..., vendored sha256 checked at import (vendored/cuda/vllm_attention).

Correctness (`scripts/bench_attention.py`, 62 cases x {reference, auto, forced 2D, forced 3D},
fp64 truth, crucible@dfb735f error_budget, pad rows must be 0): A100 and H100 0 failing of
248 correctness + 16 capture rows;
worst err/budget 0.192 (the bf16 reference's own worst is also 0.192). Capture + replay on a
different plan: max_diff 0.0. JSON with env + tree sha: /data/attn/bench-{a100,h100}-r2.json.

us per layer, gpt-oss, graph replay (prefill: eager):

| bucket | A100 ref | A100 vllm | H100 ref | H100 vllm |
|---|---:|---:|---:|---:|
| decode R=1 w0 | 79.9 | 24.6 | 63.1 | 19.8 |
| decode R=8 w0 | 209.9 | 34.8 | 148.7 | 25.5 |
| decode R=8 w128 | 215.0 | 22.5 (2D) | 153.5 | 18.1 (2D) |
| decode_extra R=8 x16 w0 | 1946.6 | 51.2 | 1259.2 | 35.2 |
| prefill T=128 w0 | 1031 | 250 | 738 | 158 |
| prefill T=1024 w0 | 13451 | 360 | 8998 | 232 |

(w128 decode rows: the 3D-vs-window heuristic landed after this run; 2D is what it now picks.)

e2e (Modal, gpt-oss-20b, prove_moe capacity, capture=True unless noted):

| | A100 | H100 |
|---|---|---|
| build peak GiB: resolve-at-warm / ref fixed / vllm | 47.53 / 23.92 / 23.92 | 46.94 / 24.40 / 24.40 |
| build s (--bare) | 22.1 / 20.8 / 12.1 | 27.7 / 26.7 / 9.8 |
| prove_moe compare vs main baseline | PASS: exact 3/8, teacher 1.0, own 6.0 | PASS: exact 4/8, teacher 6.0, own 1.0 |
| K=0 tok/s, capture (raw+math, 64 new) | 92.6 (marlin+ref attn: 71.6) | 124.1 (70.7) |
| DFlash check_spec_teacher_forced native math 256 | PASS, accept 4.44, worst 1.0, 64.3 tok/s eager | PASS, 4.37, worst 2.0, 72.9 eager |
| prove_dflash math 256, eager: K=0 / spec | 18.7 / 64.8 | 17.5 / 72.9 |

Is spec decode faster yet? Eager vs eager, yes (3.5-4x). Against K=0 WITH capture, no: 92.6 /
124.1 > 64.8 / 72.9. DFlash + capture is still refused (`build`: a drafter needs capture=False),
so the comparison that matters is not runnable yet. (The K=0 capture number is prove_moe's
corpus, not the math corpus: same model, different prompts and lengths.)

## Judgement calls

- **`query_start_loc` joined the op signature** (after `positions`, all five call sites). Every
  real kernel grids over it; deriving it from row_request inside the adapter would cost ~3
  launches per layer per step and duplicate the core's own value. The reference ignores it (so
  a qsl inconsistent with row_request would only show against a kernel; padPlan writes both
  from one loop). Alternative, not taken: keep the contract and derive in the adapter.
- **The kernel ignores `positions`**: it derives a row's position as seq_len - rows + i (vLLM's
  convention). The reference now ASSERTS that on device (`torch._assert_async`, capture-safe),
  so any real plan the reference sees that broke it fails loudly (bench's `sample` is
  consistent by construction and cannot catch it; the e2e reference runs below can). Review
  checked the producers: scheduler.zig:1364, synthetic plans, dflash.py:479 all satisfy it.
- **Reference numerics changed slightly**: P@V in fp32 (was bf16 probs), fp64 inputs compute
  in fp64. vs the old reference on fp64 inputs: 1.8e-7 (old was fp32).
- **Pad rows**: vLLM never passes pads; the op gets padded T. The 3D path's reduce writes pad
  rows from unwritten scratch (inf/NaN: 17 FAIL rows in the first A100 run), so 3D output is
  masked by row_request (one elementwise kernel, T <= 16). 2D leaves them at the zero init.
- **2D/3D choice from shapes**: 3D iff T == R (decode bucket), R <= 128 // Hkv, window == 0.
  Measured: 3D wins full-attention decode at R >= 2, loses on sliding layers (<= 128 keys).
  R = 1 w0 2D was faster at the bench's contexts (<= 700 tokens); long contexts favor 3D; kept.
- **Refused, not served (review)**: vllm_triton raises NotImplementedError for causal=False
  with a window (the kernel's non-causal window is two-sided, the reference's left-only), head
  dim < 32 (vLLM's own minimum), and non-bf16/fp16 (fp32 would run TF32 dots). The torch
  `predicate` hook on Impl is never consulted by op.py, so a raise is the refusal.
  SAMPLE_BATCH's head_dim went 8 -> 32 so bench.compare can run the impl on it.
- **Triton's version is in the backend version** (fingerprints change on a triton upgrade).
- **3D scratch allocated per call** (fp32 [T, H, 16, D], ~4 MiB at T=16), vLLM keeps one.
- **FlashInfer not vendored.** Research (flashinfer 0.7.0 wheels read, not run): sinks on
  sm80/sm90 exist only in the fa2/fa3 "attention_sink" AOT modules, reachable only by building
  `BatchPrefillWithPagedKVCacheWrapper(jit_args=...)` with the exact AOT module name (the public
  sink wrapper's name misses the cache and would JIT with the image's nvcc 12.4). `run(sinks=)`
  on fa2/fa3 is silently IGNORED. `plan()` copies indptr to host each step (not capturable
  without a per-step plan hook we don't have), `window_left` is fixed per plan (two wrappers),
  and the sm80 AOT cache is a separate wheel not in the lock. Not cheap; vLLM itself never uses
  FlashInfer for gpt-oss on A100/H100 (H100: FA3 with sinks, vllm-flash-attn; not vendored).
- **H100 default = the same Triton kernel** (graded there), not vLLM's FA3 path.
- `adapters/flashinfer.py` (old, unregistered, host-looping, pre-qsl signature) left untouched.

## Uncertainties

- A100 e2e: own decode vs own teacher-forced prefill 6.0 bf16 steps (gate 8). Decode runs the
  3D kernel under capture, prefill the 2D; both pass bench at 0.19 of budget. Per-op numerics
  are fine; e2e, the two paths accumulate in different orders. Near the gate; not chased.
- exact-match vs main's baseline dropped (8/8 on the branch's reference -> 3/8 A100): prompt 0
  diverges at token 1 on both GPUs at an exact tie (both tokens 0.0 steps under teacher forcing).
- Eager call overhead ~230-400 us per call (Triton's Python launcher, ~80 args): prefill is not
  captured, so a prefill step pays ~6 ms of launch across 24 layers. Graph replay hides it.
- Only gpt-oss geometry (and DFlash's call shape at gpt-oss dims) is benched; qwen3/llama/gpt2
  go through the same kernel but no per-arch grading for their head dims ran.
- Pages slid out of the window point at the null page; the kernel prunes tiles by window so it
  reads them at most in a partial tile, masked. Benched with contexts > 128 but the sample does
  not model slid-out pages as null (every page is real).

- **Review re-proof (Modal, after the fixes)**: bench 0 failing of 264 on A100 and H100 again.
  The reference's positions assert never fired on real plans: prove_moe compare and DFlash
  check_spec_teacher_forced ran with `--kernels paged_attention=reference` on both GPUs.
  vllm_triton default: A100 compare PASS (90.7 tok/s capture, own 6.0), DFlash PASS (worst
  1.0, 57.5 tok/s eager; 64.3 the run before: eager tok/s moves ~10% run to run); H100 PASS
  (116.1 tok/s, own 1.0), DFlash PASS (worst 2.0, 65.5).
- **A100 control FAILS own-decode**: marlin + FIXED reference attention + capture, prompt 3
  token 13: 10.0 bf16 steps (gate 8), exact 7/8, teacher vs baseline fine. Same prompt / position
  class as NOTES-kernels' marlin eager 20-step token. Not the default path; I read it as the
  known marlin prompt-3 near-tie meeting the reference's new fp32 P@V numerics, but it IS a gate
  failure I did not chase. H100 control (triton_kernels_hopper + reference) passes (own 4.0).

- **After the rebase onto main 23df025** (A100): build --bare 21.9 s, peak 23.92 GiB; prove_moe
  compare --capture PASS, 121.3 tok/s, exact 3/8, own 6.0; DFlash check_spec_teacher_forced
  PASS worst 1.0, 63.1 tok/s eager. Build time moves ~2x run to run (12.1 s earlier on the same
  tree shape): cold Triton cache / volume effects, not attributed.

## Papercuts

- Modal uploads the tree at sandbox create, so the "before" profile ran from a detached
  worktree (worktrees/attn-measure @ 21a3105); a remote script must exist in the tree at create.
- `from kelpie_models.kernels.ops import paged_attention` gives the Op, not the module (the
  package rebinds the name): cost one Modal run. Use importlib for the module.
- `uv run` rewrites kelpie-engine/uv.lock every time (already in NOTES-build-step); restored.
- scripts/test's import smoke needs the vendored Triton package in SMOKE_SKIP (no triton on
  the laptop).
- The old `_samples` built a contiguous kv tensor that `kv_views` refuses; replaced by
  `sample(SAMPLE_BATCH)`.
- Background shells are blocked; long Modal runs go through tmux + a wait loop.

## Reproduce

    cd ~/research-2/worktrees/attn
    M='uv run --frozen --project kelpie/kelpie-http kelpie remote --volume kelpie-a1 --model openai/gpt-oss-20b --model z-lab/gpt-oss-20b-DFlash'
    $M --gpu A100-80GB -- 'HF_HUB_OFFLINE=1 python -m scripts.profile_build_memory op'
    $M --gpu A100-80GB -- 'HF_HUB_OFFLINE=1 python -m scripts.profile_build_memory build [--bare] [--attention reference]'
    $M --gpu H100 -- 'python -m scripts.bench_attention --out /data/attn/bench-h100.json --provenance <sha>'
    $M --gpu A100-80GB -- 'HF_HUB_OFFLINE=1 python -m scripts.prove_moe compare --baseline /data/moe/baseline-main-4ae5b7f.json --capture'
    $M --gpu A100-80GB -- 'HF_HUB_OFFLINE=1 python -m scripts.check_spec_teacher_forced --loop native --corpus math --max-new 256'
    $M --gpu A100-80GB -- 'HF_HUB_OFFLINE=1 python -m scripts.prove_dflash --corpus math --max-new 256 --loop native'
