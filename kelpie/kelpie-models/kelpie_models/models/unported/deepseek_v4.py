"""DeepSeek-V4 forward over the StepBatch contract (HF DeepseekV4ForCausalLM semantics): shared-KV
MQA with per-head sinks, partial interleaved RoPE (plain on sliding layers, YaRN on compressed
ones), manifold-constrained hyper-connections (hc_mult residual streams, Sinkhorn-mixed), hash /
top-k MoE with a shared expert, and three attention kinds per `compress_ratios`:

  0   sliding_attention: a 128-token window ring only
  4   compressed_sparse_attention (CSA): window ring + one compressed KV entry per 4 tokens (two
      overlapping series Ca/Cb pooled over 2 windows) + a lightning indexer K per 4 tokens that
      picks the top-k entries each query may attend
  128 heavily_compressed_attention (HCA): window ring + one entry per 128 tokens, all visible

Cache groups (kelpie_models.sdk.groups.derive_groups over the layers' specs): W128 (per_token,
window 128, not cacheable), C4 (stride 4: KV + indexer K members), C128 (stride 128). The core
sizes and hands out these tables; the compress state that closes a window across a chunk
boundary lives in the request-slot StateRing (kelpie_models.state, `groups.state_specs`),
passed to the forward as `state` like Qwen3-Next's recurrent ring.
The NextN (MTP) draft layer of the checkpoint is not modelled (HF drops `mtp.*` too).
"""

from __future__ import annotations

# ruff: noqa: E402 -- the raise is deliberately ABOVE the imports: this module's imports are
# the deleted pre-Plan path, so importing it must fail with a reason, not an ImportError.
raise NotImplementedError(
    "unported: needs batch.StepBatch, kernels.backend.gather_cache, kv.KV, plan.HostPlan, state.StateRing, facts; these were the pre-Plan path and were deleted "
    "2026-09-10. Port this model to forward(weights, config, tokens, requests, kv, taps) "
    "the way models/torch/qwen3.py is written; see docs/ladder.md for the order."
)

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

import torch
import torch.nn.functional as F

from kelpie_models.batch import StepBatch, embed_tokens, host_plan
from kelpie_models.kernels.backend import gather_cache
from kelpie_models.kernels.functional import yarn_inv_freq
from kelpie_models.plan import HostPlan
from kelpie_models.sdk.groups import CSA, HCA, AttnSpec, derive_groups
from kelpie_models.sdk.kv import KV
# TODO(2026-09-10): per_seq group view. The recurrent state / compressor rings are per_seq
# cache groups the core owns now (docs/brief-slab-pool-recurrent.md step 4); this unported model
# still calls the deleted kelpie_models.state ring. Porting it means reading the group's page
# view out of the plan instead. Until then these raise rather than silently doing nothing.
StateRing = Any


def _no_state_ring(fn: str) -> NoReturn:
    raise NotImplementedError(
        f"{fn}: kelpie_models.state is gone -- recurrent/compressor state is a per_seq cache "
        "group now (TODO(2026-09-10): per_seq group view)"
    )


def advance(*args: Any, **kwargs: Any) -> NoReturn:
    del args, kwargs
    _no_state_ring("advance")


def ring_rows(*args: Any, **kwargs: Any) -> NoReturn:
    del args, kwargs
    _no_state_ring("ring_rows")


MODEL_ID = "deepseek-ai/DeepSeek-V4-Flash"
CHECKPOINT = MODEL_ID  # kelpie_models.facts: the launch layer reads these, not a name table
CHAT_FAMILY = "default"
DTYPE = "bfloat16"
ADAPTER = None
SLIDING, CSA_TYPE, HCA_TYPE = (
    "sliding_attention",
    "compressed_sparse_attention",
    "heavily_compressed_attention",
)


@dataclass(frozen=True)
class DeepseekV4Config:
    n_layers: int
    hidden: int
    n_heads: int
    head_dim: int
    rope_dim: int  # trailing channels of a head that rotate (qk_rope_head_dim)
    q_lora_rank: int
    o_groups: int
    o_lora_rank: int
    layer_types: tuple[str, ...]
    mlp_layer_types: tuple[str, ...]  # "hash_moe" | "moe"
    csa_ratio: int
    hca_ratio: int
    sliding_window: int
    index_heads: int
    index_dim: int
    index_topk: int
    n_experts: int
    top_k: int
    intermediate: int  # routed and shared expert width
    routed_scale: float
    hc_mult: int
    hc_sinkhorn_iters: int
    hc_eps: float
    eps: float
    swiglu_limit: float
    vocab: int
    eos_token: int
    rope_theta: float
    compress_rope_theta: float
    yarn_factor: float
    yarn_beta_fast: float
    yarn_beta_slow: float
    yarn_original_max: int
    yarn_truncate: bool


