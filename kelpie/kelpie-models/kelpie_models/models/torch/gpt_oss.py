"""gpt-oss: alternating sliding-window (W=128) / full GQA attention with per-head sinks, YaRN
RoPE, top-4 MoE with clamped SwiGLU. Weights are a typed pytree; the step arrives as `Tokens`
and `Requests`.

Two cache groups: sliding layers are members of the window group, full layers of the full group
(`groups.derive_groups` over the layers' AttnSpecs decides; the forward never hard-codes it).
Each layer indexes its group's member by the OFFSET derive_groups gave it, which is the layer's
position within its group -- not the layer index, because the two groups interleave. MXFP4
expert weights stay packed exactly as the hub stores them (`Mxfp4`); `kelpie::moe` owns the
dequant, so the 20b's experts are ~12 GiB resident instead of ~36 GiB.

Tensor/expert parallelism rides on `weights.mesh`: it is a field of the weight pytree, not a
forward parameter, so the six-arg signature is exact. At world 1 `Mesh.single()` makes every
collective a no-op and the forward is the single-GPU one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import torch

from kelpie_models.kernels import functional as tables  # yarn_rope_tables: construction
from kelpie_models.kernels import ops  # noqa: F401 -- declares torch.ops.kelpie.* on import
from kelpie_models.kernels.ops.moe import MXFP4_GROUP, Mxfp4
from kelpie_models.sdk.device import Requests, Tokens
from kelpie_models.sdk.groups import AttnSpec, FullAttn, SlidingAttn, derive_groups
from kelpie_models.sdk.hf import load_safetensors, resolve_hf
from kelpie_models.sdk.kv import KV
from kelpie_models.sdk.taps import Taps
from kelpie_models.shard import Mesh, all_gather, all_reduce, shard_range, shard_tensor

CHECKPOINT = "openai/gpt-oss-20b"
CHAT_FAMILY = "gpt-oss"
DTYPE = "bfloat16"
SWIGLU_ALPHA = 1.702


@dataclass(frozen=True)
class GptOssConfig:
    n_layers: int
    n_heads: int
    n_kv_heads: int
    head_dim: int
    hidden: int
    intermediate: int
    n_experts: int
    top_k: int
    vocab: int
    max_seq_len: int  # HF max_position_embeddings; the engine's context bound
    eps: float
    rope_theta: float
    rope_factor: float
    rope_beta_fast: float
    rope_beta_slow: float
    rope_original_max: int
    rope_truncate: bool
    sliding_window: int
    layer_types: tuple[str, ...]  # "sliding_attention" | "full_attention"
    swiglu_limit: float
    eos_token: int


@dataclass(frozen=True)
class GptOssLayer:
    attn: AttnSpec
    ln_1: torch.Tensor  # rms weight [hidden], kept fp32 (HF _keep_in_fp32_modules)
    q: torch.Tensor  # [n_heads * head_dim, hidden]
    q_b: torch.Tensor
    k: torch.Tensor
    k_b: torch.Tensor
    v: torch.Tensor
    v_b: torch.Tensor
    o: torch.Tensor  # [hidden, n_heads * head_dim]
    o_b: torch.Tensor
    sinks: torch.Tensor  # [n_heads]
    ln_2: torch.Tensor
    router: torch.Tensor  # [n_experts, hidden]
    router_b: torch.Tensor  # [n_experts]
    gate_up: Mxfp4  # [n_experts, 2 * intermediate, hidden / 32, 16], gate/up interleaved
    gate_up_b: torch.Tensor  # [n_experts, 2 * intermediate]
    down: Mxfp4  # [n_experts, hidden, intermediate / 32, 16]
    down_b: torch.Tensor  # [n_experts, hidden]


@dataclass(frozen=True)
class GptOss:
    embed: torch.Tensor  # [vocab, hidden]
    layers: tuple[GptOssLayer, ...]
    ln_f: torch.Tensor
    lm_head: torch.Tensor  # [vocab, hidden]
    mesh: Mesh | None = None  # runtime layout; keeps the frozen forward signature exact


def attn_specs(cfg: GptOssConfig, mesh: Mesh | None = None) -> list[AttnSpec]:
    """This rank's KV heads per layer: n_kv_heads / tp when that divides, else all of them."""
    return [attn_spec(cfg, t, local_kv_heads(cfg, mesh)) for t in cfg.layer_types]


