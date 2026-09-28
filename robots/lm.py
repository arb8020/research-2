"""Language modeling: GPT-2 weights, training forward, cross-entropy loss, data loading.

The weight dataclasses mirror kelpie's frozen-dataclass convention (GPT2, Layer, Norm, Linear)
but the forward is training-shaped: full-sequence, causal mask, standard PyTorch ops, gradients
everywhere. Kelpie's inference forward uses paged attention + custom kernels — a different
function on the same weights.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import torch
import torch.nn.functional as F

from robots.tree import register_pytree


# ---------------------------------------------------------------------------
# Weight dataclasses (same shapes as kelpie/gpt2.py)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GPT2Config:
    n_layers: int
    n_heads: int
    hidden: int
    vocab: int
    max_seq_len: int
    eps: float

    @property
    def head_dim(self) -> int:
        return self.hidden // self.n_heads


@register_pytree
@dataclass(frozen=True)
class Norm:
    w: torch.Tensor  # (hidden,)
    b: torch.Tensor  # (hidden,)


@register_pytree
@dataclass(frozen=True)
class Linear:
    w: torch.Tensor  # (in, out) — Conv1D layout, applied as x @ w
    b: torch.Tensor


@register_pytree
@dataclass(frozen=True)
class Layer:
    ln_1: Norm
    attn_qkv: Linear   # (hidden, 3 * hidden)
    attn_proj: Linear   # (hidden, hidden)
    ln_2: Norm
    fc: Linear          # (hidden, 4 * hidden)
    proj: Linear        # (4 * hidden, hidden)


@register_pytree
@dataclass(frozen=True)
class GPT2:
    wte: torch.Tensor   # (vocab, hidden) — also the lm head (tied)
    wpe: torch.Tensor   # (max_seq_len, hidden)
    layers: tuple[Layer, ...]
    ln_f: Norm


# ---------------------------------------------------------------------------
# Training forward
# ---------------------------------------------------------------------------

def gpt2_forward(weights: GPT2, config: GPT2Config, tokens: torch.Tensor) -> torch.Tensor:
    """tokens (batch, seq_len) -> logits (batch, seq_len, vocab).

    Standard transformer: embed, N x (attn + mlp), final norm, project to vocab.
    Causal mask via F.scaled_dot_product_attention(is_causal=True).
    """
    B, T = tokens.shape
    pos = torch.arange(T, device=tokens.device)

    # Embed: token + position
    x = weights.wte[tokens] + weights.wpe[pos]  # (B, T, hidden)

    for layer in weights.layers:
        # Pre-norm attention
        h = layer_norm(x, layer.ln_1, config.eps)
        x = x + attention(h, layer, config)

        # Pre-norm MLP
        h = layer_norm(x, layer.ln_2, config.eps)
        h = F.gelu(h @ layer.fc.w + layer.fc.b)    # (B, T, 4*hidden)
        x = x + h @ layer.proj.w + layer.proj.b     # (B, T, hidden)

    x = layer_norm(x, weights.ln_f, config.eps)
    logits = x @ weights.wte.T  # (B, T, vocab) — tied embedding
    return logits


def layer_norm(x: torch.Tensor, norm: Norm, eps: float) -> torch.Tensor:
    return F.layer_norm(x, (x.shape[-1],), norm.w, norm.b, eps)


def attention(h: torch.Tensor, layer: Layer, config: GPT2Config) -> torch.Tensor:
    B, T, _ = h.shape
    qkv = h @ layer.attn_qkv.w + layer.attn_qkv.b  # (B, T, 3*hidden)
    q, k, v = qkv.split(config.hidden, dim=-1)

    # Reshape to (B, n_heads, T, head_dim)
    q = q.view(B, T, config.n_heads, config.head_dim).transpose(1, 2)
    k = k.view(B, T, config.n_heads, config.head_dim).transpose(1, 2)
    v = v.view(B, T, config.n_heads, config.head_dim).transpose(1, 2)

    out = F.scaled_dot_product_attention(q, k, v, is_causal=True)  # (B, heads, T, head_dim)
    out = out.transpose(1, 2).contiguous().view(B, T, config.hidden)  # (B, T, hidden)
    return out @ layer.attn_proj.w + layer.attn_proj.b


# ---------------------------------------------------------------------------
# Loss function (plugs into train_step)
# ---------------------------------------------------------------------------

def cross_entropy_loss(
    weights: GPT2,
    batch: tuple[torch.Tensor, GPT2Config],
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """(weights, (tokens, config)) -> (loss, metrics). torch.func-safe (no .item()).

    tokens: (batch, seq_len+1). Input = tokens[:, :-1], target = tokens[:, 1:].
    """
    tokens, config = batch
    inputs = tokens[:, :-1]    # (B, T)
    targets = tokens[:, 1:]    # (B, T)

    logits = gpt2_forward(weights, config, inputs)  # (B, T, vocab)
    loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.reshape(-1))

    # "loss" itself is added by forward_backward; ppl capped to avoid overflow.
    return loss, {"ppl": loss.detach().clamp(max=20.0).exp()}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def token_loader(
    token_ids: list[int],
    seq_len: int,
    batch_size: int,
    device: str | torch.device = "cpu",
) -> callable:
    """Returns a get_batch() -> (tokens, config_placeholder) callable.

    Yields random chunks of seq_len+1 tokens (input + one target token).
    The config is passed through the batch so cross_entropy_loss can use it.
    Caller must partially apply the config.
    """
    data = torch.tensor(token_ids, dtype=torch.long, device=device)
    n = len(data)

    def get_batch() -> torch.Tensor:
        starts = torch.randint(0, n - seq_len - 1, (batch_size,))
        return torch.stack([data[s : s + seq_len + 1] for s in starts])

    return get_batch


# ---------------------------------------------------------------------------
# Load HuggingFace GPT-2 weights
# ---------------------------------------------------------------------------

def load_gpt2(
    device: str | torch.device = "cpu",
    dtype: torch.dtype = torch.float32,
    checkpoint: str = "openai-community/gpt2",
) -> tuple[GPT2, GPT2Config]:
    """Load GPT-2 weights from HuggingFace into frozen dataclasses."""
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file

    # Download config
    config_path = hf_hub_download(checkpoint, "config.json")
    with open(config_path) as f:
        hf_cfg = json.load(f)

    config = GPT2Config(
        n_layers=hf_cfg["n_layer"],
        n_heads=hf_cfg["n_head"],
        hidden=hf_cfg["n_embd"],
        vocab=hf_cfg["vocab_size"],
        max_seq_len=hf_cfg["n_positions"],
        eps=hf_cfg["layer_norm_epsilon"],
    )

    # Download weights
    st_path = hf_hub_download(checkpoint, "model.safetensors")
    sd = load_file(st_path, device=str(device))

    def t(name: str) -> torch.Tensor:
        return sd[name].to(dtype=dtype)

    def norm(p: str) -> Norm:
        return Norm(t(f"{p}.weight"), t(f"{p}.bias"))

    def linear(p: str) -> Linear:
        return Linear(t(f"{p}.weight"), t(f"{p}.bias"))

    layers = tuple(
        Layer(
            ln_1=norm(f"h.{i}.ln_1"),
            attn_qkv=linear(f"h.{i}.attn.c_attn"),
            attn_proj=linear(f"h.{i}.attn.c_proj"),
            ln_2=norm(f"h.{i}.ln_2"),
            fc=linear(f"h.{i}.mlp.c_fc"),
            proj=linear(f"h.{i}.mlp.c_proj"),
        )
        for i in range(config.n_layers)
    )

    weights = GPT2(
        wte=t("wte.weight"),
        wpe=t("wpe.weight"),
        layers=layers,
        ln_f=norm("ln_f"),
    )

    return weights, config


# ---------------------------------------------------------------------------
# Generation (for sampling during training)
# ---------------------------------------------------------------------------

def generate(
    weights: GPT2,
    config: GPT2Config,
    prompt_tokens: list[int],
    max_new_tokens: int = 50,
    temperature: float = 0.8,
) -> list[int]:
    """Autoregressive generation. Simple, not fast (recomputes full sequence each step)."""
    tokens = list(prompt_tokens)
    for _ in range(max_new_tokens):
        # Truncate to max_seq_len
        context = tokens[-config.max_seq_len :]
        x = torch.tensor([context], dtype=torch.long)
        with torch.no_grad():
            logits = gpt2_forward(weights, config, x)
        next_logits = logits[0, -1] / temperature
        probs = F.softmax(next_logits, dim=-1)
        next_token = torch.multinomial(probs, 1).item()
        tokens.append(next_token)
    return tokens
