# Cache groups across the model ladder

Sources: HF `config.json` for the seven models (fetched 2026-09-02); SGLang `mem_cache/{deepseek_v4_memory_pool,deepseek_v4_compress_state,memory_pool}.py`, `configs/mamba_utils.py`; vLLM `v1/kv_cache_interface.py` (`SlidingWindowSpec`, `CircularBufferSpec`, `MambaSpec`), `v1/core/{single_type_kv_cache_manager,kv_cache_coordinator}.py`. Builds on `kv-groups.md`; sizes are bf16, TP=1, no spec unless stated.

## Declaration (Python, model side)

```python
class FullAttn(heads, dim)                         # KV per token, forever
class SlidingAttn(heads, dim, window)              # KV per token, last W matter
class MLA(latent, rope, indexer: IndexerSpec | None | Shared)
class CSA(ratio, window, indexer)                  # DSV4 compressed sparse: stride-ratio KV + window ring + compress-state ring
class HCA(ratio)                                   # DSV4 ratio-128 layer (no indexer)
class Recurrent(state: dict[name, (shape, dtype)], n_snapshots=1)
class NoCache

@dataclass(frozen=True)
class CacheSpec:
    kind: per_token | per_seq
    stride: int                    # per_token: tokens per unit (1, 4, 128); per_seq: checkpoint interval (0 = never)
    bytes_per_unit: int            # or (heads, dim, dtype) sugar; one unit = one stride's worth for ONE layer
    retention: all | window(W) | inplace   # W in tokens
    n_snapshots: int = 1           # per_seq only
    cacheable: bool = True         # False: never enters the prefix index (DSV4 SWA ring)

def caches(spec, max_spec_tokens=0) -> list[CacheSpec]
def derive_groups(layers) -> (groups, layer_caches)
```

`derive_groups` keys a group by `(kind, stride, retention, n_snapshots, cacheable)` only; `bytes_per_unit` is *not* part of the key. Caches with the same key share one block table; a group's `bytes_per_block = block_size * sum(member.bytes_per_unit)` and every member gets a distinct `offset` (its slice of the block). This is what lets an MLA latent (1152 B) and its indexer K (132 B) ride one table, and lets a draft/MTP layer join the target's group. vLLM merges only identical specs; TokenSpeed keys on `group_id` and sums layers the same way we do.

Retention semantics on a per_token group: `all` grows; `window(W)` frees rows whose last token is `< n_computed - W` (vLLM `get_num_skipped_tokens`); `inplace` is the per_seq ring (`n_snapshots` blobs, round-robin). A per_seq group with `stride=S>0, retention=all` is the "checkpoint every S tokens" mode (vLLM `mamba_cache_mode=all`) and is really just per_token@S with a state-sized unit; kept as per_seq so `blocksFor` stays honest.

## Per-model specs and groups

Block size 16 (units per block). "blocks/4k" = a 4096-token request in steady-state decode with `in_flight=1`; a transient prefill of one 4096-token chunk holds `blocksFor(4096)` for window groups too.

**gpt2** (12 x FullAttn(12,64)). Group F: per_token s1 3072 B/tok/layer, all, 12 layers, 256 blocks/4k.

**Qwen3-0.6B** (28 x FullAttn(8,128)). Group F: per_token s1 4096 B, all, 28 layers, 256 blocks/4k.

**gpt-oss-20b** (even layers SlidingAttn(8,64,128), odd FullAttn(8,64)).

| group | kind | stride | unit | retention | layers | blocks/4k |
|---|---|---|---|---|---|---|
| F | per_token | 1 | 2048 B | all | 12 | 256 |
| W128 | per_token | 1 | 2048 B | window 128 | 12 | ceil((127+1)/16)+1 = 9 |

**Qwen3-Next-80B** (48 layers; every 4th FullAttn(2,256), 36 Recurrent GDN; +1 MTP layer, assumed FullAttn(2,256) shape — config carries no MTP field).