def attn_spec(cfg: GptOssConfig, layer_type: str, kv_heads: int | None = None) -> AttnSpec:
    heads = cfg.n_kv_heads if kv_heads is None else kv_heads
    if layer_type == "sliding_attention":
        return SlidingAttn(heads, cfg.head_dim, cfg.sliding_window)
    assert layer_type == "full_attention", layer_type
    return FullAttn(heads, cfg.head_dim)


# Sharding: attention heads over tp (K/V heads too when tp divides them, else every rank keeps
# all of them); experts over ep and tp jointly ("E/ep/tp"); embed and lm_head over tp. Keyed by
# dotted field path, not Annotated[...] on the dataclass, because the K/V rule depends on cfg vs
# the mesh.


def shard_specs(cfg: GptOssConfig, mesh: Mesh) -> dict[str, str]:
    kv = "Kd/tp M" if cfg.n_kv_heads % mesh.size("tp") == 0 else "Kd M"
    kv_b = "Kd/tp" if cfg.n_kv_heads % mesh.size("tp") == 0 else "Kd"
    return {
        "embed": "V/tp M",
        "lm_head": "V/tp M",
        "layers.q": "Hd/tp M",
        "layers.q_b": "Hd/tp",
        "layers.k": kv,
        "layers.k_b": kv_b,
        "layers.v": kv,
        "layers.v_b": kv_b,
        "layers.o": "M Hd/tp",
        "layers.sinks": "H/tp",
        "layers.gate_up.blocks": "E/ep/tp I2 Mg 16",
        "layers.gate_up.scales": "E/ep/tp I2 Mg",
        "layers.gate_up_b": "E/ep/tp I2",
        "layers.down.blocks": "E/ep/tp M Ig 16",
        "layers.down.scales": "E/ep/tp M Ig",
        "layers.down_b": "E/ep/tp M",
    }


EXPERT_ROLES = ("ep", "tp")
VOCAB_ROLES = ("tp",)


def local_kv_heads(cfg: GptOssConfig, mesh: Mesh | None) -> int:
    tp = 1 if mesh is None else mesh.size("tp")
    return cfg.n_kv_heads // tp if cfg.n_kv_heads % tp == 0 else cfg.n_kv_heads


def forward(  # noqa: PLR0913, PLR0917
    weights: GptOss,
    config: GptOssConfig,
    tokens: Tokens,
    requests: Requests,
    kv: list[KV],
    taps: Taps,
) -> torch.Tensor:
    """-> logits [R, 1 + Kmax, vocab] at each entry's tail rows (tokens.tail_rows), full-vocab on
    every rank; Kmax = 0 is [R, 1, V] at the last row. `kv` is written in place. The "resid_post" tap is the residual after the
    MoE, which `moe` all_reduces to replicated ("T M")."""
    mesh = Mesh.single(tokens.input_ids.device) if weights.mesh is None else weights.mesh
    groups, layer_caches = derive_groups([layer.attn for layer in weights.layers])
    assert len(kv) == len(groups), (len(kv), len(groups))
    assert requests.n_groups == len(groups), (requests.n_groups, len(groups))
    x = embed(weights.embed, tokens, mesh)  # T M
    rope = tables.yarn_rope_tables(
        tokens.positions,
        config.head_dim,
        config.rope_theta,
        config.rope_factor,
        config.rope_beta_fast,
        config.rope_beta_slow,
        config.rope_original_max,
        config.rope_truncate,
        x.dtype,
    )
    for i, (layer, refs) in enumerate(zip(weights.layers, layer_caches, strict=True)):
        ((group, offset),) = refs
        h = rms_norm_fp32(x, layer.ln_1, config.hidden, config.eps)
        x = x + attention(h, layer, config, (group, offset), tokens, requests, kv, rope, mesh)
        h = rms_norm_fp32(x, layer.ln_2, config.hidden, config.eps)
        x = x + moe(h, layer, config, mesh)
        taps.put("resid_post", i, x, "T M")
    # Logits at every tail row: the last history row, then each extra row, [R, 1 + Kmax];
    # columns past an entry's n_extra repeat its last row and are never read. Kmax = 0 is
    # exactly the last-row gather.
    rows = tokens.tail_rows
    last = rms_norm_fp32(x[rows.reshape(-1)], weights.ln_f, config.hidden, config.eps)
    logits = all_gather("R V/tp -> R V", last @ weights.lm_head.T, mesh)
    return logits.view(rows.shape[0], rows.shape[1], -1)


