"""`kelpie::paged_attention` on vLLM 0.29.0's Triton unified attention (vendored/cuda/
vllm_attention holds the pin). What vLLM runs for gpt-oss on A100: its backend priority for sm80
is FLASH_ATTN (refuses sinks below sm90), FLASHINFER (sinks only on sm100/sm120), TRITON_ATTN.

The glue is vLLM's own TritonAttentionImpl.forward (v1/attention/backends/triton_attn.py at the
same tag), minus quantized KV: K and V are the member's two `[pages, block, Hkv, D]` views (the
kernel takes their strides, so the arena's interleaved layout is read in place), cu_seqlens_q is
the plan's query_start_loc, seqused_k its seq_lens, the window is (W - 1, 0) as vLLM passes a
sliding window, sinks go in as the per-head logits they already are.

Deliberate differences from vLLM:
  - pad rows: vLLM hands the kernel only real rows (q[:num_actual_tokens]); the op gets the
    padded T. The 2D kernel writes only rows some entry owns, so `out` starts zeroed and a pad
    row stays zero. The 3D path's reduce_segments runs over EVERY row and writes a pad row from
    segment scratch no kernel wrote (inf / NaN / garbage, measured: NOTES-attn.md), so the 3D
    result is masked by `row_request >= 0` -- one elementwise kernel over [T, H * D], T <= 16.
  - 2D vs 3D (split-KV "flash decoding") is picked from SHAPES, not from max_seqlen_q (a host
    value the op does not have): 3D when T == R (every decode bucket; a mixed prefill bucket
    can also land here, which is fine since 3D is correct for any query length), R <= vLLM's threshold (128 // Hkv), AND the layer has no
    window: a sliding layer reads at most W keys, so splitting them only adds the reduce
    (measured, gpt-oss decode R=8 graph replay: w128 2D 22.5 us vs 3D 33.8 on A100; w0 2D 41.0
    vs 3D 34.8). The 3D kernel is correct for any query lengths (same kernel; `split=` forces
    either path, and the bench runs every case both ways), so this choice is speed only.
  - the 3D path's per-segment scratch is allocated per call ([T, H, 16, D] fp32; T <= 16 rows,
    ~4 MiB at gpt-oss sizes), from the graph pool under capture; vLLM keeps one buffer.

No host sync, no data-dependent host control flow: captures.
"""

from __future__ import annotations

import torch

from kelpie_models.kernels.ops.paged_attention import write_kv

# vLLM triton_attn.py: MIN_LAUNCH_GRID_SIZE_2D and NUM_PAR_SOFTMAX_SEGMENTS.
MIN_LAUNCH_GRID_SIZE_2D = 128
NUM_PAR_SOFTMAX_SEGMENTS = 16
MIN_HEAD_DIM = 32  # vLLM TritonAttentionBackend.supports_head_size


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
    *,
    split: bool | None = None,
) -> torch.Tensor:
    """The op's contract (ops/paged_attention.py). `positions` is not read: the kernel derives
    each row's entry from query_start_loc and its position from seq_lens; `row_request` only
    masks the 3D path's pad rows. `split` forces 3D (True) or 2D (False); None picks by shape."""
    from kelpie_models.kernels.vendored.cuda.vllm_attention import unified_attention

    del positions
    # Cases the kernel computes DIFFERENTLY from the op contract, refused rather than served:
    # vLLM's non-causal window is two-sided (the reference's is left-only), it supports head
    # sizes >= 32 only (TritonAttentionBackend.supports_head_size), and fp32 would run its dots
    # in TF32.
    if not causal and window > 0:
        raise NotImplementedError("paged_attention[vllm_triton]: causal=False with a window "
                                  "(the kernel's window is two-sided there)")
    if q.shape[-1] < MIN_HEAD_DIM or q.dtype not in (torch.bfloat16, torch.float16):
        raise NotImplementedError(f"paged_attention[vllm_triton]: head_dim {q.shape[-1]} "
                                  f"(needs >= {MIN_HEAD_DIM}), dtype {q.dtype} (needs bf16/fp16)")
    write_kv(kv_member, k, v, slot_mapping)
    n_tokens, n_heads, head_dim = q.shape
    n_reqs, n_kv = seq_lens.shape[0], k.shape[1]
    assert q.stride(-1) == 1, q.stride()
    out = torch.zeros_like(q)
    threshold = MIN_LAUNCH_GRID_SIZE_2D // n_kv
    decode = n_tokens == n_reqs and n_reqs <= threshold and window == 0
    use_3d = decode if split is None else split
    segments = {}
    if use_3d:
        padded = 1 << (head_dim - 1).bit_length()
        scratch = (n_tokens, n_heads, NUM_PAR_SOFTMAX_SEGMENTS)
        segments = {
            "seq_threshold_3D": max(threshold, n_reqs),
            "num_par_softmax_segments": NUM_PAR_SOFTMAX_SEGMENTS,
            "softmax_segm_output": torch.empty(*scratch, padded, dtype=torch.float32,
                                               device=q.device),
            "softmax_segm_max": torch.empty(scratch, dtype=torch.float32, device=q.device),
            "softmax_segm_expsum": torch.empty(scratch, dtype=torch.float32, device=q.device),
        }
    unified_attention(
        q=q,
        k=kv_member[:, 0],
        v=kv_member[:, 1],
        out=out,
        cu_seqlens_q=query_start_loc,
        # Read only by the 2D/3D choice (a query longer than 1 forces 2D): 1 lets `segments`
        # decide, 2 forces 2D.
        max_seqlen_q=1 if use_3d else 2,
        seqused_k=seq_lens,
        max_seqlen_k=None,  # not read by the kernel wrapper
        softmax_scale=head_dim**-0.5,
        causal=causal,
        window_size=(window - 1, 0) if window > 0 else (-1, -1),
        block_table=block_table,
        softcap=0,
        q_descale=None,
        k_descale=None,
        v_descale=None,
        sinks=sinks if sinks.numel() > 0 else None,
        **segments,
    )
    out = out.view(n_tokens, n_heads * head_dim)
    if use_3d:
        out = torch.where((row_request >= 0)[:, None], out, 0.0)
    return out
