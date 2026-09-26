"""Qwen3 forward: RMSNorm, QK-norm, RoPE, GQA, SwiGLU. Weights are a typed pytree
(Qwen3 / Qwen3Layer); the step arrives as `Tokens` and `Requests`."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import torch

from kelpie_models.kernels import functional as tables  # rope_tables: construction, not an op
from kelpie_models.sdk.device import Requests, Tokens
from kelpie_models.sdk.groups import AttnSpec, FullAttn
from kelpie_models.sdk.hf import load_safetensors, resolve_hf
from kelpie_models.sdk.kv import KV
from kelpie_models.kernels.ops import no_sinks  # importing ops declares torch.ops.kelpie.*
from kelpie_models.sdk.taps import Taps

CHECKPOINT = "Qwen/Qwen3-0.6B"
CHAT_FAMILY = "qwen3"
DTYPE = "bfloat16"


@dataclass(frozen=True)
class Qwen3Config:
    n_layers: int
    n_heads: int
    n_kv_heads: int
    head_dim: int
    hidden: int
    intermediate: int
    vocab: int
    max_seq_len: int  # HF max_position_embeddings; the engine's context bound
    eps: float
    rope_theta: float
    tie_embeddings: bool
    eos_token: int


@dataclass(frozen=True)
class Qwen3Layer:
    attn: AttnSpec
    ln_1: torch.Tensor  # rms weight [hidden]
    q: torch.Tensor  # [n_heads * head_dim, hidden], applied as x @ q.T
    k: torch.Tensor
    v: torch.Tensor
    o: torch.Tensor
    q_norm: torch.Tensor  # [head_dim]
    k_norm: torch.Tensor
    ln_2: torch.Tensor
    gate: torch.Tensor  # [intermediate, hidden]
    up: torch.Tensor
    down: torch.Tensor  # [hidden, intermediate]


@dataclass(frozen=True)
class Qwen3:
    embed: torch.Tensor  # [vocab, hidden]
    layers: tuple[Qwen3Layer, ...]
    ln_f: torch.Tensor
    lm_head: torch.Tensor  # [vocab, hidden]; is `embed` when tied


def attn_specs(cfg: Qwen3Config) -> list[AttnSpec]:
    return [FullAttn(cfg.n_kv_heads, cfg.head_dim)] * cfg.n_layers


def forward(
    weights: Qwen3,
    config: Qwen3Config,
    tokens: Tokens,
    requests: Requests,
    kv: list[KV],
    taps: Taps,
) -> torch.Tensor:
    """-> logits [R, 1, vocab] at each entry's last row. `kv` is written in place."""
    assert len(kv) == 1, "qwen3 declares one full-attention cache group"
    x = tokens.embed(weights.embed)
    rope = tables.rope_tables(tokens.positions, config.head_dim, config.rope_theta, x.dtype)
    for i, layer in enumerate(weights.layers):
        h = torch.ops.kelpie.rms_norm(x, layer.ln_1, config.eps)
        x = x + attention(h, layer, config, i, tokens, requests, kv[0], rope)
        h = torch.ops.kelpie.rms_norm(x, layer.ln_2, config.eps)
        h = torch.ops.kelpie.silu_mul(h @ layer.gate.T, h @ layer.up.T)
        x = x + h @ layer.down.T
        taps.put("resid_post", i, x, "T D")
    last = torch.ops.kelpie.rms_norm(x[tokens.last_rows.long()], weights.ln_f, config.eps)
    return (last @ weights.lm_head.T)[:, None, :]


