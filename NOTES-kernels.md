# NOTES: kernels/moe-routing

Branch `kernels/moe-routing` (worktrees/kernels-moe), off main 2298236. Queue item:
kelpie/docs/queue-2026-09-23.md "Next ... kernels/moe-routing".

## What changed (shape)

```
gpt_oss.forward
  moe(h, layer, cfg, mesh)
    router: h @ W_r.T + b -> topk -> softmax          (unchanged, replicated)
~   torch.ops.kelpie.moe(h, topk_ids, topk_weights,     # router output ON DEVICE
~       gate_up.blocks, gate_up.scales, gate_up_b,       # packed MXFP4, hub layout
~       down.blocks, down.scales, down_b,
~       e_lo, SWIGLU_ALPHA, swiglu_limit)                # local expert range = [e_lo, e_lo+E)
    all_reduce("T M {ep,tp} -> T M")                     (unchanged)
-   argsort / int(local.sum()) / bincount().tolist() / grouped_mm loop   # host syncs, gone
```

```
kelpie-models/kelpie_models/kernels
~   op.py                     # Binding value + epoch; bind rebinds; reset_for_test/bound()/installed() gone
~   fingerprint.py            # fingerprint(op, impl, binding)
~   backends.py               # + triton_kernels backend
    ops/
+     moe.py                  # kelpie::moe: reference (dense masked, per-expert dequant), Mxfp4, sample()
-     grouped_mm_mxfp4.py     # superseded (expert_counts: list[int] forced a host sync)
~     clamped_swiglu.py       # reference body written (moved out of gpt_oss)
    adapters/
+     moe_triton_kernels.py   # OpenAI triton_kernels v3.7.1, strided MXFP4 = zero-copy view
+     moe_flashinfer.py       # flashinfer 0.7.0 cutlass_fused_moe W4A16, sm90 only
~ sdk/run.py                  # threads Binding; cache_mod.point(cache) before bind/warm
~ sdk/cache.py                # point(); freeze's Triton hook -> compilation.listener
~ sdk/captured.py             # epoch field + recapture on mismatch (minimal, for the rung0 merge)
~ models/torch/gpt_oss.py     # experts stay packed (Mxfp4 field), dequant_mxfp4 moved to ops/moe.py
kelpie/scripts
+ prove_moe.py                # e2e greedy record/compare, tie-aware teacher-forced gate, memory, --cache
+ bench_moe.py                # per-op correctness / capture / timing
~ check_serve.py              # rolled gpt-oss gets random packed MXFP4, not a dequantized name
```

## Judgement calls

- Op signature is flat (12 args): custom_op schemas are tensors + scalars. `expert_offset: int`
  names the local slice; the op returns this rank's partial sum; the caller all_reduces.
  `topk_ids` are GLOBAL ids, any integer dtype (torch.topk gives int64; adapters cast).
- Weights in the op contract = the HUB layout (`[E, N, K/32, 16]` + `[E, N, K/32]`), not any
  backend's. The reference and bench.compare can then run every impl on the same args.
- Reference = dense + masked over local experts, dequantizing ONE expert at a time (peak temp is
  one expert in bf16, not the table). E/k x the FLOPs of routed compute. Accumulates in fp32
  (old path accumulated the k contributions in bf16 via index_add_).
- A dequantized checkpoint is now REFUSED by gpt_oss.from_state_dict (was: accepted). Only
  check_serve's random roll used that branch; it now generates random packed codes.
- Backend weight layouts: triton_kernels' unswizzled MXFP4 path takes the hub tables as a
  transposed VIEW (no copy). FlashInfer needs a one-time conversion (de-interleave, pad
  2880->2944, sm90 interleave); I cache it in the adapter keyed by the source tensor
  (weakref-dropped). That is a second resident copy of the experts -- a spike cost. The right
  fix is a load-time per-impl layout hook (weights prepared once, reference path unaffected);
  not built.
- triton_kernels combine: inverse-permutation copy + fp32 sum over k (deterministic), instead
  of vLLM's fp32 index_add_ (atomics). Foreign (EP) slots sorted last and excluded from the
  ragged metadata, so never computed; masked out of the combine.
