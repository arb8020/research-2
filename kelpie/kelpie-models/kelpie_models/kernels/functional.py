"""RoPE table construction: positions in, cos/sin out. The same on every device.

This is not an op and nothing dispatches on it: a forward builds its tables once, before the
first layer, and hands them to `torch.ops.kelpie.rope`. Every function that WAS an op here
(rms_norm, layer_norm, gelu, silu_mul, clamped_swiglu, grouped_mm, ...) moved to `ops.py` or to
`F.*` when kernel selection became `ops.bind` (2026-09-10).
"""

from __future__ import annotations

import math

import torch

TABLES = ("rope_tables", "yarn_rope_tables", "yarn_inv_freq")


def rope_tables(
    positions: torch.Tensor, head_dim: int, theta: float, dtype: torch.dtype
) -> tuple[torch.Tensor, torch.Tensor]:
    """cos/sin [T, head_dim] in HF's rotate-half layout (freqs duplicated across halves)."""
    inv = 1.0 / (
        theta
        ** (torch.arange(0, head_dim, 2, device=positions.device, dtype=torch.float32) / head_dim)
    )
    freqs = positions.float()[:, None] * inv[None, :]
    emb = torch.cat([freqs, freqs], dim=-1)
    return emb.cos().to(dtype), emb.sin().to(dtype)


def yarn_rope_tables(  # noqa: PLR0913, PLR0917
    positions: torch.Tensor,
    head_dim: int,
    theta: float,
    factor: float,
    beta_fast: float,
    beta_slow: float,
    original_max: int,
    truncate: bool,
    dtype: torch.dtype,
    attention_factor: float | None = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """YaRN cos/sin [T, head_dim], HF _compute_yarn_parameters: frequencies blend between
    interpolated (1/(factor*f)) and extrapolated (1/f) over a linear ramp between the
    beta_fast/beta_slow correction dims; cos/sin scaled by `attention_factor`, default
    0.1*ln(factor)+1 (DeepSeek passes mscale/mscale_all_dim's ratio instead)."""
    inv = yarn_inv_freq(
        head_dim, theta, factor, beta_fast, beta_slow, original_max, truncate, positions.device
    )
    if attention_factor is None:
        attention_factor = 0.1 * math.log(factor) + 1.0 if factor > 1 else 1.0
    freqs = positions.float()[:, None] * inv[None, :]
    emb = torch.cat([freqs, freqs], dim=-1)
    return (emb.cos() * attention_factor).to(dtype), (emb.sin() * attention_factor).to(dtype)


def yarn_inv_freq(  # noqa: PLR0913, PLR0917
    dim: int,
    theta: float,
    factor: float,
    beta_fast: float,
    beta_slow: float,
    original_max: int,
    truncate: bool,
    device: torch.device | str,
) -> torch.Tensor:
    """YaRN inverse frequencies [dim // 2] (HF _compute_yarn_parameters, without the scaling)."""
    idx = torch.arange(0, dim, 2, device=device, dtype=torch.float32)
    pos_freqs = theta ** (idx / dim)
    inv_extra = 1.0 / pos_freqs
    inv_inter = 1.0 / (factor * pos_freqs)

    def correction_dim(n_rot: float) -> float:
        return dim * math.log(original_max / (n_rot * 2 * math.pi)) / (2 * math.log(theta))

    low, high = correction_dim(beta_fast), correction_dim(beta_slow)
    if truncate is True:
        low, high = math.floor(low), math.ceil(high)
    low, high = max(low, 0), min(high, dim - 1)
    if low == high:
        high += 0.001
    dims = torch.arange(dim // 2, device=device, dtype=torch.float32)
    ramp = ((dims - low) / (high - low)).clamp(0, 1)
    extra_factor = 1 - ramp
    return inv_inter * (1 - extra_factor) + inv_extra * extra_factor
