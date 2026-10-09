"""Chapter 1: the GPT-2 forward pass, torch functional.

Weights are a flat dict keyed by the checkpoint's own names (`h.3.attn.c_attn.weight`). One sequence, no batch, no
KV cache: `generate` recomputes the whole prefix every step.

The code between `# region: <name>` and `# endregion` is yours to write; everything else is given. The ops the checks
grade (linear, gelu_tanh, layer_norm, causal_attention) take plain tensors, so they can be tested alone.
"""

import json
import math
from dataclasses import dataclass

import torch
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


# HF's GPT-2 stores its linears as Conv1D, [in, out]; load() transposes them to [out, in], the usual layout.
CONV1D = ("attn.c_attn.weight", "attn.c_proj.weight", "mlp.c_fc.weight", "mlp.c_proj.weight")


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
    for k in weights:
        if k.endswith(CONV1D):
            weights[k] = weights[k].T.contiguous()
    D = cfg.n_embd
    assert cfg.n_embd % cfg.n_head == 0
    assert weights["wte.weight"].shape == (cfg.vocab_size, D)
    assert weights["wpe.weight"].shape == (cfg.n_ctx, D)
    assert weights["h.0.attn.c_attn.weight"].shape == (3 * D, D)
    assert weights["h.0.mlp.c_fc.weight"].shape == (4 * D, D)
    return weights, cfg


# region: linear
def linear(x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor) -> torch.Tensor:
    """x [rows, in] -> [rows, out]; weight is [out, in]."""
    return x @ weight.T + bias
# endregion


# region: gelu
def gelu_tanh(x: torch.Tensor) -> torch.Tensor:
    """GPT-2's GELU, the tanh approximation: 0.5 x (1 + tanh(sqrt(2/pi) (x + 0.044715 x^3)))."""
    return 0.5 * x * (1.0 + torch.tanh(math.sqrt(2.0 / math.pi) * (x + 0.044715 * x**3)))
# endregion


# region: layer_norm
def layer_norm(x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor, eps: float) -> torch.Tensor:
    """(x - mean) / sqrt(var + eps) * weight + bias over the last dim; biased variance."""
    mean = x.mean(dim=-1, keepdim=True)
    var = ((x - mean) ** 2).mean(dim=-1, keepdim=True)
    return (x - mean) / torch.sqrt(var + eps) * weight + bias
# endregion


# region: attention
def causal_attention(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor) -> torch.Tensor:
    """softmax(q k^T / sqrt(head_dim)) v, each position seeing itself and the past. [..., seq, head_dim]."""
    T = q.shape[-2]
    scores = (q @ k.transpose(-1, -2)) / math.sqrt(q.shape[-1])
    future = torch.ones(T, T, dtype=torch.bool).triu(diagonal=1)  # True where key j > query i
    return torch.softmax(scores.masked_fill(future, float("-inf")), dim=-1) @ v


def attention(x: torch.Tensor, w: Weights, i: int, cfg: Config) -> torch.Tensor:
    """Causal multi-head self-attention of block i. x: [T, D] -> [T, D]."""
    T, D = x.shape
    H = cfg.n_head
    hd = D // H
    q, k, v = linear(x, w[f"h.{i}.attn.c_attn.weight"], w[f"h.{i}.attn.c_attn.bias"]).split(D, dim=-1)
    heads = [t.view(T, H, hd).transpose(0, 1) for t in (q, k, v)]  # [H, T, hd]
    out = causal_attention(*heads).transpose(0, 1).reshape(T, D)
    return linear(out, w[f"h.{i}.attn.c_proj.weight"], w[f"h.{i}.attn.c_proj.bias"])
# endregion


# region: block
def mlp(x: torch.Tensor, w: Weights, i: int) -> torch.Tensor:
    up = linear(x, w[f"h.{i}.mlp.c_fc.weight"], w[f"h.{i}.mlp.c_fc.bias"])
    return linear(gelu_tanh(up), w[f"h.{i}.mlp.c_proj.weight"], w[f"h.{i}.mlp.c_proj.bias"])


def block(x: torch.Tensor, w: Weights, i: int, cfg: Config) -> torch.Tensor:
    """Transformer block i (pre-norm): x + attention(ln_1(x)), then + mlp(ln_2(.)). [T, D] -> [T, D]."""
    x = x + attention(layer_norm(x, w[f"h.{i}.ln_1.weight"], w[f"h.{i}.ln_1.bias"], cfg.eps), w, i, cfg)
    return x + mlp(layer_norm(x, w[f"h.{i}.ln_2.weight"], w[f"h.{i}.ln_2.bias"], cfg.eps), w, i)
# endregion


# region: forward
def forward(w: Weights, cfg: Config, tokens: torch.Tensor) -> torch.Tensor:
    """tokens [T] (int64) -> logits [T, vocab]: row t predicts token t + 1."""
    assert tokens.ndim == 1
    assert tokens.dtype == torch.long
    T = tokens.shape[0]
    assert 1 <= T <= cfg.n_ctx, f"{T} tokens, context is {cfg.n_ctx}"
    x = w["wte.weight"][tokens] + w["wpe.weight"][:T]
    for i in range(cfg.n_layer):
        x = block(x, w, i, cfg)
    final = layer_norm(x, w["ln_f.weight"], w["ln_f.bias"], cfg.eps)
    logits = final @ w["wte.weight"].T  # the lm head is tied to the token embedding
    assert logits.shape == (T, cfg.vocab_size)
    return logits
# endregion


# region: generate
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
# endregion