- FlashInfer EP: the op does not know the global expert count, so foreign ids are remapped to
  E and the call passes ep_size=2, ep_rank=0. Correct at world 1 (no foreign ids); the EP bench
  case exercises the remap on one GPU.
- Binding: the one process global left is `_live` (the live epoch), because torch.library's
  kernel registration is itself process-global. Everything else (impls, call counts) lives in
  the Binding value that build threads to resolve_table / fingerprint / cache.check.
- Captured: ASSERT on epoch mismatch (first version re-captured; the review pointed out that
  adopts another build's kernels while this engine's Table/manifest describe the old ones, and
  its eager fallbacks already run the new ones -- fail-stop is the honest answer). A REPL
  rebuilds after rebinding.
- Cache: `build(cache=...)` now points TRITON_CACHE_DIR / FLASHINFER_WORKSPACE_BASE at the cache
  BEFORE bind+warm. Before, TRITON_CACHE_DIR was only set by serve's `freeze`, after the warm
  pass had already compiled into ~/.triton -- so the cache dir never held any Triton binary.

## Results (Modal, kelpie-a1; torch 2.13.0+cu130, triton 3.7.1)

Per-op (`scripts/bench_moe.py`, /data/moe/bench-{a100,h100}.json). Correctness: 9 cases
(gpt-oss T=1/16/128 x 2 seeds, EP halves @0/@16 of 32 experts, small M=256 I=128 E=8 k=2) vs
fp64 reference, budget = bench.correctness.error_budget (vendored crucible@dfb735f):
every runnable impl passes every case on both GPUs; err is ~0.2-0.5 of budget, same as the bf16
reference's own. Capture: every runnable impl captures; replay on NEW routing == eager,
bit-exact.

us per MoE layer at gpt-oss shapes, CUDA-graph replay (T=2048: eager):

| T    | A100 ref | A100 triton_kernels | H100 ref | H100 triton_kernels | H100 tk_hopper | H100 flashinfer |
|------|---------:|--------------------:|---------:|--------------------:|---------------:|----------------:|
| 1    | 57498 | 220    | 32297 | 175  | 91   | 86   |
| 8    | 57799 | 760    | 32313 | 419  | 171  | 210  |
| 64   | 58043 | 1078   | 32392 | 627  | 262  | 295  |
| 256  | 59373 | 2145   | 32879 | 744  | 380  | 626  |
| 2048 | 82883 | 158338 | 45516 | 3483 | 2491 | 4074 |

Arch: triton_kernels (strided) sm80+; triton_kernels_hopper sm90 only; flashinfer sm90 only
(no FlashInfer MXFP4 MoE on sm80; trtllm-gen MXFP4 is sm100+). On sm80 the two sm90 impls
refuse with a RuntimeError naming the arch.

e2e gpt-oss-20b (`scripts/prove_moe.py compare`, baseline recorded on the pre-change tree on
A100: weights 38.96 GiB, peak 41.13 GiB, 8.3 tok/s):

| GPU  | impl                  | exact | teacher vs baseline | own decode vs own prefill | peak GiB | tok/s |
|------|-----------------------|------:|--------------------:|--------------------------:|---------:|------:|
| A100 | reference             | 3/8   | 1.0 | (not run then)| 13.67 | 1.1  |
| A100 | triton_kernels (build)| 5/8   | 1.0 | 1.0 | 13.67 | 7.9  |
| A100 | triton_kernels (serve)| 5/8   | 1.0 | 1.0 | 13.67 | 11.1 |
| H100 | triton_kernels_hopper | 3/8   | 8.0 (= gate) | 1.0 | 24.40 | 9.1 |
| H100 | flashinfer            | 3/8   | 1.0 | 2.0 | 23.61 | 14.8 |
| H100 | triton_kernels (strided, control) | 5/8 | 2.0 | 1.0 | 13.71 | - |
| H100 | reference (control)   | -     | 1.0 | - | - | - |

Weights 12.82 GiB resident in every new row. The H100 peaks include the cached converted
copy of the experts (adapters/_prepared.py). tok/s is sequential single-request eager decode
(capture off: Captured is not fixed on main), so it measures the whole eager forward, not MoE.