| group | kind | stride | unit | retention | layers | blocks/4k |
|---|---|---|---|---|---|---|
| F | per_token | 1 | 2048 B | all | 12 (+1 MTP at offset 12) | 256 |
| R | per_seq | 0 | temporal (32,128,128) f32 2,097,152 B + conv (3,8192) bf16 49,152 B = 2,146,304 B | inplace, n_snapshots 1 (2 with prefix "align") | 36 | 1 (2) |

**GLM-5.2** (78 x MLA(512,64, indexer=full on layers {0,1,2,6,10,...,74} = 21, Shared on 57); +1 NextN MLA layer, indexer Shared).

| group | kind | stride | unit | retention | layers | blocks/4k |
|---|---|---|---|---|---|---|
| F | per_token | 1 | latent 1152 B x79 members + indexer 132 B x21 members | all | 79 layers, 100 member caches | 256 |

One group: 79 latents and 21 indexer Ks share one table; `layer_caches[6] = [(F, 6), (F, 79+3)]`.

**Kimi-K3** (93 layers: 69 Recurrent KDA, 24 MLA(512,64, indexer None); no MTP; vision encoder NoCache).

| group | kind | stride | unit | retention | layers | blocks/4k |
|---|---|---|---|---|---|---|
| F | per_token | 1 | 1152 B | all | 24 | 256 |
| R | per_seq | 0 | temporal (96,128,128) f32 6,291,456 B + conv (3, 36864) bf16 221,184 B = 6,512,640 B | inplace, 1 | 69 | 1 |

R costs 449 MB per sequence; one snapshot for prefix caching doubles it. This is the case that decides whether snapshots are per-seq blobs or checkpoints at a coarse stride.

**DeepSeek-V4-Flash** (44 entries in `compress_ratios`: layers 0,1 ratio 0; 2..41 alternate 4/128; 42 ratio 4; entry 43 = NextN draft, ratio 0). Every layer, draft included, has a 128-token SWA ring at 584 B/tok. Spec adds `max_spec_tokens` to the ring and doubles the compress-state rings (8->16, 128->256).

| group | kind | stride | unit | retention | layers | blocks/4k |
|---|---|---|---|---|---|---|
| W128 | per_token | 1 | 584 B, cacheable=false | window 128 | 44 | 9 (vLLM/SGLang: 1 ring block of 128(+spec) rows per request) |
| C4 | per_token | 4 | KV 584 B x21 + indexer K 132 B x21 | all | 21 layers, 42 members | 1024/16 = 64 |
| C128 | per_token | 128 | 584 B | all | 20 | 32/16 = 2 |
| S4 | per_seq | 0 | ring 8 (16 spec) x KVAndScore, ~2304 B/row guessed | inplace, 1 | 21 | 1 |
| S128 | per_seq | 0 | ring 128 (256 spec) x ~2304 B | inplace, 1 | 20 | 1 |

Unit validity for a stride-k group is `n_computed // k`; entry `j` is written when token `k*j + k-1` is computed (SGLang `translate_loc_from_full_to_compressed`).

## Q1. Coverage

`{per_token@stride, per_seq x n_snapshots, retention all|window|inplace}` covers all seven with two additions:

1. **`cacheable=false`** on a window group. DSV4's SWA ring is a per-request ring in both engines (vLLM `CircularBufferSpec.prefix_cacheable=False`); modelling it as `window(128)` reuses gpt-oss machinery, but the prefix matcher must then treat it as "last W tokens always recomputed" rather than "last W must be present". Without the bit, every DSV4 prefix hit is 0.
2. **Spec-dependent unit size**: `caches(spec, max_spec_tokens)`; DSV4 rings and vLLM `SlidingWindowSpec.extra_retained_tokens` are functions of lookahead. Not a new field, a parameter.

Not needed: separate `HCA`/`CSA` kinds in the core (they lower to C4/C128 + S4/S128 + W128), a "draft" kind (MTP joins the target group as another member; verify rewrites its slots), or an indexer kind (a member with 132 B). `Recurrent` with `retention=all, stride=S` is per_token@S; the taxonomy is closed under it.

## Q2. Multi-cache layers

