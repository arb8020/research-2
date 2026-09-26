"""DFlash drafter: a small Qwen3-shaped transformer that produces K draft tokens in one
non-autoregressive forward, conditioned on taps (target hidden states) injected as context KV.

Architecture (0.8B, 8 layers):
  - Borrows the target model's `embed_tokens` and `lm_head` (no duplicate vocab tensors)
  - Reads taps: resid_post@[configurable layers] from the target forward
  - inject: concat taps → fc → hidden_norm → per-layer k/v_proj → write into paged KV cache
  - forward: K noise positions with causal=False attention over injected context + query positions
  - Returns draft logits [T_draft, V] (caller slices to [R, K, V] using plan boundaries)

The inject happens inside `forward` — the step loop just calls
`forward(weights, config, tokens, requests, kv, taps, *, target_embed, target_lm_head)`.

Upstream reference: z-lab DFlash (Qwen3DFlashAttention).
Paged-cache inject strategy matches vllm and tokenspeed:
  1. concat taps → fc → hidden_norm → produces [ctx, hidden]
  2. per layer: layer.k_proj(hidden) → k_norm → RoPE → write_kv into paged cache
  3. drafter forward runs paged_attention(causal=False) over cache containing both context and noise
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import numpy as np
import torch
from kelpie_engine.sdk.engine import Emitted
from kelpie_engine.sdk.plan import Plan

from kelpie_models.kernels import functional as tables
from kelpie_models.kernels.ops import no_sinks
from kelpie_models.kernels.ops.paged_attention import write_kv
from kelpie_models.sdk.device import Host, Requests, Tokens
from kelpie_models.sdk.groups import AttnSpec, FullAttn
from kelpie_models.sdk.hf import load_safetensors, resolve_hf
from kelpie_models.sdk.kv import KV
from kelpie_models.sdk.taps import TapKey, Taps

if TYPE_CHECKING:
    from kelpie_engine.sdk.engine import Engine

    from kelpie_models.sdk.decide import Draw
    from kelpie_models.sdk.shapes import StepKey
    from kelpie_models.sdk.step import Step

# These are set by the HF config; defaults match the z-lab DFlash checkpoint.
DEFAULT_TAP_LAYERS = (1, 6, 11, 16, 21)
DEFAULT_N_DRAFT = 7

DTYPE = "bfloat16"


@dataclass(frozen=True)
class DFlashConfig:
    n_layers: int  # drafter transformer layers (8)
    n_heads: int
    n_kv_heads: int
    head_dim: int
    hidden: int  # drafter hidden dim
    intermediate: int
    target_hidden: int  # target model's hidden dim (for the tap projection)
    tap_layers: tuple[int, ...]  # which target layers to tap
    n_draft: int  # K = block_size - 1: drafts per step (block row 0 is the bonus token)
    mask_token_id: int  # fills block rows 1..K (z-lab: 200000, a reserved gpt-oss id)
    eps: float
    rope_theta: float
    rope_factor: float
    rope_beta_fast: float
    rope_beta_slow: float
    rope_original_max: int
    rope_truncate: bool
    vocab: int  # must match target's vocab
    max_seq_len: int
    attention_bias: bool  # whether q/k/v/o projections have biases


@dataclass(frozen=True)
class DFlashLayer:
    attn: AttnSpec
    ln_1: torch.Tensor  # rms weight [hidden]
    q: torch.Tensor  # [n_heads * head_dim, hidden]
    k: torch.Tensor
    v: torch.Tensor
    o: torch.Tensor
    q_bias: torch.Tensor | None  # [n_heads * head_dim] or None
    k_bias: torch.Tensor | None
    v_bias: torch.Tensor | None
    o_bias: torch.Tensor | None
    q_norm: torch.Tensor  # [head_dim]
    k_norm: torch.Tensor
    ln_2: torch.Tensor
    gate: torch.Tensor  # [intermediate, hidden]
    up: torch.Tensor
    down: torch.Tensor  # [hidden, intermediate]


@dataclass(frozen=True)
class DFlashInject:
    """Projection from target taps → drafter hidden for context KV injection.

    Upstream architecture: taps are concatenated along the feature dim, projected through
    fc (Linear, no bias), then RMSNorm'd.  The resulting [ctx, hidden] tensor is passed to
    each layer's own k_proj/v_proj to produce context K/V, which are written into the paged
    KV cache.

    Weights:
      fc:          [hidden, n_taps * target_hidden]  — projects concatenated taps to drafter hidden
      hidden_norm: [hidden]  — RMSNorm applied after fc
    """
    fc: torch.Tensor  # [hidden, n_taps * target_hidden]
    hidden_norm: torch.Tensor  # [hidden]


@dataclass(frozen=True)
class DFlash:
    # No embed or lm_head — borrowed from target at forward time
    inject: DFlashInject
    layers: tuple[DFlashLayer, ...]
    ln_f: torch.Tensor  # final rms norm weight [hidden]


def tap_keys(config: DFlashConfig) -> tuple[TapKey, ...]:
    """The taps this drafter needs from the target."""
    return tuple(("resid_post", i) for i in config.tap_layers)


def attn_specs(cfg: DFlashConfig) -> list[AttnSpec]:
    """All layers use full attention (no window) — the drafter attends over the full
    injected context with causal=False."""
    return [FullAttn(cfg.n_kv_heads, cfg.head_dim)] * cfg.n_layers


def inject_context_kv(
    weights: DFlash,
    config: DFlashConfig,
    taps: Taps,
    kv: list[KV],
    context_positions: torch.Tensor,
    context_slot_mapping: torch.Tensor,
) -> None:
    """Project target hidden states into K/V and write directly into the drafter's paged cache.

    This runs BEFORE the drafter forward.  After this call, each drafter layer's KV cache
    contains the injected context at `context_slot_mapping` positions.

    Flow (matches upstream z-lab DFlash + vllm/tokenspeed paged inject):
      1. Concatenate taps along feature dim → [ctx, n_taps * target_hidden]
      2. fc → hidden_norm → [ctx, hidden]
      3. Per layer: layer.k_proj(hidden) → k_norm → RoPE → write_kv
                    layer.v_proj(hidden) → write_kv
    """
    # 1. Concatenate taps along feature dim, sliced to the number of context tokens.
    # Taps may be padded (n_tokens_padded); context_slot_mapping has the real count.
    n_ctx = context_slot_mapping.shape[0]
    tap_tensors = [taps.got[("resid_post", i)][:n_ctx] for i in config.tap_layers]
    concatenated = torch.cat(tap_tensors, dim=-1)  # [n_ctx, n_taps * target_hidden]

    # 2. fc -> hidden_norm
    projected = concatenated @ weights.inject.fc.T  # [n_ctx, hidden]
    ctx_hidden = _rms(projected, weights.inject.hidden_norm, config.eps)

    # Build RoPE tables for context positions
    rope_cos, rope_sin = tables.yarn_rope_tables(
        context_positions, config.head_dim, config.rope_theta,
        config.rope_factor, config.rope_beta_fast, config.rope_beta_slow,
        config.rope_original_max, config.rope_truncate, ctx_hidden.dtype,
    )

    # 3. Per layer: project context K/V using that layer's own projections
    for layer_idx in range(config.n_layers):
        layer = weights.layers[layer_idx]

        # K: layer.k_proj(ctx_hidden) [+ bias] → k_norm → RoPE
        k = ctx_hidden @ layer.k.T
        if layer.k_bias is not None:
            k = k + layer.k_bias
        k = k.view(-1, config.n_kv_heads, config.head_dim)

        # V: layer.v_proj(ctx_hidden) [+ bias]
        v = ctx_hidden @ layer.v.T
        if layer.v_bias is not None:
            v = v + layer.v_bias
        v = v.view(-1, config.n_kv_heads, config.head_dim)

        # k_norm on context K (upstream applies k_norm to all K including noise;
        # for the paged-cache strategy, context K gets k_norm here, noise K gets it
        # in the layer's attention — functionally equivalent since k_norm is elementwise)
        k = _rms(k, layer.k_norm, config.eps)

        # RoPE on K
        k = torch.ops.kelpie.rope(k, rope_cos, rope_sin)

        # Write K/V directly into the drafter's paged cache for this layer
        write_kv(kv[0][layer_idx], k, v, context_slot_mapping)


def forward(
    weights: DFlash,
    config: DFlashConfig,
    tokens: Tokens,
    requests: Requests,
    kv: list[KV],
    taps: Taps,
    *,
    target_embed: torch.Tensor,
    target_lm_head: torch.Tensor,
    context_positions: torch.Tensor,
    context_slot_mapping: torch.Tensor,
) -> torch.Tensor:
    """-> draft logits [T_draft, vocab].

    The forward does three things:
    1. inject: project taps → context K/V, write into drafter's paged cache
    2. attend: run the drafter's transformer layers with causal=False over the full context
       (the KV cache now contains both injected context and the drafter's own K/V)
    3. project: apply the target's lm_head to get logits

    `tokens` has 1 + K rows per request: position 0 is the last-accepted token (context),
    positions 1..K are the draft (noise/mask) positions.
    `taps` has already been filled by the target forward.
    """
    assert len(kv) == 1, "dflash declares one full-attention cache group"
    inject_context_kv(weights, config, taps, kv, context_positions, context_slot_mapping)
    return draft_forward(
        weights, config, tokens, requests, kv,
        target_embed=target_embed, target_lm_head=target_lm_head,
    )


def draft_forward(  # noqa: PLR0913
    weights: DFlash,
    config: DFlashConfig,
    tokens: Tokens,
    requests: Requests,
    kv: list[KV],
    *,
    target_embed: torch.Tensor,
    target_lm_head: torch.Tensor,
) -> torch.Tensor:
    """-> draft logits [T_draft, vocab] over noise blocks whose context is already injected.
    `forward` minus the inject: the caller-written loop injects at the end of step t and drafts
    at the start of step t + 1 (docs/design-core-option2.md section 0)."""
    assert len(kv) == 1, "dflash declares one full-attention cache group"
    x = tokens.embed(target_embed)  # [T, hidden] — uses target's embedding table

    rope = tables.yarn_rope_tables(
        tokens.positions, config.head_dim, config.rope_theta,
        config.rope_factor, config.rope_beta_fast, config.rope_beta_slow,
        config.rope_original_max, config.rope_truncate, x.dtype,
    )
    for i, layer in enumerate(weights.layers):
        h = _rms(x, layer.ln_1, config.eps)
        x = x + attention(h, layer, config, i, tokens, requests, kv[0], rope)
        h = _rms(x, layer.ln_2, config.eps)
        h = torch.ops.kelpie.silu_mul(h @ layer.gate.T, h @ layer.up.T)
        x = x + h @ layer.down.T

    # --- project to logits ---
    x = _rms(x, weights.ln_f, config.eps)
    logits = x @ target_lm_head.T  # [T, vocab]

    return logits


def attention(  # noqa: PLR0913, PLR0917
    h: torch.Tensor,
    layer: DFlashLayer,
    config: DFlashConfig,
    member: int,
    tokens: Tokens,
    requests: Requests,
    kv: KV,
    rope: tuple[torch.Tensor, torch.Tensor],
) -> torch.Tensor:
    """QK-norm, RoPE, then paged_attention with causal=False."""
    cos, sin = rope
    t = h.shape[0]

    q = h @ layer.q.T
    k = h @ layer.k.T
    v = h @ layer.v.T
    if layer.q_bias is not None:
        q = q + layer.q_bias
    if layer.k_bias is not None:
        k = k + layer.k_bias
    if layer.v_bias is not None:
        v = v + layer.v_bias

    q = q.view(t, config.n_heads, config.head_dim)
    k = k.view(t, config.n_kv_heads, config.head_dim)
    v = v.view(t, config.n_kv_heads, config.head_dim)

    q = _rms(q, layer.q_norm, config.eps)
    k = _rms(k, layer.k_norm, config.eps)
    q = torch.ops.kelpie.rope(q, cos, sin)
    k = torch.ops.kelpie.rope(k, cos, sin)

    out = torch.ops.kelpie.paged_attention(
        q,
        k,
        v,
        kv[member],
        tokens.row_request,
        tokens.positions,
        requests.query_start_loc,
        requests.seq_lens,
        requests.block_tables[0],
        requests.slot_mapping[0],
        0,  # window=0 (full attention)
        no_sinks(q),
        causal=False,  # drafter attends to all positions (injected context + query)
    )

    o = out @ layer.o.T
    if layer.o_bias is not None:
        o = o + layer.o_bias
    return o


def load(
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float32,
    checkpoint: str | None = None,
) -> tuple[DFlash, DFlashConfig]:
    """Load the DFlash drafter weights from a HuggingFace checkpoint.

    The target's embed_tokens and lm_head are NOT loaded here — they are passed
    at forward time. This loads only the drafter's own parameters.
    """
    if checkpoint is None:
        raise ValueError("DFlash requires a checkpoint path (no default yet)")
    cfg_path, st_paths = resolve_hf(checkpoint)
    with open(cfg_path) as f:
        cfg = config_from_hf(json.load(f))
    return from_state_dict(load_safetensors(st_paths), cfg, device, dtype), cfg


def config_from_hf(c: Mapping[str, Any]) -> DFlashConfig:
    """Parse a DFlash HuggingFace config.json.

    Expected fields follow the Qwen3 pattern for the transformer layers, plus
    DFlash-specific fields for taps and draft configuration.
    """
    dflash_cfg = c.get("dflash_config", {})
    tap_layers = tuple(sorted(dflash_cfg.get("target_layer_ids",
                       c.get("target_layer_ids", DEFAULT_TAP_LAYERS))))
    rope = c.get("rope_scaling") or c.get("rope_parameters") or {}
    return DFlashConfig(
        n_layers=c["num_hidden_layers"],
        n_heads=c["num_attention_heads"],
        n_kv_heads=c["num_key_value_heads"],
        head_dim=c["head_dim"],
        hidden=c["hidden_size"],
        intermediate=c["intermediate_size"],
        target_hidden=c.get("target_hidden_size", c["hidden_size"]),
        tap_layers=tap_layers,
        n_draft=int(c.get("block_size", DEFAULT_N_DRAFT + 1)) - 1,
        mask_token_id=int(dflash_cfg["mask_token_id"]),
        eps=c["rms_norm_eps"],
        rope_theta=c.get("rope_theta", 1000000.0),
        rope_factor=rope.get("factor", 1.0),
        rope_beta_fast=rope.get("beta_fast", 32.0),
        rope_beta_slow=rope.get("beta_slow", 1.0),
        rope_original_max=rope.get(
            "original_max_position_embeddings",
            c.get("original_max_position_embeddings",
                   c.get("max_position_embeddings", 4096)),
        ),
        rope_truncate=rope.get("truncate", True),
        vocab=c["vocab_size"],
        max_seq_len=c.get("max_position_embeddings", 4096),
        attention_bias=c.get("attention_bias", False),
    )


def from_state_dict(
    sd: Mapping[str, torch.Tensor],
    cfg: DFlashConfig,
    device: torch.device | str,
    dtype: torch.dtype,
) -> DFlash:
    def t(name: str) -> torch.Tensor:
        return sd[name].to(device=device, dtype=dtype)

    def t_opt(name: str) -> torch.Tensor | None:
        """Load a tensor if it exists in the state dict, else None."""
        if name in sd:
            return sd[name].to(device=device, dtype=dtype)
        return None

    def layer(i: int) -> DFlashLayer:
        p = f"layers.{i}"
        return DFlashLayer(
            attn=FullAttn(cfg.n_kv_heads, cfg.head_dim),
            ln_1=t(f"{p}.input_layernorm.weight"),
            q=t(f"{p}.self_attn.q_proj.weight"),
            k=t(f"{p}.self_attn.k_proj.weight"),
            v=t(f"{p}.self_attn.v_proj.weight"),
            o=t(f"{p}.self_attn.o_proj.weight"),
            q_bias=t_opt(f"{p}.self_attn.q_proj.bias"),
            k_bias=t_opt(f"{p}.self_attn.k_proj.bias"),
            v_bias=t_opt(f"{p}.self_attn.v_proj.bias"),
            o_bias=t_opt(f"{p}.self_attn.o_proj.bias"),
            q_norm=t(f"{p}.self_attn.q_norm.weight"),
            k_norm=t(f"{p}.self_attn.k_norm.weight"),
            ln_2=t(f"{p}.post_attention_layernorm.weight"),
            gate=t(f"{p}.mlp.gate_proj.weight"),
            up=t(f"{p}.mlp.up_proj.weight"),
            down=t(f"{p}.mlp.down_proj.weight"),
        )

    # Inject weights: fc + hidden_norm (top-level model attributes)
    inject = DFlashInject(
        fc=t("fc.weight"),
        hidden_norm=t("hidden_norm.weight"),
    )

    w = DFlash(
        inject=inject,
        layers=tuple(layer(i) for i in range(cfg.n_layers)),
        ln_f=t("norm.weight"),
    )
    assert w.layers[0].q.shape == (cfg.n_heads * cfg.head_dim, cfg.hidden)
    assert w.inject.fc.shape == (cfg.hidden, len(cfg.tap_layers) * cfg.target_hidden)
    return w


def _rms(x: torch.Tensor, weight: torch.Tensor, eps: float) -> torch.Tensor:
    """Qwen3RMSNorm: normalize in fp32, cast to the input dtype, THEN scale by the weight."""
    ones = torch.ones_like(weight, dtype=torch.float32)
    return torch.ops.kelpie.rms_norm(x.float(), ones, eps).to(x.dtype) * weight


# ---- the caller-written loop (docs/design-core-option2.md 1(b)) -------------------------------
#
# ONE device program per step, `verify`: draft -> fill the extra rows -> target forward -> greedy
# accept -> inject. Every tensor in it is shaped by the plan's padded axes alone (T, R, Kmax),
# so the same program runs eagerly (`step`) or replays as one CUDA graph per decode_extra key
# (`DFlashStep.capture`); the host copies the plan in and reads (tokens, n) out, nothing else.


@dataclass(frozen=True)
class Drafter:
    """DFlash as loop (b) holds it: weights, its own cache (the context K/V it injects), which
    engine group that cache is, and the target's embedding and lm_head (it has neither)."""

    weights: DFlash
    config: DFlashConfig
    kv: list[KV]
    group: int  # the drafter cache's group index in the engine's plan
    target_embed: torch.Tensor
    target_lm_head: torch.Tensor
    # The core's scratch slot in the drafter group (on null block 0), read off a synthetic plan
    # by `build` -- never computed here. A masked noise block (`noise_batch`) writes there.
    scratch_slot: int

    @property
    def n_draft(self) -> int:
        return self.config.n_draft


def noise_batch(drafter: Drafter, tokens: Tokens, requests: Requests) -> tuple[Tokens, Requests]:
    """The drafter's FIXED batch: one noise block of 1 + K rows for EVERY padded entry, R x (1 + K)
    rows, built on device from the target's batch -- no host value, so it captures, and the batch
    is a function of the step's shape alone (R is the plan's padded request axis; for decode_extra
    the core pads that by the token bucket, c_api.zig reqsPadded, so R is fixed per key).

    An entry DRAFTS iff it carries the drafter's whole block (n_extra == K): its block is its
    tail rows -- the bonus (its newest token, at seq_start) then K mask rows at positions
    seq_start .. seq_start + K, on the drafter-group slots the core allocated for them, with its
    own seq_len and block table (z-lab spec_generate's block). Every other entry (a decode
    without extra rows, a prefill chunk, a pad, a synthetic entry with fewer extra rows) is a
    MASKED block: mask tokens at positions 0 .. K, seq_len 1 + K, a null block table and every
    row on the scratch slot, so it reads only null block 0 and writes only the scratch slot --
    storage no real entry reads (a real entry's pages are never block 0: `_check_rows`). Its
    drafts are garbage and `draft` zeroes them; rows are independent through every drafter op
    (attention is per entry), so a masked block cannot move a real entry's drafts."""
    config, group = drafter.config, drafter.group
    k = config.n_draft
    width = 1 + k
    n_reqs = requests.n_extra.shape[0]
    device = tokens.input_ids.device
    drafting = (requests.n_extra == k)[:, None]  # [R, 1]
    column = torch.arange(width, device=device)[None, :]  # [1, W]
    rows = (tokens.tail_rows[:, :1] + column).clamp(max=tokens.input_ids.shape[0] - 1)  # [R, W]
    input_ids = torch.where(drafting & (column == 0), tokens.input_ids[rows], config.mask_token_id)
    positions = torch.where(drafting, tokens.positions[rows], column)
    slots = torch.where(drafting, requests.slot_mapping[group][rows], drafter.scratch_slot)
    query_start_loc = torch.arange(0, n_reqs * width + 1, width, dtype=torch.int32, device=device)
    last_rows = query_start_loc[1:] - 1
    batch_tokens = Tokens(
        input_ids=input_ids.reshape(-1).to(torch.int32),
        positions=positions.reshape(-1).to(torch.int32),
        row_request=torch.arange(n_reqs, dtype=torch.int32, device=device).repeat_interleave(width),
        last_rows=last_rows,
        tail_rows=last_rows.long()[:, None],
    )
    zeros = torch.zeros(n_reqs, dtype=torch.int32, device=device)
    batch_requests = Requests(
        query_start_loc=query_start_loc,
        seq_lens=torch.where(drafting[:, 0], requests.seq_lens, width).to(torch.int32),
        slot_mapping=(slots.reshape(-1).to(torch.int32),),
        block_tables=(torch.where(drafting, requests.block_tables[group], 0),),
        kind=zeros,
        n_extra=zeros,
        # Nothing in the drafter reads `host` (the eager reference loop's; sdk/device.py), and
        # its real values are device data here: the same placeholder sdk/captured.py uses.
        host=Host(n_reqs=0, n_tokens=0, query_start_loc=(), seq_lens=(), req_ids=()),
    )
    return batch_tokens, batch_requests


def draft_logits(drafter: Drafter, tokens: Tokens, requests: Requests) -> torch.Tensor:
    """-> logits [R, 1 + K, V] over `noise_batch`'s blocks, one per padded entry (masked entries'
    rows included: see `draft`). Row 0 of a block is the bonus; rows 1 .. K are the drafts'."""
    batch_tokens, batch_requests = noise_batch(drafter, tokens, requests)
    n_reqs = requests.n_extra.shape[0]
    with torch.no_grad():
        logits = draft_forward(
            drafter.weights, drafter.config, batch_tokens, batch_requests, drafter.kv,
            target_embed=drafter.target_embed, target_lm_head=drafter.target_lm_head,
        )
    assert logits.shape[0] == n_reqs * (1 + drafter.n_draft), logits.shape
    return logits.view(n_reqs, 1 + drafter.n_draft, -1)


def draft(drafter: Drafter, tokens: Tokens, requests: Requests) -> torch.Tensor:
    """-> drafts i64[R, K]: the greedy draft of every entry carrying the drafter's block, 0 for
    every masked entry (whose extra rows, if any, then verify drafts of token 0: exact, just
    unlikely to be accepted)."""
    drafts = draft_logits(drafter, tokens, requests)[:, 1:].argmax(dim=-1)
    return torch.where((requests.n_extra == drafter.n_draft)[:, None], drafts, 0)


def fill_extra_rows(tokens: Tokens, requests: Requests, drafts: torch.Tensor) -> Tokens:
    """`tokens` with every extra row's input_id replaced by its draft: row t of entry r is extra
    row e = t - tail_rows[r, 0] - 1 when 0 <= e < n_extra[r]. One elementwise select over the T
    padded rows (no boolean indexing, whose shape is data), and the core's NO_TOKEN never
    reaches the embedding."""
    n_rows, k = tokens.input_ids.shape[0], drafts.shape[1]
    entry = tokens.row_request.long().clamp(min=0)  # a pad row borrows entry 0; masked below
    extra = torch.arange(n_rows, device=drafts.device) - tokens.tail_rows[entry, 0] - 1
    is_extra = (tokens.row_request >= 0) & (extra >= 0) & (extra < requests.n_extra[entry])
    filled = drafts[entry, extra.clamp(0, max(k - 1, 0))].to(tokens.input_ids.dtype)
    return replace(tokens, input_ids=torch.where(is_extra, filled, tokens.input_ids))


def inject(drafter: Drafter, taps: Taps, tokens: Tokens, requests: Requests) -> None:
    """Write the target's taps as drafter context at EVERY padded row of the plan: a real row at
    its drafter-group slot, a pad row at the scratch slot (padPlan's value). An extra row that
    was not kept sits at a position >= the next seq_start, inside the next noise block, which
    rewrites it before anything attends to it; a kept one is real context. So the drafter cache
    below n_computed is always real context (design T6)."""
    with torch.no_grad():
        inject_context_kv(
            drafter.weights, drafter.config, taps, drafter.kv, tokens.positions,
            requests.slot_mapping[drafter.group].long(),
        )


def verify(
    target: Step, drafter: Drafter, plan: Plan, batch: tuple[Tokens, Requests], draw: Draw
) -> torch.Tensor:
    """THE step's device program: draft -> fill the extra rows -> target forward -> greedy accept
    -> inject. -> i64[R, 2 + Kmax]: each padded entry's tokens [1 + Kmax] then n = 1 + accepted.

    `target` is the target's `Step`; `draw` its `sdk/decide.Draw`. `plan` is read for its shape
    alone (the target's step key and logits width) -- everything that varies step to step is in
    `batch` and `draw` on device, so a graph captured over them replays any plan of this key."""
    from kelpie_models.sdk.decide import decide  # noqa: PLC0415 -- sdk imports models lazily

    tokens, requests = batch
    with torch.no_grad():
        drafts = draft(drafter, tokens, requests)  # [R, Kmax]
        logits = target.forward_device(plan, fill_extra_rows(tokens, requests, drafts), requests)
        assert target.last_taps is not None, "the target forward fills the drafter's taps"
        out, n = decide(logits, draw, drafts, requests.n_extra)
        inject(drafter, target.last_taps, tokens, requests)
        return torch.cat([out, n[:, None]], dim=1)


def step(target: Step, drafter: Drafter, plan: Plan, *, inert: bool = False) -> Emitted:
    """One loop-(b) step, eagerly: `verify` over a fresh device batch. One H2D of the plan, one
    D2H of (tokens, n). -> Emitted(tokens u32[R, 1 + Kmax], n u32[R] = 1 + accepted drafts);
    next_extra left to the caller (DFlashStep asks for K)."""
    from kelpie_models.sdk.decide import draw_of  # noqa: PLC0415 -- sdk imports models lazily
    from kelpie_models.sdk.device import to_device  # noqa: PLC0415

    _check_plan(drafter, plan, inert=inert)
    device = target.device
    out = verify(target, drafter, plan, to_device(plan, device), draw_of(plan, device))
    return _emitted(out, plan)


class _Graphed:
    """One captured `verify` for one decode_extra key: the static batch a replay copies the plan
    into (`to_device`'s `into` + pinned staging, `draw_into`'s Draw), the graph, and its output
    i64[R, 2 + Kmax], the one thing the host reads back. Taps, drafts and logits are the graph's
    own intermediates: static by construction (the graph's memory pool)."""

    def __init__(  # noqa: PLR0913 -- the key's plan comes from the engine; pool is shared
        self, target: Step, drafter: Drafter, engine: Engine, key: StepKey, pool: tuple[int, int]
    ) -> None:
        from kelpie_models.sdk.captured import alloc_into  # noqa: PLC0415
        from kelpie_models.sdk.decide import draw_of  # noqa: PLC0415
        from kelpie_models.sdk.device import to_device  # noqa: PLC0415
        from kelpie_models.sdk.shapes import synthetic_plan  # noqa: PLC0415

        plan = synthetic_plan(engine, key)
        _check_plan(drafter, plan, inert=True)
        device = target.device
        self.target = target
        self.drafter = drafter
        self.n_tokens_padded, self.n_reqs_padded = plan.n_tokens_padded, plan.n_reqs_padded
        tokens, requests, self.pinned = alloc_into(plan, device)
        self.batch = to_device(plan, device, into=(tokens, requests), pinned=self.pinned)
        self.draw = draw_of(plan, device)
        # One eager run over the static buffers first: every op's lazy first-call init (cuBLAS
        # handles, workspaces, Triton launchers) must happen outside the capture. The synthetic
        # plan is inert by value (scratch slots, null tables), so this writes only scratch.
        verify(target, drafter, plan, self.batch, self.draw)
        torch.cuda.synchronize(device)
        self.graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(self.graph, pool=pool):
            self.out = verify(target, drafter, plan, self.batch, self.draw)
        self.logits = target.last_logits

    def __call__(self, plan: Plan) -> Emitted:
        """Copy `plan` into the static batch, replay, read (tokens, n)."""
        from kelpie_models.sdk.decide import draw_into  # noqa: PLC0415
        from kelpie_models.sdk.device import to_device  # noqa: PLC0415

        assert plan.n_tokens_padded == self.n_tokens_padded, (
            plan.n_tokens_padded, self.n_tokens_padded)
        assert plan.n_reqs_padded == self.n_reqs_padded, (plan.n_reqs_padded, self.n_reqs_padded)
        _check_plan(self.drafter, plan, inert=False)
        to_device(plan, self.target.device, into=self.batch, pinned=self.pinned)
        draw_into(plan, self.draw)
        self.graph.replay()
        # Diagnostics only (prove_dflash's tie report reads the verify rows' logits): the
        # graph's static logits ARE this step's, until the next replay.
        self.target.last_logits = self.logits
        return _emitted(self.out, plan)


class DFlashStep:
    """The StepFn the native loop runs for DFlash (docs/design-multigpu.md 2.4): `step` above,
    asking every entry for the drafter's whole block (K extra rows) on its next decode-shaped
    entry -- what the hand loop passed as next_extra (scripts/prove_dflash.py). The core drops
    extra rows that do not fit (budget, memory, a prefill), so asking always is safe.

    After `capture`, a decode_extra plan replays its key's graph; every other plan (a prefill
    chunk in the batch, a decode with every entry's extra rows dropped) runs `step` eagerly --
    the same program, warmed at every key by `warm`, so nothing compiles at serve."""

    def __init__(self, target: Step, drafter: Drafter) -> None:
        self.target = target
        self.drafter = drafter
        self.k = drafter.n_draft
        self._graphs: dict[StepKey, _Graphed] = {}

    def __call__(self, plan: Plan) -> Emitted:
        from kelpie_models.sdk.shapes import key_of  # noqa: PLC0415

        graphed = self._graphs.get(key_of(plan))
        out = step(self.target, self.drafter, plan) if graphed is None else graphed(plan)
        return Emitted(out.tokens, out.n, np.full(plan.n_reqs, self.k, dtype=np.uint32))

    def warm(self, plan: Plan) -> None:
        """`build`'s warm pass over one of the core's synthetic plans: the same step, so the
        drafter's ops (silu_mul, which gpt-oss itself never calls) resolve with the target's, at
        every shape the step meets. A synthetic decode_extra entry with fewer than K extra rows
        (buckets below 1 + K: reachable for a caller asking fewer, never for this loop) is a
        masked noise block, so the drafter warms at those keys' request axes too."""
        step(self.target, self.drafter, plan, inert=True)

    def capture(self, engine: Engine, steps: list[StepKey]) -> int:
        """One graph of `verify` per decode_extra key of the enumeration, largest first, all in
        one memory pool (replays never overlap: each step reads its output before the next).
        -> how many keys are captured."""
        from kelpie_models.kernels.op import BuildError  # noqa: PLC0415

        assert self.target.device.type == "cuda", f"capture needs a CUDA step: {self.target.device}"
        # An embeds override (a multimodal target) is a different program per plan; a graph
        # would freeze the capture-time plan's rows.
        if self.target.encoder is not None:
            raise BuildError("DFlash capture with a multimodal target is not built; build with "
                             "capture=False")
        per_seq = [g for g in engine.config.groups if g.kind != "per_token"]
        if per_seq:
            raise BuildError(f"DFlash capture with a per_seq cache group is not built ({per_seq}); "
                             f"build with capture=False")
        keys = [key for key in steps if key.family == "decode_extra"]
        assert keys, "a drafting engine with no decode_extra key to capture"
        assert keys == sorted(keys, key=lambda key: key.size, reverse=True), keys
        pool = torch.cuda.graph_pool_handle()
        for key in keys:
            assert key not in self._graphs, key
            self._graphs[key] = _Graphed(self.target, self.drafter, engine, key, pool)
        return len(self._graphs)


def _emitted(out: torch.Tensor, plan: Plan) -> Emitted:
    """`verify`'s i64[R, 2 + Kmax] -> the real entries' (tokens, n) on the host: the one D2H."""
    both = out[: plan.n_reqs].cpu().numpy().astype(np.uint32)
    return Emitted(tokens=both[:, :-1], n=both[:, -1])


def _check_plan(drafter: Drafter, plan: Plan, *, inert: bool) -> None:
    """Host checks off the plan's own numpy arrays (no device sync). Every real entry is greedy
    (Engine.submit refuses T > 0 with extra rows) and carries the drafter's whole block or none
    (the core grants all or nothing of what DFlashStep asks, which is K); a synthetic plan may
    carry fewer (its masked blocks). Then `_check_rows` over every real row's drafter slot."""
    n_reqs = plan.n_reqs
    assert (plan.sampling.top_ks[:n_reqs] == 1).all(), "a sampled request reached a greedy accept"
    n_extra = plan.requests.n_extra[:n_reqs]
    if not inert:
        assert ((n_extra == 0) | (n_extra == drafter.n_draft)).all(), (
            "an entry with a partial draft block", n_extra.tolist(), drafter.n_draft)
    # `noise_batch` reads a drafting entry's block as its tail rows: 1 history row + K extra.
    qsl = plan.requests.query_start_loc
    drafting = np.flatnonzero(n_extra == drafter.n_draft)
    assert (qsl[drafting + 1] - qsl[drafting] == 1 + drafter.n_draft).all(), (
        "a drafting entry is not 1 + K rows", drafting.tolist())
    slots = plan.tokens.slot_mapping[drafter.group][: plan.n_tokens].astype(np.int64)
    _check_rows(slots // _block_size(drafter), inert=inert, what="drafter")


def _check_rows(pages: np.ndarray, *, inert: bool, what: str) -> None:
    """A real plan's rows never touch null block 0; a synthetic (warm) plan's rows are ALL on
    it -- the core parks every write of an inert plan on the null block's scratch slot."""
    if inert:
        assert (pages == 0).all(), f"a synthetic plan's {what} row off the null block"
    else:
        assert (pages != 0).all(), f"a {what} row on the null block"


def _block_size(drafter: Drafter) -> int:
    """Tokens per page of the drafter cache ([pages, 2, block, heads, dim] per member)."""
    return int(drafter.kv[0][0].shape[2])