def embed(table: torch.Tensor, tokens: Tokens, mesh: Mesh) -> torch.Tensor:
    """table "V/tp M": look up locally, zero where the id belongs to another rank, sum over tp.
    At world 1 this is `tokens.embed(table)` exactly. gpt-oss has no encoder, so there are no
    embeds rows to apply."""
    assert tokens.embeds is None, "gpt-oss has no encoder; nothing produces an embeds override"
    lo, hi = shard_range(table.shape[0] * mesh.size("tp"), VOCAB_ROLES, mesh)
    ids = tokens.input_ids.long()
    local = (ids >= lo) & (ids < hi)
    x = table[torch.where(local, ids - lo, 0)]  # T M {tp}
    x = torch.where(local[:, None], x, torch.zeros((), dtype=x.dtype, device=x.device))
    return all_reduce("T M {tp} -> T M", x, mesh)


def rms_norm_fp32(x: torch.Tensor, weight: torch.Tensor, hidden: int, eps: float) -> torch.Tensor:
    """HF GptOssRMSNorm normalizes and scales in fp32; cast once at the end. The fp32 promotion
    is this model's, not the op's -- `kelpie::rms_norm` normalizes in whatever dtype it is
    handed, so the cast belongs at the call site that wants it."""
    del hidden
    return torch.ops.kelpie.rms_norm(x.float(), weight, eps).to(x.dtype)


def attention(  # noqa: PLR0913, PLR0917
    h: torch.Tensor,
    layer: GptOssLayer,
    config: GptOssConfig,
    cache: tuple[int, int],
    tokens: Tokens,
    requests: Requests,
    kv: list[KV],
    rope: tuple[torch.Tensor, torch.Tensor],
    mesh: Mesh,
) -> torch.Tensor:
    """h "T M" replicated; q/k/v/o weights head-sharded over tp; o's contraction over Hd/tp
    leaves a partial sum, all_reduced below. `cache` is this layer's (group, member offset):
    the group picks the block table / slot mapping, the offset picks the member within it."""
    group, member = cache
    cos, sin = rope
    t = h.shape[0]
    q = (h @ layer.q.T + layer.q_b).view(t, -1, config.head_dim)  # T H/tp D
    k = (h @ layer.k.T + layer.k_b).view(t, -1, config.head_dim)  # T Hkv(/tp) D
    v = (h @ layer.v.T + layer.v_b).view(t, -1, config.head_dim)
    q = torch.ops.kelpie.rope(q, cos, sin)
    k = torch.ops.kelpie.rope(k, cos, sin)
    window = layer.attn.window if isinstance(layer.attn, SlidingAttn) else 0
    o = torch.ops.kelpie.paged_attention(
        q,
        k,
        v,
        kv[group][member],
        tokens.row_request,
        tokens.positions,
        requests.query_start_loc,
        requests.seq_lens,
        requests.block_tables[group],
        requests.slot_mapping[group],
        window,
        layer.sinks,
    )
    y = o @ layer.o.T  # T M {tp}
    return all_reduce("T M {tp} -> T M", y, mesh) + layer.o_b


