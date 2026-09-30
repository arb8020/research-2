# Per-request model state under an Option-2 engine (research, 2026-09-23)

Question: if the Zig core stays ignorant of speculative decoding ("Option 2": the core offers only
`reserve(extra rows this step)` and `commit(req, tokens_emitted)`; the model step owns the 1+K row
layout, drafts and accept rule), how does model-owned per-request state learn about the request's
lifecycle? That state includes recurrent state (GDN/KDA/Mamba SSM state plus conv window) and
drafter state (EAGLE hidden state, draft tokens, DFlash aux states). The lifecycle events are: new
request admitted, slot reuse, preemption, cancel, prefix-cache hit (state at a prefix boundary),
and for recurrent state, **rollback when drafts are rejected**.

Checkouts (under `scratchpad/`):
- vLLM `vllm` @ `0549e8d`
- SGLang `sglang` @ `c3e9852`
- TokenSpeed `ext3/tokenspeed` @ `a657e47` (github.com/lightseekorg/tokenspeed)
- FLA `ext3/fla` @ `954438d`

Subagents read these. The load-bearing claims were spot-checked: the vLLM kernel's
`num_accepted_tokens` read, and kelpie's `keepCandidate` / `slotFor`. Everything else is as the
subagents reported.

---

## TL;DR

1. **None of the three engines gives the model a lifecycle hook.** The model forward sees only
   **indices plus one "has prior context" bit**. Every lifecycle event is turned into index
   choices, or into pre-forward clear/copy work that the runner does before the layers run.
2. They differ in **who resolves rollback and fresh-zeroing, and when**:
   - **vLLM** resolves both *at read time, inside the kernel*.
     - Rollback: a request holds `1+K` state slots; the kernel writes the state after token t to
       column t, and next step reads column `num_accepted_tokens-1`.
     - Fresh-zeroing: the kernel masks the initial state with `num_computed_tokens > 0`.
     - No copies, no zeroing of recycled slots.
   - **SGLang** resolves both *eagerly, in the runner*.
     - Fresh-zeroing: a new slot is `clear_slots()`-zeroed, or COW-copied from the radix cache, on
       the forward stream before the layers run.
     - Rollback: verify writes per-draft states to an `intermediate_ssm_state_cache` scratch; after
       verify, `update_mamba_state_after_mtp_verify` scatters the accepted step back into the slot.
   - **TokenSpeed** keeps recurrent state *as pages in the block table*.
     - Each step gives the model an **in page and an out page**, `in = 0` (the null page) when
       fresh.
     - The scheduler zeroes every newly allocated page (`pages_to_zero`).
     - Rollback: verify writes to scratch rows; `commit_verified_state(accepted)` copies row
       `req*(T+1)+accepted` into the committed page.
3. **Kelpie's core is already most of the way to a TokenSpeed/vLLM hybrid.** Recurrent state is a
   Zig-owned `per_seq` group:
   - rule (c): a prefix hit gives `[checkpoint, fresh live]`;
   - rule (d): `keepCandidate` reserves K+1 candidate units and keeps `first + accepted`.

   What is missing is **telling the model which unit to read and which to write**, and a **fresh
   signal** that is sound. Today the plan points `slot_mapping` at the *live (last)* unit only.
   On a checkpoint crossing, a prefix hit, or a draft step, the state to read is somewhere else,
   and the plan carries no bit saying so.
4. Option 2 and core-owned recurrent state **are compatible**: `keepCandidate` can be restated
   without the word "draft". The rule becomes: a `per_seq` group gets `1+extra` write units for
   the last `1+extra` rows, and `commit(req, n)` keeps the unit written by row `n-1` of that tail.
   That is exactly vLLM's `num_accepted_tokens - 1`, since `n = accepted + 1`. Trees (topk > 1)
   break this. See Uncertainties.

---

## 1. vLLM v1

### State slots are KV blocks of a `MambaSpec` group

- **`MambaSpec`** (`vllm/v1/kv_cache_interface.py:1014`)
  - Fields: `shapes, dtypes, page_size_padded, mamba_type, mamba_cache_mode ∈ {none, align, all},
    num_speculative_blocks, num_prefill_checkpoint_blocks, prefill_checkpoint_alignment,
    block_size`.
  - Built by `MambaBase.get_kv_cache_spec` (`model_executor/layers/mamba/abstract.py:65`) with
    `num_speculative_blocks = num_speculative_tokens`.
  - `block_size = max_model_len` when prefix caching is off, so one block is the whole sequence.
    It is the attention `block_size` when prefix caching is on.
