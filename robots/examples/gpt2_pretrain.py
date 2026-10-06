"""Pretrain GPT-2 (124M) on tiny shakespeare. Kelpie-style weights.

Self-contained: everything except Adam (robots.optim) and the pytree helpers
(robots.tree) is defined in this file.

Downloads GPT-2 weights from HuggingFace, makes them trainable, fine-tunes on
Shakespeare with our Adam implementation. Prints loss and generates samples.

  PYTHONPATH=. robots/.venv/bin/python robots/examples/gpt2_pretrain.py --iters 100
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import tiktoken
import torch
import torch.nn.functional as F

from observe import metrics, setup_logging
from observe.git import git_info
from robots.optim import AdamParams, AdamState, adam_scalars, adam_update_, init_adam
from robots.tree import register_pytree, tensor_leaves

SHAKESPEARE_URL = "https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt"


# ---------------------------------------------------------------------------
# Model: GPT-2 weight dataclasses (same shapes as kelpie/gpt2.py)
#
# The weight dataclasses mirror kelpie's frozen-dataclass convention (GPT2, Layer, Norm, Linear)
# but the forward is training-shaped: full-sequence, causal mask, standard PyTorch ops, gradients
# everywhere. Kelpie's inference forward uses paged attention + custom kernels — a different
# function on the same weights.
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
# Model: training forward
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
# Model: load HuggingFace GPT-2 weights
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
# Data loading
# ---------------------------------------------------------------------------

def download_shakespeare() -> str:
    """Download tiny shakespeare, cached in runs/."""
    import os

    cache = "runs/tinyshakespeare.txt"
    if os.path.exists(cache):
        with open(cache) as f:
            return f.read()
    os.makedirs("runs", exist_ok=True)
    print(f"Downloading tiny shakespeare...")
    data, _ = urllib.request.urlretrieve(SHAKESPEARE_URL, cache)
    with open(cache) as f:
        return f.read()


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
# Algorithm: loss function (plugs into train_step)
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
# Train: one generic step
#
#   train_step(loss_fn, weights, opt_state, inputs, cfg, step)
#     = forward_backward(loss_fn, weights, inputs)             -> grads, metrics
#     + adam_update_(weights, grads, opt_state, cfg, adam_scalars(cfg, step, device_of(weights)))
# ---------------------------------------------------------------------------

W = TypeVar("W")
I = TypeVar("I")

# (weights, inputs) -> (scalar loss, metrics). Metrics are tensors so a LossFn
# stays torch.func-safe (no .item()); convert with to_floats at the logging edge.
LossFn = Callable[[W, I], tuple[torch.Tensor, dict[str, torch.Tensor]]]
Metrics = dict[str, torch.Tensor]


def forward_backward(
    loss_fn: LossFn[W, I],
    weights: W,
    inputs: I,
) -> tuple[W, Metrics]:
    """Gradients of loss_fn w.r.t. weights, plus the loss_fn's metrics.

    grads has the same dataclass type as weights (one grad tensor per weight
    tensor). Nothing is mutated: no .grad, no optimizer. Requires the weight
    dataclass to be a registered pytree (robots.tree.register_pytree).
    metrics gains a "loss" entry.
    """
    grad_fn = torch.func.grad_and_value(loss_fn, argnums=0, has_aux=True)
    grads, (loss, metrics) = grad_fn(weights, inputs)
    assert type(grads) is type(weights)
    assert "loss" not in metrics
    return grads, {**metrics, "loss": loss.detach()}


def device_of(weights: Any) -> torch.device:
    """The device of a weight tree (asserts all leaves agree)."""
    leaves = tensor_leaves(weights)
    assert len(leaves) > 0
    device = leaves[0].device
    assert all(x.device == device for x in leaves), "weights span multiple devices"
    return device


def train_step(
    loss_fn: LossFn[W, I],
    weights: W,
    opt_state: AdamState[W],
    inputs: I,
    cfg: AdamParams,
    step: int,
) -> tuple[AdamState[W], Metrics]:
    """One update: forward_backward, then Adam in place on weights. step is 1-based."""
    grads, metrics = forward_backward(loss_fn, weights, inputs)
    scalars = adam_scalars(cfg, step, device_of(weights))
    new_state = adam_update_(weights, grads, opt_state, cfg, scalars)
    return new_state, metrics


def to_floats(metrics: Metrics) -> dict[str, float]:
    """Logging edge: tensor metrics -> Python floats (one host sync per metric)."""
    return {k: v.item() for k, v in metrics.items()}


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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Fine-tune GPT-2 on tiny shakespeare")
    p.add_argument("--name", default="gpt2-shakespeare", help="Run name")
    p.add_argument("--iters", type=int, default=100)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--seq-len", type=int, default=128)
    p.add_argument("--lr", type=float, default=3e-5)
    p.add_argument("--sample-every", type=int, default=20, help="Generate a sample every N steps")
    p.add_argument("--device", default="cpu")
    args = p.parse_args()

    # --- setup ---
    setup_logging(
        log_file=f"runs/{args.name}.jsonl",
        static_fields={"run_name": args.name, **git_info()},
    )

    # Tokenize
    print("Tokenizing...")
    enc = tiktoken.get_encoding("gpt2")
    text = download_shakespeare()
    token_ids = enc.encode(text)
    print(f"  {len(text):,} chars -> {len(token_ids):,} tokens")

    # Load GPT-2 weights. No requires_grad needed: forward_backward uses torch.func.grad.
    print("Loading GPT-2 weights...")
    weights, config = load_gpt2(device=args.device)
    print(f"  {sum(p.numel() for p in tensor_leaves(weights)):,} parameters")

    # Optimizer: config + state; the loop owns the step counter
    cfg = AdamParams(lr=args.lr)
    opt_state = init_adam(weights)

    # Data loader — returns tokens; cross_entropy_loss takes (tokens, config)
    raw_loader = token_loader(token_ids, seq_len=args.seq_len, batch_size=args.batch_size, device=args.device)


    # --- train ---
    print(f"\nTraining for {args.iters} steps...")
    for i in range(1, args.iters + 1):
        opt_state, m_t = train_step(cross_entropy_loss, weights, opt_state, (raw_loader(), config), cfg, step=i)
        m = to_floats(m_t)
        metrics(m, step=i)

        if i % 10 == 0 or i == 1:
            print(f"  step {i}: loss={m['loss']:.4f}  ppl={m['ppl']:.1f}")

        if i % args.sample_every == 0:
            prompt = enc.encode("ROMEO:")
            generated = generate(weights, config, prompt, max_new_tokens=100, temperature=0.8)
            sample = enc.decode(generated)
            print(f"\n--- sample (step {i}) ---")
            print(sample[:300])
            print("---\n")

    print("Done.")


if __name__ == "__main__":
    main()
