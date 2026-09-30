"""Synthetic tiny configs: `tiny(model_module)` rolls that model's real HF config down to the
smallest legal shape (`synth.roll.roll`) and returns it with a random-weights `load`. Decided
2026-09-09 (docs/decisions.md session 4, "Model test set..."): tiny configs = roll(HF config) +
random weights; `deepseek_v4_tiny`, `kimi_linear_tiny`. `roll` already handles Kimi's KDA/MLA
pattern and DSV4's `compress_ratios` (kelpie_models/synth/roll.py); the two names below are the
box test set's synthetic rungs, put on one chip so the CSA/DSA and KDA classes can be tested
without a multi-hundred-GB checkpoint.
"""

from __future__ import annotations

import json
from types import ModuleType
from typing import Any, NamedTuple

from kelpie_models.sdk.hf import resolve_hf
from kelpie_models.synth.roll import RolledConfig, roll


class TinyModel(NamedTuple):
    """What `tiny(model_module)` returns: the rolled config plus a `load` that returns random
    weights on it instead of the module's own checkpoint-reading `load`."""

    config: Any
    rolled: RolledConfig
    load: Any  # (device, dtype) -> (weights, config), random-initialized


def tiny(model_module: ModuleType) -> TinyModel:
    """Roll `model_module.CHECKPOINT`'s HF config.json and return a `TinyModel` whose `load`
    builds random weights on the rolled config via `model_module.config_from_hf` +
    `model_module`'s own weight pytree shapes.

    Not implemented: no model module here has a `random_weights(config, device, dtype)` -- gpt2,
    kimi_linear and deepseek_v4_flash each build their weight pytree from a safetensors state
    dict (`from_state_dict` / not yet written); this needs a second constructor per model that
    allocates the same pytree shapes from `torch.randn` instead of `sd[key]`.
    """
    cfg_path, _st_paths = resolve_hf(model_module.CHECKPOINT)
    with open(cfg_path) as f:
        rolled = roll(json.load(f))
    raise NotImplementedError(
        f"tiny({model_module.__name__}); no random_weights(config, device, dtype) constructor "
        "on this model module; decided 2026-09-09: tiny configs = roll(HF config) + random "
        "weights; deepseek_v4_tiny, kimi_linear_tiny are the box test set's synthetic rungs "
        "(docs/decisions.md session 4)"
    )


def deepseek_v4_tiny() -> TinyModel:
    from kelpie_models.models.torch import deepseek_v4_flash

    return tiny(deepseek_v4_flash)


def kimi_linear_tiny() -> TinyModel:
    from kelpie_models.models.torch import kimi_linear

    return tiny(kimi_linear)