- **Blocks per request**
  - `none`: `1 + K`
  - `align`: `2 + K (+ prefill checkpoints)` resident
  - `all`: one per block boundary `+ K`
- **`MambaManager`** (`v1/core/single_type_kv_cache_manager.py:1445`)
  - `get_num_skipped_tokens = n_computed - 1`: only the last state matters.
  - Align mode frees the block from two steps ago (`remove_skipped_blocks`).
  - Speculative scratch blocks are moved to the end of the row (`_relocate_speculative_block`).
- **Block id → state index**: `mamba_get_block_table_tensor` (`v1/attention/backends/utils.py:1136`).
  In align mode it gathers the last `1+K` blocks at `(seq_lens-1)//block_size`. Each backend then
  slices:
  - GDN (`gdn_attn.py`): `non_spec_state_indices_tensor = table[:, 0]`,
    `spec_state_indices_tensor = table[spec_mask, :K+1]`.
  - Mamba (`mamba_attn.py` `_compute_common_metadata`): `state_indices_tensor_d[:, :1+K]`,
    `state_indices_tensor_p[:, 0]`.
  - Block 0 is the null block, and kernels skip `state_idx <= 0`.

### Fresh / slot reuse: an initial-state mask, never zeroing

- `has_initial_state = num_computed_tokens > 0`:
  - GDN: `gdn_attn.py:425`
  - Mamba: `mamba_attn.py:607`
  - Prefills only; a decode always reads its slot.
- The layer applies the mask itself:
  - GDN (`qwen_gdn_linear_attn.py:~1503`):
    `initial_state = ssm_state[prefill_state_indices]; initial_state[~prefill_has_initial_state] = 0`.
  - Mamba2 (`mamba_mixer2.py:~878`): `torch.where(has_initial_states_p[...], ssm_state[idx], 0)`.
  - Conv: `causal_conv1d_fn(has_initial_state=...)`.
- **Recycled mamba blocks are never zeroed.** `KVBlockZeroer` (`v1/worker/utils.py:~138`) handles
  attention specs only. The stale data is masked out.

### Prefix caching (`mamba_cache_mode`, `vllm/config/cache.py:190`)

- **`align`** is the default with prefix caching and requires chunked prefill.
  - A state is kept only when a step's last token lands on an `i*block_size` boundary, so the
    scheduler aligns chunk ends.
  - `find_longest_cache_hit` scans right to left for the last cached state block that is aligned
    to the lcm with the attention groups.
  - `vllm/v1/worker/mamba_utils.py::preprocess_mamba` runs before the forward. It copies the hit
    block, or the previous step's block when a boundary is crossed, into the current running
    block (`collect_mamba_copy_meta` → `batch_memcpy`).
  - The model supplies the per-state copy functions: `get_mamba_state_copy_funcs`, the **only**
    model-level lifecycle hook in vLLM.
  - Partial-block hits use COW via `kv_cache_block_copies`.
- **`all`** is deprecated. The kernel reads from `block_idx_last_computed_token` and writes to
  `block_idx_last_scheduled_token` directly, with no copy.

### Spec decode: rollback without copying (the key trick)

`fused_recurrent_gated_delta_rule_fwd_kernel`
(`vllm/third_party/flash_linear_attention/ops/fused_recurrent.py:106-160`, verified):

```python
if IS_SPEC_DECODING: i_t = load(num_accepted_tokens + i_n) - 1      # read column
state_idx = load(ssm_state_indices + i_n*stride + i_t); if state_idx <= 0: return
... for each token t: if INPLACE_FINAL_STATE: store state into ssm_state_indices[i_n, t]
```

- Column t holds the state after token t. The next step reads column `num_accepted-1`, so the
  rejected columns are simply never read.
- Conv does the same through `causal_conv1d_update(num_accepted_tokens=...)`.
- `num_accepted_tokens` is computed in `_update_states_after_model_execute` as
  `(output_token_ids != -1).sum(1)` and lives in `input_batch.num_accepted_tokens_cpu`. It is reset
  to 1 for a new row (`gpu_input_batch.py:481`).
- Mamba2 also supports spec decode (`mamba_mixer2.py:540,1015-1060`).
- In align mode, `preprocess_mamba` passes `accept_token_bias = num_accepted - 1` so the copy takes
  the accepted column.

### Preemption, finish, and the persistent batch

- **Preemption**: `_preempt_request` (`v1/core/sched/scheduler.py:1526`) frees the blocks and sets
  `num_computed_tokens = 0`, which forces a recompute. The recompute can hit an aligned mamba
  snapshot.