@dataclass(frozen=True)
class HyperConnection:
    fn: torch.Tensor  # [(2 + hc) * hc, hc * hidden] fp32
    base: torch.Tensor  # [(2 + hc) * hc]
    scale: torch.Tensor  # [3]


@dataclass(frozen=True)
class Compressor:
    """One compress branch: the outer compressor (width head_dim, x2 for CSA's Ca/Cb series) or
    the CSA indexer (width index_dim x2, plus its query/scorer weights)."""

    kv: torch.Tensor  # [width, hidden]
    gate: torch.Tensor  # [width, hidden]
    position_bias: torch.Tensor  # [ratio, width] fp32
    kv_norm: torch.Tensor  # [out_dim]
    q_b: torch.Tensor | None = None  # indexer: [index_heads * index_dim, q_lora_rank]
    scorer: torch.Tensor | None = None  # indexer: [index_heads, hidden]


@dataclass(frozen=True)
class DeepseekV4Layer:
    attn: AttnSpec
    layer_type: str
    is_hash: bool
    ln_1: torch.Tensor
    ln_2: torch.Tensor
    attn_hc: HyperConnection
    ffn_hc: HyperConnection
    q_a: torch.Tensor  # [q_lora_rank, hidden]
    q_a_norm: torch.Tensor
    q_b: torch.Tensor  # [n_heads * head_dim, q_lora_rank]
    kv: torch.Tensor  # [head_dim, hidden]
    kv_norm: torch.Tensor
    o_a: torch.Tensor  # [o_groups * o_lora_rank, n_heads * head_dim / o_groups]
    o_b: torch.Tensor  # [hidden, o_groups * o_lora_rank]
    sinks: torch.Tensor  # [n_heads] fp32
    compressor: Compressor | None  # CSA / HCA
    indexer: Compressor | None  # CSA
    router: torch.Tensor  # [n_experts, hidden]
    router_bias: torch.Tensor | None  # top-k router: e_score_correction_bias [n_experts]
    tid2eid: torch.Tensor | None  # hash router: [vocab, top_k] int64
    gate_up: torch.Tensor  # [n_experts, hidden, 2 * intermediate]
    down: torch.Tensor  # [n_experts, intermediate, hidden]
    shared_gate: torch.Tensor  # [intermediate, hidden]
    shared_up: torch.Tensor
    shared_down: torch.Tensor  # [hidden, intermediate]


@dataclass(frozen=True)
class DeepseekV4:
    embed: torch.Tensor
    layers: tuple[DeepseekV4Layer, ...]
    hc_head_fn: torch.Tensor  # [hc, hc * hidden]
    hc_head_base: torch.Tensor  # [hc]
    hc_head_scale: torch.Tensor  # [1]
    ln_f: torch.Tensor
    lm_head: torch.Tensor


def attn_specs(cfg: DeepseekV4Config, itemsize: int = 2) -> list[AttnSpec]:
    return [attn_spec(cfg, t, itemsize) for t in cfg.layer_types]


def attn_spec(cfg: DeepseekV4Config, layer_type: str, itemsize: int = 2) -> AttnSpec:
    kv_bytes = cfg.head_dim * itemsize
    if layer_type == SLIDING:
        return CSA(0, cfg.sliding_window, kv_bytes)
    if layer_type == CSA_TYPE:
        return CSA(cfg.csa_ratio, cfg.sliding_window, kv_bytes, cfg.index_dim * itemsize)
    assert layer_type == HCA_TYPE, layer_type
    return HCA(cfg.hca_ratio, cfg.sliding_window, kv_bytes)


# ---- forward ---------------------------------------------------------------------------------