`layer_caches: list[list[(group, offset)]]` suffices, because `offset` names a *member*, not a layer. Layers with two caches in the same group exist in every sparse model: GLM-5.2 full-indexer layers `[(F, i), (F, 79+j)]`, DSV4 ratio-4 layers `[(W128, i), (C4, 2j), (C4, 2j+1), (S4, j)]`. No ambiguity as long as `derive_groups` assigns offsets in `(layer, cache-order-within-caches(spec))` order and the kernel plan reads them positionally: the model never looks up "my group" — it receives `(table, offset)` pairs in declaration order. The only trap is byte packing: member offsets are in bytes-of-block, so two 584 B members and one 132 B member in C4 make `bytes_per_block = 16*(21*584+21*132)`. A per_seq group with `n_snapshots>1` is the one place offset alone is insufficient: the snapshot index is `n_computed // stride % n_snapshots`, computed by the core, not by the layer.

## Q3. Prefix caching per group

Per group `g`, `hit_g(t)` for candidate boundary `t` (tokens), with `u = stride*block_size` the group's token grain:

| kind / retention | hit rule |
|---|---|
| per_token, all | prefix-closed: scan left to right; hit = first miss, floored to `u` |
| per_token, window(W), cacheable | boundary `t` resumable iff blocks covering `[t-W, t)` are all present: `ceil((W-1)/block)` contiguous blocks ending at `t`; scan right to left (vLLM `SlidingWindowManager`, TokenSpeed `SwaMatcher`) |
| per_token, window(W), not cacheable | `hit_g(t) = t - W` floored to `u`; the last W tokens are always recomputed |
| per_token, stride k | as `all` but hashes keyed by unit index; grain `u = k*block` (2048 for C128) |
| per_seq, inplace, n_snapshots | a snapshot at `t` (multiple of `stride`) hits exactly `t`; scan right to left for the newest cached snapshot |
| per_seq, stride 0 | never hits (recompute) |

Overall: `hit = fixpoint(min_g hit_g(hit))` starting from the closed groups (full, stride-k) and iterating the non-closed ones (window, per_seq) until nothing shrinks, then floor to `lcm_g(u_g)`. vLLM's `HybridKVCacheCoordinator` does exactly this loop with an eagle margin; TokenSpeed orders closed groups first (`match_order_`) and runs each matcher once, which is the same fixpoint when there is at most one non-closed group but can over-estimate with two (an SWA and a per_seq group can each invalidate the other's answer). Kelpie should keep vLLM's loop; it terminates in `<= n_groups` rounds because each round is monotone.

Alignment: for DSV4 the lcm is `128*16 = 2048` tokens. The way out is per-group `block_size` so that `stride*block_size` is equal across per_token groups (C128 at block 1, C4 at block 32, W128 at 128), which is pad-to-max territory; decide per `kv-groups.md` open question.

## Q4. Admission block need

`n_end = n_computed + n_work` (this chunk), `n_max = n_computed + n_work + max_new` (worst case), `u = stride*block`:

```
all:      need_g = ceil(n_max / u)                       (reserve up front; vLLM reserves per chunk, TokenSpeed reserves max)
window:   need_g = min(ceil(n_max / u), ceil((W - 1 + n_work + spec) / block) + 1)
inplace:  need_g = n_snapshots (+1 if prefix-caching "align": copy-then-free; vLLM 2 + num_speculative_blocks)
per_seq stride S, all:   need_g = ceil(n_max / S) + spec_blocks
slabs   = sum_g ceil((need_g - held_g) / blocks_per_slab_g)
```

`held_g` is the request's current table length minus holes; a window group's slid-out blocks are freed *before* computing need (vLLM `remove_skipped_blocks` runs first), so decode steady-state need is ~0.

## Q5. Zig core vs Python

The core owns tables, admission, and hit lengths; it must know shape and lifetime, never dtype or layout. Python owns `caches(spec)`, byte packing and `offset`s. Proposed `request.zig`:

