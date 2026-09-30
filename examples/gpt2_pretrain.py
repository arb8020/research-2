"""Pretrain GPT-2 (124M) on tiny shakespeare. Uses the robots sdk + kelpie-style weights.

Downloads GPT-2 weights from HuggingFace, makes them trainable, fine-tunes on
Shakespeare with our Adam implementation. Prints loss and generates samples.

  PYTHONPATH=. robots/.venv/bin/python examples/gpt2_pretrain.py --iters 100
"""

from __future__ import annotations

import argparse
import urllib.request

import tiktoken
import torch

from observe import metrics, setup_logging
from observe.git import git_info
from robots.lm import GPT2Config, cross_entropy_loss, generate, load_gpt2, token_loader
from robots.optim import AdamParams, make_optimizer
from robots.train import train_step
from robots.tree import tensor_leaves, trainable

SHAKESPEARE_URL = "https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt"


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

# Load GPT-2 weights and make trainable
print("Loading GPT-2 weights...")
weights, config = load_gpt2(device=args.device)
weights = trainable(weights)
params = tensor_leaves(weights)
print(f"  {sum(p.numel() for p in params):,} parameters")

# Optimizer
opt = make_optimizer(params, AdamParams(lr=args.lr))

# Data loader — returns (tokens,) batch; cross_entropy_loss needs (tokens, config)
raw_loader = token_loader(token_ids, seq_len=args.seq_len, batch_size=args.batch_size, device=args.device)


def get_batch():
    return (raw_loader(), config)


# --- train ---
print(f"\nTraining for {args.iters} steps...")
for i in range(1, args.iters + 1):
    m = train_step(get_batch, cross_entropy_loss, weights, opt)
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
