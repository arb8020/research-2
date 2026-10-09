"""gpt2.forward candidate that just calls HuggingFace: proves the plumbing end to end. The
chapter's real forward replaces this after the merge (same signature)."""

import torch
from torch import Tensor

from specs.gpt2 import hf_model

MODEL = hf_model(torch.float32)  # loaded at import, inside the child, before READY


def forward(input_ids: Tensor) -> Tensor:
    with torch.no_grad():
        return MODEL(input_ids).logits