```zig
pub const Retention = union(enum) { all, window: u32, inplace };
pub const GroupSpec = struct {
    kind: GroupKind,          // per_token | per_seq
    stride: u32,              // per_token: tokens per unit; per_seq: checkpoint interval, 0 = none
    block_size: u32,          // units per block
    retention: Retention,
    n_snapshots: u32 = 1,     // per_seq
    cacheable: bool = true,
    bytes_per_block: u32,     // for the slab pool only; sum over members, opaque
};
pub fn tokensPerBlock(g) u32 { return g.stride * g.block_size; }
pub fn blocksFor(g, n_tokens) u32   // switch on kind+retention per Q4
```

Stays in Python: member list and offsets, dtypes, `KVAndScore` ring layout, indexer sharing, TP sharding of units. Crossing the C ABI: one `tables[g].ids` per group as today, plus for per_seq groups the current snapshot index.

## Guesses

Qwen3-Next MTP layer shape (assumed one full-attention layer); DSV4 compress-state row bytes (~2304 B, read as kv+score of 576 bf16 each, not verified against `c_plan.cuh`); DSV4 indexer only on ratio-4 layers (SGLang sizes the indexer pool by `c4_logical_size`); GLM-5.2 NextN layer treated as MLA with Shared indexer (`index_share_for_mtp_iteration=true`); K3 conv width `3*(proj + 2*proj_k)` from `KimiLinearStateShape.create`.

## As built (wave1/groups)

`kelpie_models/groups.py` implements the declaration above; `tests/test_groups.py` encodes the seven specs
by hand and asserts these tables. Two places where the mechanical rule and the tables above disagree, rule
kept:

- **DSV4 S4 and S128 merge.** Both were `per_seq, stride 0, inplace, n_snapshots 1`; bytes are not in
  the key, so they were one per-seq group with 41 members of two sizes. DSV4 had four groups, not five.
  **Reversed 2026-09-10** (step 5 of docs/brief-slab-pool-recurrent.md): the compressor rings are now
  per_seq groups at `stride = ratio`, so their checkpoints line up with the C-group boundaries. Stride
  is part of the group key, so S4 (stride 4) and S128 (stride 128) no longer merge and DSV4 derives
  five groups after all.
- **Offsets are layer-major.** Q2 says offsets go in `(layer, cache order within the layer)` order, and that
  is what `derive_groups` does; the GLM-5.2 example `layer_caches[6] = [(F, 6), (F, 79+3)]` is cache-major
  and would give `[(F, 9), (F, 10)]` under the rule. Same group, same table; only the offset differs.

Core side (`request.zig`, `scheduler.zig`): a window group's table keeps its logical rows; rows below
`firstLiveRow = (n_computed - W + 1) / block_size` are freed at plan time and read 0 (vLLM
`SlidingWindowManager`). Admission need is `rowsFor(n_end) - table.n` summed over groups (a window
group's own frees pay for its own growth only: traces `two_groups_*.txt`); the decode reserve per group is
`blocksFor(reserve_tokens)`, capped for a window group at `ceil((W-1)/block)+1`. Window groups publish
nothing into the prefix index yet (their hit rule is 0 on main), so a model with a window group gets no
prefix hits: the Q3 windowed matcher is the next step.

### Qwen3-Next as built (derisk/qwen3next)

`Recurrent` now lowers to **no cache at all** (`caches(Recurrent) == []`), so Qwen3-Next and Kimi-K3
derive to one core group (the full-attention F) instead of the F + R tables above; the R row's
bytes are `Recurrent.nbytes`, allocated by `kelpie_models.state.alloc_state_ring` as one
`[max_requests, R, *shape]` tensor per (layer, blob) and indexed by the plan's `req_ids` (request
ids are slot indices, request.zig). DSV4's compress rings (CSA/HCA) now live in the same ring
(see below). Consequences that fell out, none of them a core change:

- `StepBatch.req_ids` (kelpie_models.batch) is now part of the model contract for models with
  recurrent layers; the ops derive "fresh request" from `seq_len == n_work` (context start 0):
  first chunk, re-prefill after preemption, reused slot -- all start from a zero state without a
  signal from the core. Chunked prefill continues from the slot (conv tail + S).