def forward(  # noqa: PLR0913, PLR0917
    w: DeepseekV4,
    cfg: DeepseekV4Config,
    batch: StepBatch,
    kv: list[KV],
    state: StateRing,
    ops,
) -> tuple[torch.Tensor, list[KV], StateRing]:
    """-> (logits [padded_num_reqs, 1 + K, vocab] at each request's accept_index rows, kv,
    state). kv: one KV (a tuple of per-member arrays) per derived group; `state`: the
    request-slot ring holding the compress rings (kelpie_models.state), indexed by the host
    plan's request slots."""
    assert state is not None, "deepseek_v4 keeps its compress rings in the StateRing"
    itemsize = kv[0][0].dtype.itemsize
    groups, layer_caches = derive_groups(attn_specs(cfg, itemsize), itemsize=itemsize)
    assert len(kv) == len(groups), (len(kv), len(groups))
    assert all(len(kv[g]) == len(groups[g].members) for g in range(len(groups)))
    kv = list(kv)
    host = host_plan(batch)
    x = embed_tokens(w.embed, batch)
    streams = x[:, None, :].expand(-1, cfg.hc_mult, -1).contiguous()  # [T, hc, hidden]
    rope = RopeTables.build(cfg, batch.positions, x.dtype)
    for i, (layer, refs) in enumerate(zip(w.layers, layer_caches, strict=True)):
        post, comb, h = hyper_connection(streams, layer.attn_hc, cfg)
        h = ops.rms_norm(h, layer.ln_1, cfg.eps)
        ctx = LayerCtx(i, layer, cfg, batch, host, kv, refs, rope, ops, state)
        a, kv, state = attention(h, ctx)
        streams = mix(post, comb, a, streams)
        post, comb, h = hyper_connection(streams, layer.ffn_hc, cfg)
        h = ops.rms_norm(h, layer.ln_2, cfg.eps)
        streams = mix(post, comb, moe(h, batch.input_ids, layer, cfg, ops), streams)
    for r in range(host.num_reqs):
        advance(state, host.req_ids[r], host.seq_lens[r])
    picked = streams[batch.accept_index.long()]  # [R, 1 + K, hc, hidden]
    r, k1 = picked.shape[0], picked.shape[1]
    last = hyper_head(picked.reshape(r * k1, cfg.hc_mult, cfg.hidden), w, cfg)
    last = ops.rms_norm(last, w.ln_f, cfg.eps)
    return (last @ w.lm_head.T).view(r, k1, cfg.vocab), kv, state


def mix(
    post: torch.Tensor, comb: torch.Tensor, out: torch.Tensor, streams: torch.Tensor
) -> torch.Tensor:
    """HF DeepseekV4DecoderLayer:
    streams'[t, k] = post[t, k] * out[t] + sum_j comb[t, j, k] * streams[t, j]."""
    dt = streams.dtype
    return post.to(dt)[..., None] * out[:, None, :] + torch.einsum(
        "tjk,tjd->tkd", comb.to(dt), streams
    )


