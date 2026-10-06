"""Pretrain GPT-2 (124M) on tiny shakespeare. Uses the robots sdk + kelpie-style weights.

Downloads GPT-2 weights from HuggingFace, makes them trainable, fine-tunes on
Shakespeare with our Adam implementation. Prints loss and generates samples.

  PYTHONPATH=. robots/.venv/bin/python robots/examples/gpt2_pretrain.py --iters 100
"""

from __future__ import annotations

import argparse
import urllib.request

import tiktoken
import torch

from observe import metrics, setup_logging
from observe.git import git_info
from robots.lm import GPT2Config, cross_entropy_loss, generate, load_gpt2, token_loader
from robots.optim import AdamParams, init_adam
from robots.train import to_floats, train_step
from robots.tree import tensor_leaves

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
