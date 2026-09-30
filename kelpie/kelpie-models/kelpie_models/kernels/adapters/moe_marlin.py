"""`kelpie::moe` on vLLM's Marlin MoE (W4A16: bf16 activations x MXFP4 weights), vLLM 0.29.0.

What vLLM runs for gpt-oss MXFP4 on A100: its mxfp4 oracle
(model_executor/layers/fused_moe/oracle/mxfp4.py) tries TRITON (triton_kernels, sm90..sm10x
only), the FlashInfer paths (sm90/sm100) and lands on MARLIN, which needs sm75+. The kernels are
vLLM's own prebuilt ops (adapters/_vllm_marlin_ops.py holds the pins: vllm==0.29.0 wheel sha256,
source tag v0.29.0 = 98dff2a81d747d1dba01a47f939f48c3526d4206). This file is the Python glue,
ported from that tag:
  - weight prep: quantization/utils/marlin_utils_fp4.py `prepare_moe_mxfp4_layer_for_marlin`
    + marlin_utils.py `marlin_permute_scales` / `marlin_permute_bias` /
    `mxfp4_marlin_process_scales`, with the oracle's Marlin padding (hidden -> multiple of 256,
    intermediate -> multiple of 128: 2880 -> 3072 / 2944; zero weights, zero bias);
  - forward: fused_moe/experts/marlin_moe.py `fused_marlin_moe` (block_size_m heuristic,
    moe_align_block_size, gemm1 -> swigluoai_and_mul -> gemm2 with the router weights ->
    moe_sum), activation fused_moe/activation.py SWIGLUOAI (gate/up INTERLEAVED, as the hub).

Deviations from vLLM, both deliberate:
  - expert parallel: vLLM passes an `expert_map` over the global experts. This op does not know
    the global count, so foreign ids become -1 in a LOCAL id tensor: moe_align_block_size skips
    an id outside [0, E) and moe_sum's pad-aware path skips a negative one (moe_align_sum_kernels
    .cu, `get_local_expert_id` / `moe_sum_pad_aware_skip`). A foreign slot is never computed.
  - the one-time weight conversion is cached per table (adapters/_prepared.py), not done at
    load: the same second-resident-copy cost as the FlashInfer / Hopper adapters (NOTES).

No host sync: the M block size comes from shapes, the routing tables are built on device, the
workspace is a fresh zeroed int32 buffer per call (the kernel's lock counters). Captures.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F

from kelpie_models.kernels.adapters._prepared import Prepared

MXFP4_GROUP = 32
E8M0_ONE = 127  # scale code for 2^0, used for padded groups (their weights are zero)
HIDDEN_MULTIPLE = 256  # vLLM oracle: round_up(hidden, 256) for Marlin
INTERMEDIATE_MULTIPLE = 128  # vLLM oracle: round_up(intermediate, 128)
FLOAT4_E2M1F_ID = 562949953487106  # vllm.scalar_type.scalar_types.float4_e2m1f.id (0.29.0)
BLOCK_SIZES_M = (8, 16, 32, 48, 64)  # fused_marlin_moe's M block heuristic
BLOCK_FILL = 0.9
WORKSPACE_BLOCKS_PER_SM = 4  # marlin_make_workspace_new(device, 4)
MIN_ARCH = (8, 0)  # the kernel runs on sm75+, but this op takes bf16 activations: sm80+
# get_scale_perms(): scale_perm (grouped scales) and scale_perm_single (bias).
SCALE_PERM = tuple(i + 8 * j for i in range(8) for j in range(8))
SCALE_PERM_SINGLE = tuple(2 * i + j for i in range(4) for j in (0, 1, 8, 9, 16, 17, 24, 25))
FP8_SCALE_ORDER = (0, 2, 1, 3)  # mxfp4_marlin_process_scales, bf16 activations


@dataclass(frozen=True)
class MarlinTables:
    """One layer's experts in Marlin layout, padded: hidden M -> Mp, intermediate I -> Ip."""

    w13: torch.Tensor  # repacked int32, gate/up interleaved on 2 * Ip
    s13: torch.Tensor  # float8_e8m0fnu, permuted
    b13: torch.Tensor  # bf16, permuted
    w2: torch.Tensor
    s2: torch.Tensor
    b2: torch.Tensor
    hidden: int  # M
    hidden_padded: int  # Mp
    intermediate_padded: int  # Ip


PREPARED: Prepared[MarlinTables] = Prepared()


