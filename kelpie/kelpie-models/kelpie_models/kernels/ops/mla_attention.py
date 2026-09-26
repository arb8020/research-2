"""kelpie::mla_attention -- DeepSeek-style multi-head latent attention.

Attention over a compressed per-token latent cache: Kimi's 7 MLA-no-RoPE layers, and
DeepSeek-V3.2 / V4-Flash's compressed KV. Shares this family's plan tensors with
`paged_attention` but not its signature -- attention is a family of ops, not one signature.
"""

from __future__ import annotations

import torch

from kelpie_models.kernels.op import mutates, op


@op
@mutates("kv_member")
def mla_attention(q: torch.Tensor,
    latent: torch.Tensor,
    kv_member: torch.Tensor,
    query_start_loc: torch.Tensor,
    seq_lens: torch.Tensor,
    block_table: torch.Tensor,
    slot_mapping: torch.Tensor,
    n_reqs: int,) -> torch.Tensor:
    """q [T, H, D]; `latent` [T, L] this step's compressed rows, scattered into `kv_member`
    at `slot_mapping`. Plan tensors as `paged_attention` documents them. -> [T, H * D]."""
    del q, latent, kv_member, query_start_loc, seq_lens, block_table, slot_mapping, n_reqs
    raise NotImplementedError(
        "mla_attention: reference body not written; the FlashInfer MLA source it wraps is not a dependency of this tree yet"
    )


@mla_attention.register_fake
def _fake(q: torch.Tensor,
    latent: torch.Tensor,
    kv_member: torch.Tensor,
    query_start_loc: torch.Tensor,
    seq_lens: torch.Tensor,
    block_table: torch.Tensor,
    slot_mapping: torch.Tensor,
    n_reqs: int,) -> torch.Tensor:
    del latent, kv_member, query_start_loc, seq_lens, block_table, slot_mapping, n_reqs
    return torch.empty(q.shape[0], q.shape[1] * q.shape[2], dtype=q.dtype, device=q.device)


@mla_attention.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    raise NotImplementedError(
        "mla_attention.sample_args: needs the reference body first -- args with no runnable "
        "reference cannot be opchecked or compared"
    )


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


mla_attention.register_autograd(_backward)



@mla_attention.register("flashinfer", source="flashinfer.mla")
def _flashinfer(*args: object) -> torch.Tensor:
    del args
    raise NotImplementedError(
        "mla_attention[flashinfer]: not a dependency of this tree yet"
    )