- **Worker side**: `cleanup_mamba_state_idx` (`mamba_utils.py:1384`).
- **`GPUModelRunner._update_states`** (`gpu_model_runner.py:1192`) handles `finished_req_ids`,
  `scheduled_new_reqs`, `scheduled_cached_reqs.resumed_req_ids`, and
  `unscheduled` (removed from the batch but state kept).
- **None of this reaches the model**, apart from `num_computed_tokens` (which becomes
  has_initial_state), the state indices, and `num_accepted_tokens`. The runner keeps a
  `mamba_state_idx: dict[req_id, int]` (`gpu_model_runner.py:967`).

## 2. SGLang

### Pool and mapping (`srt/mem_cache/memory_pool.py`)

- **`MambaPool`** (line 399)
  - Holds `State(conv, temporal)` with shape `[layers, slots, ...]`.
  - `SpeculativeState` adds `intermediate_ssm` and `intermediate_conv_window`.
  - `clear_slots(indices)` (line 998) must run on the forward stream and uses the fused
    `mamba_slot_fused.fused_clear_conv_slots`.
  - `copy_from(src, dst)` (line 1030).
- **`HybridReqToTokenPool`** (line 1222)
  - `req_index_to_mamba_index_mapping[req_pool_idx] → mamba slot` (line 1380).
  - An optional ping-pong track buffer (1 or 2 slots) holds prefix-cache snapshots.
- **`alloc(reqs)`** (line 1432): allocates one slot and sets `req.kv.mamba_needs_clear = True`.
  A request that already holds a slot (continuing chunked prefill, or COW) keeps it.

### Fresh and prefix-hit are deferred runner ops, not model signals

1. `ScheduleBatch._collect_deferred_mamba_cow_and_clear` (`managers/schedule_batch.py:3074`)
   produces `mamba_clear_indices` and `mamba_cow_src/dst_indices` on the `ForwardBatch`. COW takes
   precedence over clear.
2. `ModelRunner._maybe_execute_deferred_mamba_cow_and_clear` (`model_executor/model_runner.py:1807`)
   runs `clear_slots` / `copy_mamba_state` **before the layers**, in the target forward only.
3. `MultiLayerEagleWorkerV2._apply_deferred_mamba_init_to_draft_pools`
   (`speculative/multi_layer_eagle_worker_v2.py:559`) repeats this for the drafter's own mamba
   pools.

Kernel-level "has initial state":
- GDN (`layers/attention/linear/gdn_backend.py:942`) and KDA (`kda_backend.py:823`):
  `extend_prefix_lens > 0`, but it is passed only to `causal_conv1d_fn`. The chunked delta-rule
  SSM always reads `ssm_states[slot]` and relies on the slot having been zeroed or COW-filled
  (inferred from the call sites).
- Mamba2 (`mamba2_metadata.py:262`; `mamba.py:595`): masks with `torch.where` like vLLM.

### Spec decode (EAGLE/MTP/DFlash/n-gram) with GDN/KDA

- **Verify** writes per-step states into `intermediate_ssm_state_cache [layers, bs+1, T, ...]` and
  conv windows into `intermediate_conv_window`. The persistent slot is not advanced.
- **Commit**: `eagle_worker_common.run_eagle_verify` → `spec_utils.commit_mamba_states_after_verify`
  (line 921) → `_verify_commit_step_indices` computes `last_correct_step_indices` →
  `HybridLinearAttnBackend.update_mamba_state_after_mtp_verify`
  (`hybrid_linear_attn_backend.py:1425`) → `scatter_mamba_states_after_mtp_verify`, a fused
  gather-scatter that also writes the prefix-cache track slot.
- **Trees (topk > 1)** are supported for GDN, and for KDA with the Triton backend. The verify
  kernels take `retrieve_next_token / next_sibling / parent_token`, and the accepted *node* (not a
  row prefix) chooses the step.
- **ReplaySSM variant** (`--enable-linear-replayssm-spec`, KDA `commit_kda_replayssm_after_verify`):
  verify stores only the projections, and the commit replays the accepted prefix into the slot.
  This trades compute for memory, with no `T × state` scratch.

### Prefix caching, preemption, and hooks

- **Prefix caching** (`mem_cache/unified_cache/components/mamba.py`)
  - One slot per radix leaf node. Checkpoints sit on `lcm(mamba_cache_chunk_size, page)`.
  - On match (`finalize_match_result_in_cache`, line 188): allocate a dst slot and set
    `mamba_cow_src_index`. The copy is deferred as above.
  - On insert (`prepare_for_caching_req`): donate the ping-pong slot, or copy active → new.
