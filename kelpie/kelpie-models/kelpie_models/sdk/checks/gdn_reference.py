"""A naive `chunk_gated_delta_rule`: the GDN recurrence written out one token at a time.

This is the reference body for the `gated_delta_net` op -- correctness first, no chunking, no
fused kernel. The recurrence (Qwen3-Next / GatedDeltaNet, Yang et al. 2024) carries a matrix
state S [v_heads, k_dim, v_dim] and per token does

    S <- diag(g) * S + k (v - S^T k)^T * beta        (delta rule with a forget gate)
    o  = S^T q

with `g` the per-head forget gate, `beta` the per-token write strength. A fused chunked kernel
computes the same thing blockwise; this one is what it is checked against.
"""

from __future__ import annotations

import torch


def chunk_gated_delta_rule(
    q: torch.Tensor,  # [T, H, Dk]
    k: torch.Tensor,  # [T, H, Dk]
    v: torch.Tensor,  # [T, H, Dv]
    g: torch.Tensor,  # [T, H] log-space forget gate
    beta: torch.Tensor,  # [T, H]
    state: torch.Tensor,  # [H, Dk, Dv], updated in place and returned
) -> tuple[torch.Tensor, torch.Tensor]:
    """-> (out [T, H, Dv], state [H, Dk, Dv]). Sequential over T; one request's rows."""
    n_tokens, n_heads, k_dim = q.shape
    v_dim = v.shape[-1]
    assert k.shape == q.shape and v.shape == (n_tokens, n_heads, v_dim)
    assert g.shape == beta.shape == (n_tokens, n_heads)
    assert state.shape == (n_heads, k_dim, v_dim), (state.shape, (n_heads, k_dim, v_dim))

    out = torch.empty(n_tokens, n_heads, v_dim, dtype=v.dtype, device=v.device)
    s = state
    for t in range(n_tokens):
        decay = torch.exp(g[t]).reshape(n_heads, 1, 1)  # [H,1,1]
        s = decay * s
        kt = k[t].unsqueeze(-1)  # [H, Dk, 1]
        vt = v[t].unsqueeze(1)  # [H, 1, Dv]
        # delta = v - S^T k, the part of v the state does not already predict
        pred = (kt * s).sum(dim=1, keepdim=True)  # [H, 1, Dv]
        delta = (vt - pred) * beta[t].reshape(n_heads, 1, 1)
        s = s + kt * delta
        out[t] = (q[t].unsqueeze(-1) * s).sum(dim=1)  # [H, Dv]
    state.copy_(s)
    return out, state
