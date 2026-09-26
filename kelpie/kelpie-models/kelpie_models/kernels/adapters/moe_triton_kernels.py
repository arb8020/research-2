"""`kelpie::moe` on OpenAI's `triton_kernels` (triton-lang/triton python/triton_kernels @ v3.7.1).

The same library vLLM runs gpt-oss on for Hopper/Blackwell (`gpt_oss_triton_kernels_moe.py`,
its "3.8" API branch: `matmul` + `RaggedTensorMetadata`; v3.7.1 already has that API). Two
matmuls over expert-sorted rows, SwiGLU fused into the first one's epilogue, router weights
(`gammas`) fused into the second.

Routing is built ON DEVICE from `topk_ids`: a stable argsort by local expert, per-expert counts
by scatter_add, and `make_ragged_tensor_metadata` (two Triton launches sized from shapes). No
host sync, so it captures.

Weights: the hub's packed tables used IN PLACE. triton_kernels' unswizzled ("strided") MXFP4
layout wants W as [E, K, N] with K the unit-stride axis; the hub stores [E, N, K/2] bytes with K
unit-stride, so the transpose is a VIEW -- no copy, no second resident table (`moe`). That is
triton_kernels' default layout on sm80. On sm90 its default -- and vLLM's -- is a swizzled
Hopper layout: a one-time copy, cached per table (`moe_hopper`, adapters/_prepared.py).

Deviations from vLLM, both deliberate:
- foreign-expert rows (EP) are sorted LAST and left out of the ragged metadata, so they are
  never computed; vLLM clamps them to expert 0 with weight 0 and computes them anyway.
- the top-k combine is an inverse-permutation copy + sum over k in fp32 (deterministic), not
  vLLM's fp32 `index_add_` (atomics, run-to-run nondeterministic).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import torch
import torch.nn.functional as F

from kelpie_models.kernels.adapters._prepared import Prepared

MXFP4_GROUP = 32
HOPPER = (9, 0)
# The unswizzled path's warp heuristic is max(block_m * block_n // 4096, 1): ONE warp for a 16x256
# decode tile (the swizzled Hopper layout brings its own). Measured on A100-80GB, one MoE layer at
# gpt-oss shapes: T=1 4635 -> 1646 us, T=8 13467 -> 1727 us, T=256 35446 -> 3038 us with 8 warps;
# T=2048 flat (~159 ms either way).
STRIDED_NUM_WARPS = 8
HOPPER_SCALE_WARPS = 8  # vLLM's num_warps for the Hopper scale swizzle
HOPPER_SCALE_GROUP_MULTIPLE = 4
_CONSTRAINTS_LOCK = threading.Lock()  # the dict below is process-global in triton_kernels


def route(
    topk_ids: torch.Tensor, topk_weights: torch.Tensor, expert_offset: int, n_local: int
) -> tuple[object, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """-> (ragged metadata over the LOCAL experts, gather rows [T*k] int32 (sorted slot ->
    token), gammas [T*k] fp32 (sorted slot -> weight, 0 for a foreign slot), order [T*k] (sorted
    slot -> flat slot), local [T*k] bool (flat slot is a local expert))."""
    from triton_kernels.tensor import make_ragged_tensor_metadata

    t, k = topk_ids.shape
    local_id = topk_ids.reshape(-1).long() - expert_offset
    local = (local_id >= 0) & (local_id < n_local)
    key = torch.where(local, local_id, n_local)  # foreign slots sort after every local one
    order = torch.argsort(key, stable=True)
    counts = torch.zeros(n_local + 1, dtype=torch.int32, device=topk_ids.device)
    counts.scatter_add_(0, key, torch.ones_like(key, dtype=torch.int32))
    ragged = make_ragged_tensor_metadata(counts[:n_local], t * k)
    gather = (order // k).to(torch.int32)
    weights = torch.where(local, topk_weights.reshape(-1).float(), 0.0)
    return ragged, gather, weights[order], order, local


def packed_view(blocks: torch.Tensor, scales: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Hub [E, N, K/32, 16] u8 + [E, N, K/32] u8 -> ([E, K/2, N] u8, [E, K/32, N] u8), both
    views with the K axis unit-stride (what `matmul` asserts for an mx weight below sm100)."""
    e, n, g, b = blocks.shape
    values = blocks.view(e, n, g * b).transpose(-1, -2)
    assert values.stride(-2) == 1, values.stride()
    return values, scales.transpose(-1, -2)


@contextmanager
def _constraints(extra: dict[str, int]) -> Iterator[None]:
    """triton_kernels keeps its tile constraints in ONE process-global dict; set ours for the
    duration of the two matmuls and put back whatever was there. Locked: a loop thread's eager
    step and a build's warm pass may dispatch at once."""
    from triton_kernels.matmul_details import opt_flags

    with _CONSTRAINTS_LOCK:
        saved = dict(opt_flags._opt_flags_constraints)  # noqa: SLF001 -- no public getter
        opt_flags.update_opt_flags_constraints(extra)
        try:
            yield
        finally:
            opt_flags.reset_opt_flags_constraints()
            opt_flags.update_opt_flags_constraints(saved)


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
    """Unswizzled: the hub tables as views, any sm80+."""
    w13, s13 = packed_view(gate_up_blocks, gate_up_scales)
    w2, s2 = packed_view(down_blocks, down_scales)
    tables = Tables(w13, s13, gate_up_bias.float(), w2, s2, down_bias.float())
    with _constraints({"num_warps": STRIDED_NUM_WARPS}):
        return _run(h, topk_ids, topk_weights, tables, expert_offset, swiglu_alpha, swiglu_limit)