- **Retract/abort**: `release_kv_cache(..., is_insert=False)` → `free_mamba_cache`, then
  `req.reset_for_retract()` clears the mamba fields. The request recomputes, taking a fresh
  cleared slot or a prefix COW.
- **No model hook.** Qwen3-Next and Kimi call `RadixLinearAttention.forward(forward_batch, ...)`.
  The backend resolves slots through `req_pool_indices`.

## 3. TokenSpeed (github.com/lightseekorg/tokenspeed)

A real engine: C++ scheduler (`tokenspeed-scheduler/csrc`) and Python runtime
(`python/tokenspeed/runtime`). Design docs: `docs/design/{cache-concepts,scheduler,unified_path}.md`.

- **State lives in pages.** Each recurrent layer is an `AttnKind::kMambaState` group whose block
  covers `checkpoint_granularity` tokens. Its pages hold `conv_state` and `recurrent_state` as
  components.
- **The model gets an in/out page pair per request per step.**
  `backends/state/checkpoint.py::compute_state_block_indices`:
  - `in = rows[(before-1)//g]`, or **0 (a reserved always-zero null page) when `before == 0`**.
  - `out = rows[(after-1)//g]`.
  - `in == out` means an in-place update. Crossing a boundary, or resuming from a prefix hit,
    means "read the old page, write a new one", so no copy is ever needed.
  - Decode kernel: `gdn_decode_step(initial_state=ssm_states, initial_state_indices=in,
    output_state_indices=out)`.
- **`kMambaStateWindow = 2`** (`csrc/cache/coordinator/group_geometry.h`, `ExpiredBlocksAt`) keeps
  the read page and the write page alive. It has nothing to do with spec decode or overlap.
- **Fresh and slot reuse.** `Scheduler::admit` (`operations/forward.cpp`) adds every new page to
  `ExecutionPlan::pages_to_zero`, and `DeviceHandle` runs `executor.zero_cache_pages` before the
  next forward. A fresh request reads null page 0 anyway.
- **Prefix caching.** Snapshots are published only at aligned "materialized" boundaries. A prefill
  that ends off a boundary does a body scan plus a tail scan in one forward
  (`_run_prefill_recurrent`), writing both the checkpoint page and the final state.
- **Spec decode.**
  - Verify reads committed state (`_verify_state_blocks`) and writes per-position states to
    scratch rows `max_bs*(T+1)`.
  - `commit_speculative_state_after_verify` → `MambaAttnBackend.commit_verified_state(accepted)`
    copies row `req*(T+1)+accepted` into the committed page.
  - A ReplaySSM mode exists (`gdn_replay_commit`).
  - KV needs no rollback: `NumComputedTokens` advances by the accepted count only.
- **Scheduler → model** (`operations/forward.h`, `ForwardBatch`): request ids, pool indices, input
  lengths, `extend_prefix_lens`, `block_tables[group]`, and `spec_candidate_ids`, plus the plan's
  `pages_to_zero`. There are **no new/finished lists**; the model derives state positions from
  lengths.

## 4. Kernel APIs (FLA and the forks)

**Upstream FLA** (`fla-org/flash-linear-attention` @ `954438d`): **dense state only**. The wrappers
assert `initial_state.shape[0] == len(cu_seqlens)-1`. State is `[N, HV, K, V]`
(`state_v_first=True` gives `[N, HV, V, K]`).

```
chunk_gated_delta_rule(q,k,v,g,beta, scale=None, initial_state=None, output_final_state=False,
    use_qk_l2norm_in_kernel=False, ..., state_v_first=False, cu_seqlens=None, cu_seqlens_cpu=None,
    chunk_indices=None, cp_context=None)
fused_recurrent_gated_delta_rule(q,k,v,g=None,gk=None,gv=None,beta=None, scale=None,
    initial_state=None, output_final_state=False, ..., state_v_first=False, cu_seqlens=None)
chunk_kda(q,k,v,g,beta, ..., initial_state=None, output_final_state=False, ...,
    return_intermediate_states=False, state_v_first=False, cu_seqlens=None, ...)
fused_recurrent_kda(q,k,v,g,beta, A_log=None, dt_bias=None, ..., initial_state=None,
    output_final_state=False, ..., cu_seqlens=None)
causal_conv1d(x, weight=None, bias=None, residual=None, initial_state=None,
    output_final_state=False, activation=None, backend='triton', cu_seqlens=None, ...)  # state [N,D,W]
```

(Internally, `fused_recurrent_kda_fwd` already has vLLM-style `ssm_state_indices,
num_accepted_tokens, inplace_final_state`; the public API does not expose them.)

