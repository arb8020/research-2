"""kelpie::dsa_indexer_topk -- DeepSeek's lightning indexer.

Scores one key per token per query and returns the top-`k` token indices attention may
see (DeepSeek-V3.2's DSA, reused by V4-Flash's CSA layers).
"""

from __future__ import annotations

import torch

from kelpie_models.kernels.op import mutates, op


@op
@mutates("indexer_member")
def dsa_indexer_topk(q: torch.Tensor,
    indexer_member: torch.Tensor,
    query_start_loc: torch.Tensor,
    seq_lens: torch.Tensor,
    block_table: torch.Tensor,
    slot_mapping: torch.Tensor,
    n_reqs: int,
    topk: int,) -> torch.Tensor:
    """q [T, H, D]; `indexer_member` the per-token index cache, written at `slot_mapping`.
    -> i32 [T, topk], the token indices attention is allowed to gather."""
    del q, indexer_member, query_start_loc, seq_lens, block_table, slot_mapping, n_reqs, topk
    raise NotImplementedError(
        "dsa_indexer_topk: reference body not written; the reference is rasbt's DSA teaching code, not ported yet, and then a vendored kernel"
    )


@dsa_indexer_topk.register_fake
def _fake(q: torch.Tensor,
    indexer_member: torch.Tensor,
    query_start_loc: torch.Tensor,
    seq_lens: torch.Tensor,
    block_table: torch.Tensor,
    slot_mapping: torch.Tensor,
    n_reqs: int,
    topk: int,) -> torch.Tensor:
    del indexer_member, query_start_loc, seq_lens, block_table, slot_mapping, n_reqs
    return torch.empty(q.shape[0], topk, dtype=torch.int32, device=q.device)


@dsa_indexer_topk.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    raise NotImplementedError(
        "dsa_indexer_topk.sample_args: needs the reference body first -- args with no runnable "
        "reference cannot be opchecked or compared"
    )


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


dsa_indexer_topk.register_autograd(_backward)



@dsa_indexer_topk.register("nki", source="kernels.vendored.neuron._dense")
def _nki(*args: object) -> torch.Tensor:
    del args
    raise NotImplementedError(
        "dsa_indexer_topk[nki]: vendored but unimported until the torch-neuronx port lands"
    )


@dsa_indexer_topk.register("pallas", source="kernels.vendored.tpu._pallas")
def _pallas(*args: object) -> torch.Tensor:
    del args
    raise NotImplementedError(
        "dsa_indexer_topk[pallas]: vendored but unimported until the torchax port lands"
    )
