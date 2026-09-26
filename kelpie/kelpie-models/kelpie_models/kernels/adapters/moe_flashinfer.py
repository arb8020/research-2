"""`kelpie::moe` on FlashInfer's CUTLASS fused MoE, MXFP4 weights x bf16 activations (W4A16).

`flashinfer.fused_moe.cutlass_fused_moe(..., use_w4_group_scaling=True)` -- the one FlashInfer
MXFP4 MoE entry point that takes PRECOMPUTED routing below Blackwell. It is sm90 only
(flashinfer 0.7.0 `_CUTLASS_W4A16_ARCHS = (90,)`); there is no FlashInfer MXFP4 MoE for sm80, and
the trtllm-gen MXFP4 paths (`trtllm_fp4_block_scale_*moe`) are sm100+. vLLM's equivalent is
`FLASHINFER_CUTLASS_MXFP4_BF16` (oracle/mxfp4.py), behind triton_kernels in its gpt-oss order.

The kernel wants its own weight layout, so this adapter pays a ONE-TIME conversion per expert
table (vLLM does the same at load, `oracle/mxfp4.py:1021-1098`):
  - gate/up de-interleaved and stored [up; gate] (its SwigluBias epilogue reads linear first);
  - hidden and intermediate zero-padded to a multiple of 128 (2880 -> 2944: the sm90 scale
    interleave needs rows % 64 and K/32 % 4), padded scales = 127 (2^0), padded bias = 0, so
    padded rows compute swiglu(0) = 0 and padded columns multiply zero weights;
  - `interleave_moe_{weights,scales}_for_sm90_mixed_gemm`.
The converted tables are CACHED, keyed by the source blocks tensor and dropped with it
(`adapters/_prepared.py`). That is a second resident copy of the experts while the model also
holds the hub tables -- a spike's cost, recorded in NOTES-kernels.md; the permanent answer is a
load-time layout hook, not this cache.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F

from kelpie_models.kernels.adapters._prepared import Prepared

SM90 = (9, 0)
PAD = 128  # sm90 mixed-gemm: rows % 64 and (K / 32) % 4
E8M0_ONE = 127
MXFP4_GROUP = 32


@dataclass(frozen=True)
class Sm90Tables:
    w13: torch.Tensor
    s13: torch.Tensor
    b13: torch.Tensor
    w2: torch.Tensor
    s2: torch.Tensor
    b2: torch.Tensor
    alpha: torch.Tensor  # [E] fp32, one per expert as the kernel takes them
    beta: torch.Tensor  # gpt-oss's `(up + 1)`: beta = 1
    limit: torch.Tensor
    hidden: int  # unpadded M


PREPARED: Prepared[Sm90Tables] = Prepared()


def _round_up(n: int) -> int:
    return -(-n // PAD) * PAD


def _pad_table(blocks: torch.Tensor, scales: torch.Tensor, rows: int, k: int
               ) -> tuple[torch.Tensor, torch.Tensor]:
    """[E, N, K/32, 16] + [E, N, K/32] -> [E, rows, k/2] u8 zeros-padded + [E, rows, k/32] u8
    127-padded."""
    e, n, g, b = blocks.shape
    values = F.pad(blocks.reshape(e, n, g * b), (0, k // 2 - g * b, 0, rows - n))
    padded_scales = F.pad(scales, (0, k // MXFP4_GROUP - g, 0, rows - n), value=E8M0_ONE)
    return values, padded_scales


def convert(  # noqa: PLR0913, PLR0917
    gate_up_blocks: torch.Tensor,
    gate_up_scales: torch.Tensor,
    gate_up_bias: torch.Tensor,
    down_blocks: torch.Tensor,
    down_scales: torch.Tensor,
    down_bias: torch.Tensor,
    swiglu_alpha: float,
    swiglu_limit: float,
) -> Sm90Tables:
    from flashinfer.fused_moe import (
        interleave_moe_scales_for_sm90_mixed_gemm,
        interleave_moe_weights_for_sm90_mixed_gemm,
    )

    e, two_i, _, _ = gate_up_blocks.shape
    i, m = two_i // 2, down_blocks.shape[1]
    i_pad, m_pad = _round_up(i), _round_up(m)
    # [up; gate], each half padded to i_pad rows on its own.
    up_w, up_s = _pad_table(gate_up_blocks[:, 1::2], gate_up_scales[:, 1::2], i_pad, m_pad)
    gate_w, gate_s = _pad_table(gate_up_blocks[:, 0::2], gate_up_scales[:, 0::2], i_pad, m_pad)
    down_w, down_s = _pad_table(down_blocks, down_scales, m_pad, i_pad)
    b13 = torch.cat([F.pad(gate_up_bias[:, 1::2], (0, i_pad - i)),
                     F.pad(gate_up_bias[:, 0::2], (0, i_pad - i))], dim=1)
    per_expert = dict(dtype=torch.float32, device=gate_up_blocks.device)
    return Sm90Tables(
        w13=interleave_moe_weights_for_sm90_mixed_gemm(torch.cat([up_w, gate_w], 1), "fp4"),
        s13=interleave_moe_scales_for_sm90_mixed_gemm(torch.cat([up_s, gate_s], 1)),
        b13=b13.to(torch.bfloat16).contiguous(),
        w2=interleave_moe_weights_for_sm90_mixed_gemm(down_w.contiguous(), "fp4"),
        s2=interleave_moe_scales_for_sm90_mixed_gemm(down_s.contiguous()),
        b2=F.pad(down_bias, (0, m_pad - m)).to(torch.bfloat16).contiguous(),
        alpha=torch.full((e,), swiglu_alpha, **per_expert),
        beta=torch.full((e,), 1.0, **per_expert),
        limit=torch.full((e,), swiglu_limit, **per_expert),
        hidden=m,
    )


def moe(  # noqa: PLR0913, PLR0917 -- kelpie::moe's schema
    h: torch.Tensor,
    topk_ids: torch.Tensor,
    topk_weights: torch.Tensor,
    gate_up_blocks: torch.Tensor,
    gate_up_scales: torch.Tensor,
    gate_up_bias: torch.Tensor,
    down_blocks: torch.Tensor,
    down_scales: torch.Tensor,
    down_bias: torch.Tensor,
    expert_offset: int,
    swiglu_alpha: float,
    swiglu_limit: float,
) -> torch.Tensor:
    from flashinfer.fused_moe import ActivationType, cutlass_fused_moe

    assert h.dtype == torch.bfloat16, f"flashinfer W4A16 MoE: bf16 activations, got {h.dtype}"
    arch = torch.cuda.get_device_capability(h.device)
    if arch != SM90:
        raise RuntimeError(f"flashinfer MXFP4 W4A16 MoE runs on sm90 only; this device is "
                           f"sm{arch[0]}{arch[1]} (flashinfer 0.7.0 _CUTLASS_W4A16_ARCHS)")
    tables = PREPARED.get(gate_up_blocks, lambda: convert(
        gate_up_blocks, gate_up_scales, gate_up_bias, down_blocks, down_scales, down_bias,
        swiglu_alpha, swiglu_limit))
    n_local = gate_up_blocks.shape[0]
    # Expert parallel without knowing the global expert count: local ids stay [0, E), a foreign
    # id becomes E, and (ep_size 2, ep_rank 0) tells the kernel [E, 2E) belongs to someone else.
    local_id = topk_ids - expert_offset
    foreign = (local_id < 0) | (local_id >= n_local)
    ids = torch.where(foreign, n_local, local_id).to(torch.int32)
    x = F.pad(h, (0, tables.w2.shape[1] - h.shape[1]))
    out = cutlass_fused_moe(
        x, ids, topk_weights.float(), tables.w13, tables.w2, torch.bfloat16,
        [tables.s13, tables.s2],
        fc1_expert_biases=tables.b13, fc2_expert_biases=tables.b2,
        swiglu_alpha=tables.alpha, swiglu_beta=tables.beta, swiglu_limit=tables.limit,
        ep_size=2, ep_rank=0,
        use_w4_group_scaling=True, activation_type=ActivationType.Swiglu,
    )
    # Not min-latency mode: [output, active experts per node, expert->token score, active ids].
    # Contiguous: the op's fake promises empty_like(h), and all_reduce (NCCL) needs it.
    return out[0][:, : tables.hidden].contiguous()
