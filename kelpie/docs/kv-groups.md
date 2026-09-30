# KV cache groups: one slab pool, many cache types

Sources: TokenSpeed `docs/design/cache-concepts.md`, `csrc/cache/coordinator/*`, `csrc/cache/core/block_pool.h`, `kv_cache/recipes/plan.py::pack`; vLLM `vllm/v1/kv_cache_interface.py`, `vllm/v1/core/{kv_cache_utils,kv_cache_coordinator,single_type_kv_cache_manager}.py`; Jenga (arXiv 2503.18292); SGLang `srt/mem_cache/{memory_pool,swa_memory_pool}.py`.

## The problem

`request.zig` assumes one block = `block_size` tokens of full-attention KV for every layer. Real models mix cache *types*: full attention (grows forever), sliding-window attention (only the last W tokens matter), Mamba/GDN/KDA recurrent state (one fixed-size blob per sequence, not per token), and a speculative draft model with its own smaller KV. Each type has a different bytes-per-token and a different lifetime, so a separate pool per type means static partitioning: one pool starves while another sits idle (Jenga measures up to 79.6% waste). Jenga's answer, adopted by vLLM v1 and TokenSpeed, is one pool of fixed-size units whose size is the LCM of the per-type unit sizes, with each type ("cache group") carving its own smaller pages out of a unit. Prefix caching then has to reconcile hit lengths across groups, because "cached" means something different for each.

## The slab model

One pool of `n_slabs` units of `slab_bytes`. Each group `g` declares what one of *its* blocks costs and how many tokens it covers:

```
Group = struct {
    kind:            enum { full, sliding_window, recurrent },
    layers:          []u32,       // model layers sharing this block table
    bytes_per_block: u32,         // all layers of g, one block
    tokens_per_block:u32,         // full/SWA: block_size; recurrent: checkpoint interval
    window:          u32,         // SWA only
    blocks_per_slab: u32 = slab_bytes / bytes_per_block,
};
```

Two ways to pick `slab_bytes`:

- **LCM (Jenga, TokenSpeed `pack`)**: `slab_bytes = lcm(bytes_per_block[g])`; `blocks_per_slab[g] = slab_bytes / bytes_per_block[g]`. Zero padding, but the LCM can blow up (TokenSpeed caps it and rejects if any group's padding fraction > `max_padding_fraction=0.25`, `plan.py:843-860`).
- **Pad to max (vLLM `unify_kv_cache_spec_page_size`)**: every group's page is inflated to `max(page_size_bytes)`, either by raising the group's `block_size` when the ratio is integral (SWA with half the heads gets 2x tokens per block) or by literally padding the page (`page_size_padded`, used for Mamba whose page does not scale with tokens). Simpler: `blocks_per_slab == 1` for every group, one free list. Cost: memory padding, and a bigger `block_size` for the small-page group coarsens its prefix-cache grain.

TokenSpeed's pool tracks, per slab, `bound_group` + an occupancy bitmap (`block_pool.h: struct LcmBlock`). A slab is bound to one group at a time; allocation fills the most-occupied partial slab first, then takes empty slabs (`planLocations`). Capacity in slabs for a demand of `pages[g]` is `sum_g ceil(pages[g] / blocks_per_slab[g])` (`LcmBlocksNeededFor`). Kelpie's pool would be the same: `free_slabs` stack + `slab_owner[g]` partial lists.

## What the request's block table becomes

One array per group, each in that group's block ids. Row `i` of group `g` covers tokens `[i*tokens_per_block[g], (i+1)*tokens_per_block[g])`; a null id (0) means "no storage here" (slid out, or a skipped Mamba checkpoint). TokenSpeed keeps absolute slot positions and punches holes rather than compacting (`cache-concepts.md` "Logical width does not imply dense physical residency").

```
Request = struct {
    ...
    n_computed: u32,                       // unchanged: one cursor for all groups
    tables: [max_groups]BlockTable,        // one per group, index = group id
};
BlockTable = struct {
    ids: []u32,      // capacity = blocksFor(g, max_seq_len); 0 = null
    n_blocks: u32,   // logical rows in use (including holes)
};
```

The model call receives `tables[g].ids` for each `g`; a layer looks up its group. `n_computed` stays one number per request: all groups advance together.

## What the scheduler needs per group

At **admission** (prompt of `n` tokens, worst case `n + max_new`):

```
slabs_needed = 0
for g in groups:
    blocks = switch g.kind {
        full      => blocksFor(g, n + reserve),
        swa       => min(blocksFor(g, n + reserve), ceil((W - 1 + in_flight) / tpb) + 1),  // vLLM SlidingWindowSpec.max_admission_blocks_per_request
        recurrent => 1 (+1 snapshot for overlap/spec; TokenSpeed kMambaStateWindow = 2),
    }
    slabs_needed += ceil(blocks / g.blocks_per_slab)
```

At **decode** (each step, `n_computed` moves by 1):

- full: new block when `n_computed % tpb == 0`. Never frees.
- SWA: same growth, but blocks `[0, (n_computed - W + 1) / tpb)` have fully slid out and are freed and nulled (vLLM `SlidingWindowManager.get_num_skipped_tokens`, TokenSpeed `GroupGeometry.ExpiredBlocksAt`). Steady state holds `ceil(W/tpb)+1` blocks; the freed block usually pays for the new one, so net demand is ~0.
- recurrent: the state is updated in place; nothing grows. vLLM keeps "the state of the last token only" (`MambaManager.get_num_skipped_tokens = n - 1`); with prefix caching ("align" mode) it allocates a new block every `tpb` tokens, copies state into it, and frees the one from two steps ago. (SGLang: a ping-pong pair per request, `HybridReqToTokenPool`.)
- draft-model KV: just another full-attention group with smaller `bytes_per_block`; `n_computed` for it lags the target by the unverified draft tokens.

Preemption frees every group's table.

## Prefix caching across groups

Each group publishes `(hash of tokens[0..k*tpb], group_id) -> block` (vLLM `BlockHashWithGroupId`, TokenSpeed `CacheKey{group_id, content_hash, page_offset}`). What counts as a hit differs:

- full: prefix-closed. Scan left to right until the first miss; every block up to there is a hit.
- SWA: not closed. A boundary at token `t` is resumable iff the `ceil((W-1)/tpb)` blocks *ending* at `t` are all cached; scan right to left for such a run (vLLM `SlidingWindowManager.find_longest_cache_hit`, TokenSpeed `SwaMatcher`). Blocks before the run are null.
- recurrent: a single checkpoint block at boundary `t` is a hit for prefix length `t`; scan right to left for the last one (vLLM `MambaManager.find_longest_cache_hit`). Jenga caches "every 512 tokens".

The combined hit length is a fixed point: start with the full-attention hit, then let each other group shorten it until nobody shrinks (vLLM `HybridKVCacheCoordinator.find_longest_cache_hit`; TokenSpeed orders closed groups first, `match_order_`). Consequence: a Mamba group with checkpoints every 512 tokens caps the whole hit at a multiple of 512, and an SWA group can turn a 10k-token full-attention hit into 0 if the window just before 10k was evicted. Both engines align cacheable length to the coarsest group's block.

## What kelpie should do now (GPT-2, one group)

Do not build the coordinator. Make the shape such that adding a second group is additive:

1. `Config.block_size` becomes `groups: []GroupConfig` with one entry (`kind=full, tokens_per_block, bytes_per_block`). `blocksFor` takes the group.
2. `Request.block_table` becomes `tables: [max_groups]BlockTable` with `max_groups` a comptime constant (say 4); only `tables[0]` is used. `n_blocks` moves into `BlockTable`.
3. The KV pool hands out slab ids, and a group maps `block id -> (slab id, slot)`; with `blocks_per_slab == 1` this is the identity, which is what GPT-2 gets.
4. Pass `tables[g].ids` per group across the Python boundary (`core-api.md` forward-pass args) so the FFI does not change later.
5. Keep block id 0 reserved as null now, so holes are representable later. **Block 0 is null**: `kv_pool.Pool.init(num_blocks)` never puts id 0 on the free list (`nFree == num_blocks - 1`, `num_blocks >= 2`), so no request ever owns it. The same `num_blocks` crosses the C ABI unchanged; the model allocates `[num_blocks]` and points pad slots (slot -1) at a scratch slot inside block 0 (`kelpie_models/kv.py::write_kv`). Nothing reads block 0.

The scheduler still calls `blocksFor(groups[0], n)`.

## Open questions

- LCM vs pad-to-max: TokenSpeed pays complexity for zero padding; vLLM accepts padding. For the models kelpie targets (Gemma-style 5:1 SWA:full, Qwen3-Next GDN+full), what is the actual LCM and padding fraction? Compute before choosing.
- Should SWA reuse the freed block for the new one in the same step (TokenSpeed "slide credit") to avoid transient over-allocation?
- Recurrent checkpoint interval for prefix caching: fixed (512) or equal to the full-attention block? Tied to the fixed-point hit length.
- Is a per-slab `bound_group` (TokenSpeed) needed, or is `blocks_per_slab == 1` everywhere (vLLM) good enough for v1? The latter keeps one free list and one refcount owner (design rule 5).
- Draft-model group: does its `n_computed` need its own cursor, or does the spec-decode verify step keep it in lockstep?
