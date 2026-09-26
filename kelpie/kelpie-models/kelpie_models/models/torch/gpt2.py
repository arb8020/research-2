"""GPT-2 forward. Weights are a typed pytree (GPT2 / Layer / Norm); the step arrives as the two
views a forward reads (`Tokens`, `Requests`) and the kv it writes in place."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import torch
import torch.nn.functional as F

from kelpie_models.sdk.device import Requests, Tokens
from kelpie_models.sdk.groups import AttnSpec, FullAttn
from kelpie_models.sdk.hf import load_safetensors, resolve_hf
from kelpie_models.sdk.kv import KV
from kelpie_models.kernels.ops import no_sinks  # importing ops declares torch.ops.kelpie.*
from kelpie_models.sdk.taps import Taps

CHECKPOINT = "openai-community/gpt2"
CHAT_FAMILY = "default"
DTYPE = "float32"


@dataclass(frozen=True)
class GPT2Config:
    n_layers: int
    n_heads: int
    hidden: int
    vocab: int
    max_seq_len: int  # HF n_positions; the engine's context bound
    eps: float
    eos_token: int

    @property
    def head_dim(self) -> int:
        return self.hidden // self.n_heads

    @property
    def n_kv_heads(self) -> int:
        return self.n_heads


@dataclass(frozen=True)
class Norm:
    w: torch.Tensor
    b: torch.Tensor


@dataclass(frozen=True)
class Linear:
    w: torch.Tensor  # [in, out], applied as x @ w (HF Conv1D layout)
    b: torch.Tensor


@dataclass(frozen=True)
class Layer:
    attn: AttnSpec
    ln_1: Norm
    attn_qkv: Linear  # [hidden, 3 * hidden]
    attn_proj: Linear
    ln_2: Norm
    fc: Linear
    proj: Linear


@dataclass(frozen=True)
class GPT2:
    wte: torch.Tensor  # [vocab, hidden]; also the lm head
    wpe: torch.Tensor  # [max_seq_len, hidden]
    layers: tuple[Layer, ...]
    ln_f: Norm


def attn_specs(cfg: GPT2Config) -> list[AttnSpec]:
    return [FullAttn(cfg.n_kv_heads, cfg.head_dim)] * cfg.n_layers


def forward(  # noqa: PLR0913, PLR0917
    weights: GPT2,
    config: GPT2Config,
    tokens: Tokens,
    requests: Requests,
    kv: list[KV],
    taps: Taps,
) -> torch.Tensor:
    """-> logits [R, 1, vocab] at each entry's last row. `kv` is written in place."""
    assert len(kv) == 1, "gpt2 declares one full-attention cache group"
    x = tokens.embed(weights.wte) + weights.wpe[tokens.positions.long()]
    for i, layer in enumerate(weights.layers):
        h = torch.ops.kelpie.layer_norm(x, layer.ln_1.w, layer.ln_1.b, config.eps)
        x = x + attention(h, layer, config, i, tokens, requests, kv[0])
        h = torch.ops.kelpie.layer_norm(x, layer.ln_2.w, layer.ln_2.b, config.eps)
        h = torch.ops.kelpie.gelu(h @ layer.fc.w + layer.fc.b)
        x = x + h @ layer.proj.w + layer.proj.b
        taps.put("resid_post", i, x, "T D")
    last = torch.ops.kelpie.layer_norm(
        x[tokens.last_rows.long()], weights.ln_f.w, weights.ln_f.b, config.eps
    )
    return (last @ weights.wte.T)[:, None, :]


def attention(  # noqa: PLR0913, PLR0917
    h: torch.Tensor,
    layer: Layer,
    config: GPT2Config,
    member: int,
    tokens: Tokens,
    requests: Requests,
    kv: KV,
) -> torch.Tensor:
    qkv = h @ layer.attn_qkv.w + layer.attn_qkv.b
    q, k, v = (
        t.view(h.shape[0], config.n_heads, config.head_dim) for t in qkv.split(config.hidden, -1)
    )
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
    return out @ layer.attn_proj.w + layer.attn_proj.b


def load(
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float32,
    checkpoint: str = CHECKPOINT,
) -> tuple[GPT2, GPT2Config]:
    cfg_path, st_paths = resolve_hf(checkpoint)
    with open(cfg_path) as f:
        cfg = config_from_hf(json.load(f))
    return from_state_dict(load_safetensors(st_paths), cfg, device, dtype), cfg


def config_from_hf(c: Mapping[str, Any]) -> GPT2Config:
    return GPT2Config(
        n_layers=c["n_layer"],
        n_heads=c["n_head"],
        hidden=c["n_embd"],
        vocab=c["vocab_size"],
        max_seq_len=c["n_positions"],
        eps=c["layer_norm_epsilon"],
        eos_token=c["eos_token_id"],
    )


def from_state_dict(
    sd: Mapping[str, torch.Tensor],
    cfg: GPT2Config,
    device: torch.device | str,
    dtype: torch.dtype,
) -> GPT2:
    def t(name: str) -> torch.Tensor:
        key = name if name in sd else "transformer." + name
        return sd[key].to(device=device, dtype=dtype)

    def norm(p: str) -> Norm:
        return Norm(t(f"{p}.weight"), t(f"{p}.bias"))

    def linear(p: str) -> Linear:
        return Linear(t(f"{p}.weight"), t(f"{p}.bias"))

    layers = tuple(
        Layer(
            attn=FullAttn(cfg.n_kv_heads, cfg.head_dim),
            ln_1=norm(f"h.{i}.ln_1"),
            attn_qkv=linear(f"h.{i}.attn.c_attn"),
            attn_proj=linear(f"h.{i}.attn.c_proj"),
            ln_2=norm(f"h.{i}.ln_2"),
            fc=linear(f"h.{i}.mlp.c_fc"),
            proj=linear(f"h.{i}.mlp.c_proj"),
        )
        for i in range(cfg.n_layers)
    )
    w = GPT2(wte=t("wte.weight"), wpe=t("wpe.weight"), layers=layers, ln_f=norm("ln_f"))
    assert w.wte.shape == (cfg.vocab, cfg.hidden), w.wte.shape
    assert w.layers[0].attn_qkv.w.shape == (cfg.hidden, 3 * cfg.hidden)
    return w