def moe(h: torch.Tensor, layer: GptOssLayer, cfg: GptOssConfig, mesh: Mesh) -> torch.Tensor:
    """Top-k router (replicated, HF GptOssTopKRouter), then `kelpie::moe` on device. Expert
    tables are "E/ep/tp": this rank holds experts [e_lo, e_hi) and the op returns only their
    contribution; partials sum over ep and tp."""
    logits = h @ layer.router.T + layer.router_b  # [T, E]
    top_v, top_i = torch.topk(logits, cfg.top_k, dim=-1)
    weights = torch.softmax(top_v, dim=-1, dtype=top_v.dtype)  # [T, k]
    e_lo, _ = shard_range(cfg.n_experts, EXPERT_ROLES, mesh)
    out = torch.ops.kelpie.moe(
        h, top_i, weights,
        layer.gate_up.blocks, layer.gate_up.scales, layer.gate_up_b,
        layer.down.blocks, layer.down.scales, layer.down_b,
        e_lo, SWIGLU_ALPHA, cfg.swiglu_limit,
    )  # T M {ep,tp}
    return all_reduce("T M {ep,tp} -> T M", out, mesh)


def load(
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.bfloat16,
    checkpoint: str = CHECKPOINT,
    mesh: Mesh | None = None,
) -> tuple[GptOss, GptOssConfig]:
    """With a mesh, each tensor is sliced to this rank (shard_specs) before it is moved or
    dequantized, so a rank never materialises more than its shard."""
    cfg_path, st_paths = resolve_hf(checkpoint)
    with open(cfg_path) as f:
        cfg = config_from_hf(json.load(f))
    return from_state_dict(load_safetensors(st_paths), cfg, device, dtype, mesh), cfg


def config_from_hf(c: Mapping[str, Any]) -> GptOssConfig:
    rope = c.get("rope_scaling") or c.get("rope_parameters") or {}
    return GptOssConfig(
        n_layers=c["num_hidden_layers"],
        n_heads=c["num_attention_heads"],
        n_kv_heads=c["num_key_value_heads"],
        head_dim=c["head_dim"],
        hidden=c["hidden_size"],
        intermediate=c["intermediate_size"],
        n_experts=c["num_local_experts"],
        top_k=c["num_experts_per_tok"],
        vocab=c["vocab_size"],
        max_seq_len=c["max_position_embeddings"],
        eps=c["rms_norm_eps"],
        rope_theta=c.get("rope_theta") or rope["rope_theta"],
        rope_factor=rope.get("factor", 1.0),
        rope_beta_fast=rope.get("beta_fast", 32.0),
        rope_beta_slow=rope.get("beta_slow", 1.0),
        rope_original_max=rope.get(
            "original_max_position_embeddings", c["max_position_embeddings"]
        ),
        rope_truncate=rope.get("truncate", True),
        sliding_window=c["sliding_window"],
        layer_types=tuple(c["layer_types"][: c["num_hidden_layers"]]),
        swiglu_limit=c.get("swiglu_limit", 7.0),
        eos_token=c["eos_token_id"],
    )


