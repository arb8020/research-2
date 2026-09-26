"""FlashInfer paged attention adapter.

Bridges kelpie's paged_attention op contract to FlashInfer's BatchDecode/BatchPrefill
wrappers. The translation is metadata-only — the KV data itself is a view (no copy).

INTERFACE DIFFERENCES (kelpie → FlashInfer):

  KV layout:   kelpie [pages, 2, block, Hkv, D]  =  FlashInfer NHD (same, no copy needed).

  Page table:  kelpie block_table i32[R, P] (dense, padded with 0s beyond seq)
               → FlashInfer CSR: indptr i32[R+1], indices i32[sum(n_pages)], last_page_len i32[R]

  Queries:     kelpie query_start_loc i32[R+1]  →  FlashInfer qo_indptr (same thing)

FlashInfer requires a plan() call before each run(). The wrapper is allocated once (per layer
in practice, but this adapter creates one per call — the cost is ~50μs per plan(), dwarfed
by the kernel itself). If profiling shows plan() overhead matters, cache the wrapper.
"""

from __future__ import annotations

import torch

# Lazy import so the module can be loaded without flashinfer installed (for config parsing).
_fi = None


def _ensure_flashinfer():
    global _fi
    if _fi is None:
        import flashinfer
        _fi = flashinfer


def _dense_to_csr(
    block_table: torch.Tensor,
    seq_lens: torch.Tensor,
    block_size: int,
    n_reqs: int,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Convert kelpie's dense block_table [R, P] + seq_lens [R] to FlashInfer's CSR format.

    Returns (indptr, indices, last_page_len), all i32 on the same device.
    Only the first `n_reqs` rows are real; the rest are padding.
    """
    device = block_table.device

    # Number of pages per request: ceil(seq_len / block_size)
    real_seq = seq_lens[:n_reqs].int()
    n_pages_per_req = (real_seq + block_size - 1) // block_size  # i32[n_reqs]

    # indptr: cumulative sum with leading 0
    indptr = torch.zeros(n_reqs + 1, dtype=torch.int32, device=device)
    torch.cumsum(n_pages_per_req, dim=0, out=indptr[1:])

    # indices: gather the page IDs from the dense table
    total_pages = int(indptr[-1].item())
    indices = torch.empty(total_pages, dtype=torch.int32, device=device)
    offset = 0
    for r in range(n_reqs):
        np = int(n_pages_per_req[r].item())
        indices[offset : offset + np] = block_table[r, :np]
        offset += np

    # last_page_len: how many tokens are in the last page of each request
    last_page_len = ((real_seq - 1) % block_size + 1).to(torch.int32)

    return indptr, indices, last_page_len


def paged_attention(  # noqa: PLR0913, PLR0917
    q: torch.Tensor,
    k: torch.Tensor,
    v: torch.Tensor,
    kv_member: torch.Tensor,
    row_request: torch.Tensor,
    positions: torch.Tensor,
    seq_lens: torch.Tensor,
    block_table: torch.Tensor,
    slot_mapping: torch.Tensor,
    window: int,
    sinks: torch.Tensor,
) -> torch.Tensor:
    """FlashInfer paged attention — same signature as kelpie::paged_attention.

    Writes k/v into the cache at slot_mapping, then runs FlashInfer's decode or prefill
    kernel depending on whether queries are single-token (decode) or multi-token (prefill).
    """
    _ensure_flashinfer()
    from kelpie_models.kernels.ops.paged_attention import write_kv

    # Write this step's k/v into the paged cache.
    write_kv(kv_member, k, v, slot_mapping)

    n_tokens, n_heads, head_dim = q.shape
    n_kv_heads = k.shape[1]
    block_size = kv_member.shape[2]  # [pages, 2, block, Hkv, D]

    # Determine how many real requests (non-pad rows).
    live = row_request >= 0
    n_reqs = int(live.any(dim=0).sum().item()) if live.dim() > 1 else int((row_request >= 0).sum().item())

    # Use query_start_loc to find n_reqs properly: count entries with >0 tokens.
    # row_request maps each token to its request; unique non-negative values = real requests.
    real_req_ids = row_request[live].unique()
    n_reqs = len(real_req_ids)

    if n_reqs == 0:
        return torch.zeros(n_tokens, n_heads * head_dim, dtype=q.dtype, device=q.device)

    # KV is already [pages, 2, block, Hkv, D] — FlashInfer's NHD layout.
    kv_data = kv_member

    # Convert dense block table to CSR.
    indptr, indices, last_page_len = _dense_to_csr(block_table, seq_lens, block_size, n_reqs)

    # Workspace buffer for FlashInfer (~128MB).
    workspace = torch.empty(128 * 1024 * 1024, dtype=torch.uint8, device=q.device)

    # Decide decode vs prefill: decode = 1 token per request, prefill = variable.
    is_decode = (n_tokens == n_reqs)

    if is_decode:
        wrapper = _fi.decode.BatchDecodeWithPagedKVCacheWrapper(
            workspace, kv_layout="NHD",
        )
        wrapper.plan(
            indptr=indptr,
            indices=indices,
            last_page_len=last_page_len,
            num_qo_heads=n_heads,
            num_kv_heads=n_kv_heads,
            head_dim=head_dim,
            page_size=block_size,
            q_data_type=q.dtype,
            kv_data_type=kv_member.dtype,
        )
        # Decode q: [batch, heads, dim] — FlashInfer wants one token per request.
        # Extract the live tokens only.
        q_live = q[live]  # [n_reqs, n_heads, head_dim]
        out_live = wrapper.run(q_live, kv_data).reshape(-1, n_heads * head_dim)

        # Scatter back into the full output.
        out = torch.zeros(n_tokens, n_heads * head_dim, dtype=q.dtype, device=q.device)
        out[live] = out_live.to(q.dtype)
        return out

    else:
        # Prefill: variable tokens per request.
        # Build qo_indptr from row_request: count tokens per request.
        qo_lens = torch.zeros(n_reqs, dtype=torch.int32, device=q.device)
        for i, req_id in enumerate(real_req_ids):
            qo_lens[i] = (row_request == req_id).sum()
        qo_indptr = torch.zeros(n_reqs + 1, dtype=torch.int32, device=q.device)
        torch.cumsum(qo_lens, dim=0, out=qo_indptr[1:])

        wrapper = _fi.prefill.BatchPrefillWithPagedKVCacheWrapper(
            workspace, kv_layout="NHD",
        )
        wrapper.plan(
            qo_indptr=qo_indptr,
            paged_kv_indptr=indptr,
            paged_kv_indices=indices,
            paged_kv_last_page_len=last_page_len,
            num_qo_heads=n_heads,
            num_kv_heads=n_kv_heads,
            head_dim_qk=head_dim,
            page_size=block_size,
            causal=True,
            q_data_type=q.dtype,
            kv_data_type=kv_member.dtype,
        )
        # Gather live tokens in request order.
        q_live = q[live]  # [sum(qo_lens), n_heads, head_dim]
        out_live = wrapper.run(q_live, kv_data).reshape(-1, n_heads * head_dim)

        out = torch.zeros(n_tokens, n_heads * head_dim, dtype=q.dtype, device=q.device)
        out[live] = out_live.to(q.dtype)
        return out
