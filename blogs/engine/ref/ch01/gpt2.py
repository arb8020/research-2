"""Chapter 1: the GPT-2 forward pass, torch functional.

Weights are a flat dict keyed by the checkpoint's own names (`h.3.attn.c_attn.weight`), so what
you read here is what is in the file. One sequence, no batch, no KV cache: `generate` recomputes
the whole prefix every step.
"""

import json
import math
from dataclasses import dataclass

import torch
import torch.nn.functional as F
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file

CHECKPOINT = "openai-community/gpt2"

Weights = dict[str, torch.Tensor]


@dataclass(frozen=True)
class Config:
    n_layer: int
    n_head: int
    n_embd: int
    vocab_size: int
    n_ctx: int  # HF n_positions: rows in wpe, so the longest sequence the model can see
    eps: float  # layer norm epsilon


def load(dtype: torch.dtype, checkpoint: str = CHECKPOINT) -> tuple[Weights, Config]:
    """Download (once, to the HF cache) and parse config.json + model.safetensors."""
    with open(hf_hub_download(checkpoint, "config.json")) as f:
        raw = json.load(f)
    if raw["activation_function"] != "gelu_new":
        raise ValueError(f"expected gelu_new (tanh GELU), got {raw['activation_function']!r}")
    if raw.get("scale_attn_by_inverse_layer_idx", False) or raw.get("reorder_and_upcast_attn", False):
        raise ValueError("this forward implements plain 1/sqrt(head_dim) attention only")
    cfg = Config(
        n_layer=raw["n_layer"],
        n_head=raw["n_head"],
        n_embd=raw["n_embd"],
        vocab_size=raw["vocab_size"],
        n_ctx=raw["n_positions"],
        eps=raw["layer_norm_epsilon"],
    )
    state = load_file(hf_hub_download(checkpoint, "model.safetensors"))
    # `h.N.attn.bias` is a stored causal-mask buffer, not a parameter; we build the mask ourselves.
    weights = {k: v.to(dtype) for k, v in state.items() if not k.endswith((".attn.bias", ".attn.masked_bias"))}
    expected = {"wte.weight", "wpe.weight", "ln_f.weight", "ln_f.bias"} | {
        f"h.{i}.{name}"
        for i in range(cfg.n_layer)
        for name in (
            "ln_1.weight", "ln_1.bias", "attn.c_attn.weight", "attn.c_attn.bias",
            "attn.c_proj.weight", "attn.c_proj.bias", "ln_2.weight", "ln_2.bias",
            "mlp.c_fc.weight", "mlp.c_fc.bias", "mlp.c_proj.weight", "mlp.c_proj.bias",
        )
    }
    if set(weights) != expected:
        raise ValueError(f"checkpoint keys differ: missing {expected - set(weights)}, extra {set(weights) - expected}")
    D = cfg.n_embd
    assert cfg.n_embd % cfg.n_head == 0
    assert weights["wte.weight"].shape == (cfg.vocab_size, D)
    assert weights["wpe.weight"].shape == (cfg.n_ctx, D)
    # HF's Conv1D stores linears as [in, out], applied as x @ W (not x @ W.T).
    assert weights["h.0.attn.c_attn.weight"].shape == (D, 3 * D)
    assert weights["h.0.mlp.c_fc.weight"].shape == (D, 4 * D)
    return weights, cfg


def layer_norm(x: torch.Tensor, w: Weights, name: str, cfg: Config) -> torch.Tensor:
    return F.layer_norm(x, (cfg.n_embd,), w[f"{name}.weight"], w[f"{name}.bias"], cfg.eps)


def linear(x: torch.Tensor, w: Weights, name: str) -> torch.Tensor:
    return x @ w[f"{name}.weight"] + w[f"{name}.bias"]


def attention(x: torch.Tensor, w: Weights, i: int, cfg: Config) -> torch.Tensor:
    """Causal multi-head self-attention. x: [T, D] -> [T, D]."""
    T, D = x.shape
    H = cfg.n_head
    hd = D // H
    q, k, v = linear(x, w, f"h.{i}.attn.c_attn").split(D, dim=-1)
    qh = q.view(T, H, hd).transpose(0, 1)  # [H, T, hd]
    kh = k.view(T, H, hd).transpose(0, 1)
    vh = v.view(T, H, hd).transpose(0, 1)
    scores = (qh @ kh.transpose(-1, -2)) / math.sqrt(hd)  # [H, T, T]
    future = torch.ones(T, T, dtype=torch.bool).triu(diagonal=1)  # True where key j > query i
    probs = torch.softmax(scores.masked_fill(future, float("-inf")), dim=-1)
    out = (probs @ vh).transpose(0, 1).reshape(T, D)
    return linear(out, w, f"h.{i}.attn.c_proj")


def mlp(x: torch.Tensor, w: Weights, i: int) -> torch.Tensor:
    up = linear(x, w, f"h.{i}.mlp.c_fc")
    return linear(F.gelu(up, approximate="tanh"), w, f"h.{i}.mlp.c_proj")


def residual_stream(w: Weights, cfg: Config, tokens: torch.Tensor) -> list[torch.Tensor]:
    """The residual stream after the embeddings and after each block: n_layer + 1 tensors [T, D]."""
    assert tokens.ndim == 1
    assert tokens.dtype == torch.long
    T = tokens.shape[0]
    assert 1 <= T <= cfg.n_ctx, f"{T} tokens, context is {cfg.n_ctx}"
    stream = [w["wte.weight"][tokens] + w["wpe.weight"][:T]]
    for i in range(cfg.n_layer):
        x = stream[-1]
        after_attn = x + attention(layer_norm(x, w, f"h.{i}.ln_1", cfg), w, i, cfg)
        after_mlp = after_attn + mlp(layer_norm(after_attn, w, f"h.{i}.ln_2", cfg), w, i)
        stream.append(after_mlp)
    assert len(stream) == cfg.n_layer + 1
    return stream


def forward(w: Weights, cfg: Config, tokens: torch.Tensor) -> torch.Tensor:
    """tokens [T] (int64) -> logits [T, vocab]: row t predicts token t + 1."""
    final = layer_norm(residual_stream(w, cfg, tokens)[-1], w, "ln_f", cfg)
    logits = final @ w["wte.weight"].T  # the lm head is tied to the token embedding
    assert logits.shape == (tokens.shape[0], cfg.vocab_size)
    return logits


@torch.no_grad()
def generate(w: Weights, cfg: Config, prompt_ids: list[int], n: int) -> list[int]:
    """Greedy decode n tokens, recomputing the whole sequence every step."""
    assert len(prompt_ids) >= 1
    assert n >= 1
    if len(prompt_ids) + n - 1 > cfg.n_ctx:
        raise ValueError(f"prompt {len(prompt_ids)} + {n} new tokens exceeds context {cfg.n_ctx}")
    ids = list(prompt_ids)
    for _ in range(n):
        logits = forward(w, cfg, torch.tensor(ids, dtype=torch.long))
        ids.append(int(logits[-1].argmax()))
    return ids[len(prompt_ids):]
