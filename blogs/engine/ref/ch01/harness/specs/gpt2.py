"""gpt2.forward: token ids -> logits. The reference is HuggingFace GPT2LMHeadModel (eager, fp32,
CPU); the truth is the same model in fp64. A model-level check: it always blocks, and it opts
into the greedy top-k logprob check on top of the logits budget.

The candidate contract is `forward(input_ids [batch, seq] int64) -> logits [batch, seq, 50257]
fp32`; the candidate loads its own weights (sending 124M params over the pipe per call would
be silly). After the merge, the chapter's real forward plugs in through a one-line adapter.
"""

from __future__ import annotations

import functools

import torch
from jaxtyping import Float, Int
from torch import Tensor

from harness.cases import Case
from harness.registry import GreedyTopK, op

MODEL_ID = "openai-community/gpt2"
VOCAB = 50257
PROMPTS = ("The capital of France is", "def fibonacci(n):", "Once upon a time, there was a")


@functools.cache
def hf_model(dtype: torch.dtype) -> torch.nn.Module:
    from transformers import GPT2LMHeadModel

    model = GPT2LMHeadModel.from_pretrained(MODEL_ID, attn_implementation="eager")
    return model.to(dtype).eval()


@functools.cache
def _tokenizer():  # noqa: ANN202 -- transformers' tokenizer type
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(MODEL_ID)


def tokenize(prompt: str) -> torch.Tensor:
    return torch.tensor([_tokenizer().encode(prompt)], dtype=torch.int64)


# seq 1 is a lone token; 64 is long enough for every position-embedding row to matter a little.
@op(name="gpt2.forward", dims={"batch": (1, 2), "seq": (1, 5, 17, 64)},
    dtypes=(torch.float32,), model=True,
    greedy=GreedyTopK(prompts=PROMPTS, steps=8, k=5, tokenize=tokenize))
def forward(input_ids: Int[Tensor, "batch seq"]) -> Float[Tensor, "batch seq vocab"]:
    with torch.no_grad():
        return hf_model(torch.float32)(input_ids).logits


@forward.truth
def _truth(input_ids: Tensor) -> Tensor:
    with torch.no_grad():
        return hf_model(torch.float64)(input_ids).logits


@forward.inputs
def _inputs(case: Case, generator: torch.Generator) -> tuple:
    sizes = dict(case.sizes)
    return (torch.randint(0, VOCAB, (sizes["batch"], sizes["seq"]), generator=generator),)
