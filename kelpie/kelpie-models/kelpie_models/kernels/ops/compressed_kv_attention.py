"""kelpie::compressed_kv_attention -- DeepSeek-V4-Flash's CSA / HCA.

Attention over a stride-`ratio` compressed KV table, gathered at `indices` (the indexer's
top-k for CSA, every entry for HCA).
"""

from __future__ import annotations

import torch

from kelpie_models.kernels.op import mutates, op


@op
@mutates("kv_member")
def compressed_kv_attention(q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    kv_member: torch.Tensor,
    indices: torch.Tensor,
    query_start_loc: torch.Tensor,
    seq_lens: torch.Tensor,
    block_table: torch.Tensor,
    slot_mapping: torch.Tensor,
    n_reqs: int,
    ratio: int,) -> torch.Tensor:
    """q [T, H, D], k/v [T, Hkv, D]; `indices` i32 [T, topk] the rows this query may see;
    `ratio` the compression stride. Plan tensors as `paged_attention` documents them.
    -> [T, H * D]."""
    del q, k, v, kv_member, indices, query_start_loc, seq_lens, block_table
    del slot_mapping, n_reqs, ratio
    raise NotImplementedError(
        "compressed_kv_attention: reference body not written; the FlashInfer source it wraps is not a dependency of this tree yet"
    )


@compressed_kv_attention.register_fake
def _fake(q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    kv_member: torch.Tensor,
    indices: torch.Tensor,
    query_start_loc: torch.Tensor,
    seq_lens: torch.Tensor,
    block_table: torch.Tensor,
    slot_mapping: torch.Tensor,
    n_reqs: int,
    ratio: int,) -> torch.Tensor:
    del k, v, kv_member, indices, query_start_loc, seq_lens, block_table
    del slot_mapping, n_reqs, ratio
    return torch.empty(q.shape[0], q.shape[1] * q.shape[2], dtype=q.dtype, device=q.device)


@compressed_kv_attention.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    raise NotImplementedError(
        "compressed_kv_attention.sample_args: needs the reference body first -- args with no runnable "
        "reference cannot be opchecked or compared"
    )


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


compressed_kv_attention.register_autograd(_backward)



@compressed_kv_attention.register("flashinfer", source="flashinfer.mla")
def _flashinfer(*args: object) -> torch.Tensor:
    del args
    raise NotImplementedError(
        "compressed_kv_attention[flashinfer]: not a dependency of this tree yet"
    )
