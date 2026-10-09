"""PLANTED BUG (model level): gpt2 attention without the 1/sqrt(head_dim) scale."""

import torch
from torch import Tensor
from transformers import GPT2LMHeadModel

from specs.gpt2 import MODEL_ID

MODEL = GPT2LMHeadModel.from_pretrained(MODEL_ID, attn_implementation="eager",
                                        scale_attn_weights=False).eval()


def forward(input_ids: Tensor) -> Tensor:
    with torch.no_grad():
        return MODEL(input_ids).logits