**The forks add indexed pools.** These arguments are what shape the ideal kelpie plan fields.

| engine | recurrent-kernel state args | spec rollback arg |
|---|---|---|
| vLLM | `ssm_state_indices [N] or [N,T]`, `inplace_final_state=True` | `num_accepted_tokens [N]` (read col `n-1`) |
| vLLM conv | `conv_state_indices`, `has_initial_state`, `query_start_loc` | `num_accepted_tokens` |
| SGLang | `initial_state_source, initial_state_indices`, `disable_state_update` | `intermediate_states_buffer, intermediate_state_indices, cache_steps, retrieve_parent_token` |
| SGLang chunk | `initial_state, initial_state_indices, inplace_update=True` | n/a |
| TokenSpeed decode | `initial_state_indices=in, output_state_indices=out` | scratch rows + commit copy |

Consequence for kelpie: upstream FLA forces a gather → dense → scatter step in torch
(`index_select` / `index_copy_`). That is fine for the reference kernel. A fast path wants an
`(in_idx[N], out_idx[N, T])` kernel shape, which is TokenSpeed's decode kernel generalised to T
rows. vLLM's `[N, 1+K]` plus `num_accepted_tokens` is a close second, but it puts the "which unit
is live" decision into the kernel instead of the core.

## 5. Kelpie today

### What the model sees

- **Loop**: `Engine.plan() -> Plan | None` (`kelpie-engine/kelpie_engine/sdk/engine.py:333`),
  `Engine.commit(sampled: u32[n_reqs])` (:341), `has_work()` (:247).
  - The trampoline in `start_loop` (:~292) takes exactly one token per request.
  - `kelpie_commit_payload` (`kelpie.h:239`) can carry `n_tokens` / drafts, but no Python caller
    uses it.
- **Plan** (`sdk/plan.py`):
  - `Tokens{input_ids, positions, slot_mapping[g], row_request}`
  - `Requests{req_ids, query_start_loc, seq_lens, block_tables[g], kinds, n_drafts}`
  - `Sampling`, `mm_hashes`
  - `KelpieConfig.n_draft` = K, one per engine.
- **Model call**: `Step.forward` (`kelpie-models/kelpie_models/sdk/step.py:93`) →
  `model.forward(weights, config, tokens, requests, kv, taps)`. `kv` is mutated in place.
  - The device-side `Requests` has **no req_ids, no stable slot index, no n_computed, no fresh flag**.
  - `Step.attach/detach(request_id, payload)` already exists, for multimodal payloads only.
    Attach happens at submit; detach at the poll that observes finish, or at cancel.

### Recurrent state is already a core-owned `per_seq` group (StateRing deleted)

- **Spec**: `sdk/groups.py:94` `Recurrent(state, n_snapshots, checkpoint_every=S)` →
  `CacheSpec("per_seq", S, nbytes, All() if S==0 else Window(2+K), ...)`. The arena is one flat
  byte tensor with strided views `[pages, block, *unit]` (`sdk/kv.py:125-139`); page 0 is null.
- **Core rules** (`kelpie-core/src/scheduler.zig`):
  - (b) `slotFor` (:1036): every row's `slot_mapping[g]` points at the **live unit
    `ids[n-1]`**.
  - Checkpoints: `rowsFor` (`request.zig:147`) gives `min(1 + n/S + K, 2+K)` units; `slideOut`
    frees the oldest.
  - (c) `claimPrefix` (:716): the table becomes `[checkpoint (shared, read-only), fresh live]`.
  - (d) `keepCandidate` (:927, verified): the last `n_drafts+1` rows are candidates, "candidate j
    holds the state after accepting j drafts". Commit keeps `first+accepted`, frees the rest, and
    **copies nothing**. This is the vLLM column trick, resolved at commit time by the core instead
    of at read time by the kernel.
  - Preemption (`request.zig:255`): `n_computed = 0`, all tables freed, full re-prefill.

### How a model learns a slot was reused: it infers it

- Nothing zeroes recycled pages; the arena is zeroed only at startup.
- The convention (`docs/cache-groups-ladder.md:186-189`) is that ops derive "fresh" from
  `seq_len == n_work`, i.e. `seq_lens[r] - (qsl[r+1]-qsl[r]) == 0`. This is vLLM's
  `num_computed_tokens > 0`, stated implicitly.

### Gaps (from reading traces and code, not run)

- **Checkpoint crossing.** `traces/per_seq_state_checkpoint.txt`: after a 16-token prompt, the
  decode has table `[3,5]`. `slot_mapping` points at the never-written unit 5, while the state
  lives in unit 3 (row n-2), and the plan carries no bit saying "read row n-2".
