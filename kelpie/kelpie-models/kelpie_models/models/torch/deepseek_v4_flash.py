"""DeepSeek-V4-Flash forward on the kernel seam (`forward(weights, config, tokens, requests, kv,
taps)`). Reference semantics live at `kelpie_models/models/unported/deepseek_v4.py` (the old
StepBatch contract, NOT moved -- docs/brief-stubs-decisions-in-code.md: "Do not move unported/
files"); this file is the seam-shaped stub per docs/ladder.md rung 09 and
docs/cache-groups-ladder.md "DeepSeek-V4-Flash".

Cache groups (44 `compress_ratios` entries: 0 = sliding-only, 4 = CSA, 128 = HCA, entry 43 =
NextN draft not modelled here per the unported reference's own note):
  W128 (per_token, stride 1, 584 B/tok, window 128, cacheable=false) -- every layer's SWA ring.
  C4   (per_token, stride 4, KV 584 B + indexer K 132 B x21 members, retention all) -- ratio-4
       layers' compressed KV + lightning indexer.
  C128 (per_token, stride 128, 584 B, retention all) -- ratio-128 layers' compressed KV.
  S4   (per_seq, stride 0, retention inplace, n_snapshots 1) -- ratio-4 compress-state ring.
  S128 (per_seq, stride 0, retention inplace, n_snapshots 1) -- ratio-128 compress-state ring.

Custom ops this forward will call once vendored: `torch.ops.kelpie.compressed_kv_attention`
(CSA/HCA), `torch.ops.kelpie.dsa_indexer_topk` (the lightning indexer), and
`torch.ops.kelpie.moe` (the MoE) -- all declared in `kelpie_models/ops.py` today as
raising stubs.
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

CHECKPOINT = "deepseek-ai/DeepSeek-V4-Flash-0731"
CHAT_FAMILY = "deepseek"
DTYPE = "bfloat16"


@dataclass(frozen=True)
class DeepseekV4FlashConfig:
    n_layers: int
    n_heads: int
    head_dim: int
    hidden: int
    vocab: int
    max_seq_len: int
    eps: float
    compress_ratios: tuple[int, ...]  # per docs/cache-groups-ladder.md: 0 | 4 | 128 per layer
    window: int  # SWA ring width; 128 per the ladder doc
    eos_token: int


def config_from_hf(c: Mapping[str, Any]) -> DeepseekV4FlashConfig:
    return DeepseekV4FlashConfig(
        n_layers=c["num_hidden_layers"],
        n_heads=c.get("num_attention_heads", 1),
        head_dim=c.get("head_dim", 0),
        hidden=c["hidden_size"],
        vocab=c["vocab_size"],
        max_seq_len=c.get("max_position_embeddings", 0),
        eps=c.get("rms_norm_eps", 1e-6),
        compress_ratios=tuple(int(r) for r in c.get("compress_ratios", ())),
        window=128,
        eos_token=c.get("eos_token_id", 0),
    )


def attn_specs(config: DeepseekV4FlashConfig) -> list[Any]:
    """CSA(ratio, window, ...) for ratio-4 layers, HCA(ratio, window, ...) for ratio-128 layers,
    per docs/cache-groups-ladder.md "DeepSeek-V4-Flash" -> groups W128 + C4 + C128 + S4 + S128."""
    raise NotImplementedError(
        "deepseek_v4_flash.attn_specs; CSA/HCA member byte sizes (584 B KV, 132 B indexer K) and "
        "the compress-state ring shapes are not pinned for this checkpoint; decided 2026-09-09: "
        "groups W128 (window, cacheable=false) + C4 (CSA) + C128 (HCA) + S4 + S128 per "
        "docs/cache-groups-ladder.md 'DeepSeek-V4-Flash'"
    )


def load(
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.bfloat16,
    checkpoint: str = CHECKPOINT,
) -> tuple[Any, DeepseekV4FlashConfig]:
    cfg_path, _st_paths = resolve_hf(checkpoint)
    with open(cfg_path) as f:
        config = config_from_hf(json.load(f))
    raise NotImplementedError(
        "deepseek_v4_flash.load; weight pytree and torch.ops.kelpie.compressed_kv_attention / "
        "dsa_indexer_topk / moe (vendored FlashInfer + Pallas/NKI reference per "
        "docs/decisions.md 2026-09-09 session 4 'Kernel libraries') not implemented; needs a "
        "cache design pass before M7 per docs/ladder.md rung 09"
    )


def forward(
    weights: Any,
    config: DeepseekV4FlashConfig,
    tokens: Tokens,
    requests: Requests,
    kv: list[KV],
    taps: Taps,
) -> torch.Tensor:
    """-> logits [R, 1, vocab]. `kv` is written in place across groups W128, C4, C128, S4, S128
    (see module docstring); S4/S128 are per_seq state rings, not core groups, per
    docs/decisions.md index 'cache memory = one Zig slab pool...' (spike zig/cache-spike)."""
    del weights, config, tokens, requests, kv, taps
    raise NotImplementedError(
        "deepseek_v4_flash.forward; needs torch.ops.kelpie.compressed_kv_attention (CSA/HCA, "
        "vendored FlashInfer), torch.ops.kelpie.dsa_indexer_topk (lightning indexer top-k, "
        "vendored Pallas/NKI reference), and torch.ops.kelpie.moe (MoE); decided "
        "2026-09-09: kernels come from torch/vendored Triton behind kelpie:: custom ops, "
        "selection via ops.bind once in build()"
    )
