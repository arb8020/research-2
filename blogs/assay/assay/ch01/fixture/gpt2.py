"""TEST FIXTURE, not chapter content: engine/ref/ch01/gpt2.py reshaped into the op-shaped functions the ch01 checks
bind by name (linear, gelu, layer_norm, causal_attention, forward), with `# region:` markers. The chapter's real
region file replaces this once it lands; until then `run_checks ch01` is demoed and tested against this tree.
"""

import json
import math
from dataclasses import dataclass

import torch
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file

CHECKPOINT = "openai-community/gpt2"

Weights = dict[str, torch.Tensor]


# region: load
@dataclass(frozen=True)
class Config:
    n_layer: int
    n_head: int
    n_embd: int
    vocab_size: int
    n_ctx: int
    eps: float


def load(dtype: torch.dtype, checkpoint: str = CHECKPOINT) -> tuple[Weights, Config]:
    with open(hf_hub_download(checkpoint, "config.json")) as f:
        raw = json.load(f)
    cfg = Config(raw["n_layer"], raw["n_head"], raw["n_embd"], raw["vocab_size"], raw["n_positions"],
                 raw["layer_norm_epsilon"])
    state = load_file(hf_hub_download(checkpoint, "model.safetensors"))
    weights = {k: v.to(dtype) for k, v in state.items() if not k.endswith((".attn.bias", ".attn.masked_bias"))}
    return weights, cfg
# endregion


# region: linear
def linear(x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor) -> torch.Tensor:
    """GPT-2 stores linears as [in, out]: x @ W + b."""
    return x @ weight + bias
# endregion


# region: gelu
def gelu(x: torch.Tensor) -> torch.Tensor:
    return 0.5 * x * (1.0 + torch.tanh(math.sqrt(2.0 / math.pi) * (x + 0.044715 * x**3)))
# endregion


# region: layer_norm
def layer_norm(x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor, eps: float) -> torch.Tensor:
    mean = x.mean(dim=-1, keepdim=True)
    var = ((x - mean) ** 2).mean(dim=-1, keepdim=True)
    return (x - mean) / torch.sqrt(var + eps) * weight + bias
# endregion


# region: attention
def causal_attention(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor) -> torch.Tensor:
    """q, k, v: [heads, T, head_dim] -> [heads, T, head_dim]."""
    T = q.shape[-2]
    scores = (q @ k.transpose(-1, -2)) / math.sqrt(q.shape[-1])
    future = torch.ones(T, T, dtype=torch.bool, device=q.device).triu(diagonal=1)
    return torch.softmax(scores.masked_fill(future, float("-inf")), dim=-1) @ v


def attention(x: torch.Tensor, w: Weights, i: int, cfg: Config) -> torch.Tensor:
    T, D = x.shape
    H = cfg.n_head
    q, k, v = linear(x, w[f"h.{i}.attn.c_attn.weight"], w[f"h.{i}.attn.c_attn.bias"]).split(D, dim=-1)
    heads = [t.view(T, H, D // H).transpose(0, 1) for t in (q, k, v)]
    out = causal_attention(*heads).transpose(0, 1).reshape(T, D)
    return linear(out, w[f"h.{i}.attn.c_proj.weight"], w[f"h.{i}.attn.c_proj.bias"])
# endregion


# region: block
def mlp(x: torch.Tensor, w: Weights, i: int) -> torch.Tensor:
    up = linear(x, w[f"h.{i}.mlp.c_fc.weight"], w[f"h.{i}.mlp.c_fc.bias"])
    return linear(gelu(up), w[f"h.{i}.mlp.c_proj.weight"], w[f"h.{i}.mlp.c_proj.bias"])


def block(x: torch.Tensor, w: Weights, i: int, cfg: Config) -> torch.Tensor:
    x = x + attention(layer_norm(x, w[f"h.{i}.ln_1.weight"], w[f"h.{i}.ln_1.bias"], cfg.eps), w, i, cfg)
    return x + mlp(layer_norm(x, w[f"h.{i}.ln_2.weight"], w[f"h.{i}.ln_2.bias"], cfg.eps), w, i)
# endregion


# region: forward
def forward(w: Weights, cfg: Config, tokens: torch.Tensor) -> torch.Tensor:
    """tokens [T] (int64) -> logits [T, vocab]: row t predicts token t + 1."""
    T = tokens.shape[0]
    x = w["wte.weight"][tokens] + w["wpe.weight"][:T]
    for i in range(cfg.n_layer):
        x = block(x, w, i, cfg)
    x = layer_norm(x, w["ln_f.weight"], w["ln_f.bias"], cfg.eps)
    return x @ w["wte.weight"].T
# endregion


# region: generate
@torch.no_grad()
def generate(w: Weights, cfg: Config, prompt_ids: list[int], n: int) -> list[int]:
    ids = list(prompt_ids)
    for _ in range(n):
        ids.append(int(forward(w, cfg, torch.tensor(ids, dtype=torch.long))[-1].argmax()))
    return ids[len(prompt_ids):]
# endregion