- **Prefix hit.** Same problem: the live unit is fresh, and the resume state is row 0.
- **Prefill crossing a boundary.** `insertSeq` (`prefix.zig:225-246`) publishes row n-2 as the
  checkpoint, but a model that writes only `slot_mapping` never writes it.
- **Drafts.** `slot_mapping` points at the last candidate. Candidate j is found only through
  `block_tables[g][r][n-1-K+j]`.
- **Models.**
  - `models/unported/qwen3_next.py` raises at import and still assumes StateRing (:36-51).
    Its `Recurrent` has `S=0`.
  - `models/torch/kimi_linear.py` is all `NotImplementedError`.
- **Checks.** `sdk/checks/recurrent_batching.py` checks only batched == single on fresh zeroed
  pages, plus rule (b). It does not cover reuse, chunking, boundaries, prefix hits or drafts
  (listed as "Owed" in `slab-lcm-ladder.md:138-149`).
- **Stale docs.**
  - `model-contract.md`, `README.md:29` and `roadmap.md:91` still describe StateRing.
  - `decisions.md:20,38` point at the old `groups.py` path.
  - `slab-lcm-ladder.md:116-136` says K has no path in, but `KelpieConfig.n_draft` exists.
  - `n_snapshots` is not used by the core (window = 2+K) and `check_groups` does not compare it.

---

## 6. Program design: lifecycle signalling for an Option-2 engine

### The Option-2 contract, restated so `per_seq` groups fit without the core knowing about drafts

```
core API (unchanged in spirit)
  plan() -> Plan
  reserve(req, extra_rows)                 # before plan; model/driver decides K per req
  commit(req, tokens: u32[n_emitted])      # n_emitted >= 1

group semantics under reserve/commit (the only per_seq addition)
  per_token group : extra rows = extra slots, as today; commit advances n_computed by n_emitted
  per_seq group   : a step with R rows and `extra` reserved gets
                      read  unit  : the unit holding state after the last committed token
                                    (0 = null/zero when context_start == 0)
                      write units : 1 + extra, one per tail row j in [R-1-extra, R-1]
                    commit(n_emitted) keeps write unit (n_emitted - 1), frees the others
                    (== keepCandidate, renamed: "row", not "draft")
```

"Keep the unit written by row `n_emitted-1` of the tail" does not depend on why the model processed
extra rows. The same rule covers a non-spec lookahead, or jump-forward decoding under a grammar.
That is the Option-2 property.

### Shared types (what the plan must carry, whichever design)

```python
@dataclass(frozen=True)
class Requests:                       # existing, plus:
    slot: u32[R]                      # NEW stable per-admission index (req_pool_idx / persistent row)
    context_start: u32[R]             # NEW = seq_lens - n_rows; 0 => fresh (vLLM has_initial_state)
    n_reserved: u32[R]                # NEW = extra rows this step (0 when plain decode/prefill)

@dataclass(frozen=True)
class StateIdx:                       # per per_seq group g
    read:  u32[R]                     # unit to read; NULL_ZERO when fresh
    write: u32[R, 1 + Kmax]           # units to write, tail-aligned; 0 = don't write (pad)
    ckpt:  u32[R]                     # unit to also write at an S-boundary inside this chunk; 0 = none
    ckpt_row: u32[R]                  # row index (within the request) whose post-state goes to ckpt
```

Recurrent layer, with kernel shape `(in_idx[N], out_idx[N,T])`:

```python
def gdn_layer(x, plan, kv_g):
    st = plan.state[g]
    y = gdn_kernel(q, k, v, g_, beta,
                   state_pool=kv_g.temporal, conv_pool=kv_g.conv,
                   in_idx=st.read,                       # zero state when == NULL_ZERO
                   out_idx=st.write,                     # per-tail-row write
                   ckpt_idx=st.ckpt, ckpt_row=st.ckpt_row,
                   cu_seqlens=plan.requests.query_start_loc)
```

### Candidate A: flags and indices in the plan, stateless model (≈ vLLM, index-level ≈ TokenSpeed)

- **The plan carries**: `context_start` (fresh ⇔ 0), `StateIdx` per `per_seq` group, and `slot`.
- **Fresh and slot reuse.** Either the kernel reads `NULL_ZERO` or masks with
  `context_start > 0`. Stale recycled pages are harmless.
- **Prefix hit.** `read` = the shared checkpoint unit and `write` = a fresh unit. No copy
  (TokenSpeed); vLLM align mode copies instead.
