"""Self-test candidates that are honest code: correct implementations (must PASS) and planted bugs (must FAIL, each
for its stated reason). Each check imports this whole file in its own fresh child and binds one function by name."""

import math

import torch
import torch.nn.functional as F
from torch import Tensor

# ---- correct ------------------------------------------------------------------------------------------------------


def linear(x_TD: Tensor, w_DF: Tensor, b_F: Tensor) -> Tensor:
    """torch's F.linear wants [out, in] weights: transpose GPT-2's [in, out]."""
    return F.linear(x_TD, w_DF.T, b_F)


def gelu(x: Tensor) -> Tensor:
    return F.gelu(x, approximate="tanh")


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    return F.layer_norm(x, (x.shape[-1],), weight, bias, eps)


def attention(q_TNH: Tensor, k_SNH: Tensor, v_SNH: Tensor) -> Tensor:
    """torch's SDPA wants heads first: [N, T, H]."""
    q, k, v = (t.transpose(0, 1) for t in (q_TNH, k_SNH, v_SNH))
    return F.scaled_dot_product_attention(q, k, v, is_causal=True).transpose(0, 1)


# ---- planted bugs -------------------------------------------------------------------------------------------------


def linear_no_bias(x_TD: Tensor, w_DF: Tensor, b_F: Tensor) -> Tensor:
    """PLANTED: forgets the bias."""
    return x_TD @ w_DF


def gelu_exact(x: Tensor) -> Tensor:
    """PLANTED: exact (erf) GELU where gpt2 uses the tanh approximation."""
    return F.gelu(x)


def layer_norm_no_eps(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """PLANTED: no eps. A row of one element has variance 0 -> 0/0."""
    mean = x.mean(dim=-1, keepdim=True)
    var = ((x - mean) ** 2).mean(dim=-1, keepdim=True)
    return (x - mean) / torch.sqrt(var) * weight + bias


def layer_norm_wrong_axis(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """PLANTED: normalizes over T (dim 0) instead of D."""
    mean = x.mean(dim=0, keepdim=True)
    var = ((x - mean) ** 2).mean(dim=0, keepdim=True)
    return (x - mean) / torch.sqrt(var + eps) * weight + bias


def layer_norm_untested_branch(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """COVERAGE DEMO: correct on every case, but has a fast path for hidden sizes that are a multiple of 1024 -- a
    size the sweep never generates -- so that branch never runs."""
    if x.shape[-1] % 1024 == 0:
        return F.layer_norm(x.float(), (x.shape[-1],), weight.float(), bias.float(), eps).to(x.dtype)
    return F.layer_norm(x, (x.shape[-1],), weight, bias, eps)


def _attend(q_TNH: Tensor, k_SNH: Tensor, v_SNH: Tensor, scale: float, diagonal: int) -> Tensor:
    q, k, v = (t.transpose(0, 1) for t in (q_TNH, k_SNH, v_SNH))  # [N, T|S, H]
    T, S = q.shape[-2], k.shape[-2]
    scores = q @ k.transpose(-1, -2) * scale
    allowed = torch.ones(T, S, dtype=torch.bool).tril(diagonal=diagonal)
    return (torch.softmax(scores.masked_fill(~allowed, float("-inf")), dim=-1) @ v).transpose(0, 1)


def attention_scale(q_TNH: Tensor, k_SNH: Tensor, v_SNH: Tensor) -> Tensor:
    """PLANTED: scaled by 1/H instead of 1/sqrt(H)."""
    return _attend(q_TNH, k_SNH, v_SNH, 1 / q_TNH.shape[-1], 0)


def attention_mask_off_by_one(q_TNH: Tensor, k_SNH: Tensor, v_SNH: Tensor) -> Tensor:
    """PLANTED: causal mask off by one -- each query also sees the NEXT key."""
    return _attend(q_TNH, k_SNH, v_SNH, 1 / math.sqrt(q_TNH.shape[-1]), 1)