Cache (A100, /data/kernel-cache/gpt-oss-20b-a100-triton_kernels): run 1 BUILD, 13 Triton
kernels compiled, manifest 5 entries; run 2 SERVE, 0 compiled / 13 disk hits, manifest check
passed, freeze did not refuse.

## Uncertainties

- H100 triton_kernels_hopper: prompt 3's baseline token sits exactly 8.0 bf16 steps below the
  row max (the gate is <= 8). flashinfer on the same GPU gives 1.0 there. Per-op the Hopper
  path's errors match the strided path's to every digit, but the control runs on the same H100
  put prompt 3 at 0.0 (strided triton_kernels) and the reference at 1.0 worst -- so the 8.0 is
  specific to the swizzled path's e2e numerics (other tile shapes at prefill sizes than the
  bench exercises?). It passes the gate, at the edge; I would not make it the H100 default
  without a wider teacher-forced corpus.
- The baseline was recorded on A100; H100 rows compare across GPUs as well as kernels.
- triton_kernels on sm80 is correct but slow: an untuned path (vLLM uses Marlin on A100). 8
  warps fixes decode; prefill (T=2048) is 2x slower than the dense reference.
- FlashInfer EP via ep_size=2/ep_rank=0 with foreign ids remapped to E: passes the one-GPU EP
  bench cases; not exercised across ranks.
- Captured's recapture-on-epoch-mismatch is unexercised on GPU (Captured's forward/sample
  passthroughs are the rung0 branch, not on main). A rebind while the Zig loop thread is
  replaying would race; a REPL must stop the loop before rebinding.
- Fingerprints hash the thin registered wrapper (`_triton_kernels(*args)`), not the adapter
  module it imports, so editing adapters/moe_*.py does not invalidate a cache entry (same as
  every existing impl that delegates to vendored/). The backend version is in the hash.

## Papercuts

- PyPI `triton-kernels` 0.1.0 is an unrelated project (kernelize-ai). The real one installs from
  git: `triton_kernels @ git+https://github.com/triton-lang/triton.git@v3.7.1#subdirectory=python/triton_kernels`.
- `cache.freeze` used `knobs.runtime.jit_cache_hook`, which triton calls on every in-process miss
  BEFORE the disk-cache lookup: a frozen, fully built cache would still refuse the first call of
  every kernel in a new process. Switched to `knobs.compilation.listener` (reports cache_hit).
- `freeze` chmods the cache tree read-only ON THE MODAL VOLUME, persistently: a later BUILD into
  the same directory fails on permissions. Pick a new deployment dir or chmod it back.
- Background bash is blocked by a hook; long Modal runs go through tmux + Monitor.
- triton_kernels v3.7.1 vs vLLM's "3.8" code: layout factories return the layout (not
  (layout, opts)); Hopper layouts need mx_axis=-2 (vLLM passes 1); PrecisionConfig has no
  b_microblock_size. Each was a failed H100 run.
- flashinfer 0.7.0's full cutlass_fused_moe returns a LIST ([out, ...]) unless min_latency.
- flashinfer needs the `flashinfer-jit-cache` top-level stub for `__version__`, but installing
  it with deps pulls every arch's wheel (~1 GB). Install the stub `--no-deps` + only
  `flashinfer-jit-cache-sm90a`, from https://flashinfer.ai/whl/cu130/ (torch 2.13 is cu130).
- Neither backend is in the uv lock / image: every Modal run pip-installs at runtime (~10 s).
- Reference dequant: a LUT tensor built per call was a host->device copy, which capture
  refuses; e2m1 is now decoded from its bits (slower eager: A100 35 -> 57 ms per layer).
- Modal: uploading the tree happens at sandbox create, so a scratch script must exist in the
  tree until then (I copied ad-hoc scripts in and deleted them after `box.setup`).


## Review (independent subagent over 2298236..HEAD) and what I did

Must fix -- both fixed:
- fingerprints hashed only the thin registered wrapper, so an adapter edit kept a graded
  manifest entry valid. Now `fingerprint` also hashes the fn's own kernels module and every
  `kelpie_models.kernels.*` module the impl imports (one level). Invalidates every existing
  cache once (proved: serving the pre-fix cache refuses).
- FlashInfer returned `out[:, :2880]` of a 2944-wide buffer: non-contiguous, breaking the
  fake's `empty_like` contract and NCCL all_reduce under EP/TP. `.contiguous()`.
