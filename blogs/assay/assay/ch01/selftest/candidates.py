"""Self-test candidates that are honest code: correct implementations (must PASS) and planted bugs (must FAIL, each
for its stated reason). Each check imports this whole file in its own fresh child and binds one function by name."""

import math

import torch
import torch.nn.functional as F
from torch import Tensor

# ---- correct ------------------------------------------------------------------------------------------------------


def linear(x: Tensor, weight: Tensor, bias: Tensor) -> Tensor:
    """torch's F.linear wants [out, in] weights: transpose GPT-2's [in, out]."""
    return F.linear(x, weight.T, bias)


def gelu(x: Tensor) -> Tensor:
    return F.gelu(x, approximate="tanh")


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    return F.layer_norm(x, (x.shape[-1],), weight, bias, eps)


def causal_attention(q: Tensor, k: Tensor, v: Tensor) -> Tensor:
    return F.scaled_dot_product_attention(q, k, v, is_causal=True)


# ---- planted bugs -------------------------------------------------------------------------------------------------


def linear_no_bias(x: Tensor, weight: Tensor, bias: Tensor) -> Tensor:
    """PLANTED: forgets the bias."""
    return x @ weight


def gelu_exact(x: Tensor) -> Tensor:
    """PLANTED: exact (erf) GELU where gpt2 uses the tanh approximation."""
    return F.gelu(x)


def layer_norm_no_eps(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """PLANTED: no eps. A row of one element has variance 0 -> 0/0."""
    mean = x.mean(dim=-1, keepdim=True)
    var = ((x - mean) ** 2).mean(dim=-1, keepdim=True)
    return (x - mean) / torch.sqrt(var) * weight + bias


def layer_norm_wrong_axis(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """PLANTED: normalizes over rows (dim 0) instead of the hidden dim."""
    mean = x.mean(dim=0, keepdim=True)
    var = ((x - mean) ** 2).mean(dim=0, keepdim=True)
    return (x - mean) / torch.sqrt(var + eps) * weight + bias


def layer_norm_untested_branch(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """COVERAGE DEMO: correct on every case, but has a fast path for hidden sizes that are a multiple of 1024 -- a
    size the sweep never generates -- so that branch never runs."""
    if x.shape[-1] % 1024 == 0:
        return F.layer_norm(x.float(), (x.shape[-1],), weight.float(), bias.float(), eps).to(x.dtype)
    return F.layer_norm(x, (x.shape[-1],), weight, bias, eps)


def attention_scale(q: Tensor, k: Tensor, v: Tensor) -> Tensor:
    """PLANTED: scaled by 1/head_dim instead of 1/sqrt(head_dim)."""
    seq = q.shape[-2]
    scores = q @ k.transpose(-1, -2) / q.shape[-1]
    allowed = torch.ones(seq, seq, dtype=torch.bool).tril()
    return torch.softmax(scores.masked_fill(~allowed, float("-inf")), dim=-1) @ v


def attention_mask_off_by_one(q: Tensor, k: Tensor, v: Tensor) -> Tensor:
    """PLANTED: causal mask off by one -- each query also sees the NEXT key."""
    seq = q.shape[-2]
    scores = q @ k.transpose(-1, -2) / math.sqrt(q.shape[-1])
    allowed = torch.ones(seq, seq, dtype=torch.bool).tril(diagonal=1)
    return torch.softmax(scores.masked_fill(~allowed, float("-inf")), dim=-1) @ v