- **Preempt, cancel.** Nothing to do; the core frees units. After re-admission, `context_start`
  is 0 or a prefix-hit read unit.
- **Spec rollback.** Core-side keep-one-of-(1+K) at commit (kelpie rule d). The model writes one
  unit per tail row.
- **Drafter state.**
  - Tensor state (EAGLE last hidden, DFlash aux hidden, draft-model conv/SSM) **is declared as
    more `per_seq` groups** and inherits the same lifecycle for free.
  - Host-only state (n-gram index, Python dicts) keys on `(slot, generation)`, where
    `generation` = a u32 that changes on each admission. `context_start == 0` also works as the
    reset trigger.

```
usage loop (A)
while engine.has_work():
  plan = engine.plan()
+   # plan.requests.{slot, context_start, n_reserved}, plan.state[g].{read, write, ckpt}
  out = step(plan)                                   # model: forward over 1+K rows, accept rule
+   #   gdn layers read state[g].read, write state[g].write[:, j] per tail row
+   #   drafter reads its own per_seq group the same way
  for r, toks in out.emitted():                      # toks = accepted drafts + bonus
    engine.commit(r, toks)                           # core: per_seq keeps write[n-1]
  for r in out.next_k(): engine.reserve(r, k_r)      # next step's extra rows
```

### Candidate B: explicit event stream plus runner pre-ops (≈ SGLang, TokenSpeed `pages_to_zero`)

- **The plan carries** a per-step `events` list and pre-forward ops:

  ```python
  Event = Admitted(req, slot, prefix_len, cow_src: unit|None)
        | Released(req, slot, why: finish|cancel|preempt)
  plan.pre_ops = PreOps(zero: u32[], copy_src: u32[], copy_dst: u32[])   # per per_seq group
  ```

- **Fresh.** `Step` runs `zero(units)` before the forward (SGLang `clear_slots`, TokenSpeed
  `zero_cache_pages`), so kernels can always read `state[read]` without a mask.
- **Prefix hit.** `copy(ckpt → live)` (SGLang COW, vLLM `preprocess_mamba`), then the same single
  live unit.
- **Spec rollback.** Either the core-side keep-one (as in A), or SGLang style: scratch
  `intermediate[bs, T]` plus a model-side scatter after the accept rule. The scatter is fully
  model-owned, so the core needs no `write[R, 1+K]`, only one live unit per request. That is the
  most Option-2-pure shape, but it adds a post-verify kernel and a `T × state` scratch.
- **Drafter state.** Handled by the events: `Step.attach/detach` generalised
  (`on_admit(req, slot)`, `on_release(req, slot)`). This has kelpie precedent in the multimodal
  attach/detach.
- **Cost.**
  - The pre-ops run outside CUDA graphs. SGLang skips them for draft/verify modes and runs them on
    the forward stream.
  - Two sources of truth for "what is live" (events plus indices).

```
usage loop (B)
while engine.has_work():
  plan = engine.plan()
+   for ev in plan.events: step.on_event(ev)      # drafter dicts, host state
+   step.apply_pre_ops(plan.pre_ops)              # zero fresh units, COW prefix hits
  out = step(plan)                                # kernels read/write the single live unit
+   #   if spec: intermediate states -> scratch; step.scatter_accepted(out.accepted)
  for r, toks in out.emitted(): engine.commit(r, toks)
```

### Candidate C: all model per-request state is core-owned units with read/write/ckpt roles (TokenSpeed-pure, kelpie's current direction taken to its end)

- A with no host-side escape hatch. **Every** per-request model state, recurrent or drafter, is a
  `per_seq` (or per_token, for a draft KV) group declared in `attn_specs`.
- The core also owns an always-zero `NULL_ZERO` unit, distinct from the pad-scratch block 0.
- The core zeroes nothing and copies nothing. Fresh reads NULL_ZERO. A prefix hit reads the
  checkpoint. A spec step writes `1+extra` units, and commit keeps one.
- The model gets no events and no dicts. Idempotent replay and CUDA graphs come for free, because
  the step is a pure function of (plan, pools).
