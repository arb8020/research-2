"""Dense masked softmax over concatenated per-request contexts, block-diagonal + causal mask.
vs. the jnp reference's per-token page gather: at (1024 tokens, 64 pages) that reference
materializes 4 GB/layer in fp32; this layout is 1 GB and R x larger than the useful triangle.
A production kernel would replace this with an NKI flash-attention over pages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from kelpie_models.jax.attention import KV, check_plan, no_refill, write_kv, zero_pad_rows
from kelpie_models.kernels.attention import AttentionBackend
from kelpie_models.kernels.backend import Workspace
from kelpie_models.plan import HostPlan, StepBatch
from kelpie_models.sdk.groups import Group, KVLayout, reference_kv_layout

if TYPE_CHECKING:
    from jax import Array


class BlockDiagonalAttention(AttentionBackend):
    name = "block_diagonal"

    @classmethod
    def eligible(cls, cfg: Any, device: str) -> list[str]:
        del cfg
        return [] if device == "neuron" else [f"requires neuron, got {device}"]

    def kv_layout(self, cfg: Any, group: Group, dtype: Any) -> KVLayout:
        del cfg
        return reference_kv_layout(group, np.dtype(dtype).itemsize)

    def prepare_workspace(self, batch: StepBatch, host: HostPlan, kv: list[KV]) -> None:
        check_plan(batch, host, kv)

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
        import jax
        import jax.numpy as jnp

        assert window == 0 and sinks is None, "sliding window / sinks: not wired to Trainium yet"
        kv = write_kv(kv, member, k, v, batch.slot_mapping[group])
        t_len, n_heads, head_dim = q.shape
        n_kv = k.shape[1]
        rep = n_heads // n_kv
        page = kv[member]
        block_size = page.shape[1]
        pages = batch.block_tables[group]
        n_reqs, pages_per_seq = pages.shape
        ctx = pages_per_seq * block_size
        rows = n_reqs * ctx
        kr = page[pages, :, 0::2, :].reshape(rows, n_kv, head_dim)
        vr = page[pages, :, 1::2, :].reshape(rows, n_kv, head_dim)

        t = jnp.arange(t_len, dtype=jnp.int32)
        seq = jnp.sum(t[:, None] >= batch.query_start_loc[None, 1:], axis=1, dtype=jnp.int32)
        seq = jnp.minimum(seq, n_reqs - 1)  # pad tokens land on the last (pad) request; masked
        kv_len = batch.seq_lens[seq]
        qpos = kv_len - (batch.query_start_loc[seq + 1] - t)  # position in its context
        r_of_row = jnp.arange(rows, dtype=jnp.int32) // ctx
        kpos = jnp.arange(rows, dtype=jnp.int32) % ctx
        mask = (
            (r_of_row[None, :] == seq[:, None])
            & (kpos[None, :] < kv_len[:, None])
            & (kpos[None, :] <= qpos[:, None])
        )

        qf = q.astype(jnp.float32).reshape(t_len, n_kv, rep, head_dim)
        scores = jnp.einsum("tgrd,cgd->tgrc", qf, kr.astype(jnp.float32)) * head_dim**-0.5
        scores = jnp.where(mask[:, None, None, :], scores, -jnp.inf)
        probs = jax.nn.softmax(scores, axis=-1)
        o = jnp.einsum("tgrc,cgd->tgrd", probs, vr.astype(jnp.float32))
        o = o.reshape(t_len, n_heads * head_dim).astype(q.dtype)
        return zero_pad_rows(o, batch), kv
