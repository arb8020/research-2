"""Kimi-Linear-48B-A3B forward: 20 KDA (recurrent gated delta) layers + 7 MLA layers with no
RoPE (`mla_use_nope`), per docs/ladder.md rung 04 and docs/cache-groups-ladder.md "Kimi-K3".

Not implemented yet. Cache groups per the ladder doc:
  F (per_token, stride 1, MLA latent 1152 B, retention all) -- the 24 MLA layers' KV.
  R (per_seq, stride 0, retention inplace, n_snapshots 1) -- the KDA layers' temporal +
    conv state ring (69 layers; 6,512,640 B/request at K3 scale). Not a core group until the
    Zig slab-pool ruling lands (docs/decisions.md index: "cache memory = one Zig slab pool,
    groups carve pages; recurrent state is a per_seq group" -> kelpie-core/src/kv_pool.zig:Pool,
    kelpie_models/groups.py:derive_groups; spike zig/cache-spike).

Custom ops this forward will call once vendored: `torch.ops.kelpie.chunk_gated_delta_rule`
(the KDA recurrence, vendored from flash-linear-attention) and `torch.ops.kelpie.mla_attention`
(the MLA layers, no-RoPE variant) -- both declared in `kelpie_models/ops.py` today as raising
stubs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import torch

from kelpie_models.sdk.device import Requests, Tokens
from kelpie_models.sdk.hf import resolve_hf
from kelpie_models.sdk.kv import KV
from kelpie_models.sdk.taps import Taps

CHECKPOINT = "moonshotai/Kimi-Linear-48B-A3B-Instruct"
CHAT_FAMILY = "kimi"
DTYPE = "bfloat16"


@dataclass(frozen=True)
class KimiLinearConfig:
    n_layers: int
    n_heads: int
    n_kv_heads: int
    head_dim: int
    hidden: int
    intermediate: int
    vocab: int
    max_seq_len: int
    eps: float
    kda_layers: tuple[int, ...]  # 0-indexed layer numbers that are KDA (recurrent)
    mla_latent: int
    mla_rope: int  # 0: mla_use_nope
    eos_token: int


def config_from_hf(c: Mapping[str, Any]) -> KimiLinearConfig:
    """`docs/ladder.md` rung 04: 20 KDA layers (`linear_attn_config.kda_layers`, 1-indexed in the
    checkpoint) + 7 MLA layers, `mla_use_nope` so `mla_rope=0`."""
    lac = c.get("linear_attn_config", {})
    kda = tuple(int(i) - 1 for i in lac.get("kda_layers", ()))
    return KimiLinearConfig(
        n_layers=c["num_hidden_layers"],
        n_heads=c["num_attention_heads"],
        n_kv_heads=c.get("num_key_value_heads", c["num_attention_heads"]),
        head_dim=c.get("head_dim", c["hidden_size"] // c["num_attention_heads"]),
        hidden=c["hidden_size"],
        intermediate=c["intermediate_size"],
        vocab=c["vocab_size"],
        max_seq_len=c.get("max_position_embeddings", 0),
        eps=c.get("rms_norm_eps", 1e-6),
        kda_layers=kda,
        mla_latent=c.get("kv_lora_rank", 512),
        mla_rope=0 if c.get("mla_use_nope", True) else c.get("qk_rope_head_dim", 64),
        eos_token=c.get("eos_token_id", 0),
    )


def attn_specs(config: KimiLinearConfig) -> list[Any]:
    """MLA(latent, rope=0) on the 24 MLA layers, Recurrent(...) on the 20+ KDA layers -- see
    module docstring for the F/R group split. Not implemented: the KDA state shape (temporal +
    conv rings) is not yet pinned for this checkpoint size."""
    raise NotImplementedError(
        "kimi_linear.attn_specs; KDA Recurrent state shape (temporal + conv rings) not pinned "
        "for this checkpoint; decided 2026-09-09: 20 KDA + 7 MLA-no-RoPE layers per docs/ladder.md "
        "rung 04, cache groups F (MLA latent, per_token all) + R (KDA state, per_seq inplace) per "
        "docs/cache-groups-ladder.md 'Kimi-K3'"
    )


def load(
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.bfloat16,
    checkpoint: str = CHECKPOINT,
) -> tuple[Any, KimiLinearConfig]:
    cfg_path, _st_paths = resolve_hf(checkpoint)
    with open(cfg_path) as f:
        config = config_from_hf(json.load(f))
    raise NotImplementedError(
        "kimi_linear.load; weight pytree and torch.ops.kelpie.chunk_gated_delta_rule "
        "(vendored from flash-linear-attention, per docs/decisions.md 2026-09-09 session 4 "
        "'Kernel libraries') not implemented; decided 2026-09-09: KDA generalizes GDN so "
        "qwen3_next needs no separate kernel once this lands"
    )


def forward(
    weights: Any,
    config: KimiLinearConfig,
    tokens: Tokens,
    requests: Requests,
    kv: list[KV],
    taps: Taps,
) -> torch.Tensor:
    """-> logits [R, 1, vocab]. `kv` is written in place: group 0 (F, MLA) and the KDA per_seq
    state ring (group 1 once the Zig slab-pool ruling lands; today a Python StateRing, per
    docs/decisions.md index 'cache memory = one Zig slab pool...')."""
    del weights, config, tokens, requests, kv, taps
    raise NotImplementedError(
        "kimi_linear.forward; needs torch.ops.kelpie.chunk_gated_delta_rule (KDA recurrence, "
        "vendored flash-linear-attention Triton) and torch.ops.kelpie.mla_attention (no-RoPE "
        "MLA layers, vendored FlashInfer); decided 2026-09-09: kernels come from torch/vendored "
        "Triton behind kelpie:: custom ops, selection via ops.bind once in build()"
    )