- **Leftovers.** Host-side drafters (n-gram, suffix trees) do not fit; they need a
  `generation`-keyed cache (A's escape hatch) or events (B). Tree drafts need `commit` to name a
  row, not a count.

### Mapping

| lifecycle event | vLLM | SGLang | TokenSpeed | A | B | C |
|---|---|---|---|---|---|---|
| fresh / reuse | mask `n_computed>0` | `clear_slots` pre-op | `pages_to_zero` + read null page | `read=NULL_ZERO` / mask | `zero` pre-op | `read=NULL_ZERO` |
| prefix hit | copy hit→running (`preprocess_mamba`) | COW pre-op | read ckpt page, write new | read ckpt, write new | copy pre-op | read ckpt, write new |
| boundary crossing | copy prev→curr block | ping-pong track slot | in≠out pages | read n-2, write n-1 | copy pre-op | read/write units |
| spec rollback | kernel reads col `acc-1` next step | scratch + scatter after verify | scratch + copy at commit | core keeps `write[n-1]` | scatter (model) or core keep | core keeps `write[n-1]` |
| preempt / cancel | free, recompute | free, reset_for_retract | free pages | free; no model action | `Released` event | free |
| model hook | `get_mamba_state_copy_funcs` only | none | none | none | on_event | none |

### Call tree for one spec step under A/C (Qwen3-Next GDN + MTP drafter)

```
driver loop
  engine.plan()
~   core.planStep                                # per_seq: read unit, 1+extra write units, ckpt
+     fill Requests.{slot, context_start, n_reserved}, StateIdx[g]
  step(plan)
    Step.forward
      model.forward(weights, cfg, tokens, requests, kv, taps)
        for layer:
          full-attn: slot_mapping / block_tables   (unchanged)
+         gdn:       gdn_kernel(in=read, out=write[:, j], ckpt)
+     drafter.forward(hidden_tail, drafter_groups)  # its own per_seq/per_token groups
    accept rule (model-owned)                     # -> emitted tokens per req, next K per req
  engine.commit(req, emitted)
~   core.commit                                  # per_token: n_computed += n; per_seq: keep write[n-1]
+ engine.reserve(req, k_next)
```

---

## 7. Uncertainties

- **Trees (topk > 1).** "Keep write unit `n-1`" assumes the accepted path is a prefix of the rows.
  For trees, the survivor is an arbitrary node (SGLang `last_correct_step_indices`), so `commit`
  would need `commit(req, tokens, keep_row)`. That is still spec-agnostic ("keep the state written
  by row j"), but the per_token KV also needs compaction, and Option 2 does not address that yet.
- **vLLM `none`-mode non-spec decode after a spec step.** It was not confirmed how column
  `acc-1` becomes column 0 when a request decodes without drafts. It is probably avoided because
  every spec-enabled decode is a spec row.
- **SGLang GDN chunked prefill.** It may ignore `has_initial_state` for the SSM path and rely
  purely on `clear_slots`. This was inferred from the call sites; not every backend (flashinfer,
  cutedsl, helion) was read.
- **TokenSpeed.** Its kernel signatures (`gdn_decode_step`, `gdn_decode_mtp`) and hybrid-drafter
  state handling were not read.
- **Kelpie `n_snapshots` vs `Window(2+K)`.** It is unclear which one is meant to size the ring.
- **Memory cost of `write[R, 1+K]` units vs scratch.** Core-owned write units cost
  `(1+K) × state_bytes` per request from the pool. SGLang/TokenSpeed scratch costs
  `max_bs × T × state_bytes` outside the pool. With Qwen3-Next's ~ fp32 `[H, 128, 128]` per layer
  times 36 GDN layers, K=3 roughly quadruples recurrent residency. This was not computed exactly.
- **Chunked prefill crossing an S boundary.** Needs `ckpt`/`ckpt_row` (TokenSpeed body+tail scan).
  The alternative is to make `chunkFor` end chunks on S boundaries (vLLM align mode), so only the
  final state is ever written. Both are viable; they trade kernel complexity against scheduler
  constraints.

## 8. Papercuts

- **Block 0 is not guaranteed zero.** Kelpie points pad rows at a scratch slot inside block 0
  (`kv.py::write_kv`), so "fresh reads the null page" is unsafe unless recurrent kernels skip
  writes for idx 0 (vLLM does: `state_idx <= 0 → return`) or there is a separate NULL_ZERO unit.
- **The commit path cannot carry drafts.** The Python trampoline can only commit one token per
  request, so `kelpie_commit_payload` needs wiring before any of this is testable end to end.
- **The model cannot key host-side per-request state today.** The device-side `Requests` has no
  `req_ids` or slot, and `Host.req_ids` has a TODO to delete it.
- **Tree layout moved in both engines.** vLLM's FLA moved to `vllm/third_party/flash_linear_attention/`,
  and SGLang's kernels moved to `python/sglang/kernels/ops/attention/fla/`. Sparse-checkout paths
  from older kelpie docs are stale.
- **`chunkFor` looks only at group 0** (`scheduler.zig:810`) to decide `per_seq` chunking. A hybrid
  model's group order matters.
