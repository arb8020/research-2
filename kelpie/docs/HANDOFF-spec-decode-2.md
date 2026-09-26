# Spec Decode Handoff 2 — 2026-09-21

## What we did

### 1. Drafter gets its own KV pool via combined engine groups
**Files:** `kv.py`, `run.py`, `engine.py` (unchanged)

The drafter's KV cache group is appended to the target's groups. The engine sees
all groups (2 target + 1 drafter = 3), Zig manages pages for all of them from one
slab pool. `derive_groups` runs separately per model (so identical FullAttn specs
don't merge), then `choose_block_sizes` runs over the concatenated list.

- `alloc_kv` gains `group_slice` param to allocate from a subset of `cfg.groups`
- `_assemble` returns `n_target_groups` so `build` can split allocations
- Slab plan tiles cleanly — all three groups have page size 196608, padding 0.0

### 2. Real `_drafter_inputs` — 1+K rows per request
**File:** `step.py`

Builds the drafter's Tokens/Requests view from the target plan:
- 1+K rows per request: accepted token + K mask tokens
- Positions: `ctx, ctx+1, ..., ctx+K`
- Slot mappings computed from drafter block_table: `slot = bt[r, pos // bs] * bs + pos % bs`
- Context positions/slot_mapping for inject: map THIS STEP's target tokens into drafter cache slots (not full 0..ctx-1 — taps only cover this step)
- Taps sliced to `n_tokens` real entries in `inject_context_kv` (was using `n_tokens_padded`)

### 3. Target forward produces [R, 1+K, V] logits
**File:** `gpt_oss.py`

When `max_k > 0` (drafts active), the forward gathers all 1+K rows per request
using `query_start_loc` and produces logits at each position. K=0 path unchanged
(takes `last_rows` only → `[R, 1, V]`).

### 4. Yarn RoPE on drafter
**File:** `dflash.py`

Added `rope_factor/beta_fast/beta_slow/original_max/truncate` to `DFlashConfig`.
Both inject and forward call `yarn_rope_tables` instead of `rope_tables`. Config
parsed from HF checkpoint's `rope_scaling` dict.

### 5. Draft logits argmax fix
**File:** `step.py`

`draft_logits` is `[R*(1+K), vocab]`. Argmax over vocab dim first, then reshape
to `[R, 1+K]` and take columns `1..K` (skip position 0 = accepted token).

### 6. Target forward group slicing
**File:** `step.py`

When drafter groups are appended, `Step.forward` slices `requests.block_tables`
and `requests.slot_mapping` to only the target's groups before calling the model.

### 7. Zig core: store proposed drafts in seq.tokens
**File:** `kelpie-core/src/scheduler.zig`

`commitEntry` now stores proposed draft tokens past the committed history:
```zig
for (drafts, 0..) |draft, j| {
    req.seq.tokens[req.seq.n + j] = draft;
}
```
Without advancing `seq.n` (speculative, not committed). The next plan's
`emitEntry` reads `seq.tokens[n_computed..n_computed + n_work]` to fill
`input_ids` — draft positions now have actual token ids.

**NOT YET VERIFIED ON GPU** — the Zig rebuild on the box failed due to cache
staleness. Needs `rm -rf .zig-cache zig-out && scripts/zig build lib`.

### 8. Wide event observability
**Files:** `run.py` (SDK + launcher), `step.py`, `verify_and_prove.py`, `observe/`

Spans via `observe.span()` at every phase:
- `box.image_build`, `box.create`, `box.setup`, `box.run` (launcher)
- `build`, `assemble` (SDK — checkpoint, device, groups, slab geometry)
- `spec_decode_step` (K, R, step, n_tokens, max_n_drafts, qsl, mean_accepted)

Console + JSONL sinks via `setup_logging`. Noop fallback when `observe` not installed.

### 9. Streaming box output + iteration fixes
**Files:** `box/providers/modal.py`, `examples/gpt-oss-20b-dflash/run.py`

- `box.exec(stream=True)` prints stdout line-by-line
- Fresh path and reuse path both stream
- `engine._step` attached for `prove_dflash` access

## What's blocking prove_dflash green

### Zig rebuild verification (the next session's first task)

The `commitEntry` draft storage change (item 7) compiles but hasn't been tested
on GPU. The box's Zig cache was stale — `rm -rf .zig-cache zig-out` + rebuild
needed. Once rebuilt:

1. Step 5 should have `n_tokens=8, qsl=[0, 8]` (1+7 draft rows)
2. `verify_sample` should find draft token ids in `input_ids[1..8]`
3. The verification loop should accept/reject drafts and continue

### Other issues that may surface after Zig fix lands

- **`prove_dflash` cleanup:** daemon thread crash leaves model in GPU memory.
  Need `pkill -9` between runs. Should add proper error propagation + cleanup.
- **`observe` not in image:** `observe/` is outside `KELPIE_DIR`. Either vendor
  it into kelpie or add to Dockerfile mounts.
- **MASK_TOKEN_ID = 0:** needs verification against checkpoint's actual mask token.
- **Per-request loop in gpt_oss [R, 1+K, V]:** the K>0 path uses a Python loop
  over requests. Fine for vertical slice, needs vectorization for production.
- **Context slot mapping CPU loops:** `_drafter_inputs` computes slots with Python
  loops. Needs a kernel for production batch sizes.

## Files changed

```
kelpie-models/kelpie_models/sdk/
    kv.py                 # group_slice param on alloc_kv
    run.py                # combined groups, _assemble returns n_target_groups,
                          #   build passes drafter slice + block_sizes,
                          #   engine._step attachment, spans
    step.py               # real _drafter_inputs, target group slicing in forward,
                          #   spec_decode_step with proper logit/draft handling, spans

kelpie-models/kelpie_models/models/torch/
    gpt_oss.py            # [R, 1+K, V] logits when max_k > 0
    dflash.py             # yarn RoPE (config + 2 call sites), taps slicing

kelpie-core/src/
    scheduler.zig         # commitEntry stores proposed drafts in seq.tokens

kelpie-engine/kelpie_engine/sdk/
    (engine.py unchanged — GroupSpec import added to run.py)

box/
    providers/modal.py    # stream=True on exec
    provider.py           # stream param on abstract exec

examples/gpt-oss-20b-dflash/
    run.py                # observe spans, streaming, setup_logging

scripts/
    verify_and_prove.py   # setup_logging call
```

## Box state

Last active box: sb-89u36j3WjnqMgFg5nP5nfs (may have timed out)
- Setup done, models downloaded, venvs ready
- libkelpie.so is STALE (pre-Zig-fix). Needs rebuild.
- `observe/` uploaded to `/workspace/observe/`
- PYTHONPATH needs `/workspace` for observe

## Iteration notes

- Box timeout is the main pain point. Boxes die after ~2h idle.
- Model load is 8-11s per build (cached weights on volume).
- `prove_dflash` loads the model TWICE (baseline + spec-decode). Could cache
  baseline tokens to skip the first load.
- No live streaming from Modal during image build / setup. Spans help but only
  emit at span close.
- GPU memory leaks from crashed daemon threads. Need `pkill -9 -f python` before
  each run, or proper error propagation in the spec-decode loop thread.