def from_state_dict(
    sd: Mapping[str, torch.Tensor],
    cfg: GptOssConfig,
    device: torch.device | str,
    dtype: torch.dtype,
    mesh: Mesh | None = None,
) -> GptOss:
    """Experts come as hub MXFP4 (`gate_up_proj_blocks` + `_scales`), sliced along E for this
    rank and moved to `device` still packed. A dequantized checkpoint (`gate_up_proj`) is
    refused: re-quantizing it would be a lossy step nothing here should take silently."""
    specs = {} if mesh is None else shard_specs(cfg, mesh)

    def take(field: str, x: torch.Tensor) -> torch.Tensor:
        return x if field not in specs or mesh is None else shard_tensor(x, specs[field], mesh)

    def t(field: str, name: str, dt: torch.dtype = dtype) -> torch.Tensor:
        return take(field, sd[name]).to(device=device, dtype=dt)

    def expert(field: str, p: str, name: str) -> Mxfp4:
        if f"{p}.{name}_blocks" not in sd:
            raise ValueError(f"{p}.{name}: gpt-oss loads hub MXFP4 (`{name}_blocks`/`_scales`); "
                             f"a dequantized checkpoint is not supported")
        return Mxfp4(
            blocks=take(f"{field}.blocks", sd[f"{p}.{name}_blocks"]).to(device),
            scales=take(f"{field}.scales", sd[f"{p}.{name}_scales"]).to(device),
        )

    def layer(i: int) -> GptOssLayer:
        p = f"model.layers.{i}"
        a, e = f"{p}.self_attn", f"{p}.mlp.experts"
        return GptOssLayer(
            attn=attn_spec(cfg, cfg.layer_types[i], local_kv_heads(cfg, mesh)),
            ln_1=t("layers.ln_1", f"{p}.input_layernorm.weight", torch.float32),
            q=t("layers.q", f"{a}.q_proj.weight"),
            q_b=t("layers.q_b", f"{a}.q_proj.bias"),
            k=t("layers.k", f"{a}.k_proj.weight"),
            k_b=t("layers.k_b", f"{a}.k_proj.bias"),
            v=t("layers.v", f"{a}.v_proj.weight"),
            v_b=t("layers.v_b", f"{a}.v_proj.bias"),
            o=t("layers.o", f"{a}.o_proj.weight"),
            o_b=t("layers.o_b", f"{a}.o_proj.bias"),
            sinks=t("layers.sinks", f"{a}.sinks", torch.float32),
            ln_2=t("layers.ln_2", f"{p}.post_attention_layernorm.weight", torch.float32),
            router=t("layers.router", f"{p}.mlp.router.weight"),
            router_b=t("layers.router_b", f"{p}.mlp.router.bias"),
            gate_up=expert("layers.gate_up", e, "gate_up_proj"),
            gate_up_b=t("layers.gate_up_b", f"{e}.gate_up_proj_bias"),
            down=expert("layers.down", e, "down_proj"),
            down_b=t("layers.down_b", f"{e}.down_proj_bias"),
        )

    w = GptOss(
        embed=t("embed", "model.embed_tokens.weight"),
        layers=tuple(layer(i) for i in range(cfg.n_layers)),
        ln_f=t("ln_f", "model.norm.weight", torch.float32),
        lm_head=t("lm_head", "lm_head.weight"),
        mesh=mesh,
    )
    tp = 1 if mesh is None else mesh.size("tp")
    e_local = cfg.n_experts if mesh is None else cfg.n_experts // (tp * mesh.size("ep"))
    assert w.embed.shape == (cfg.vocab // tp, cfg.hidden), w.embed.shape
    groups = MXFP4_GROUP
    assert w.layers[0].gate_up.blocks.shape == (
        e_local, 2 * cfg.intermediate, cfg.hidden // groups, groups // 2)
    assert w.layers[0].gate_up.scales.shape == (
        e_local, 2 * cfg.intermediate, cfg.hidden // groups)
    assert w.layers[0].down.blocks.shape == (
        e_local, cfg.hidden, cfg.intermediate // groups, groups // 2)
    assert w.layers[0].down.scales.shape == (e_local, cfg.hidden, cfg.intermediate // groups)
    return w


def to_hf_state_dict(w: GptOss) -> dict[str, torch.Tensor]:
    """Tensors are shared, not copied, so an HF oracle built from this costs no extra memory."""
    sd = {
        "model.embed_tokens.weight": w.embed,
        "model.norm.weight": w.ln_f,
        "lm_head.weight": w.lm_head,
    }
    names = {
        "ln_1": "input_layernorm.weight",
        "q": "self_attn.q_proj.weight",
        "q_b": "self_attn.q_proj.bias",
        "k": "self_attn.k_proj.weight",
        "k_b": "self_attn.k_proj.bias",
        "v": "self_attn.v_proj.weight",
        "v_b": "self_attn.v_proj.bias",
        "o": "self_attn.o_proj.weight",
        "o_b": "self_attn.o_proj.bias",
        "sinks": "self_attn.sinks",
        "ln_2": "post_attention_layernorm.weight",
        "router": "mlp.router.weight",
        "router_b": "mlp.router.bias",
        "gate_up_b": "mlp.experts.gate_up_proj_bias",
        "down_b": "mlp.experts.down_proj_bias",
    }
    packed = {"gate_up": "mlp.experts.gate_up_proj", "down": "mlp.experts.down_proj"}
    for i, layer in enumerate(w.layers):
        for name, hf_name in names.items():
            sd[f"model.layers.{i}.{hf_name}"] = getattr(layer, name)
        for name, hf_name in packed.items():
            table = getattr(layer, name)
            sd[f"model.layers.{i}.{hf_name}_blocks"] = table.blocks
            sd[f"model.layers.{i}.{hf_name}_scales"] = table.scales
    return sd
