# Spec Decode Handoff — 2026-09-21

## What we did

### 1. Paged attention OOM fix
**File:** `kelpie-models/kelpie_models/kernels/ops/paged_attention.py`

The reference paged_attention kernel gathered the entire block_table (`O(T × max_seq_len)`)
regardless of actual sequence occupancy. For gpt-oss-20b with 128k max_seq_len, the
intermediate tensor was ~256 GiB.

**Fix:** Slice block_table to `ceil(seq_lens.max() / block_size)` columns before the gather.
Guarded by `torch.cuda.is_current_stream_capturing()` — during CUDA graph capture, falls
back to full gather (capture forbids data-dependent shapes / host syncs).

**Verified on A100:** All 6 test cases pass, including the `sparse_occupancy` probe that
reproduces the original OOM (block_table 64 columns wide, seq_lens [5, 3]).

### 2. Kernel verification system
**Files:** `verify.py` (new), `op.py` (modified), `paged_attention.py` (test_cases added)

Two-level correctness checking at bind() time:
- **BLOCK:** impl vs reference at native dtype, dtype-aware atol/rtol (crucible's DTYPE_FLOORS)
- **WARN:** impl at native dtype vs reference at fp64, error budget comparison

Features:
- Cache by fingerprint + device + torch_version (`~/.cache/kelpie/verify/`)
- Probes (cheap, early-exit on failure) + graded cases (production shapes)
- 3 seeds per case (catches nondeterminism)
- `bind(..., verify=False)` escape hatch for dev
- Caught a real issue: rope[triton] at bf16 exceeded atol=1e-3 — fixed by making
  tolerances dtype-aware (bf16 floor = 2e-2)

**TODO roadmap** (in verify.py docstring):
1. jaxtyping annotations → auto-generated test grids (popcorn-style)
2. Per-op tolerance functions
3. Region-aware per-call dispatch (FlashInfer for decode, Triton for prefill)
4. Unified JIT + verification cache
5. test_cases on every op (not just paged_attention)
6. PAD_POISON in probes
7. Multi-dtype sweep

### 3. DFlash drafter architecture fix
**File:** `kelpie-models/kelpie_models/models/torch/dflash.py` (rewritten)

The original dflash.py was written speculatively. The actual z-lab/gpt-oss-20b-DFlash
checkpoint has a different architecture:

| | Old (speculative) | New (matches checkpoint) |
|---|---|---|
| Tap combination | `mean(taps)` | `concat(taps, dim=-1)` → `fc` Linear |
| Context K/V | Fused `inject.fused_kv` GEMM | Per-layer `layer.k_proj`/`v_proj` |
| Inject weights | `model.inject.hidden_norm/fused_kv/k_norm` | `fc.weight`, `hidden_norm.weight` (no `model.` prefix) |
| Attention biases | None | q/k/v/o biases (optional, loaded via `t_opt`) |
| Config | `target_layer_ids` at top level | Nested under `dflash_config` |

Weight loading now matches the actual checkpoint keys (verified by inspecting safetensors
on A100).

### 4. Iteration speed improvements
**Files:** `run.py` (rewritten), `box/setup.py` (patched), `box/provider.py` + `box/providers/modal.py`

- `--keep-alive` / `--box-id sb-XXXX` — reuse a running box instead of terminate+recreate
- `--list` — list active boxes (via `Provider.list()` / `Provider.from_id()`)
- `TRITON_CACHE_DIR=/data/triton-cache` — persist Triton JIT cache on volume
- Fixed setup fingerprint: `build_libkelpie` and `build_cuda_launch` were inlined, bypassing
  existence checks. Now call the functions that skip if artifacts exist.
- File upload path for code iteration: `box.upload()` to push changed files to a live box

### 5. Engine wiring fixes
- `Capacity.max_seq_len` wired through `EngineConfig.from_model` (was declared but unused)
- `prove_dflash.py` passes `Capacity(max_seq_len=512)` and `capture=False`
- Pinned CPU staging buffers for CUDA graph capture (`captured.py`, `device.py`)
- `reset_for_test()` between baseline and spec-decode runs in prove_dflash
- Taps sorted after set union (`run.py` line 153)

## What's blocking prove_dflash green

### Drafter engine wiring (the next session's work)

The drafter needs its own KV cache, but `alloc_kv` on line 163 of `run.py` tries to
allocate it from the target engine's config (which has 2 attention groups — windowed + full).
The drafter has 1 group (all full attention). This assertion fails:

```
alloc_kv(drafter_specs, engine.live_config(), device, torch_dtype)
# AssertionError: (1, 2)  — drafter has 1 group, engine has 2
```

**Design questions to resolve:**
1. Does the drafter get its own engine (its own Zig core, its own block_table, its own
   slot_mapping)? Or does it share the target engine's slab pool with its own group?
2. How do `_drafter_inputs` work? The drafter needs its own `Tokens`/`Requests` view
   (1+K rows per request, draft positions). Currently stubbed (`step.py:237`).
3. How do context slot_mappings work? The inject writes target taps into drafter KV cache
   positions — where do those positions come from? The target engine assigns slots, but
   the drafter's cache has different pages/block_size.

**What vllm/tokenspeed do:** The drafter gets its own KV pool. The engine allocates drafter
pages alongside target pages. Context positions in the drafter's cache are assigned by the
scheduler (the drafter "sees" the context as if they were regular tokens in its own cache).

### Other spec decode TODOs
- `step.py:192` — proper context position alignment for drafter
- `step.py:237` — `_drafter_inputs` needs its own view (1+K rows, draft positions)
- `run.py:255` — warm pass per bucket shape
- `run.py:468` — proper lifecycle (stop signal, error propagation)
- `prove_dflash.py` — `greedy_decode_with_spec` loop (lines 118-143) is speculative;
  needs to match actual engine step API
- Rope scaling (yarn) — checkpoint uses `rope_type: yarn` with factor 32, not handled

## Files changed (uncommitted on m4/spec-decode)

```
kelpie-models/kelpie_models/kernels/
    ops/paged_attention.py    # OOM fix + test_cases
    op.py                     # verify gate in bind(), test_cases decorator
    verify.py                 # NEW — correctness verification system

kelpie-models/kelpie_models/models/torch/
    dflash.py                 # rewritten — matches upstream checkpoint

kelpie-models/kelpie_models/sdk/
    device.py                 # pinned staging buffers
    step.py                   # pinned kwarg passthrough
    captured.py               # pinned alloc + passthrough
    run.py                    # Capacity.max_seq_len, sorted taps, drafter load

kelpie-engine/kelpie_engine/sdk/
    engine.py                 # max_seq_len param on from_model

box/
    provider.py               # BoxInfo, Provider.list(), Provider.from_id()
    providers/modal.py        # Modal.list(), Modal.from_id()
    setup.py                  # fingerprint fix (call functions, don't inline)

examples/gpt-oss-20b-dflash/
    run.py                    # --keep-alive/--box-id/--list, TRITON_CACHE_DIR

scripts/
    prove_dflash.py           # capacity, capture, reset_for_test, new_tokens
    verify_and_prove.py       # NEW — runs verification then prove_dflash
```

## Research references

- **vllm/sglang:** paged_attention kernels iterate only occupied blocks via `seq_lens[seq_idx]`
- **tokenspeed:** `numerics/` module — per-family tolerances, structured generators, `verify_kernel()`
- **popcorn (tilde-research):** Regions (validity sets), jaxtyping → covering arrays, fp64 ground truth, per-call dispatch
- **crucible:** Three-tier spec (Callable/Checked/Timed), BudgetTolerance with DTYPE_FLOORS, probes+graded cases, PAD_POISON
- All four: paged-cache inject strategy for DFlash (pre-compute context K/V, write into paged cache, drafter sees through normal paged attention)
