# Copyright 2023-2024 SGLang Team
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import math

import torch

KIND_DECODE = 1  # KELPIE_KIND_DECODE (kelpie-core/include/kelpie.h)

NEG_INF = -math.inf
MAX_HEAD_DIM = 256


def _kernel():  # noqa: PLR0915 -- two colocated Triton programs share one lazy import
    try:
        import triton
        import triton.language as tl
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("the cuda_triton kernel set requires Triton") from exc

    @triton.jit
    def paged_decode_kernel(  # noqa: PLR0913, PLR0917
        q,
        cache,
        block_tables,
        seq_lens,
        query_start_loc,
        kinds,
        num_drafts,
        sinks,
        out,
        stride_qt: tl.constexpr,
        stride_qh: tl.constexpr,
        stride_qd: tl.constexpr,
        stride_cb: tl.constexpr,
        stride_ct: tl.constexpr,
        stride_ch: tl.constexpr,
        stride_cd: tl.constexpr,
        stride_br: tl.constexpr,
        stride_bp: tl.constexpr,
        stride_ot: tl.constexpr,
        stride_oh: tl.constexpr,
        stride_od: tl.constexpr,
        H_Q: tl.constexpr,
        H_KV: tl.constexpr,
        D: tl.constexpr,
        BLOCK_SIZE: tl.constexpr,
        WINDOW: tl.constexpr,
        HAS_SINKS: tl.constexpr,
        NEGATIVE_INFINITY: tl.constexpr,
        KIND_DECODE_CONST: tl.constexpr,
        BLOCK_N: tl.constexpr,
    ):
        # One program per request slot of the padded plan. The partition is read here, from the
        # core's own per-request decision -- never rebuilt on the host, and never inferred from a
        # row count (kernels/backend.py check_kinds). This kernel reads a single query row, so it
        # serves a decode with no drafts; every other entry (a prefill, even a one-row one; a
        # decode verifying drafts) is the prefill kernel's, which grids over rows.
        request = tl.program_id(0)
        kv_head = tl.program_id(1)
        kind = tl.load(kinds + request)
        # `n_draft`, not `k`: `k` is the key tile of the loop below, and Triton's loop-carried
        # type check rejects the shadow.
        n_draft = tl.load(num_drafts + request)
        if kind != KIND_DECODE_CONST or n_draft != 0:
            return
        query_row = tl.load(query_start_loc + request)
        seq = tl.load(seq_lens + request)
        start = tl.maximum(0, seq - WINDOW) if WINDOW > 0 else 0
        first_tile = (start // BLOCK_N) * BLOCK_N
        d = tl.arange(0, D)
        for repeated_head in tl.static_range(0, H_Q // H_KV):
            query_head = kv_head * (H_Q // H_KV) + repeated_head
            qv = tl.load(q + query_row * stride_qt + query_head * stride_qh + d * stride_qd)
            if HAS_SINKS == 1:
                m = tl.load(sinks + query_head).to(tl.float32)
                denom = 1.0
            else:
                m, denom = NEGATIVE_INFINITY, 0.0
            acc = tl.zeros((D,), tl.float32)
            for base in range(first_tile, tl.cdiv(seq, BLOCK_N) * BLOCK_N, BLOCK_N):
                pos = base + tl.arange(0, BLOCK_N)
                valid = (pos >= start) & (pos < seq)
                logical_block = pos // BLOCK_SIZE
                block = tl.load(
                    block_tables + request * stride_br + logical_block * stride_bp,
                    mask=valid,
                    other=0,
                )
                token = pos % BLOCK_SIZE
                k_ptr = (
                    cache
                    + block[:, None] * stride_cb
                    + token[:, None] * stride_ct
                    + (2 * kv_head) * stride_ch
                    + d[None, :] * stride_cd
                )
                k = tl.load(k_ptr, mask=valid[:, None], other=0.0)
                logits = tl.sum(k.to(tl.float32) * qv[None, :].to(tl.float32), axis=1)
                logits = tl.where(valid, logits * (D**-0.5), NEGATIVE_INFINITY)
                tile_m = tl.max(logits, axis=0)
                new_m = tl.maximum(m, tile_m)
                alpha = tl.where(m == NEGATIVE_INFINITY, 0.0, tl.exp(m - new_m))
                p = tl.exp(logits - new_m)
                denom = denom * alpha + tl.sum(p, axis=0)
                v = tl.load(k_ptr + stride_ch, mask=valid[:, None], other=0.0)
                acc = acc * alpha + tl.sum(p[:, None] * v.to(tl.float32), axis=0)
                m = new_m
            tl.store(
                out + query_row * stride_ot + query_head * stride_oh + d * stride_od, acc / denom
            )

    # Adapted from SGLang's Apache-2.0 extend-attention online-softmax kernel:
    # python/sglang/kernels/ops/attention/extend_attention.py::_fwd_kernel at
    # 19c7679e9e9c6f36e0ede15c0900ab3c63fafdd5.
    @triton.jit
    def paged_prefill_kernel(  # noqa: PLR0913, PLR0917
        q,
        cache,
        block_tables,
        seq_lens,
        query_start_loc,
        request_for_row,
        kinds,
        num_drafts,
        sinks,
        out,
        stride_qt: tl.constexpr,
        stride_qh: tl.constexpr,
        stride_qd: tl.constexpr,
        stride_cb: tl.constexpr,
        stride_ct: tl.constexpr,
        stride_ch: tl.constexpr,
        stride_cd: tl.constexpr,
        stride_br: tl.constexpr,
        stride_bp: tl.constexpr,
        stride_ot: tl.constexpr,
        stride_oh: tl.constexpr,
        stride_od: tl.constexpr,
        H_Q: tl.constexpr,
        H_KV: tl.constexpr,
        D: tl.constexpr,
        BLOCK_SIZE: tl.constexpr,
        WINDOW: tl.constexpr,
        HAS_SINKS: tl.constexpr,
        NEGATIVE_INFINITY: tl.constexpr,
        KIND_DECODE_CONST: tl.constexpr,
        BLOCK_N: tl.constexpr,
    ):
        # One program per row of the padded plan. row_request is the core's: -1 for a pad row.
        # A row belonging to a no-draft decode is the decode kernel's, so it returns here.
        row = tl.program_id(0)
        kv_head = tl.program_id(1)
        request = tl.load(request_for_row + row)
        if request < 0:
            return
        kind = tl.load(kinds + request)
        n_draft = tl.load(num_drafts + request)
        if kind == KIND_DECODE_CONST and n_draft == 0:
            return
        q0 = tl.load(query_start_loc + request)
        q1 = tl.load(query_start_loc + request + 1)
        seq = tl.load(seq_lens + request)
        end = seq - (q1 - q0) + (row - q0) + 1
        start = tl.maximum(0, end - WINDOW) if WINDOW > 0 else 0
        first_tile = (start // BLOCK_N) * BLOCK_N
        d = tl.arange(0, D)
        for repeated_head in tl.static_range(0, H_Q // H_KV):
            query_head = kv_head * (H_Q // H_KV) + repeated_head
            qv = tl.load(q + row * stride_qt + query_head * stride_qh + d * stride_qd)
            if HAS_SINKS == 1:
                m = tl.load(sinks + query_head).to(tl.float32)
                denom = 1.0
            else:
                m, denom = NEGATIVE_INFINITY, 0.0
            acc = tl.zeros((D,), tl.float32)
            for base in range(first_tile, tl.cdiv(end, BLOCK_N) * BLOCK_N, BLOCK_N):
                pos = base + tl.arange(0, BLOCK_N)
                valid = (pos >= start) & (pos < end)
                logical_block = pos // BLOCK_SIZE
                block = tl.load(
                    block_tables + request * stride_br + logical_block * stride_bp,
                    mask=valid,
                    other=0,
                )
                token = pos % BLOCK_SIZE
                k_ptr = (
                    cache
                    + block[:, None] * stride_cb
                    + token[:, None] * stride_ct
                    + (2 * kv_head) * stride_ch
                    + d[None, :] * stride_cd
                )
                k = tl.load(k_ptr, mask=valid[:, None], other=0.0)
                logits = tl.sum(k.to(tl.float32) * qv[None, :].to(tl.float32), axis=1)
                logits = tl.where(valid, logits * (D**-0.5), NEGATIVE_INFINITY)
                tile_m = tl.max(logits, axis=0)
                new_m = tl.maximum(m, tile_m)
                alpha = tl.where(m == NEGATIVE_INFINITY, 0.0, tl.exp(m - new_m))
                p = tl.exp(logits - new_m)
                denom = denom * alpha + tl.sum(p, axis=0)
                v = tl.load(k_ptr + stride_ch, mask=valid[:, None], other=0.0)
                acc = acc * alpha + tl.sum(p[:, None] * v.to(tl.float32), axis=0)
                m = new_m
            tl.store(out + row * stride_ot + query_head * stride_oh + d * stride_od, acc / denom)

    return paged_decode_kernel, paged_prefill_kernel


_PAGED_DECODE = None
_PAGED_PREFILL = None
_RMS_NORM = None
_ROPE = None
_SILU_MUL = None
_SAMPLE = None


def _elementwise_kernels():  # noqa: PLR0915
    try:
        import triton
        import triton.language as tl
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("the cuda_triton kernel set requires Triton") from exc

    @triton.jit
    def rms_norm_kernel(
        x, weight, out, width: tl.constexpr, eps: tl.constexpr, BLOCK: tl.constexpr
    ):
        row = tl.program_id(0)
        col = tl.arange(0, BLOCK)
        mask = col < width
        value = tl.load(x + row * width + col, mask=mask, other=0.0).to(tl.float32)
        inv = tl.rsqrt(tl.sum(value * value, axis=0) / width + eps)
        scale = tl.load(weight + col, mask=mask, other=0.0)
        tl.store(out + row * width + col, value * inv * scale, mask=mask)

    @triton.jit
    def rope_kernel(
        x, cos, sin, out, heads: tl.constexpr, width: tl.constexpr, BLOCK: tl.constexpr
    ):
        row = tl.program_id(0)
        token = row // heads
        col = tl.arange(0, BLOCK)
        mask = col < width
        half = width // 2
        other = tl.where(col < half, col + half, col - half)
        value = tl.load(x + row * width + col, mask=mask, other=0.0)
        rotated = tl.load(x + row * width + other, mask=mask, other=0.0)
        rotated = tl.where(col < half, -rotated, rotated)
        c = tl.load(cos + token * width + col, mask=mask, other=0.0)
        s = tl.load(sin + token * width + col, mask=mask, other=0.0)
        tl.store(out + row * width + col, value * c + rotated * s, mask=mask)

    @triton.jit
    def silu_mul_kernel(gate, up, out, n_elements: tl.constexpr, BLOCK: tl.constexpr):
        offsets = tl.program_id(0) * BLOCK + tl.arange(0, BLOCK)
        mask = offsets < n_elements
        g = tl.load(gate + offsets, mask=mask).to(tl.float32)
        u = tl.load(up + offsets, mask=mask)
        tl.store(out + offsets, (g / (1.0 + tl.exp(-g))) * u, mask=mask)

    @triton.jit
    def sample_kernel(  # noqa: PLR0913, PLR0917
        logits,
        temperatures,
        key,
        logit_mask,
        tokens,
        accepted,
        vocab: tl.constexpr,
        words: tl.constexpr,
        BLOCK: tl.constexpr,
    ):
        row = tl.program_id(0)
        temperature = tl.load(temperatures + row)
        key0 = tl.load(key).to(tl.uint64)
        key1 = tl.load(key + 1).to(tl.uint64)
        best = -1.0e30
        best_id = 0
        for base in range(0, vocab, BLOCK):
            ids = base + tl.arange(0, BLOCK)
            valid = ids < vocab
            allowed = valid
            if words > 0:
                word = tl.load(logit_mask + row * words + ids // 32, mask=valid, other=0)
                allowed &= ((word >> (ids % 32)) & 1) != 0
            score = tl.load(logits + row * vocab + ids, mask=valid, other=-1.0e30).to(tl.float32)
            if temperature > 0.0:
                c0 = tl.full((BLOCK,), row, tl.uint64)
                c1 = tl.zeros((BLOCK,), tl.uint64)
                c2 = ids.to(tl.uint64)
                c3 = tl.zeros((BLOCK,), tl.uint64)
                k0, k1 = key0, key1
                for philox_round in tl.static_range(0, 10):
                    if philox_round > 0:
                        k0 = (k0 + 0x9E3779B9) & 0xFFFFFFFF
                        k1 = (k1 + 0xBB67AE85) & 0xFFFFFFFF
                    p0 = c0 * 0xD2511F53
                    p1 = c2 * 0xCD9E8D57
                    hi0, lo0 = (p0 >> 32) & 0xFFFFFFFF, p0 & 0xFFFFFFFF
                    hi1, lo1 = (p1 >> 32) & 0xFFFFFFFF, p1 & 0xFFFFFFFF
                    c0, c1, c2, c3 = (
                        (hi1 ^ c1 ^ k0) & 0xFFFFFFFF,
                        lo1,
                        (hi0 ^ c3 ^ k1) & 0xFFFFFFFF,
                        lo0,
                    )
                uniform = ((c0 & 0xFFFFFF).to(tl.float32) + 0.5) * (1.0 / (1 << 24))
                score = score / temperature - tl.log(-tl.log(uniform))
            score = tl.where(allowed, score, -1.0e30)
            tile_best = tl.max(score, axis=0)
            tile_id = tl.min(tl.where(score == tile_best, ids, vocab), axis=0)
            replace = (tile_best > best) | ((tile_best == best) & (tile_id < best_id))
            best = tl.where(replace, tile_best, best)
            best_id = tl.where(replace, tile_id, best_id)
        tl.store(tokens + row, tl.where(best == -1.0e30, 0, best_id))  # noqa: PLR2004
        tl.store(accepted + row, 0)

    return rms_norm_kernel, rope_kernel, silu_mul_kernel, sample_kernel


def _ensure_elementwise_kernels():
    global _RMS_NORM, _ROPE, _SILU_MUL, _SAMPLE
    if _RMS_NORM is None:
        _RMS_NORM, _ROPE, _SILU_MUL, _SAMPLE = _elementwise_kernels()


def rms_norm(x: torch.Tensor, weight: torch.Tensor, eps: float) -> torch.Tensor:
    import triton

    _ensure_elementwise_kernels()
    width = x.shape[-1]
    out = torch.empty_like(x)
    _RMS_NORM[(x.numel() // width,)](
        x,
        weight,
        out,
        width=width,
        eps=eps,
        BLOCK=triton.next_power_of_2(width),
        num_warps=4,
    )
    return out


def rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    import triton

    _ensure_elementwise_kernels()
    out = torch.empty_like(x)
    _ROPE[(x.shape[0] * x.shape[1],)](
        x,
        cos,
        sin,
        out,
        heads=x.shape[1],
        width=x.shape[2],
        BLOCK=triton.next_power_of_2(x.shape[2]),
        num_warps=1,
    )
    return out


def silu_mul(gate: torch.Tensor, up: torch.Tensor) -> torch.Tensor:
    import triton

    _ensure_elementwise_kernels()
    out = torch.empty_like(gate)
    block = 256
    _SILU_MUL[(triton.cdiv(gate.numel(), block),)](
        gate,
        up,
        out,
        n_elements=gate.numel(),
        BLOCK=block,
        num_warps=4,
    )
    return out


# TODO(2026-09-25): not an impl of kelpie::sample, and not wireable as one: it branches on
# temperature > 0, but the core now sends a greedy request as (T=1, top_k=1) and this takes no
# top_ks. Wiring it means taking top_ks and the op's contract (ops/sample.py).
def sample(  # noqa: PLR0913, PLR0917
    logits: torch.Tensor,
    temperatures: torch.Tensor,
    key: torch.Tensor,
    logit_mask: torch.Tensor,
    draft_ids: torch.Tensor,
    draft_probs: torch.Tensor | None,
    num_drafts: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    # must reproduce ops.sample's Philox-4x32-10 counter/uniform bitwise for the same key.
    _ensure_elementwise_kernels()
    r, k1, vocab = logits.shape
    assert k1 == 1 + draft_ids.shape[1] == 1, "K > 0 needs the rejection sampler"
    assert draft_probs is None, "no drafts today"
    del num_drafts
    tokens = torch.empty((r, 1), dtype=torch.int32, device=logits.device)
    accepted = torch.empty(r, dtype=torch.int32, device=logits.device)
    _SAMPLE[(r,)](
        logits,
        temperatures,
        key,
        logit_mask,
        tokens,
        accepted,
        vocab=vocab,
        words=logit_mask.shape[1],
        BLOCK=2048,
        num_warps=8,
    )
    return tokens, accepted


def paged_attention_decode(
    q, cache, block_tables, seq_lens, query_start_loc, kinds, num_drafts, window=0, sinks=None
):
    global _PAGED_DECODE
    assert q.is_cuda and cache.is_cuda
    assert q.dtype in (torch.bfloat16, torch.float32)
    assert cache.dtype in (torch.bfloat16, torch.float32)
    _, hq, d = q.shape
    hkv = cache.shape[3]  # [pages, 2, block, Hkv, D]
    assert hq % hkv == 0 and d == cache.shape[4] and 0 < d <= MAX_HEAD_DIM, (
        q.shape,
        cache.shape,
    )
    assert block_tables.dtype == seq_lens.dtype == query_start_loc.dtype == torch.int32
    assert kinds.dtype == torch.int32 and num_drafts.dtype == torch.int32
    if _PAGED_DECODE is None:
        _PAGED_DECODE = _kernel()[0]
    out = torch.zeros(q.shape, device=q.device, dtype=cache.dtype)
    sink_arg = sinks if sinks is not None else torch.empty(1, device=q.device, dtype=q.dtype)
    _PAGED_DECODE[(kinds.shape[0], hkv)](
        q,
        cache,
        block_tables,
        seq_lens,
        query_start_loc,
        kinds,
        num_drafts,
        sink_arg,
        out,
        q.stride(0),
        q.stride(1),
        q.stride(2),
        cache.stride(0),
        cache.stride(1),
        cache.stride(2),
        cache.stride(3),
        block_tables.stride(0),
        block_tables.stride(1),
        out.stride(0),
        out.stride(1),
        out.stride(2),
        H_Q=hq,
        H_KV=hkv,
        D=d,
        BLOCK_SIZE=cache.shape[2],  # [pages, 2, block, Hkv, D]
        WINDOW=window,
        HAS_SINKS=sinks is not None,
        NEGATIVE_INFINITY=NEG_INF,
        KIND_DECODE_CONST=KIND_DECODE,
        BLOCK_N=16,
        num_warps=4,
    )
    return out.to(q.dtype)


def paged_attention_prefill(
    q,
    cache,
    block_tables,
    seq_lens,
    query_start_loc,
    request_for_row,
    kinds,
    num_drafts,
    window=0,
    sinks=None,
):
    global _PAGED_PREFILL
    assert q.is_cuda and cache.is_cuda
    assert q.dtype in (torch.bfloat16, torch.float32)
    assert cache.dtype in (torch.bfloat16, torch.float32)
    _, hq, d = q.shape
    hkv = cache.shape[3]  # [pages, 2, block, Hkv, D]
    assert hq % hkv == 0 and d == cache.shape[4] and 0 < d <= MAX_HEAD_DIM
    if _PAGED_PREFILL is None:
        _PAGED_PREFILL = _kernel()[1]
    out = torch.zeros(q.shape, device=q.device, dtype=cache.dtype)
    sink_arg = sinks if sinks is not None else torch.empty(1, device=q.device, dtype=q.dtype)
    _PAGED_PREFILL[(request_for_row.shape[0], hkv)](
        q,
        cache,
        block_tables,
        seq_lens,
        query_start_loc,
        request_for_row,
        kinds,
        num_drafts,
        sink_arg,
        out,
        q.stride(0),
        q.stride(1),
        q.stride(2),
        cache.stride(0),
        cache.stride(1),
        cache.stride(2),
        cache.stride(3),
        block_tables.stride(0),
        block_tables.stride(1),
        out.stride(0),
        out.stride(1),
        out.stride(2),
        H_Q=hq,
        H_KV=hkv,
        D=d,
        BLOCK_SIZE=cache.shape[2],  # [pages, 2, block, Hkv, D]
        WINDOW=window,
        HAS_SINKS=sinks is not None,
        NEGATIVE_INFINITY=NEG_INF,
        KIND_DECODE_CONST=KIND_DECODE,
        BLOCK_N=16,
        num_warps=4,
    )
    return out.to(q.dtype)


# `TritonAttention` (the StepBatch-shaped backend class) was deleted with the old path on
# 2026-09-10. The two kernels above already take `window` and `sinks` and are what a
# `paged_attention` override for cuda should call once it is re-signatured to
# `ops.paged_attention`'s tensor/int contract (kernels/adapters/triton.py).