def _round_up(n: int, multiple: int) -> int:
    return -(-n // multiple) * multiple


def _pad_table(blocks: torch.Tensor, scales: torch.Tensor, rows: int, k: int
               ) -> tuple[torch.Tensor, torch.Tensor]:
    """Hub [E, N, K/32, 16] + [E, N, K/32] -> [E, rows, k/2] u8 (zero codes = 0.0) +
    [E, rows, k/32] u8 (padded groups 2^0)."""
    e, n, g, b = blocks.shape
    values = F.pad(blocks.reshape(e, n, g * b), (0, k // 2 - g * b, 0, rows - n))
    padded_scales = F.pad(scales, (0, k // MXFP4_GROUP - g, 0, rows - n), value=E8M0_ONE)
    return values, padded_scales


def _repack(weights: torch.Tensor, size_n: int, size_k: int) -> torch.Tensor:
    """[E, N, K/2] u8 -> Marlin's int32 tiles per expert (`_repack_marlin_experts`)."""
    no_perm = torch.empty(0, dtype=torch.int32, device=weights.device)
    return torch.stack([
        torch.ops._C.gptq_marlin_repack(w.view(torch.int32).T.contiguous(), no_perm,
                                        size_k, size_n, 4, False)
        for w in weights
    ])


def _permute_scales(scales: torch.Tensor, size_n: int) -> torch.Tensor:
    """[E, N, K/32] e8m0 codes -> Marlin-permuted e8m0 per expert (`permute_scales` in
    prepare_moe_mxfp4_layer_for_marlin: e8m0 -> bf16, permute, reorder, back to e8m0)."""
    perm = torch.tensor(SCALE_PERM, device=scales.device)
    order = torch.tensor(FP8_SCALE_ORDER, device=scales.device)
    out = []
    for s in scales.view(torch.float8_e8m0fnu).to(torch.bfloat16):
        # marlin_permute_scales, grouped branch (group 32 < K), then the bf16-activation reorder.
        permuted = s.T.reshape(-1, len(SCALE_PERM))[:, perm].reshape(-1, size_n)
        reordered = permuted.reshape(-1, len(FP8_SCALE_ORDER))[:, order]
        out.append(reordered.reshape(permuted.shape).to(torch.float8_e8m0fnu))
    return torch.stack(out)


def _permute_bias(bias: torch.Tensor) -> torch.Tensor:
    """[E, N] -> bf16, Marlin-permuted per expert (`marlin_permute_bias`)."""
    perm = torch.tensor(SCALE_PERM_SINGLE, device=bias.device)
    e, n = bias.shape
    return bias.to(torch.bfloat16).reshape(-1, len(SCALE_PERM_SINGLE))[:, perm].reshape(e, n)


def convert(  # noqa: PLR0913, PLR0917
    gate_up_blocks: torch.Tensor,
    gate_up_scales: torch.Tensor,
    gate_up_bias: torch.Tensor,
    down_blocks: torch.Tensor,
    down_scales: torch.Tensor,
    down_bias: torch.Tensor,
) -> MarlinTables:
    """Hub tables -> padded, repacked Marlin tables (a copy). Runs on the first (eager) call:
    the permutation index tensors are host -> device copies, which a capture would refuse."""
    _, two_i, _, _ = gate_up_blocks.shape
    i, m = two_i // 2, down_blocks.shape[1]
    ip, mp = _round_up(i, INTERMEDIATE_MULTIPLE), _round_up(m, HIDDEN_MULTIPLE)
    # gate/up stay interleaved: padded channels are appended as (gate, up) pairs of zeros, and
    # swigluoai of a zero pair is 0 (see the oracle's padding note).
    w13, s13 = _pad_table(gate_up_blocks, gate_up_scales, 2 * ip, mp)
    w2, s2 = _pad_table(down_blocks, down_scales, mp, ip)
    return MarlinTables(
        w13=_repack(w13, 2 * ip, mp),
        s13=_permute_scales(s13, 2 * ip),
        b13=_permute_bias(F.pad(gate_up_bias, (0, 2 * ip - two_i))),
        w2=_repack(w2, mp, ip),
        s2=_permute_scales(s2, mp),
        b2=_permute_bias(F.pad(down_bias, (0, mp - m))),
        hidden=m,
        hidden_padded=mp,
        intermediate_padded=ip,
    )


def block_size_m(tokens: int, top_k: int, n_local: int) -> int:
    """fused_marlin_moe's heuristic: the smallest block whose expected fill is under 0.9.
    Under expert parallelism vLLM first scales the token count by local / global experts; this
    op does not know the global count, so it can pick a larger block than vLLM (speed only)."""
    for size in BLOCK_SIZES_M:
        if tokens * top_k / n_local / size < BLOCK_FILL:
            return size
    return BLOCK_SIZES_M[-1]


def _gemm(  # noqa: PLR0913, PLR0917
    a: torch.Tensor,
    w: torch.Tensor,
    bias: torch.Tensor,
    scales: torch.Tensor,
    routing: tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, int],
    top_k: int,
    size_m: int,
    mul_topk_weights: bool,
    workspace: torch.Tensor,
) -> torch.Tensor:
    sorted_ids, expert_ids, n_padded, weights, block_m = routing
    size_n = bias.shape[1]
    size_k = a.shape[1]
    return torch.ops._moe_C.moe_wna16_marlin_gemm(
        a, None, w, bias, scales, None, None, None, None, None, workspace,
        sorted_ids, expert_ids, n_padded, weights,
        block_m, top_k, mul_topk_weights, FLOAT4_E2M1F_ID, size_m, size_n, size_k,
        True,  # is_k_full (no act-order)
        False,  # use_atomic_add
        True,  # use_fp32_reduce (vLLM's default)
        False,  # is_zp_float
        -1, -1, -1,  # thread_k, thread_n, blocks_per_sm: the kernel's own choice
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
    from kelpie_models.kernels.adapters import _vllm_marlin_ops  # noqa: F401 -- loads the ops

    assert h.dtype == torch.bfloat16, f"marlin W4A16 MoE: bf16 activations, got {h.dtype}"
    arch = torch.cuda.get_device_capability(h.device)
    if arch < MIN_ARCH:
        raise RuntimeError(f"marlin (bf16 activations) needs sm80+; this device is "
                           f"sm{arch[0]}{arch[1]}")
    tables = PREPARED.get(gate_up_blocks, lambda: convert(
        gate_up_blocks, gate_up_scales, gate_up_bias, down_blocks, down_scales, down_bias))
    t, m = h.shape
    if t == 0:  # neither vLLM kernel host function guards an empty launch (moe_sum grid of 0)
        return torch.empty_like(h)
    top_k = topk_ids.shape[1]
    n_local = gate_up_blocks.shape[0]
    local_id = topk_ids - expert_offset
    foreign = (local_id < 0) | (local_id >= n_local)
    ids = torch.where(foreign, -1, local_id).to(torch.int32)
    block_m = block_size_m(t, top_k, n_local)
    # moe_align_block_size's buffer sizes (fused_moe/moe_align_block_size.py).
    max_padded = ids.numel() + n_local * (block_m - 1)
    if ids.numel() < n_local:
        max_padded = min(ids.numel() * block_m, max_padded)
    sorted_ids = torch.empty(max_padded, dtype=torch.int32, device=h.device)
    expert_ids = torch.empty(-(-max_padded // block_m), dtype=torch.int32, device=h.device)
    n_padded = torch.empty(1, dtype=torch.int32, device=h.device)
    torch.ops._moe_C.moe_align_block_size(ids, n_local, block_m, sorted_ids, expert_ids,
                                          n_padded, None)
    # fp32 and contiguous: the kernel indexes the router weights flat, by slot.
    routing = (sorted_ids, expert_ids, n_padded, topk_weights.float().contiguous(), block_m)
    sms = torch.cuda.get_device_properties(h.device).multi_processor_count
    workspace = torch.zeros(sms * WORKSPACE_BLOCKS_PER_SM, dtype=torch.int32, device=h.device)
    ip, mp = tables.intermediate_padded, tables.hidden_padded
    x = F.pad(h, (0, mp - m)).contiguous()
    gate_up = _gemm(x, tables.w13, tables.b13, tables.s13, routing, top_k, t, False, workspace)
    act = torch.empty(t * top_k, ip, dtype=h.dtype, device=h.device)
    torch.ops._C.swigluoai_and_mul(act, gate_up.view(-1, 2 * ip), swiglu_alpha, swiglu_limit)
    # Second gemm: one row per (token, slot), the router weight applied in its epilogue.
    down = _gemm(act, tables.w2, tables.b2, tables.s2, routing, 1, t * top_k, True, workspace)
    out = torch.empty(t, m, dtype=h.dtype, device=h.device)
    # Sum over the k slots in fp32, skipping foreign (-1) slots; reads the unpadded columns.
    torch.ops._moe_C.moe_sum(down.view(t, top_k, mp)[:, :, :m], out, ids, None)
    return out
