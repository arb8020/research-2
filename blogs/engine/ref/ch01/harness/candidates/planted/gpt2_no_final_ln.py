"""PLANTED BUG (model level): gpt2 with the final layernorm (ln_f) removed."""

import torch
from torch import Tensor

from specs.gpt2 import hf_model

MODEL = hf_model(torch.float32)
MODEL.transformer.ln_f = torch.nn.Identity()


def forward(input_ids: Tensor) -> Tensor:
    with torch.no_grad():
        return MODEL(input_ids).logits