- `prefix_cache` must be off for such a model (`bridge.bind` asserts it; kelpie-http sets it from
  `bridge.has_recurrent_state`). The core cannot apply the Q3 rule "per_seq stride 0 never hits" to
  a group it does not know about, and a hit would resume a request at a boundary for which no
  recurrent state exists. Prefix caching of recurrent state (snapshots, R > 1) is the deferred
  follow-up, and needs either a core-visible per_seq group or a hit-length hook.
- The MTP layer is another `FullAttn` member of F (offset n_layers), loaded from the hub's
  `mtp.*` weights when present; the config carries no field, so `n_mtp` is decided by the loader.

## As built (derisk/dsv4): stride groups and DeepSeek-V4

`GroupSpec.stride` (request.zig, default 1) is in: `tokensPerBlock = stride * block_size`,
`rowsFor = ceil(ceil(n / stride) / block_size)`, the slot of a token names its unit `pos / stride`
(scheduler.zig slotFor), the prefix chain hashes `tokensPerBlock` tokens per block and the overall
hit is floored to the lcm of the groups' grains (claimPrefix `hitGrain`; DSV4: 2048). Crosses the
C ABI as an appended `group_strides` array (NULL = all 1); `kelpie.GroupSpec.stride`; the
reference scheduler carries it (`Group.stride`, `hit_grain`) and the differential test runs half
its streams with a stride-4 second group. Traces: `stride_group_growth`, `stride_two_groups_admission`,
`stride_prefix_shared`, `window_nocache_no_prefix`. Nothing beyond `stride` was needed in the core.

DeepSeek-V4 (`kelpie_models/unported/deepseek_v4.py`, rolled config, HF fp64 oracle, `tests/test_deepseek_v4.py`)
lowers to **three** groups, not the table's five: W128 (window, not cacheable), C4 (stride 4: KV +
indexer K members of different widths on one packed table, the same `kv.alloc_kv_groups` packed
layout dsv32 uses for latent + indexer K), C128. The S4/S128 compress rings are per-request state
in the one `StateRing` Qwen3-Next's GDN blobs live in (`groups.state_specs`, `state.ring_rows`): the last
`2 * ratio` (CSA: previous window's Ca slice + open window) or `ratio` (HCA) tokens' raw
(kv | gate) projections, indexed by absolute position mod R, keyed by request id. They carry a
window across any chunk boundary (tested at 130/137/138/199 and 3/257 and 255 tokens: chunked ==
one-shot to 4e-7), so the scheduler owes them nothing: chunks stay block-aligned, never
ratio-aligned. The forward takes the ring as `state`, exactly as Qwen3-Next does (`runner.forward_kwargs`).

Two corrections to Q3 above, found by building it:

- **`window(W, cacheable=False)` must hit 0, not `t - W`.** Recomputing the last W tokens from an
  empty ring does not reproduce their hidden states: the query at the resume point needs the W
  keys before it, which need their own W, and so on. Only a cached window (vLLM
  `SlidingWindowManager`) or a full recompute is exact. The core's 0 is kept; for DSV4 the
  overall hit is therefore 0 even though the stride groups match (`window_nocache_no_prefix.txt`,
  `kelpie-py/tests/test_dsv4_groups.py`).
- **CSA's overlap makes a stride-4 boundary non-resumable on its own.** Entry `j` reads the raw
  rows of window `j - 1` (Ca), so resuming at `h = 4j` needs tokens `[h - 4, h)` in the ring,
  which a prefix hit never provides. If DSV4 prefix caching is ever wanted, the contract change
  is: the chunk after a hit at `h` starts at `h - ratio` with those `ratio` tokens ring-fill only
  (their compressed unit is already cached and must not be re-emitted), which needs the plan to
  carry the hit boundary per request. Today `state.ring_rows` asserts the ring is contiguous
  from 0 (`test_ring_rejects_a_resume_it_never_saw`).

Not modelled: the NextN/MTP draft layer (HF drops `mtp.*`), the runner/bridge wiring for the
rings, TP sharding of packed members. Indexer top-k ties (scores exactly 0 after ReLU) can
differ from HF's `topk` order; not observed with `index_topk=2` on the rolled config.
