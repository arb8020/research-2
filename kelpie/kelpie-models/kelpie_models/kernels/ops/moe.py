"""kelpie::moe -- a routed mixture-of-experts FFN over packed MXFP4 expert weights.

The router runs OUTSIDE the op and hands in its result on device: `topk_ids` / `topk_weights`
[T, k]. Nothing about the partition (which rows go to which expert, how many) ever reaches the
host -- every backend (triton_kernels' ragged metadata, FlashInfer's permute, a masked dense
reference) derives it on device, so the op is CUDA-graph capturable end to end. The previous
contract (`grouped_mm_mxfp4(..., expert_counts: list[int])`) forced a host sync per layer.

Expert weights stay PACKED in memory, in the checkpoint's own layout (`Mxfp4`); the reference
dequantizes one expert at a time inside the op, so a forward never holds more than one expert
in bf16. gpt-oss-20b's experts are ~12 GiB packed vs ~36 GiB dequantized.

Expert parallelism is a local slice: the tables hold experts [expert_offset, expert_offset + E)
and the op computes only their contribution -- a token routed elsewhere contributes zero here.
The caller sums the partials across ranks (gpt_oss.moe: all_reduce over ep, tp).
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from kelpie_models.kernels.op import op
from kelpie_models.kernels.ops.clamped_swiglu import clamped_swiglu

MXFP4_GROUP = 32  # e2m1 values sharing one e8m0 scale
MXFP4_BYTES_PER_GROUP = MXFP4_GROUP // 2  # two e2m1 nibbles per byte
E8M0_BIAS = 127
FP4_VALUES = (
    0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0,
    -0.0, -0.5, -1.0, -1.5, -2.0, -3.0, -4.0, -6.0,
)  # e2m1 code -> value (sign bit 3)


@dataclass(frozen=True)
class Mxfp4:
    """One packed expert table, exactly as the hub stores it (`*_blocks` / `*_scales`):
    `blocks` [E, N, K/32, 16] uint8, two e2m1 codes per byte, LOW nibble first; `scales`
    [E, N, K/32] uint8 e8m0 (value 2^(s - 127)). Expert e's matrix is [N, K]: the op computes
    x @ W_e.T, i.e. `x [T, K] -> [T, N]`."""

    blocks: torch.Tensor
    scales: torch.Tensor


def dequant_mxfp4(blocks: torch.Tensor, scales: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    """blocks [..., N, K/32, 16] u8, scales [..., N, K/32] u8 -> [..., K, N] in `dtype`.
    Matches HF convert_moe_packed_tensors: low nibble first, then transpose. Any leading dims
    (none for one expert, E for a table)."""
    *lead, n, g, b = blocks.shape
    assert b == MXFP4_BYTES_PER_GROUP, blocks.shape
    assert tuple(scales.shape) == (*lead, n, g), (blocks.shape, scales.shape)
    assert blocks.dtype == torch.uint8, blocks.dtype
    assert scales.dtype == torch.uint8, scales.dtype
    vals = torch.stack((e2m1(blocks & 0x0F, dtype), e2m1(blocks >> 4, dtype)), dim=-1)
    scaled = torch.ldexp(vals.reshape(*lead, n, g, 2 * b), (scales.int() - E8M0_BIAS)[..., None])
    return scaled.reshape(*lead, n, g * 2 * b).transpose(-1, -2)


def e2m1(code: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
    """4-bit e2m1 codes -> values (`FP4_VALUES[code]`), computed from the bits instead of looked
    up: a lookup table would be a host -> device copy on every call, which a CUDA graph capture
    refuses. Bit 3 sign, bits 1-2 exponent (bias 1), bit 0 mantissa; exponent 0 is subnormal."""
    c = code.int()
    exponent = (c >> 1) & 0b11
    mantissa = (c & 1).to(dtype) * 0.5
    normal = torch.ldexp(1 + mantissa, exponent - 1)  # unused where exponent == 0
    magnitude = torch.where(exponent == 0, mantissa, normal)
    return torch.where((c >> 3) == 1, -magnitude, magnitude)


@op
def moe(  # noqa: PLR0913, PLR0917 -- a custom op's schema is flat tensors and scalars
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
    """out[t] = sum_j topk_weights[t, j] * FFN_{topk_ids[t, j]}(h[t]) over the LOCAL experts,
    FFN_e(x) = clamped_swiglu(x @ gate_up_e.T + gate_up_bias[e]) @ down_e.T + down_bias[e].

    h [T, M]; topk_ids [T, k] integer GLOBAL expert ids (distinct per row); topk_weights [T, k]
    (the router's softmax over its top-k). gate_up: Mxfp4 [E, 2I, M/32, 16] + [E, 2I, M/32],
    gate and up INTERLEAVED on 2I; gate_up_bias [E, 2I]. down: [E, M, I/32, 16] + [E, M, I/32];
    down_bias [E, M]. Local expert e is global expert `expert_offset + e`. -> [T, M] in h's
    dtype: this rank's partial sum.

    Reference: dense and masked. EVERY local expert runs on EVERY token and a zero weight drops
    the unrouted rows -- E/k times the FLOPs of a routed kernel, but static shapes, no host
    sync, no data-dependent control flow, so it captures. Accumulates in fp32 (fp64 when h is
    fp64, which is how `bench.compare` measures truth)."""
    n_local = gate_up_blocks.shape[0]
    acc_dtype = torch.promote_types(h.dtype, torch.float32)
    out = torch.zeros(h.shape, dtype=acc_dtype, device=h.device)
    for e in range(n_local):  # static bound: the table's expert count, not the routing
        routed = topk_ids == expert_offset + e  # [T, k]; at most one hit per row
        weight = torch.where(routed, topk_weights, 0).sum(dim=-1)  # [T]
        gate_up = h @ dequant_mxfp4(gate_up_blocks[e], gate_up_scales[e], h.dtype)
        act = clamped_swiglu.reference(gate_up + gate_up_bias[e], swiglu_limit, swiglu_alpha)
        y = act @ dequant_mxfp4(down_blocks[e], down_scales[e], h.dtype) + down_bias[e]
        out += y.to(acc_dtype) * weight.to(acc_dtype)[:, None]
    return out.to(h.dtype)


@moe.register_fake
def _fake(  # noqa: PLR0913, PLR0917
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
    del topk_ids, topk_weights, gate_up_blocks, gate_up_scales, gate_up_bias
    del down_blocks, down_scales, down_bias, expert_offset, swiglu_alpha, swiglu_limit
    return torch.empty_like(h)


@dataclass(frozen=True)
class Shape:
    """One MoE problem size, for `sample` and the per-op bench (scripts/bench_moe.py)."""

    tokens: int
    hidden: int
    intermediate: int
    experts: int  # local experts in the table
    top_k: int
    expert_offset: int = 0
    global_experts: int | None = None  # routing draws from [0, this); None = experts


SAMPLE_SHAPE = Shape(tokens=5, hidden=64, intermediate=64, experts=4, top_k=2)
SWIGLU_ALPHA = 1.702
SWIGLU_LIMIT = 7.0
# e8m0 codes drawn for sample scales: 2^-6 .. 2^-3, the magnitude gpt-oss's checkpoint uses, so
# activations stay O(1) through two matmuls instead of overflowing bf16.
SAMPLE_SCALE_CODES = (E8M0_BIAS - 6, E8M0_BIAS - 3)


def sample(shape: Shape, device: str, dtype: torch.dtype, seed: int = 0) -> tuple:
    """Random args for `moe` at `shape`: random e2m1 codes and gpt-oss-sized scales, random
    distinct top-k per row over the GLOBAL expert range (so with an offset, some rows route to
    no local expert at all), softmaxed weights."""
    g = torch.Generator(device="cpu").manual_seed(seed)
    t, m, i, e, k = shape.tokens, shape.hidden, shape.intermediate, shape.experts, shape.top_k
    n_global = shape.global_experts or e
    assert k <= n_global, shape
    assert m % MXFP4_GROUP == 0, shape
    assert i % MXFP4_GROUP == 0, shape

    def table(n: int, kk: int) -> tuple[torch.Tensor, torch.Tensor]:
        blocks = torch.randint(0, 256, (e, n, kk // MXFP4_GROUP, MXFP4_BYTES_PER_GROUP),
                               generator=g, dtype=torch.uint8)
        scales = torch.randint(*SAMPLE_SCALE_CODES, (e, n, kk // MXFP4_GROUP), generator=g,
                               dtype=torch.uint8)
        return blocks.to(device), scales.to(device)

    gate_up_blocks, gate_up_scales = table(2 * i, m)
    down_blocks, down_scales = table(m, i)
    ids = torch.rand(t, n_global, generator=g).argsort(dim=-1)[:, :k]
    weights = torch.softmax(torch.randn(t, k, generator=g), dim=-1)
    return (
        torch.randn(t, m, generator=g).to(device=device, dtype=dtype),
        ids.to(device),
        weights.to(device=device, dtype=dtype),
        gate_up_blocks,
        gate_up_scales,
        (torch.randn(e, 2 * i, generator=g) * 0.1).to(device=device, dtype=dtype),
        down_blocks,
        down_scales,
        (torch.randn(e, m, generator=g) * 0.1).to(device=device, dtype=dtype),
        shape.expert_offset,
        SWIGLU_ALPHA,
        SWIGLU_LIMIT,
    )


@moe.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    return sample(SAMPLE_SHAPE, device, dtype)


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


moe.register_autograd(_backward)


@moe.register("triton_kernels", source="triton_kernels.matmul.matmul (triton v3.7.1)")
def _triton_kernels(*args: object) -> torch.Tensor:
    """Unswizzled MXFP4 over the hub tables in place; any sm80+ (adapters/moe_triton_kernels)."""
    from kelpie_models.kernels.adapters import moe_triton_kernels as adapter

    return adapter.moe(*args)


@moe.register("triton_kernels_hopper", backend="triton_kernels",
              source="triton_kernels.matmul.matmul, Hopper MX layouts (triton v3.7.1)")
def _triton_kernels_hopper(*args: object) -> torch.Tensor:
    """sm90 swizzled layout, vLLM's H100 default; a one-time cached conversion per table."""
    from kelpie_models.kernels.adapters import moe_triton_kernels as adapter

    return adapter.moe_hopper(*args)


@moe.register("flashinfer", source="flashinfer.fused_moe.cutlass_fused_moe W4A16 (0.7.0)")
def _flashinfer(*args: object) -> torch.Tensor:
    """sm90 only; a one-time cached layout conversion per table (adapters/moe_flashinfer)."""
    from kelpie_models.kernels.adapters import moe_flashinfer as adapter

    return adapter.moe(*args)


@moe.register("marlin", backend="vllm_marlin",
              source="vLLM 0.29.0 moe_wna16_marlin_gemm (prebuilt .so, wheel sha256-pinned)")
def _marlin(*args: object) -> torch.Tensor:
    """vLLM's A100 gpt-oss path, sm75+; a one-time cached repack per table
    (adapters/moe_marlin, adapters/_vllm_marlin_ops)."""
    from kelpie_models.kernels.adapters import moe_marlin as adapter

    return adapter.moe(*args)