@dataclass(frozen=True)
class RopeTables:
    """cos/sin [T, rope_dim] in the interleaved layout (each frequency twice): `main` (plain,
    sliding layers) and `compress` (YaRN, attention_factor 1: HF V4 forces it) at the batch's
    positions, plus the compress inverse frequencies to rope compressed entries at their own
    positions (window index * ratio)."""

    main: tuple[torch.Tensor, torch.Tensor]
    compress: tuple[torch.Tensor, torch.Tensor]
    compress_inv: torch.Tensor
    dtype: torch.dtype

    @staticmethod
    def build(cfg: DeepseekV4Config, positions: torch.Tensor, dtype: torch.dtype) -> RopeTables:
        d = cfg.rope_dim
        main_inv = 1.0 / (
            cfg.rope_theta
            ** (torch.arange(0, d, 2, device=positions.device, dtype=torch.float32) / d)
        )
        comp_inv = yarn_inv_freq(
            d,
            cfg.compress_rope_theta,
            cfg.yarn_factor,
            cfg.yarn_beta_fast,
            cfg.yarn_beta_slow,
            cfg.yarn_original_max,
            cfg.yarn_truncate,
            positions.device,
        )
        return RopeTables(
            interleaved_tables(positions, main_inv, dtype),
            interleaved_tables(positions, comp_inv, dtype),
            comp_inv,
            dtype,
        )

    def compress_at(self, positions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        return interleaved_tables(positions, self.compress_inv, self.dtype)


def interleaved_tables(
    positions: torch.Tensor, inv_freq: torch.Tensor, dtype: torch.dtype
) -> tuple[torch.Tensor, torch.Tensor]:
    freqs = positions.float()[:, None] * inv_freq[None, :]
    emb = freqs.repeat_interleave(2, dim=-1)
    return emb.cos().to(dtype), emb.sin().to(dtype)


# ---- hyper-connections -----------------------------------------------------------------------


def unweighted_rms(x: torch.Tensor, eps: float) -> torch.Tensor:
    return x * torch.rsqrt(x.float().square().mean(-1, keepdim=True) + eps).to(x.dtype)


def hyper_connection(
    streams: torch.Tensor, hc: HyperConnection, cfg: DeepseekV4Config
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """HF DeepseekV4HyperConnection -> (post [T, hc], comb [T, hc, hc] doubly stochastic by
    Sinkhorn, collapsed [T, hidden]); everything in fp32 but the collapse."""
    n = cfg.hc_mult
    flat = unweighted_rms(streams.flatten(1).float(), cfg.eps)
    pre_w, post_w, comb_w = (flat @ hc.fn.float().T).split([n, n, n * n], dim=-1)
    pre_b, post_b, comb_b = hc.base.float().split([n, n, n * n])
    pre_s, post_s, comb_s = hc.scale.float().unbind(0)
    pre = torch.sigmoid(pre_w * pre_s + pre_b) + cfg.hc_eps
    post = 2 * torch.sigmoid(post_w * post_s + post_b)
    comb = torch.softmax(comb_w.view(-1, n, n) * comb_s + comb_b.view(n, n), dim=-1) + cfg.hc_eps
    comb = comb / (comb.sum(dim=-2, keepdim=True) + cfg.hc_eps)
    for _ in range(cfg.hc_sinkhorn_iters - 1):
        comb = comb / (comb.sum(dim=-1, keepdim=True) + cfg.hc_eps)
        comb = comb / (comb.sum(dim=-2, keepdim=True) + cfg.hc_eps)
    collapsed = (pre[..., None] * streams).sum(dim=1).to(streams.dtype)
    return post, comb, collapsed


def hyper_head(streams: torch.Tensor, w: DeepseekV4, cfg: DeepseekV4Config) -> torch.Tensor:
    flat = unweighted_rms(streams.flatten(1).float(), cfg.eps)
    mixes = flat @ w.hc_head_fn.float().T
    pre = torch.sigmoid(mixes * w.hc_head_scale.float() + w.hc_head_base.float()) + cfg.hc_eps
    return (pre[..., None] * streams).sum(dim=1).to(streams.dtype)


# ---- attention -------------------------------------------------------------------------------


@dataclass(frozen=True)
class LayerCtx:
    """Everything one layer's attention reads besides its input (keeps the call sites short).
    `kv` is the forward's list of groups: a write stores the returned group back into it."""

    index: int
    layer: DeepseekV4Layer
    cfg: DeepseekV4Config
    batch: StepBatch
    host: HostPlan
    kv: list[KV]
    refs: list[tuple[int, int]]  # this layer's (group, member index)s, in caches() order
    rope: RopeTables
    ops: Any
    state: StateRing

    def cache(self, i: int) -> tuple[torch.Tensor, int, int]:
        """(member array [num_blocks, block_size, width], group index, member index) of this
        layer's i-th cache."""
        g, member = self.refs[i]
        return self.kv[g][member], g, member

    def write(self, i: int, x: torch.Tensor, slots: torch.Tensor) -> None:
        """x [n, width] into this layer's i-th cache at flat `slots`, threading the group."""
        g, member = self.refs[i]
        self.kv[g] = self.ops.write_cache(self.kv[g], member, x, slots)


def attention(h: torch.Tensor, c: LayerCtx) -> tuple[torch.Tensor, list[KV], StateRing]:
    """-> (attention output [padded_num_tokens, hidden] with zero pad rows, kv, state)."""
    cfg, layer, ops, batch, host = c.cfg, c.layer, c.ops, c.batch, c.host
    t = h.shape[0]
    cos, sin = c.rope.main if layer.layer_type == SLIDING else c.rope.compress
    q_res = ops.rms_norm(h @ layer.q_a.T, layer.q_a_norm, cfg.eps)
    q = unweighted_rms((q_res @ layer.q_b.T).view(t, cfg.n_heads, cfg.head_dim), cfg.eps)
    q = ops.rope_pairs(q, cos, sin)
    k = ops.rms_norm(h @ layer.kv.T, layer.kv_norm, cfg.eps)
    k = ops.rope_pairs(k[:, None, :], cos, sin)[:, 0]  # [T, head_dim]

    _, g_win, _ = c.cache(0)
    c.write(0, k, batch.slot_mapping[g_win])
    comp = compress_step(h, q_res, c)  # None for sliding layers
    win = c.cache(0)[0]
    out = torch.zeros(
        batch.padded_num_tokens, cfg.n_heads, cfg.head_dim, dtype=h.dtype, device=h.device
    )
    for r in range(host.num_reqs):
        s = host.seq_lens[r]
        q0, q1 = host.rows(r)
        nq = q1 - q0
        qpos = torch.arange(s - nq, s, device=h.device)
        keys, bias = window_rows(win, batch.block_tables[g_win][r], qpos, s, cfg.sliding_window)
        if comp is not None:
            entries, ebias = comp.entries_for(r, qpos, s, (q_res[q0:q1], h[q0:q1]), c)
            keys, bias = torch.cat([keys, entries]), torch.cat([bias, ebias], dim=1)
        out[q0:q1] = ops.sink_attention(q[q0:q1], keys, bias, layer.sinks, cfg.head_dim**-0.5)
    out = ops.rope_pairs(out, cos, -sin)  # K == V picked up rope: undo it on the output
    grouped = out.reshape(batch.padded_num_tokens, cfg.o_groups, -1)  # [T, g, H*D/g]
    w_a = layer.o_a.view(cfg.o_groups, cfg.o_lora_rank, -1).transpose(1, 2)  # [g, H*D/g, r]
    mixed = (
        torch.bmm(grouped.transpose(0, 1), w_a).transpose(0, 1).reshape(batch.padded_num_tokens, -1)
    )
    return mixed @ layer.o_b.T, c.kv, c.state


def window_rows(
    cache: torch.Tensor, table: torch.Tensor, qpos: torch.Tensor, s: int, window: int
) -> tuple[torch.Tensor, torch.Tensor]:
    """Keys [S, D] of positions [k0, s) from the window ring member [num_blocks, block_size, D]
    and their mask bias [nq, S]: query at p sees keys in [p - window + 1, p]. k0 is the first
    position any query sees; rows the core slid out (null block) lie before it and are never
    gathered."""
    block_size = cache.shape[1]
    k0 = max(0, int(qpos[0]) - window + 1)
    b0, b1 = k0 // block_size, (s + block_size - 1) // block_size
    blocks = table[b0:b1].long()
    assert bool((blocks > 0).all()), "null block inside the live window"
    slots = (blocks[:, None] * block_size + torch.arange(block_size, device=cache.device)).view(-1)
    slots = slots[k0 - b0 * block_size : s - b0 * block_size]
    keys = cache.view(-1, cache.shape[-1])[slots]
    kpos = torch.arange(k0, s, device=cache.device)
    hidden = (kpos[None, :] > qpos[:, None]) | (kpos[None, :] <= qpos[:, None] - window)
    return keys, torch.zeros(hidden.shape, dtype=cache.dtype, device=cache.device).masked_fill(
        hidden, float("-inf")
    )


@dataclass(frozen=True)
class Compressed:
    """A compressing layer's state for this step: the member array holding its entries and its
    C group (for the block table), plus, for CSA, the same for its indexer K."""

    ratio: int
    kv: torch.Tensor  # [num_blocks, block_size, head_dim]
    group: int
    idx_kv: torch.Tensor | None = None  # [num_blocks, block_size, index_dim]
    idx_group: int = 0

    def entries_for(  # noqa: PLR0913, PLR0917
        self,
        r: int,
        qpos: torch.Tensor,
        s: int,
        rows: tuple[torch.Tensor, torch.Tensor],
        c: LayerCtx,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Compressed entries [n_entries, D] a request's queries may see and their bias [nq, n]:
        entry j (tokens [ratio*j, ratio*j + ratio)) is visible to the query at p iff
        j < (p + 1) // ratio (HF causal_threshold); CSA further keeps only the indexer's top-k.
        rows: the request's (q_residual, layer input) rows, for the indexer query and scorer."""
        q_res, h = rows
        n = s // self.ratio
        n_visible = (qpos + 1) // self.ratio
        entries = gather_cache(self.kv, c.batch.block_tables[self.group][r], n)
        hidden = torch.arange(n, device=qpos.device)[None, :] >= n_visible[:, None]
        bias = torch.zeros(hidden.shape, dtype=entries.dtype, device=entries.device).masked_fill(
            hidden, float("-inf")
        )
        if self.idx_kv is None:
            return entries, bias
        idx = c.layer.indexer
        assert idx is not None and idx.q_b is not None and idx.scorer is not None
        cfg = c.cfg
        keys = gather_cache(self.idx_kv, c.batch.block_tables[self.idx_group][r], n)
        cos, sin = c.rope.compress_at(qpos)
        qi = (q_res @ idx.q_b.T).view(-1, cfg.index_heads, cfg.index_dim)
        qi = c.ops.rope_pairs(qi, cos, sin)
        scores = F.relu(torch.einsum("qhd,td->qht", qi.float(), keys.float())) * cfg.index_dim**-0.5
        weights = (h.float() @ idx.scorer.float().T) * cfg.index_heads**-0.5  # [nq, heads]
        scores = (scores * weights[..., None]).sum(dim=1)  # [nq, n]
        return entries, c.ops.index_topk(scores, n_visible, cfg.index_topk).to(entries.dtype)


def compress_step(h: torch.Tensor, q_res: torch.Tensor, c: LayerCtx) -> Compressed | None:
    """Close every window that ends inside this chunk (per request) and write its entry (and,
    for CSA, its indexer K) into the stride group; returns where they live."""
    layer, cfg = c.layer, c.cfg
    if layer.compressor is None:
        return None
    ratio = cfg.csa_ratio if layer.layer_type == CSA_TYPE else cfg.hca_ratio
    overlap = layer.layer_type == CSA_TYPE
    emit_entries(h, layer.compressor, "compressor", ratio, overlap, 1, c)
    kv_t, g, _ = c.cache(1)
    if not overlap:
        return Compressed(ratio, kv_t, g)
    assert layer.indexer is not None
    emit_entries(h, layer.indexer, "indexer", ratio, True, 2, c)
    ikv, ig, _ = c.cache(2)
    return Compressed(ratio, kv_t, g, ikv, ig)


def emit_entries(  # noqa: PLR0913, PLR0917
    h: torch.Tensor,
    comp: Compressor,
    member: str,
    ratio: int,
    overlap: bool,
    dest: int,
    c: LayerCtx,
) -> None:
    """HF DeepseekV4{HCA,CSA}Compressor / Indexer window closing, per request: raw rows
    (kv | gate) of the chunk join the ring's rows of the open window (and the previous one for
    CSA's Ca slice), whole windows are pooled, normed, roped at ratio * j and written at unit j
    of this layer's `dest`-th cache."""
    cache, g, _ = c.cache(dest)
    batch, ops, host = c.batch, c.ops, c.host
    width = comp.kv.shape[0]
    raw = torch.cat([h @ comp.kv.T, h @ comp.gate.T], dim=-1)  # [T, 2 * width]
    out_dim = cache.shape[2]
    for r in range(host.num_reqs):
        s = host.seq_lens[r]
        q0, q1 = host.rows(r)
        a, b = s - (q1 - q0), s
        first_w, end_w = a // ratio, b // ratio
        lo = max(0, (first_w - (1 if overlap else 0)) * ratio)
        rows = ring_rows(c.state, host.req_ids[r], c.index, member, lo, a, raw[q0:q1])  # [lo, b)
        if end_w == first_w:
            continue
        kv_rows, gate_rows = rows[:, :width], rows[:, width:]
        n_win = end_w - first_w
        win0 = first_w * ratio - lo  # row offset of window first_w
        win_kv = kv_rows[win0 : win0 + n_win * ratio].view(n_win, ratio, width)
        win_gate = gate_rows[win0 : win0 + n_win * ratio].view(
            n_win, ratio, width
        ) + comp.position_bias.to(rows.dtype)
        if overlap:
            slot_kv = win_kv.new_zeros(n_win, 2 * ratio, out_dim)
            slot_gate = win_gate.new_full((n_win, 2 * ratio, out_dim), float("-inf"))
            slot_kv[:, ratio:], slot_gate[:, ratio:] = (
                win_kv[..., out_dim:],
                win_gate[..., out_dim:],
            )
            if first_w > 0:  # previous window's Ca slice (from the ring for window first_w - 1)
                prev_kv = kv_rows[win0 - ratio : win0, :out_dim]
                prev_gate = gate_rows[win0 - ratio : win0, :out_dim] + comp.position_bias[
                    :, :out_dim
                ].to(rows.dtype)
                slot_kv[0, :ratio], slot_gate[0, :ratio] = prev_kv, prev_gate
            if n_win > 1:
                slot_kv[1:, :ratio], slot_gate[1:, :ratio] = (
                    win_kv[:-1, :, :out_dim],
                    win_gate[:-1, :, :out_dim],
                )
        else:
            slot_kv, slot_gate = win_kv, win_gate
        pooled = ops.rms_norm(ops.pool_windows(slot_kv, slot_gate), comp.kv_norm, c.cfg.eps)
        wpos = torch.arange(first_w, end_w, device=h.device) * ratio
        cos, sin = c.rope.compress_at(wpos)
        pooled = ops.rope_pairs(pooled[:, None, :], cos, sin)[:, 0]
        # unit j is written through the slot of its last token (ratio * j + ratio - 1): in chunk
        last = q0 + (wpos + ratio - 1 - a)
        c.write(dest, pooled, batch.slot_mapping[g][last])


# ---- MoE -------------------------------------------------------------------------------------


def moe(
    h: torch.Tensor, ids: torch.Tensor, layer: DeepseekV4Layer, cfg: DeepseekV4Config, ops
) -> torch.Tensor:
    """HF DeepseekV4SparseMoeBlock: sqrt(softplus) scores; experts by hash table (tid2eid) or
    bias-corrected top-k; weights renormalised and scaled; clamped SwiGLU experts as two grouped
    matmuls over tokens sorted by expert; plus the shared expert."""
    t = h.shape[0]
    scores = F.softplus(h @ layer.router.T).sqrt()  # [T, E]
    if layer.tid2eid is not None:
        idx = layer.tid2eid[ids.long()]
    else:
        assert layer.router_bias is not None
        idx = torch.topk(scores + layer.router_bias, cfg.top_k, dim=-1, sorted=False).indices
    weights = scores.gather(1, idx)
    weights = weights / (weights.sum(dim=-1, keepdim=True) + 1e-20) * cfg.routed_scale
    expert = idx.reshape(-1)
    order = torch.argsort(expert, stable=True)
    counts = torch.bincount(expert, minlength=cfg.n_experts).tolist()  # host sync (reference)
    token = order // cfg.top_k
    zeros_gu = layer.gate_up.new_zeros(cfg.n_experts, 2 * cfg.intermediate)
    zeros_d = layer.down.new_zeros(cfg.n_experts, cfg.hidden)
    gate_up = ops.grouped_mm(h[token], layer.gate_up, zeros_gu, counts)
    gate, up = gate_up.chunk(2, dim=-1)
    act = ops.silu_mul(
        gate.clamp(max=cfg.swiglu_limit), up.clamp(min=-cfg.swiglu_limit, max=cfg.swiglu_limit)
    )
    y = ops.grouped_mm(act, layer.down, zeros_d, counts) * weights.reshape(-1)[order, None]
    out = torch.zeros(t, cfg.hidden, dtype=h.dtype, device=h.device)
    out.index_add_(0, token, y.to(h.dtype))
    gate = (h @ layer.shared_gate.T).clamp(max=cfg.swiglu_limit)
    up = (h @ layer.shared_up.T).clamp(min=-cfg.swiglu_limit, max=cfg.swiglu_limit)
    return out + ops.silu_mul(gate, up) @ layer.shared_down.T


# ---- loading ---------------------------------------------------------------------------------


def config_from_hf(c: Mapping[str, Any]) -> DeepseekV4Config:
    """From an HF DeepseekV4Config.to_dict() (or the hub config.json: legacy keys accepted)."""
    n = c["num_hidden_layers"]
    rates = c.get("compress_rates") or {CSA_TYPE: 4, HCA_TYPE: 128}
    ratio_to_type = {0: SLIDING, rates[CSA_TYPE]: CSA_TYPE, rates[HCA_TYPE]: HCA_TYPE}
    layer_types = c.get("layer_types") or [ratio_to_type[r] for r in c["compress_ratios"]]
    n_hash = c.get("num_hash_layers", 3)
    mlp_types = c.get("mlp_layer_types") or ["hash_moe"] * n_hash + ["moe"] * (n - n_hash)
    rp = c.get("rope_parameters") or {}
    yarn = rp.get("compress") or c.get("rope_scaling") or {}
    rope_dim = c.get("qk_rope_head_dim") or int(
        c["head_dim"] * c.get("partial_rotary_factor", 0.125)
    )
    return DeepseekV4Config(
        n_layers=n,
        hidden=c["hidden_size"],
        n_heads=c["num_attention_heads"],
        head_dim=c["head_dim"],
        rope_dim=rope_dim,
        q_lora_rank=c["q_lora_rank"],
        o_groups=c["o_groups"],
        o_lora_rank=c["o_lora_rank"],
        layer_types=tuple(layer_types[:n]),
        mlp_layer_types=tuple(mlp_types[:n]),
        csa_ratio=rates[CSA_TYPE],
        hca_ratio=rates[HCA_TYPE],
        sliding_window=c["sliding_window"],
        index_heads=c["index_n_heads"],
        index_dim=c["index_head_dim"],
        index_topk=c["index_topk"],
        n_experts=c.get("num_local_experts") or c["n_routed_experts"],
        top_k=c["num_experts_per_tok"],
        intermediate=c.get("intermediate_size") or c["moe_intermediate_size"],
        routed_scale=c["routed_scaling_factor"],
        hc_mult=c["hc_mult"],
        hc_sinkhorn_iters=c["hc_sinkhorn_iters"],
        hc_eps=c.get("hc_eps", 1e-6),
        eps=c["rms_norm_eps"],
        swiglu_limit=c.get("swiglu_limit", 10.0),
        vocab=c["vocab_size"],
        eos_token=c["eos_token_id"],
        rope_theta=(rp.get("main") or {}).get("rope_theta") or c["rope_theta"],
        compress_rope_theta=yarn.get("rope_theta") or c["compress_rope_theta"],
        yarn_factor=yarn["factor"],
        yarn_beta_fast=yarn.get("beta_fast", 32),
        yarn_beta_slow=yarn.get("beta_slow", 1),
        yarn_original_max=yarn["original_max_position_embeddings"],
        yarn_truncate=yarn.get("truncate", True),
    )


def from_state_dict(
    sd: Mapping[str, torch.Tensor],
    cfg: DeepseekV4Config,
    device: torch.device | str,
    dtype: torch.dtype,
) -> DeepseekV4:
    """HF DeepseekV4ForCausalLM parameter names -> pytree. Expert weights are transposed to
    [E, in, out] for grouped_mm; norms, hc, sinks, position biases kept fp32 (HF
    _keep_in_fp32_modules_strict)."""

    def t(name: str, dt: torch.dtype = dtype) -> torch.Tensor:
        return sd[name].to(device=device, dtype=dt)

    def hc(p: str) -> HyperConnection:
        return HyperConnection(
            t(f"{p}.fn", torch.float32),
            t(f"{p}.base", torch.float32),
            t(f"{p}.scale", torch.float32),
        )

    def compressor(p: str, indexer: bool) -> Compressor:
        return Compressor(
            kv=t(f"{p}.kv_proj.weight"),
            gate=t(f"{p}.gate_proj.weight"),
            position_bias=t(f"{p}.position_bias", torch.float32),
            kv_norm=t(f"{p}.kv_norm.weight", torch.float32),
            q_b=t(f"{p}.q_b_proj.weight") if indexer else None,
            scorer=t(f"{p}.scorer.weights_proj.weight") if indexer else None,
        )

    def layer(i: int) -> DeepseekV4Layer:
        p, lt = f"model.layers.{i}", cfg.layer_types[i]
        a, m = f"{p}.self_attn", f"{p}.mlp"
        is_hash = cfg.mlp_layer_types[i] == "hash_moe"
        return DeepseekV4Layer(
            attn=attn_spec(cfg, lt, dtype.itemsize),
            layer_type=lt,
            is_hash=is_hash,
            ln_1=t(f"{p}.input_layernorm.weight", torch.float32),
            ln_2=t(f"{p}.post_attention_layernorm.weight", torch.float32),
            attn_hc=hc(f"{p}.attn_hc"),
            ffn_hc=hc(f"{p}.ffn_hc"),
            q_a=t(f"{a}.q_a_proj.weight"),
            q_a_norm=t(f"{a}.q_a_norm.weight", torch.float32),
            q_b=t(f"{a}.q_b_proj.weight"),
            kv=t(f"{a}.kv_proj.weight"),
            kv_norm=t(f"{a}.kv_norm.weight", torch.float32),
            o_a=t(f"{a}.o_a_proj.weight"),
            o_b=t(f"{a}.o_b_proj.weight"),
            sinks=t(f"{a}.sinks", torch.float32),
            compressor=compressor(f"{a}.compressor", False) if lt != SLIDING else None,
            indexer=compressor(f"{a}.compressor.indexer", True) if lt == CSA_TYPE else None,
            router=t(f"{m}.gate.weight"),
            router_bias=None if is_hash else t(f"{m}.gate.e_score_correction_bias", torch.float32),
            tid2eid=t(f"{m}.gate.tid2eid", torch.int64) if is_hash else None,
            gate_up=t(f"{m}.experts.gate_up_proj").transpose(1, 2).contiguous(),
            down=t(f"{m}.experts.down_proj").transpose(1, 2).contiguous(),
            shared_gate=t(f"{m}.shared_experts.gate_proj.weight"),
            shared_up=t(f"{m}.shared_experts.up_proj.weight"),
            shared_down=t(f"{m}.shared_experts.down_proj.weight"),
        )

    w = DeepseekV4(
        embed=t("model.embed_tokens.weight"),
        layers=tuple(layer(i) for i in range(cfg.n_layers)),
        hc_head_fn=t("model.hc_head.hc_fn", torch.float32),
        hc_head_base=t("model.hc_head.hc_base", torch.float32),
        hc_head_scale=t("model.hc_head.hc_scale", torch.float32),
        ln_f=t("model.norm.weight", torch.float32),
        lm_head=t("lm_head.weight"),
    )
    assert w.embed.shape == (cfg.vocab, cfg.hidden), w.embed.shape
    assert w.layers[0].gate_up.shape == (cfg.n_experts, cfg.hidden, 2 * cfg.intermediate)
    assert w.layers[0].q_b.shape == (cfg.n_heads * cfg.head_dim, cfg.q_lora_rank)
    assert (
        math.prod(w.layers[0].o_a.shape)
        == cfg.o_groups * cfg.o_lora_rank * cfg.n_heads * cfg.head_dim // cfg.o_groups
    )
    return w
