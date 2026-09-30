"""jax.experimental.pallas ragged_paged_attention. Kernel constraints (jax==0.11.1):
- kv_pages [num_pages, page_size, 2 * n_kv_heads, head_dim], k/v interleaved on the head axis,
  one array per layer.
- kv_lens, page_indices, cu_q_lens int32; num_seqs i32[1]; len(cu_q_lens) == len(kv_lens) + 1.
- num_kv_pages_per_block <= pages_per_seq; num_queries_per_block <= padded_num_tokens.
- head_dim must be >= 128 (kernel.py:570 asserts on the l/m scratch, 128 lanes); 2 * n_kv_heads /
  packing must be in {1, 2, 4, 8} or a multiple of 8 (can_be_xla_fully_tiled); the q block
  (get_min_heads_per_blk) must be a multiple of 8 or the whole array (Mosaic block rule).
  head_plan() searches the smallest accepted (q heads, kv heads, head_dim) padding.
- output rows past cu_q_lens[num_seqs] are unspecified: masked to zero here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from kelpie_models.jax.attention import KV, check_plan, no_refill, write_kv, zero_pad_rows
from kelpie_models.kernels.attention import AttentionBackend
from kelpie_models.kernels.backend import Workspace
from kelpie_models.plan import HostPlan, StepBatch
from kelpie_models.sdk.groups import Group, KVLayout, reference_kv_layout

if TYPE_CHECKING:
    from jax import Array

DEFAULT_KV_PAGES_PER_BLOCK = 8
DEFAULT_QUERIES_PER_BLOCK = 32
MIN_HEAD_DIM = 128
KV_MEMBER_RANK = 2


@dataclass(frozen=True)
class RPAWorkspace:
    num_kv_pages_per_block: int
    num_queries_per_block: int


class RPAAttention(AttentionBackend):
    name = "rpa"

    @classmethod
    def eligible(cls, cfg: Any, device: str) -> list[str]:
        reasons = [] if device == "tpu" else [f"requires tpu, got {device}"]
        if getattr(cfg, "head_dim", 128) <= 0:
            reasons.append("head_dim must be positive")
        return reasons

    def kv_layout(self, cfg: Any, group: Group, dtype: Any) -> KVLayout:
        _, n_kv, head_dim = head_plan(cfg.n_heads, cfg.n_kv_heads, cfg.head_dim, dtype)
        ref = reference_kv_layout(group, np.dtype(dtype).itemsize)
        rows = tuple((2 * n_kv, head_dim) if len(r) == KV_MEMBER_RANK else r for r in ref.rows)
        assert len(rows) == len(ref.rows)
        return KVLayout(rows)

    def prepare_workspace(self, batch: StepBatch, host: HostPlan, kv: list[KV]) -> RPAWorkspace:
        check_plan(batch, host, kv)
        pages_per_seq = int(batch.block_tables[0].shape[1])
        return RPAWorkspace(
            num_kv_pages_per_block=min(DEFAULT_KV_PAGES_PER_BLOCK, pages_per_seq),
            num_queries_per_block=min(DEFAULT_QUERIES_PER_BLOCK, batch.padded_num_tokens),
        )

    def copy_workspace(self, dst: Workspace, src: Workspace) -> None:
        raise AssertionError(no_refill(self))

    def forward(  # noqa: PLR0913, PLR0917
        self,
        q: Array,
        k: Array,
        v: Array,
        batch: StepBatch,
        kv: KV,
        member: int,
        group: int = 0,
        window: int = 0,
        sinks: Array | None = None,
    ) -> tuple[Array, KV]:
        from jax.experimental.pallas.ops.tpu.ragged_paged_attention import ragged_paged_attention

        ws = batch.attn[group].workspace
        assert isinstance(ws, RPAWorkspace), "batch was not prepared by RPAAttention"
        assert window == 0 and sinks is None, "sliding window / sinks: not wired to the kernel yet"
        t_len, n_heads, head_dim = q.shape
        n_kv = k.shape[1]
        n_kv_pad, head_dim_pad = kv[member].shape[3], kv[member].shape[4]  # [pages, 2, block, Hkv, D]
        n_q_pad, _, _ = head_plan(n_heads, n_kv, head_dim, q.dtype)
        q = pad_q_heads(q, n_kv, n_kv_pad, n_q_pad // n_kv_pad, head_dim_pad)
        k = pad_heads(k, n_kv_pad, head_dim_pad)
        v = pad_heads(v, n_kv_pad, head_dim_pad)
        kv = write_kv(kv, member, k, v, batch.slot_mapping[group])
        o = ragged_paged_attention(
            q,
            kv[member],
            batch.seq_lens,
            batch.block_tables[group],
            batch.query_start_loc,
            batch.num_seqs,
            sm_scale=head_dim**-0.5,
            num_kv_pages_per_block=ws.num_kv_pages_per_block,
            num_queries_per_block=ws.num_queries_per_block,
        )
        rep = n_heads // n_kv
        o = o.reshape(t_len, n_kv_pad, n_q_pad // n_kv_pad, head_dim_pad)[:, :n_kv, :rep, :head_dim]
        o = o.reshape(t_len, n_heads * head_dim)
        return zero_pad_rows(o, batch), kv


def head_plan(n_heads: int, n_kv_heads: int, head_dim: int, dtype: Any) -> tuple[int, int, int]:
    rep = n_heads // n_kv_heads
    best = None
    for n_kv in range(n_kv_heads, n_kv_heads + 9):
        for ratio in range(rep, rep + 3):
            n_q = ratio * n_kv
            if kernel_accepts(n_q, n_kv, dtype) and (
                best is None or n_q * n_kv < best[0] * best[1]
            ):
                best = (n_q, n_kv)
    assert best is not None, (n_heads, n_kv_heads, dtype)
    return best[0], best[1], max(head_dim, MIN_HEAD_DIM)


def kernel_accepts(n_q: int, n_kv: int, dtype: Any) -> bool:
    import jax.numpy as jnp
    from jax.experimental.pallas.ops.tpu.ragged_paged_attention.kernel import (
        get_min_heads_per_blk,
    )

    try:
        q_blk, _ = get_min_heads_per_blk(n_q, 2 * n_kv, jnp.dtype(dtype), jnp.dtype(dtype))
    except ValueError:  # not XLA fully tiled
        return False
    return q_blk % 8 == 0 or q_blk == n_q


def pad_heads(x: Array, n_heads: int, head_dim: int) -> Array:
    import jax.numpy as jnp

    t, h, d = x.shape
    if (h, d) == (n_heads, head_dim):
        return x
    return jnp.pad(x, ((0, 0), (0, n_heads - h), (0, head_dim - d)))


def pad_q_heads(q: Array, n_kv: int, n_kv_pad: int, ratio_pad: int, head_dim_pad: int) -> Array:
    # kernel groups q heads as [Hkv, ratio]; q head (g, r) must stay on kv head g after padding.
    import jax.numpy as jnp

    t, h, d = q.shape
    rep = h // n_kv
    g = q.reshape(t, n_kv, rep, d)
    g = jnp.pad(g, ((0, 0), (0, n_kv_pad - n_kv), (0, ratio_pad - rep), (0, head_dim_pad - d)))
    return g.reshape(t, n_kv_pad * ratio_pad, head_dim_pad)