@dataclass(frozen=True)
class Tables:
    """What the two matmuls read: weights + mx scales (torch views or triton_kernels Tensors
    in a swizzled layout) and fp32 biases (the kernel's bias dtype, as vLLM passes it)."""

    w13: object
    s13: object
    b13: torch.Tensor
    w2: object
    s2: object
    b2: torch.Tensor


def _run(  # noqa: PLR0913, PLR0917
    h: torch.Tensor,
    topk_ids: torch.Tensor,
    topk_weights: torch.Tensor,
    tables: Tables,
    expert_offset: int,
    swiglu_alpha: float,
    swiglu_limit: float,
) -> torch.Tensor:
    from triton_kernels.matmul import FusedActivation, PrecisionConfig, matmul
    from triton_kernels.specialize import FnSpecs
    from triton_kernels.swiglu import swiglu_fn

    assert h.dtype == torch.bfloat16, f"triton_kernels mxfp4 path: bf16 activations, got {h.dtype}"
    t, m = h.shape
    k = topk_ids.shape[1]
    n_local = tables.b13.shape[0]
    ragged, gather, gammas, order, local = route(topk_ids, topk_weights, expert_offset, n_local)
    swiglu = FusedActivation(
        FnSpecs("swiglu", swiglu_fn, ("alpha", "limit"), reduction_n=2),
        (swiglu_alpha, swiglu_limit),
    )
    inter = matmul(h, tables.w13, tables.b13, ragged, None, gather, None,
                   PrecisionConfig(b_mx_scale=tables.s13), fused_activation=swiglu)  # [T*k, I]
    y = matmul(inter, tables.w2, tables.b2, ragged, None, None, None,
               PrecisionConfig(b_mx_scale=tables.s2), gammas=gammas)  # [T*k, M], weighted
    flat = torch.empty_like(y)
    flat[order] = y  # back to (token, j) order; a permutation, so no two writes collide
    # A foreign slot's row was never computed (outside the ragged metadata): drop it by mask,
    # not by multiplying garbage by zero.
    kept = torch.where(local[:, None], flat, torch.zeros((), dtype=flat.dtype, device=h.device))
    return kept.view(t, k, m).float().sum(dim=1).to(h.dtype)


PREPARED: Prepared[Tables] = Prepared()


def hopper_tables(blocks13: torch.Tensor, scales13: torch.Tensor, bias13: torch.Tensor,
                  blocks2: torch.Tensor, scales2: torch.Tensor, bias2: torch.Tensor) -> Tables:
    """vLLM's `_swizzle_mxfp4` for sm90 (quantization/utils/mxfp4_utils.py): scale groups padded
    to a multiple of 4 (its "#47303, until triton 3.8" patch; 2880/32 = 90 needs it), then
    `convert_layout` to the Hopper value / scale layouts -- a copy."""
    from triton_kernels.tensor import FP4, convert_layout, wrap_torch_tensor
    from triton_kernels.tensor_details import layout

    def swizzle(blocks: torch.Tensor, scales: torch.Tensor) -> tuple[object, object]:
        e, n, g, b = blocks.shape
        values = blocks.view(e, n, g * b).transpose(-1, -2)
        padded = F.pad(scales, (0, -g % HOPPER_SCALE_GROUP_MULTIPLE)).transpose(-1, -2)
        # mx_axis -2 (the K axis of [E, K, N]); vLLM passes 1, which v3.7.1's Hopper layouts
        # reject (`assert mx_axis in [-1, -2]`).
        # v3.7.1's factories return the layout itself (vLLM's "3.8" code unpacks (layout, opts)).
        value_layout = layout.make_default_matmul_mxfp4_w_layout(mx_axis=-2)
        scale_layout = layout.make_default_matmul_mxfp4_w_scale_layout(
            mx_axis=-2, num_warps=HOPPER_SCALE_WARPS)
        return (convert_layout(wrap_torch_tensor(values, dtype=FP4), value_layout),
                convert_layout(wrap_torch_tensor(padded), scale_layout))

    w13, s13 = swizzle(blocks13, scales13)
    w2, s2 = swizzle(blocks2, scales2)
    return Tables(w13, s13, bias13.float(), w2, s2, bias2.float())


def moe_hopper(  # noqa: PLR0913, PLR0917 -- kelpie::moe's schema
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
    """Swizzled Hopper layout (vLLM's H100 default); sm90 only, one cached conversion per table."""
    arch = torch.cuda.get_device_capability(h.device)
    if arch != HOPPER:
        raise RuntimeError(f"triton_kernels_hopper needs sm90 (Hopper MX layouts); this device "
                           f"is sm{arch[0]}{arch[1]} -- use impl triton_kernels")
    tables = PREPARED.get(gate_up_blocks, lambda: hopper_tables(
        gate_up_blocks, gate_up_scales, gate_up_bias, down_blocks, down_scales, down_bias))
    with _constraints({"split_k": 1}):  # vLLM's sm90 constraint for this layout
        return _run(h, topk_ids, topk_weights, tables, expert_offset, swiglu_alpha, swiglu_limit)
