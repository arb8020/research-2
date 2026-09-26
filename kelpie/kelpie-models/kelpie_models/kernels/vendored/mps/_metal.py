from __future__ import annotations

from functools import cache

import torch

_SOURCE = r"""
#include <metal_stdlib>
using namespace metal;

constant uint GROUP = 256;

kernel void layer_norm_f32(
    device float* out [[buffer(0)]],
    device const float* x [[buffer(1)]],
    device const float* weight [[buffer(2)]],
    device const float* bias [[buffer(3)]],
    constant float& eps [[buffer(4)]],
    constant uint& width [[buffer(5)]],
    uint row [[threadgroup_position_in_grid]],
    uint lane [[thread_position_in_threadgroup]],
    uint simd_lane [[thread_index_in_simdgroup]],
    uint simd_id [[simdgroup_index_in_threadgroup]]) {
  threadgroup float partial_sum[GROUP / 32];
  threadgroup float partial_sq[GROUP / 32];
  device const float* xr = x + (ulong)row * width;
  device float* outr = out + (ulong)row * width;
  float s = 0.0f, sq = 0.0f;
  for (uint c = lane; c < width; c += GROUP) {
    float v = xr[c];
    s += v;
    sq += v * v;
  }
  s = simd_sum(s);
  sq = simd_sum(sq);
  if (simd_lane == 0) {
    partial_sum[simd_id] = s;
    partial_sq[simd_id] = sq;
  }
  threadgroup_barrier(mem_flags::mem_threadgroup);
  if (simd_id == 0) {
    float ts = simd_lane < GROUP / 32 ? partial_sum[simd_lane] : 0.0f;
    float tq = simd_lane < GROUP / 32 ? partial_sq[simd_lane] : 0.0f;
    ts = simd_sum(ts);
    tq = simd_sum(tq);
    if (simd_lane == 0) {
      partial_sum[0] = ts;
      partial_sq[0] = tq;
    }
  }
  threadgroup_barrier(mem_flags::mem_threadgroup);
  float mean = partial_sum[0] / float(width);
  float var = partial_sq[0] / float(width) - mean * mean;
  float rstd = rsqrt(max(var, 0.0f) + eps);
  for (uint c = lane; c < width; c += GROUP) {
    outr[c] = (xr[c] - mean) * rstd * weight[c] + bias[c];
  }
}

kernel void gelu_tanh_f32(
    device float* out [[buffer(0)]],
    device const float* x [[buffer(1)]],
    constant uint& n [[buffer(2)]],
    uint i [[thread_position_in_grid]]) {
  if (i >= n) return;
  float v = x[i];
  float u = 0.7978845608028654f * (v + 0.044715f * v * v * v);  // sqrt(2/pi)
  out[i] = 0.5f * v * (1.0f + tanh(u));
}
"""

GROUP = 256


@cache
def _library():
    compile_shader = getattr(torch.mps, "compile_shader", None)
    if compile_shader is None:
        raise RuntimeError("Metal kernels require torch.mps.compile_shader")
    return compile_shader(_SOURCE)


def _check(name: str, *tensors: torch.Tensor) -> None:
    for t in tensors:
        assert t.device.type == "mps", f"metal {name}: MPS tensors only, got {t.device}"
        assert t.dtype == torch.float32, f"metal {name}: float32 only, got {t.dtype}"
        assert t.is_contiguous(), f"metal {name}: contiguous tensors only"
        assert t.numel() > 0, f"metal {name}: empty tensor"


def layer_norm(
    x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor, eps: float
) -> torch.Tensor:
    # mean/var from sum and sum-of-squares (no two-pass); fine at fp32, D~768.
    _check("layer_norm", x, weight, bias)
    width = x.shape[-1]
    assert weight.shape == (width,) and bias.shape == (width,), (x.shape, weight.shape, bias.shape)
    rows = x.numel() // width
    out = torch.empty_like(x)
    _library().layer_norm_f32(
        out,
        x,
        weight,
        bias,
        float(eps),
        width,
        threads=(rows * GROUP, 1, 1),
        group_size=(GROUP, 1, 1),
    )
    return out


def gelu(x: torch.Tensor) -> torch.Tensor:
    _check("gelu", x)
    out = torch.empty_like(x)
    n = x.numel()
    _library().gelu_tanh_f32(out, x, n, threads=(n, 1, 1), group_size=(min(n, GROUP), 1, 1))
    return out


__all__ = ["gelu", "layer_norm"]
