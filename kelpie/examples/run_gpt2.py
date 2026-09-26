"""gpt2 on cpu through `run()`: the whole of kelpie as usage code.

    uv run --project kelpie-http python examples/run_gpt2.py                # device defaults
    uv run --project kelpie-http python examples/run_gpt2.py --my-layer-norm  # a kernels= override

`run(model, ...)` builds (bind, load, warm every step shape, freeze the kernel table) and starts
the Zig loop; the build log shows the shapes it warmed and the kernel each op resolved to:

    kernels: shapes: decode[4]=1,2,4,8 prefill[11]=1,2,...,1024
    kernels: kernels[cpu]: gelu=reference layer_norm=reference paged_attention=reference ...

A kernel is chosen per op, keyed by the op OBJECT: `kernels={ops.layer_norm: layer_norm}`. The
override replaces the op's kernel for this process (bind runs once per process); naming an op
this model never calls is an error, not a no-op.
"""

from __future__ import annotations

import argparse
import logging

import torch
from kelpie_models.kernels import ops
from kelpie_models.models.torch import gpt2
from kelpie_models.sdk.run import run
from tokenizers import Tokenizer

PROMPT = "The capital of France is"
MAX_NEW_TOKENS = 12


def layer_norm(
    x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor, eps: float
) -> torch.Tensor:
    """A user's own `kelpie::layer_norm`: same signature, its own arithmetic. It must not call
    `torch.ops.kelpie.layer_norm` (that recurses) or `F.layer_norm` (the reference in a hat)."""
    mean = x.mean(-1, keepdim=True)
    var = (x - mean).pow(2).mean(-1, keepdim=True)
    return (x - mean) * torch.rsqrt(var + eps) * weight + bias


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--my-layer-norm", action="store_true", help="kernels={ops.layer_norm: ...}")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    tokenizer = Tokenizer.from_pretrained(gpt2.CHECKPOINT)
    prompt = tokenizer.encode(PROMPT).ids
    kernels = {ops.layer_norm: layer_norm} if args.my_layer_norm else None
    with run(gpt2, device="cpu", kernels=kernels) as engine:
        rid = engine.submit(prompt, max_new_tokens=MAX_NEW_TOKENS)
        done = engine.wait(rid, timeout_s=120.0)
    print(f"{PROMPT!r} -> {tokenizer.decode(done.new_tokens)!r}")


if __name__ == "__main__":
    main()