Should consider -- done:
- Captured recapture -> assert (above).
- serve's JIT refusal now installed by `point(cache, serve=True)` BEFORE the warm pass (was:
  freeze, after it). The listener is installed once per process.
- Prepared cache keys on the source's `_version` too (in-place weight writes re-convert).
- triton_kernels' global constraint dict is mutated under a lock.
- deepseek_v4_flash's messages pointed at the deleted grouped_mm_mxfp4.
Should consider -- left, recorded:
- no CUDA default for moe (devices.DEFAULTS): triton_kernels / flashinfer are not in the lock,
  and bind's `require` would fail on an image without them. gpt-oss on CUDA therefore runs the
  dense reference unless `kernels={ops.moe: ...}`.
- Prepared entries outlive a rebind away from their impl (freed with the weights).
- a missing kernel at serve time on a frozen (read-only) dir surfaces as Triton's write error
  if the listener cannot fire first (Triton writes before it calls the listener).
- T = 0 and "no token routes to any local expert" untested for the backends (the reference
  handles both; gpt-oss plans always have >= 1 token).
- docs/HANDOFF-spec-decode.md still mentions reset_for_test (historical handoff; not edited).

## Round 2: rebase on rung 0, pinned backends, Marlin on A100, per-arch defaults

### Rebase
Onto main 773b0c8 (rung 0). Conflicts in sdk/{captured,run}.py only. Kept both: `Built` has
`binding` AND rung 0's `drafter_module` / `stepper`; the epoch assert moved from
`Captured.__call__` into `Captured.forward` (rung 0's `__call__` now goes through `forward`).
Zig: 69/69. check_core_loop by hand 4/4, --native 4/4. **--native --replay fails** (`replay`:
`AssertionError: (7, 141, 147)`, counts vary run to run) -- on pristine main 773b0c8 too, and on
7e8d510 / 7b49edf, on this laptop. Not touched; NOTES-rung0 records 16/16 PASS for it.

### Pins (every backend is in the image; no runtime pip)
| backend | pin | how it gets in |
|---|---|---|
| triton_kernels | triton-lang/triton@f797708c0626e5f9840ca5b0a98790e2c7cb09ad (tag v3.7.1), subdir python/triton_kernels | kelpie-http extra `triton-kernels`, git source in [tool.uv.sources], uv.lock |
| flashinfer | flashinfer-python==0.7.0 (PyPI) + flashinfer-jit-cache==0.7.0+cu130 + flashinfer-jit-cache-sm90a==0.7.0+cu130 (https://flashinfer.ai/whl/cu130/, explicit index) | kelpie-http extra `flashinfer`, uv.lock |
| vllm_marlin | vllm==0.29.0 wheel (PyPI, sha256 09d48617fc2be9c6cdcd5db480651ab0d84817b257204f2cc2e3ecbb70bbb635; source v0.29.0 = 98dff2a81d747d1dba01a47f939f48c3526d4206); only _moe_C / _C stable-ABI .so kept, each sha256-checked at load | oci/Dockerfile, $KELPIE_VLLM_MARLIN_DIR |

modal_run exports kelpie-http with both extras and installs the closure `--no-deps` with the
pyproject's extra index.

### Results
A100 per layer (us; graph replay, T=2048 eager): reference 57604 / 57829 / 58022 / 59412 /
83250, triton_kernels 257 / 757 / 1078 / 2148 / 158397, **marlin 110 / 281 / 451 / 753 / 4427**
(T = 1 / 8 / 64 / 256 / 2048). marlin passes all 9 correctness cases (err 0.96..2.44 vs budget
4.4..9.0) and captures (replay == eager, 0.0). Poisoning the caching allocator with NaN / 7.0 /
-1e30 before a call changes nothing (no uninitialized reads).

H100 per layer, same buckets: triton_kernels_hopper 92 / 172 / 263 / 380 / 2581, flashinfer
85 / 212 / 295 / 621 / 4078, marlin 66 / 158 / 239 / 391 / 2265. **Marlin is at least as fast as
the Hopper path on H100 at most sizes**; H100's default stays triton_kernels_hopper as asked.

Drift (prove_moe drift, same token sequences: raw+math, 256 new each, 1929 teacher rows):
| GPU | impl vs reference | argmax agree | worst steps | rows > 1 / 4 / 8 | max abs logit |
|---|---|---:|---:|---|---:|
| H100 | triton_kernels (strided) | 1916 | 2.0 | 1 / 0 / 0 | 7.52 |
| H100 | triton_kernels_hopper | 1916 | 2.0 | 1 / 0 / 0 | 7.52 |
| H100 | flashinfer | 1912 | 9.0 | 2 / 1 / 1 | 7.72 |
| A100 | triton_kernels | 1916 | 1.0 | 0 / 0 / 0 | 8.06 |
| A100 | marlin | 1915 | 9.0 | 3 / 1 / 1 | 5.94 |

The 8.0 Hopper outlier: on H100 the strided and Hopper-swizzled paths give bit-identical logits
(max |diff| 0.0 over 512 rows), and both sit closer to the reference than FlashInfer. The 8.0
is prompt 3's A100-recorded baseline token vs H100 rows (a cross-GPU near-tie); it reproduces
for the Hopper path today. The earlier "strided control put it at 0.0" does not reproduce now
(same numbers expected, since the two are bit-identical); I did not chase that old run.

e2e (prove_moe compare vs the pre-change A100 baseline; weights 12.82 GiB everywhere):
| GPU | moe (default) | mode | tok/s | exact | teacher worst | own decode | peak GiB |
|---|---|---|---:|---:|---:|---:|---:|
| A100 | marlin | capture | 71.6 | 5/8 | 1.0 | 1.0 | 24.01 |
| A100 | marlin | eager | 18.9 | 4/8 | 1.0 | **20.0 (FAIL)** | 23.99 |
| A100 | triton_kernels | eager | 7.3 | 5/8 | 1.0 | 1.0 | 13.67 |
| H100 | triton_kernels_hopper | capture | 70.7 | 5/8 | 8.0 | 8.0 | 24.40 |
| H100 | triton_kernels_hopper | eager | 9.2 | 3/8 | 8.0 | - | 24.40 |

DFlash on H100 (check_spec_teacher_forced --loop native --corpus math --max-new 256, eager):
hopper 38.0 tok/s, accept 4.19, worst 0.0 steps; reference MoE 4.6 tok/s, accept 4.44, worst 2.0.
Both PASS. build refuses drafter + capture (`assert drafter is None or not (captures or
compile)`, run.py:178): not run, not changed.

### The A100 eager 20-step token (why marlin is still the A100 default)
Prompt 3, own decode token 17: eager decode picked 11144 at 14.125 over 279 at 13.938; the
teacher-forced prefill over the same tokens has 279 at 12.94 and 11144 at 11.69. Deterministic
(same on 2 reruns). Decode-vs-prefill logit drift over 64 steps (max |decode - prefill| per
step, prompts 3 and 0): median 0.125 / 0.25 for marlin, 0.125 / 0.22 triton_kernels, 0.125 / 0.20
reference; max 2.8 / 1.2 marlin, 1.1 / 2.0 triton, 0.85 / 3.3 reference. So swings of 2-3 logits
between decode and prefill happen for the reference too; marlin's happened to land on an argmax.
With capture the same prompt matches the baseline exactly. I read it as the near-tie class
at a larger gap than the ad-hoc 8-step gate, not a kernel fault -- but it IS a gate failure,
and marlin is measurably noisier than triton_kernels (drift worst 9 vs 1). vLLM does the same
math (bf16 intermediate, router weight cast to bf16 in the epilogue). Revert = drop the (8, 0)
row in devices.CUDA_ARCH_DEFAULTS.

### Judgement calls
- Backends live in kelpie-http extras (the image's export root), not kelpie-models: the laptop
  lock stays CUDA-free and backends.py's `install kelpie[...]` hint names them.
- flashinfer-jit-cache's other-arch deps removed with `override-dependencies` and a marker
  that cannot hold (`python_version < '3'`); `sys_platform == 'never'` does not work (uv treats
  it as a possible platform in universal resolution).
- cuda-bindings held at 13.3.1 with a constraint: without it, cuda-python (a flashinfer dep)
  moved torch's cuda-bindings to 13.4.1 for every run.
- exclude-newer exemption for flashinfer-python only (published 2026-09-22, inside the 8-day
  window; you named 0.7.0). For vLLM I took 0.29.0 (2026-09-09), not 0.30.0 (2026-09-22),
  to stay outside the window; its Marlin gemm schema differs (g_idx/perm/is_k_full) and the
  glue is ported from the 0.29.0 wheel's own Python.
- Marlin via vLLM's prebuilt stable-ABI .so, loaded with torch.ops.load_library, not a pip
  install (vllm pins flashinfer 0.6.18) and not a JIT build (the image's nvcc is 12.4 vs torch
  cu130). The .so path comes from $KELPIE_VLLM_MARLIN_DIR (Dockerfile ENV), read once at import.
- EP for Marlin: foreign ids = -1; moe_align_block_size and moe_sum both skip them (read in the
  v0.29.0 source). No expert_map.
- Per-arch defaults are keyed by exact capability; A10G/L4/B200 keep the reference MoE.
- Captured: warms only buckets <= bucket(min(max_batch_tokens, max_batch_reqs)). Needed for
  capture=True on gpt-oss at all (the 8192 warm OOMed); outside MoE, small.
- Load-time layout hook: NOT built. It is not contained: the converted tables would replace the
  hub tensors in the op args, which changes the op contract (every impl takes the hub layout;
  bench runs all impls on the same args), needs a `prepare=` on `register`, a way for
  gpt_oss.load to see the bound impl (bind happens before load, but load takes no binding),
  and the Hopper tables are triton_kernels Tensor objects, not torch tensors (the adapter would
  rewrap raw storage). Cost today: H100 hopper peak 24.4 GiB vs 13.7 strided; A100 marlin
  24.0 vs 13.7.

### Uncertainties
- The A100 eager 20-step token above.
- Marlin's topk-weight cast to bf16 is a systematic ~2^-9 relative error per slot (vLLM's own).
- The .so stable-ABI promise across torch patch versions: pinned torch 2.13.0 matches the wheel.
- check_core_loop --native --replay failing on main on this laptop.

### Papercuts
- `uv run` in kelpie-engine silently relocked it (exclude-newer span moved); use `--frozen`.
- Changing oci/Dockerfile re-keys the xgrammar / libkelpie builds (one rebuild on the volume).
- Remote `grep -v USDT` block-buffers, so Monitor sees nothing until a command ends.
- .proof/*.sh still has the old ad-hoc pip lines (local, ignored); nothing runs them now.

### Review (independent subagent over 443c170..HEAD) and what I did
Verified by the reviewer: the Marlin gemm arg order vs the 0.29.0 schema, the fp4 type id, both
.so sha256s, the scale / bias permutes bit-identical to vLLM's code on CPU at gpt-oss sizes, the
-1 skip in align and moe_sum, the strided moe_sum read, padding, the Captured bucket filter (no
off-by-one), the rebase (`Built` keeps drafter_module / stepper; epoch assert in `forward`).
Must-decide -- left as is, flagged:
- A100 default = marlin while its eager own-decode check fails at one token (above).
- bind resolves every op's default, so on an A100 / H100 outside the image every CUDA build
  fails at bind until `kernels={ops.moe: ...}` is named (now said in devices.py).
Fixed:
- a failed dlopen (OSError) now surfaces as the backend being unavailable (ImportError).
- the backend version is `0.29.0+b08ed394.0375f3ec`: the .so digests are in every fingerprint.
- marlin returns early on T = 0 (neither vLLM host function guards an empty launch).
- MIN_ARCH sm80 (bf16 activations), not sm75; router weights made contiguous.
- modal_run keeps the export's hashes: with unsafe-best-match over two indexes, every file must
  still be the locked one.
- check_spec_teacher_forced prints tok/s only for sequential runs; drift refuses --kernels;
  Captured uses `_ffi.bucket`.
Left: the block-size heuristic under EP picks a larger block than vLLM (the op does not know
the global expert count; speed only, now in the docstring).
Re-proved after the fixes (Modal): A100 bench marlin 9/9 + capture ok; A100 compare --capture
71.9 tok/s, 5/8 exact, own 1.0, PASSED; H100 check_serve OK (image rebuilt with hashes).
