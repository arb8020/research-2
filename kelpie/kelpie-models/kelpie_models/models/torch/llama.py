"""Llama-family decoder (SmolLM2, Llama-3): RMSNorm, RoPE, GQA, SwiGLU. No QK-norm (that is
Qwen3). Weights are a typed pytree; the step arrives as `Tokens` and `Requests`. Used standalone
by a Llama checkpoint and as the text tower of SmolVLM, which calls this `forward` whole."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import torch
import torch.nn.functional as F

from kelpie_models.kernels import functional as tables  # rope_tables: construction, not an op
from kelpie_models.sdk.device import Requests, Tokens
from kelpie_models.sdk.groups import AttnSpec, FullAttn
from kelpie_models.sdk.hf import load_safetensors, resolve_hf
from kelpie_models.sdk.kv import KV
from kelpie_models.kernels.ops import no_sinks  # importing ops declares torch.ops.kelpie.*
from kelpie_models.sdk.taps import Taps

CHECKPOINT = "meta-llama/Llama-3.2-1B-Instruct"
CHAT_FAMILY = "llama-3"
DTYPE = "bfloat16"


@dataclass(frozen=True)
class LlamaConfig:
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
class LlamaLayer:
    attn: AttnSpec
    ln_1: torch.Tensor  # rms weight [hidden]
    q: torch.Tensor  # [n_heads * head_dim, hidden], applied as x @ q.T
    k: torch.Tensor
    v: torch.Tensor
    o: torch.Tensor
    ln_2: torch.Tensor
    gate: torch.Tensor  # [intermediate, hidden]
    up: torch.Tensor
    down: torch.Tensor  # [hidden, intermediate]


@dataclass(frozen=True)
class Llama:
    embed: torch.Tensor  # [vocab, hidden]
    layers: tuple[LlamaLayer, ...]
    ln_f: torch.Tensor
    lm_head: torch.Tensor  # [vocab, hidden]; is `embed` when tied


def attn_specs(cfg: LlamaConfig) -> list[AttnSpec]:
    return [FullAttn(cfg.n_kv_heads, cfg.head_dim)] * cfg.n_layers


def forward(  # noqa: PLR0913, PLR0917
    weights: Llama,
    config: LlamaConfig,
    tokens: Tokens,
    requests: Requests,
    kv: list[KV],
    taps: Taps,
) -> torch.Tensor:
    """-> logits [R, 1, vocab] at each entry's last row. `kv` is written in place. Image rows of
    a SmolVLM prompt arrive already embedded on `tokens` (`Tokens.embeds`); no pixel reaches
    here."""
    assert len(kv) == 1, "llama declares one full-attention cache group"
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
    layer: LlamaLayer,
    config: LlamaConfig,
    member: int,
    tokens: Tokens,
    requests: Requests,
    kv: KV,
    rope: tuple[torch.Tensor, torch.Tensor],
) -> torch.Tensor:
    """`n_kv_heads` < `n_heads` is the whole of GQA here: `paged_attention` repeats k/v to
    match q."""
    cos, sin = rope
    t = h.shape[0]
    q = (h @ layer.q.T).view(t, config.n_heads, config.head_dim)
    k = (h @ layer.k.T).view(t, config.n_kv_heads, config.head_dim)
    v = (h @ layer.v.T).view(t, config.n_kv_heads, config.head_dim)
    q = torch.ops.kelpie.rope(q, cos, sin)
    k = torch.ops.kelpie.rope(k, cos, sin)
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
    dtype: torch.dtype = torch.bfloat16,
    checkpoint: str = CHECKPOINT,
) -> tuple[Llama, LlamaConfig]:
    cfg_path, st_paths = resolve_hf(checkpoint)
    with open(cfg_path) as f:
        cfg = config_from_hf(json.load(f))
    return from_state_dict(load_safetensors(st_paths), cfg, device, dtype), cfg


def config_from_hf(c: Mapping[str, Any], eos_token: int | None = None) -> LlamaConfig:
    heads = c["num_attention_heads"]
    return LlamaConfig(
        n_layers=c["num_hidden_layers"],
        n_heads=heads,
        n_kv_heads=c["num_key_value_heads"],
        head_dim=c.get("head_dim") or c["hidden_size"] // heads,
        hidden=c["hidden_size"],
        intermediate=c["intermediate_size"],
        vocab=c["vocab_size"],
        max_seq_len=c["max_position_embeddings"],
        eps=c["rms_norm_eps"],
        rope_theta=c.get("rope_theta") or c["rope_parameters"]["rope_theta"],
        tie_embeddings=c.get("tie_word_embeddings", False),
        eos_token=c["eos_token_id"] if eos_token is None else eos_token,
    )


def from_state_dict(  # noqa: PLR0913, PLR0917
    sd: Mapping[str, torch.Tensor],
    cfg: LlamaConfig,
    device: torch.device | str,
    dtype: torch.dtype,
    prefix: str = "model",
    lm_head: str = "lm_head.weight",
) -> Llama:
    """`prefix` is the text model's root ("model" for Llama, "model.text_model" inside Idefics3)."""

    def t(name: str) -> torch.Tensor:
        return sd[name].to(device=device, dtype=dtype)

    def layer(i: int) -> LlamaLayer:
        p = f"{prefix}.layers.{i}"
        return LlamaLayer(
            attn=FullAttn(cfg.n_kv_heads, cfg.head_dim),
            ln_1=t(f"{p}.input_layernorm.weight"),
            q=t(f"{p}.self_attn.q_proj.weight"),
            k=t(f"{p}.self_attn.k_proj.weight"),
            v=t(f"{p}.self_attn.v_proj.weight"),
            o=t(f"{p}.self_attn.o_proj.weight"),
            ln_2=t(f"{p}.post_attention_layernorm.weight"),
            gate=t(f"{p}.mlp.gate_proj.weight"),
            up=t(f"{p}.mlp.up_proj.weight"),
            down=t(f"{p}.mlp.down_proj.weight"),
        )

    embed = t(f"{prefix}.embed_tokens.weight")
    if lm_head in sd:
        head = t(lm_head)
    else:
        assert cfg.tie_embeddings, "no lm_head and embeddings not tied"
        head = embed
    w = Llama(
        embed=embed,
        layers=tuple(layer(i) for i in range(cfg.n_layers)),
        ln_f=t(f"{prefix}.norm.weight"),
        lm_head=head,
    )
    assert w.embed.shape == (cfg.vocab, cfg.hidden), w.embed.shape
    assert w.layers[0].q.shape == (cfg.n_heads * cfg.head_dim, cfg.hidden)
    return w
