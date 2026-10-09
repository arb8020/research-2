"""The model-level op: gpt2 `forward`, token ids [T] -> logits [T, vocab]. The reference is HuggingFace GPT2LMHeadModel
(eager attention); the truth is the same model in fp64 on the candidate's device. Cases are long, non-repetitive
prompts: 1-token and repetitive prompts hide the attention-scale and mask bugs (engine/ch01-forward RESULTS.md).

The candidate side is the reader's `gpt2.py`: `load(dtype) -> (weights, config)` (given) and
`forward(weights, config, tokens) -> logits`; the child's "forward" adapter loads once per dtype and calls forward.
"""

from __future__ import annotations

import functools
from typing import Any

import torch
from jaxtyping import Float, Int
from torch import Tensor

from assay.ch01 import texts
from assay.ch01.cases import Case
from assay.ch01.registry import op

MODEL_ID = "openai-community/gpt2"
VOCAB = 50257
# name -> (text, token count). ~384 and ~192 tokens: long enough that every planted bug shows (KL >= 2e-5 on the
# subtlest, exact GELU, at 69-111 tokens), short enough that the fp64 truth (T x 50257 x 8 bytes) stays ~230 MB.
PROMPTS = {"prose": (texts.LONG, 384), "code": (texts.CODE + "\n" + texts.UNICODE + "\n" + texts.MOBY_DICK, 192)}


def _local_first(load: Any) -> Any:
    """From the HF cache without touching the network (each check would pay a HEAD request per file), else download."""
    try:
        return load(local_files_only=True)
    except OSError:
        return load(local_files_only=False)


@functools.cache
def tokenizer():  # noqa: ANN201 -- tokenizers.Tokenizer; the fast library, not transformers (2 s import)
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    return Tokenizer.from_file(_local_first(lambda **kw: hf_hub_download(MODEL_ID, "tokenizer.json", **kw)))


def prompt_ids(name: str) -> list[int]:
    text, count = PROMPTS[name]
    ids = tokenizer().encode(text).ids
    assert len(ids) >= count, f"prompt {name}: only {len(ids)} tokens, want {count}"
    return ids[:count]


@functools.cache
def hf_model(dtype: torch.dtype, device: str) -> torch.nn.Module:
    from transformers import GPT2LMHeadModel
    from transformers.utils import logging

    logging.disable_progress_bar()
    model = _local_first(lambda **kw: GPT2LMHeadModel.from_pretrained(
        MODEL_ID, attn_implementation="eager", dtype=dtype, **kw))
    return model.to(device).eval()


@op(name="forward", kind="model", dims={}, dtypes=(torch.float32, torch.bfloat16))
def forward(tokens: Int[Tensor, "tokens"]) -> Float[Tensor, "tokens vocab"]:
    with torch.no_grad():
        return hf_model(torch.float32, str(tokens.device))(tokens[None], use_cache=False).logits[0]


@forward.cases
def _cases() -> list[Case]:
    return [Case((("tokens", PROMPTS[name][1]),), (), dtype, 0, prompt=name)
            for dtype in forward.sweep.dtypes for name in PROMPTS]


@forward.inputs
def _inputs(case: Case, generator: torch.Generator) -> tuple:
    return (torch.tensor(prompt_ids(case.prompt), dtype=torch.int64),)


@forward.truth
def _truth(case: Case, inputs: tuple, device: str) -> tuple[Tensor, Tensor]:
    """(fp64 truth, the reference at the case's dtype), both HF, both on `device`."""
    tokens = inputs[0].to(device)[None]
    with torch.no_grad():
        truth = hf_model(torch.float64, device)(tokens, use_cache=False).logits[0]
        reference = hf_model(case.dtype, device)(tokens, use_cache=False).logits[0]
    return truth, reference