def attention(  # noqa: PLR0913, PLR0917
    h: torch.Tensor,
    layer: Qwen3Layer,
    config: Qwen3Config,
    member: int,
    tokens: Tokens,
    requests: Requests,
    kv: KV,
    rope: tuple[torch.Tensor, torch.Tensor],
) -> torch.Tensor:
    """QK-norm (per-head RMSNorm over head_dim, HF Qwen3Attention) then RoPE. `n_kv_heads` <
    `n_heads` is the whole of GQA here: `paged_attention` repeats k/v to match q."""
    cos, sin = rope
    t = h.shape[0]
    q = (h @ layer.q.T).view(t, config.n_heads, config.head_dim)
    k = (h @ layer.k.T).view(t, config.n_kv_heads, config.head_dim)
    v = (h @ layer.v.T).view(t, config.n_kv_heads, config.head_dim)
    q_normed = torch.ops.kelpie.rms_norm(q, layer.q_norm, config.eps)
    k_normed = torch.ops.kelpie.rms_norm(k, layer.k_norm, config.eps)
    q = torch.ops.kelpie.rope(q_normed, cos, sin)
    k = torch.ops.kelpie.rope(k_normed, cos, sin)
    out = torch.ops.kelpie.paged_attention(
        q,
        k,
        v,
        kv[member],
        tokens.row_request,
        tokens.positions,
        requests.query_start_loc,
        requests.seq_lens,
        requests.block_tables[0],
        requests.slot_mapping[0],
        0,
        no_sinks(q),
    )
    return out @ layer.o.T


def load(
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float32,
    checkpoint: str = CHECKPOINT,
) -> tuple[Qwen3, Qwen3Config]:
    cfg_path, st_paths = resolve_hf(checkpoint)
    with open(cfg_path) as f:
        cfg = config_from_hf(json.load(f))
    return from_state_dict(load_safetensors(st_paths), cfg, device, dtype), cfg


def config_from_hf(c: Mapping[str, Any]) -> Qwen3Config:
    return Qwen3Config(
        n_layers=c["num_hidden_layers"],
        n_heads=c["num_attention_heads"],
        n_kv_heads=c["num_key_value_heads"],
        head_dim=c["head_dim"],
        hidden=c["hidden_size"],
        intermediate=c["intermediate_size"],
        vocab=c["vocab_size"],
        max_seq_len=c["max_position_embeddings"],
        eps=c["rms_norm_eps"],
        rope_theta=c.get("rope_theta") or c["rope_parameters"]["rope_theta"],
        tie_embeddings=c.get("tie_word_embeddings", False),
        eos_token=c["eos_token_id"],
    )


def from_state_dict(
    sd: Mapping[str, torch.Tensor],
    cfg: Qwen3Config,
    device: torch.device | str,
    dtype: torch.dtype,
) -> Qwen3:
    def t(name: str) -> torch.Tensor:
        return sd[name].to(device=device, dtype=dtype)

    def layer(i: int) -> Qwen3Layer:
        p = f"model.layers.{i}"
        return Qwen3Layer(
            attn=FullAttn(cfg.n_kv_heads, cfg.head_dim),
            ln_1=t(f"{p}.input_layernorm.weight"),
            q=t(f"{p}.self_attn.q_proj.weight"),
            k=t(f"{p}.self_attn.k_proj.weight"),
            v=t(f"{p}.self_attn.v_proj.weight"),
            o=t(f"{p}.self_attn.o_proj.weight"),
            q_norm=t(f"{p}.self_attn.q_norm.weight"),
            k_norm=t(f"{p}.self_attn.k_norm.weight"),
            ln_2=t(f"{p}.post_attention_layernorm.weight"),
            gate=t(f"{p}.mlp.gate_proj.weight"),
            up=t(f"{p}.mlp.up_proj.weight"),
            down=t(f"{p}.mlp.down_proj.weight"),
        )

    embed = t("model.embed_tokens.weight")
    if "lm_head.weight" in sd:
        lm_head = t("lm_head.weight")
    else:
        assert cfg.tie_embeddings, "no lm_head and embeddings not tied"
        lm_head = embed
    w = Qwen3(
        embed=embed,
        layers=tuple(layer(i) for i in range(cfg.n_layers)),
        ln_f=t("model.norm.weight"),
        lm_head=lm_head,
    )
    assert w.embed.shape == (cfg.vocab, cfg.hidden), w.embed.shape
    assert w.layers[0].q.shape == (cfg.n_heads * cfg.head_dim, cfg.hidden)
    return w
