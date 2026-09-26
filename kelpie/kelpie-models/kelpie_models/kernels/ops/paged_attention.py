"""kelpie::paged_attention -- paged causal GQA over one cache-group member, one layer.

KV LAYOUT, stated here once and nowhere else (the op contract owns it). A layer's cache member
is `[pages, 2, block, Hkv, D]`: K and V are two members of that unit, each a contiguous
`[pages, block, Hkv, D]` view (`member[:, 0]` and `member[:, 1]`). This is the FlashInfer/vLLM
standard layout. `groups.py:reference_kv_layout` and `sdk/kv.py` allocate to this shape, and an
adapter either reads it or refuses via its `predicate`. There is no bind-time layout property:
one layout, stated by the contract.

PLAN METADATA is the core's one canonical form -- dense `block_table[R, P]`, `seq_lens[R]`,
`query_start_loc[R+1]`, `slot_mapping[T]`. An adapter that wants something else (FlashInfer's
CSR indptr/indices/last_page_len) derives it inside the adapter. No backend-shaped field enters
the plan until a real adapter measures the conversion cost.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from kelpie_models.kernels.op import mutates, op

KV_MEMBERS = 2


def kv_views(kv_member: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """The member `[pages, 2, block, Hkv, D]` as its two members K and V, each
    `[pages * block, Hkv, D]` contiguous in the page/slot dimension."""
    pages, two, block, heads, dim = kv_member.shape
    assert two == KV_MEMBERS, kv_member.shape
    # [:, 0] and [:, 1] select K and V; each is [pages, block, heads, dim],
    # then reshape to [pages * block, heads, dim] for flat-slot indexing.
    k, v = (kv_member[:, i].reshape(pages * block, heads, dim) for i in range(KV_MEMBERS))
    # reshape silently COPIES when (pages, block) cannot merge -- e.g. a contiguous
    # [pages, 2, block, H, D] tensor, or a page with padding past its last row -- and then every
    # write_kv lands in a temporary. The engine's arena views (K,V interleaved per row, pages
    # tiled exactly) merge; anything else must fail loudly here.
    assert k.untyped_storage().data_ptr() == kv_member.untyped_storage().data_ptr(), (
        "kv member layout does not flatten to a view", kv_member.shape, kv_member.stride())
    return k, v


def write_kv(
    kv_member: torch.Tensor, k: torch.Tensor, v: torch.Tensor, slot_mapping: torch.Tensor
) -> None:
    """Scatter k, v [T, Hkv, D] into the member at flat slots. Pad rows already point at the
    scratch slot, so this is one fixed-shape index_copy_ per member: no masking, no host sync."""
    flat_k, flat_v = kv_views(kv_member)
    assert k.shape[1:] == flat_k.shape[1:], (k.shape, flat_k.shape)
    slots = slot_mapping.long()
    flat_k.index_copy_(0, slots, k.to(kv_member.dtype))
    flat_v.index_copy_(0, slots, v.to(kv_member.dtype))


# The reference's working set per chunk of rows: each row's K and V gathered over the entry's
# occupied slots and upcast to the compute dtype, torch.einsum's permuted copies of both, and the
# scores. Bounding it is what keeps the ORACLE runnable: build's warm pass runs a 1024-row
# prefill, and one [T, slots, H, D] fp32 tensor there was ~23 GiB (NOTES-attn.md).
CHUNK_BYTES = 256 * 2**20
# Bytes per (row, slot) of that working set, in units of the compute dtype's itemsize: K and V
# upcast (2) + einsum's contiguous copies of both (2), per kv head x D; scores, masked scores
# and probs (3) per q head.
CHUNK_KV_COPIES, CHUNK_SCORE_COPIES = 4, 3


@op
@mutates("kv_member")
def paged_attention(  # noqa: PLR0913, PLR0917
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    kv_member: torch.Tensor,
    row_request: torch.Tensor,
    positions: torch.Tensor,
    query_start_loc: torch.Tensor,
    seq_lens: torch.Tensor,
    block_table: torch.Tensor,
    slot_mapping: torch.Tensor,
    window: int,
    sinks: torch.Tensor,
    causal: bool = True,
) -> torch.Tensor:
    """q [T, H, D], k/v [T, Hkv, D] for this step's rows; `kv_member`
    [pages, 2, block, Hkv, D] is the layer's cache, written in place at `slot_mapping`.

    THE PLAN IS READ ON DEVICE. `row_request` i32[T] gives each padded row its entry (-1 = a
    pad row), `positions` i32[T] its absolute position, `seq_lens` i32[R] each entry's context
    length and `block_table` i32[R, P] its pages. There is no `n_reqs` and no host loop over
    requests. One exception, eager only: the gathered width is the batch's max occupancy
    (`seq_lens.max()`, a host sync) and the row-chunk count follows from it, so the eager
    reference is NOT one traced graph per shape. Captured calls use the whole table width.
    TODO(2026-09-25): an XLA-traced reference needs a static width (the table's) and a memory
    bound that does not depend on data.

    `query_start_loc` i32[R+1] is the same partition as `row_request`, in the form every real
    kernel grids over (vLLM's cu_seqlens_q, FlashInfer's qo_indptr): entry r owns rows
    [qsl[r], qsl[r+1]), entries in order, pad entries empty at the tail (padPlan writes both
    from one loop). The reference computes from `row_request` and `positions`. A kernel that
    reads qsl derives each row's position as `seq_lens[r] - rows_r + i` (an entry's rows are its
    newest positions, which is what a plan is); the reference ASSERTS that on device, so a plan
    breaking it fails wherever the reference runs.

    window > 0: query at position p sees keys [p - window + 1, p] only. `sinks` f32[H] adds one
    per-head logit inside the softmax that is then dropped (gpt-oss's attention sinks); pass an
    empty tensor for a model without them. causal=False (the DFlash drafter): every row sees
    its entry's whole context. -> out [T, H * D]; pad rows zero.

    Computed in fp32 (fp64 for fp64 inputs, the bench's truth), over bounded chunks of rows."""
    write_kv(kv_member, k, v, slot_mapping)
    flat_k, flat_v = kv_views(kv_member)
    block_size = kv_member.shape[2]  # [pages, 2, block, Hkv, D]
    n_tokens, n_heads, head_dim = q.shape
    n_kv = k.shape[1]
    compute = torch.promote_types(q.dtype, torch.float32)

    live = row_request >= 0
    rows = row_request.clamp(min=0).long()  # a pad row borrows entry 0 and is masked out below
    # Gather only the columns some entry occupies: O(max occupancy), not O(max_seq_len). The
    # bound is a host sync (seq_lens.max()), which capture forbids; a captured call gathers
    # the whole table instead (captured plans are decode buckets, a handful of rows).
    if q.is_cuda and torch.cuda.is_current_stream_capturing():
        width = block_table.shape[1]
    else:
        width = int((seq_lens.max().item() + block_size - 1) // block_size)
    table = block_table[:, :width].long()
    n_slots = width * block_size
    _assert_newest_positions(row_request, positions, query_start_loc, seq_lens, live, rows)
    per_row = max(1, n_slots) * compute.itemsize * (
        CHUNK_KV_COPIES * n_kv * head_dim + CHUNK_SCORE_COPIES * n_heads)
    chunk = max(1, min(n_tokens, CHUNK_BYTES // per_row))
    out = torch.cat([
        _attend(q[at: at + chunk].to(compute), flat_k, flat_v,
                table.index_select(0, rows[at: at + chunk]),
                _visible(rows[at: at + chunk], positions[at: at + chunk], seq_lens, n_slots,
                         window, live[at: at + chunk], causal),
                sinks, block_size)
        for at in range(0, n_tokens, chunk)
    ])
    return (out * live[:, None]).to(q.dtype)


def _assert_newest_positions(  # noqa: PLR0913, PLR0917
    row_request: torch.Tensor,
    positions: torch.Tensor,
    query_start_loc: torch.Tensor,
    seq_lens: torch.Tensor,
    live: torch.Tensor,
    rows: torch.Tensor,
) -> None:
    """Every live row t of entry r: qsl[r] <= t < qsl[r+1] and positions[t] == seq_lens[r] -
    (qsl[r+1] - qsl[r]) + (t - qsl[r]). A device assert (no host sync; capture-safe)."""
    t = torch.arange(row_request.shape[0], device=row_request.device)
    start, stop = query_start_loc[rows].long(), query_start_loc[rows + 1].long()
    want = seq_lens[rows].long() - (stop - start) + (t - start)
    ok = (t >= start) & (t < stop) & (positions.long() == want)
    torch._assert_async(torch.all(ok | ~live), "plan rows are not their entry's newest positions")


def _attend(  # noqa: PLR0913, PLR0917
    q: torch.Tensor,
    flat_k: torch.Tensor,
    flat_v: torch.Tensor,
    pages: torch.Tensor,
    visible: torch.Tensor,
    sinks: torch.Tensor,
    block_size: int,
) -> torch.Tensor:
    """C rows of attention in q's (compute) dtype: q [C, H, D], each row's pages [C, P] and
    its mask [C, P * block] -> [C, H * D]. GQA groups the q heads of each kv head
    ([C, Hkv, H/Hkv, D]) instead of repeating K and V H/Hkv times."""
    c, n_heads, head_dim = q.shape
    n_kv = flat_k.shape[1]
    offsets = torch.arange(block_size, device=q.device)
    slots = (pages[:, :, None] * block_size + offsets[None, None, :]).reshape(-1)
    keys = flat_k.index_select(0, slots).view(c, -1, n_kv, head_dim).to(q.dtype)
    values = flat_v.index_select(0, slots).view(c, -1, n_kv, head_dim).to(q.dtype)
    grouped = q.view(c, n_kv, n_heads // n_kv, head_dim)
    scores = torch.einsum("tgrd,tsgd->tgrs", grouped, keys) * head_dim**-0.5
    scores = scores.masked_fill(~visible[:, None, None, :], -torch.inf)
    probs = _softmax_with_sinks(scores.reshape(c, n_heads, -1), sinks, n_heads)
    out = torch.einsum("tgrs,tsgd->tgrd", probs.view_as(scores), values)
    return out.reshape(c, n_heads * head_dim)


def _visible(  # noqa: PLR0913, PLR0917
    rows: torch.Tensor,
    positions: torch.Tensor,
    seq_lens: torch.Tensor,
    n_slots: int,
    window: int,
    live: torch.Tensor,
    causal: bool = True,
) -> torch.Tensor:
    """bool [T, n_slots]: may row t attend to cache position j?

    Three conditions, all elementwise, none a Python branch: j is inside this entry's context,
    j is not in the future of this row's position (when causal=True), and -- when a window is
    set -- j is not older than the window. A pad row sees nothing, which is what the sink guard
    below rescues from an all -inf softmax.

    When causal=False (used by drafter models like DFlash), the future-masking condition is
    skipped: every row can attend to all populated cache positions within its entry."""
    kpos = torch.arange(n_slots, device=positions.device)[None, :]
    pos = positions.long()[:, None]
    within = kpos < seq_lens.index_select(0, rows).long()[:, None]
    visible = within & live[:, None]
    if causal:
        visible &= kpos <= pos
    if window > 0:
        visible &= kpos > pos - window
    return visible


def _softmax_with_sinks(
    scores: torch.Tensor, sinks: torch.Tensor, n_heads: int
) -> torch.Tensor:
    """Softmax over the key axis with an optional per-head SINK logit that competes and is then
    dropped, so a head can attend to "nothing" (gpt-oss).

    The appended logit also rescues a fully masked row: an all -inf softmax is NaN, and a pad
    row is exactly that. With the sink column present the row's real weights are all zero, so
    the output is zero -- the same answer the old host loop gave by never visiting the row."""
    n_tokens = scores.shape[0]
    if sinks.numel() > 0:
        assert sinks.shape == (n_heads,), (sinks.shape, n_heads)
        extra = sinks.to(scores.dtype).view(1, n_heads, 1).expand(n_tokens, n_heads, 1)
    else:
        # -inf would reproduce a plain softmax exactly but re-introduces the NaN on a pad row.
        # A zero logit changes a live row's weights, so the sink-free path must renormalize:
        # see below, where the dropped column's mass is divided back out.
        extra = torch.zeros(n_tokens, n_heads, 1, dtype=scores.dtype, device=scores.device)
    full = torch.softmax(torch.cat([scores, extra], dim=-1), dim=-1)
    probs = full[..., :-1]
    if sinks.numel() > 0:
        return probs
    # Sink-free: divide the placeholder column's mass back out, so a live row gets exactly the
    # plain softmax and a fully masked row (whose real mass is 0) stays 0 instead of NaN.
    mass = probs.sum(dim=-1, keepdim=True)
    return probs / mass.clamp(min=torch.finfo(probs.dtype).tiny)


def no_sinks(like: torch.Tensor) -> torch.Tensor:
    """The `sinks` argument for a model without attention sinks: empty, on `like`'s device."""
    return torch.empty(0, dtype=torch.float32, device=like.device)


@paged_attention.register_fake
def _fake(  # noqa: PLR0913, PLR0917
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    kv_member: torch.Tensor,
    row_request: torch.Tensor,
    positions: torch.Tensor,
    query_start_loc: torch.Tensor,
    seq_lens: torch.Tensor,
    block_table: torch.Tensor,
    slot_mapping: torch.Tensor,
    window: int,
    sinks: torch.Tensor,
    causal: bool = True,
) -> torch.Tensor:
    del k, v, kv_member, row_request, positions, query_start_loc, seq_lens, block_table
    del slot_mapping
    del window, sinks, causal
    return torch.empty(q.shape[0], q.shape[1] * q.shape[2], dtype=q.dtype, device=q.device)


@dataclass(frozen=True)
class Batch:
    """One layer's paged-attention step, for `sample` and the per-op bench
    (scripts/bench_attention.py). Defaults are gpt-oss-20b's attention (64 q / 8 kv heads, D 64).

    `entries` is (context already in the cache, rows this step) per REAL entry, in plan order;
    `tokens` / `reqs` are the padded T / R, as the core's padPlan leaves them (pad rows: entry
    -1, position 0, the scratch slot; pad entries: no rows, seq_len 1, an all-null block row)."""

    entries: tuple[tuple[int, int], ...]
    tokens: int
    reqs: int
    heads: int = 64
    kv_heads: int = 8
    head_dim: int = 64
    block: int = 16
    window: int = 0
    sinks: bool = True
    causal: bool = True
    spare_pages: int = 2  # block-table columns past the longest entry (null), as the engine has

    @property
    def n_rows(self) -> int:
        return sum(rows for _, rows in self.entries)


GARBAGE = 64.0  # every never-written KV slot: finite (the reference reads masked slots too) but
# far from the data, so a kernel that reads a slot it must mask is off by a visible amount


def sample(batch: Batch, device: str, dtype: torch.dtype, seed: int = 0) -> tuple:
    """Random args for `paged_attention` at `batch`, laid out as the engine lays them out: K/V
    interleaved per row of a two-member page (so `kv_member` is a strided view, like the
    arena's), pages handed out in a random order, page 0 the null page, the scratch slot its
    last row. Values are drawn once in fp32 and rounded to bf16 before the cast to `dtype`, so
    a float64 sample of the same seed is the bf16 sample's exact truth."""
    g = torch.Generator(device="cpu").manual_seed(seed)
    b = batch
    assert b.n_rows <= b.tokens and len(b.entries) <= b.reqs, b
    assert b.heads % b.kv_heads == 0, b

    def draw(*shape: int, scale: float = 1.0) -> torch.Tensor:
        x = (torch.randn(*shape, generator=g) * scale).to(torch.bfloat16)
        return x.to(device=device, dtype=dtype)

    lens = [ctx + rows for ctx, rows in b.entries]
    need = [-(-n // b.block) for n in lens]
    width = max(need, default=1) + b.spare_pages
    n_pages = 1 + sum(need)
    order = (torch.randperm(n_pages - 1, generator=g) + 1).tolist()
    table = torch.zeros(b.reqs, width, dtype=torch.int32)
    for r, n in enumerate(need):
        table[r, :n] = torch.tensor(order[:n], dtype=torch.int32)
        order = order[n:]
    # [pages, block, member, K/V, Hkv, D]: this layer is member 1 of 2, so every stride but D's
    # is wider than a contiguous tensor's.
    arena = torch.full((n_pages, b.block, 2, KV_MEMBERS, b.kv_heads, b.head_dim), GARBAGE,
                       dtype=dtype, device=device)
    kv_member = arena[:, :, 1].permute(0, 2, 1, 3, 4)
    flat_k, flat_v = kv_views(kv_member)
    flat_k[: b.block].copy_(draw(b.block, b.kv_heads, b.head_dim))  # null page: pad-row writes
    flat_v[: b.block].copy_(draw(b.block, b.kv_heads, b.head_dim))

    row_request = torch.full((b.tokens,), -1, dtype=torch.int32)
    positions = torch.zeros(b.tokens, dtype=torch.int32)
    slot_mapping = torch.full((b.tokens,), b.block - 1, dtype=torch.int32)  # scratch slot
    seq_lens = torch.ones(b.reqs, dtype=torch.int32)
    query_start_loc = torch.full((b.reqs + 1,), b.n_rows, dtype=torch.int32)
    query_start_loc[0] = 0
    row = 0
    for r, (ctx, rows) in enumerate(b.entries):
        slots = table[r, torch.arange(ctx + rows) // b.block] * b.block + (
            torch.arange(ctx + rows) % b.block).to(torch.int32)
        flat_k.index_copy_(0, slots[:ctx].to(device).long(), draw(ctx, b.kv_heads, b.head_dim))
        flat_v.index_copy_(0, slots[:ctx].to(device).long(), draw(ctx, b.kv_heads, b.head_dim))
        row_request[row: row + rows] = r
        positions[row: row + rows] = torch.arange(ctx, ctx + rows, dtype=torch.int32)
        slot_mapping[row: row + rows] = slots[ctx:]
        seq_lens[r] = ctx + rows
        row += rows
        query_start_loc[r + 1] = row
    sinks = (torch.randn(b.heads, generator=g) * 2).to(device) if b.sinks else no_sinks(
        torch.empty(0, device=device))
    return (
        draw(b.tokens, b.heads, b.head_dim),
        draw(b.tokens, b.kv_heads, b.head_dim),
        draw(b.tokens, b.kv_heads, b.head_dim),
        kv_member,
        row_request.to(device),
        positions.to(device),
        query_start_loc.to(device),
        seq_lens.to(device),
        table.to(device),
        slot_mapping.to(device),
        b.window,
        sinks,
        b.causal,
    )


# A small odd case for opcheck and `bench.compare`: GQA 2, one entry with context + two rows,
# one decode row, a pad entry and a pad row, window 3, sinks.
SAMPLE_BATCH = Batch(entries=((5, 2), (3, 1)), tokens=4, reqs=3, heads=4, kv_heads=2,
                     head_dim=32, block=4, window=3)  # head_dim 32: vllm_triton's minimum


@paged_attention.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    return sample(SAMPLE_BATCH, device, dtype)


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


paged_attention.register_autograd(_backward)


def _no_sinks_predicate(*args: object) -> bool:
    """FlashInfer's paged decode has no attention-sink logit, so it must refuse a model that
    has one rather than silently dropping it."""
    # sinks is arg 11 (0-indexed): q,k,v,kv_member,row_request,positions,query_start_loc,
    # seq_lens,block_table,slot_mapping,window,sinks[,causal]
    sinks = args[11]
    return isinstance(sinks, torch.Tensor) and sinks.numel() == 0


@paged_attention.register(
    "flashinfer",
    source="flashinfer.decode.BatchDecodeWithPagedKVCacheWrapper",
    predicate=_no_sinks_predicate,
)
def _flashinfer(*args: object) -> torch.Tensor:
    del args
    raise NotImplementedError(
        "paged_attention[flashinfer]: not wired; the wrapper wants CSR "
        "(indptr/indices/last_page_len) derived here from block_table/seq_lens, and a plan-"
        "lifetime `plan()` call this op has no place to hold"
    )


@paged_attention.register(
    "vllm_triton", backend="vllm_triton_attn",
    source="vllm v0.29.0 v1/attention/ops/triton_unified_attention.unified_attention (vendored)")
def _vllm_triton(*args: object) -> torch.Tensor:
    """vLLM's TRITON_ATTN, its gpt-oss path on A100: sinks, sliding window, GQA, ragged rows,
    causal or not; sm80+ bf16/fp16 (adapters/paged_attention_vllm, vendored/cuda/vllm_attention)."""
    from kelpie_models.kernels.adapters import paged_attention_vllm as adapter

    return adapter.paged_attention(*args)


@paged_attention.register("triton", source="kernels.vendored.cuda._triton.TritonAttention")
def _triton(*args: object) -> torch.Tensor:
    del args
    raise NotImplementedError(
        "paged_attention[triton]: kernels/vendored/cuda/_triton.py's TritonAttention is still "
        "StepBatch-shaped (kind/num_drafts grid split), not this op's tensor/int contract"
    )


@paged_attention.register("pallas", source="kernels.vendored.tpu._pallas.ragged_paged_attention")
def _pallas(*args: object) -> torch.Tensor:
    del args
    raise NotImplementedError(
        "paged_attention[pallas]: TPU is reached via torchax (spike owed); the Pallas source "
        "stays vendored but unimported until that port lands"
    )


@paged_attention.register("nki", source="kernels.vendored.neuron._dense.BlockDiagonalAttention")
def _nki(*args: object) -> torch.Tensor:
    del args
    raise NotImplementedError(
        "paged_attention[nki]: Trainium is reached via torch-neuronx; the NKI source stays "
        "vendored but unimported until that port lands"
    )
