"""DeepSeek-V3.2 forward over the StepBatch contract: MLA attention with the DSA lightning
indexer on every layer, dense MLP on the first `first_k_dense_replace` layers, then MoE with
sigmoid noaux_tc grouped top-k routing and shared experts; YaRN RoPE (interleaved on MLA,
rotate-half on the indexer); one MTP (NextN) layer. GLM-5 shares the attention.

Cache groups: every layer's AttnSpec is MLA(latent, rope, indexer=IndexerSpec(...)), which lowers
to two per_token members of different widths (latent+rope and indexer K); derive_groups puts
all of them, MTP layer included, into ONE group (one array per member, kelpie_models.kv), so one
block table and one release serve both caches of a token. The forward never hard-codes the group.

HF's DeepseekV32ForCausalLM drops the MTP layer's weights on load, so the MTP head is
served from the checkpoint's `model.layers.{n_layers}` names and has no HF oracle of its own
(tests build one from HF's decoder layer class). Weights are a typed pytree.
"""

from __future__ import annotations

# ruff: noqa: E402 -- the raise is deliberately ABOVE the imports: this module's imports are
# the deleted pre-Plan path, so importing it must fail with a reason, not an ImportError.
raise NotImplementedError(
    "unported: needs batch.StepBatch, kv.KV, facts; these were the pre-Plan path and were deleted "
    "2026-09-10. Port this model to forward(weights, config, tokens, requests, kv, taps) "
    "the way models/torch/qwen3.py is written; see docs/ladder.md for the order."
)

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import torch

from kelpie_models.batch import StepBatch, embed_tokens
from kelpie_models.kernels.functional import yarn_rope_tables
from kelpie_models.sdk.groups import MLA, AttnSpec, IndexerSpec, derive_groups
from kelpie_models.sdk.hf import load_safetensors, resolve_hf
from kelpie_models.sdk.kv import KV

MODEL_ID = "deepseek-ai/DeepSeek-V3.2"
CHECKPOINT = MODEL_ID  # kelpie_models.facts: the launch layer reads these, not a name table
CHAT_FAMILY = "deepseek-v3.2"
DTYPE = "bfloat16"
ADAPTER = None


@dataclass(frozen=True)
class DeepseekV32Config:
    n_layers: int
    n_mtp: int  # NextN layers after the trunk (num_nextn_predict_layers)
    n_heads: int
    hidden: int
    q_lora: int
    kv_lora: int
    nope: int  # qk_nope_head_dim
    rope: int  # qk_rope_head_dim
    v_dim: int
    index_heads: int
    index_dim: int
    index_topk: int
    intermediate: int
    moe_intermediate: int
    n_experts: int
    top_k: int
    n_group: int
    topk_group: int
    n_shared: int
    routed_scale: float
    norm_topk: bool
    mlp_types: tuple[str, ...]  # "dense" | "sparse" per trunk layer; MTP layers are sparse
    vocab: int
    eps: float
    rope_theta: float
    rope_factor: float
    rope_beta_fast: float
    rope_beta_slow: float
    rope_original_max: int
    rope_mscale: float
    rope_mscale_all_dim: float
    eos_token: int

    @property
    def qk_dim(self) -> int:
        return self.nope + self.rope

    @property
    def softmax_scale(self) -> float:
        """HF yarn_apply_mscale: qk_dim^-0.5 * mscale^2 with mscale from mscale_all_dim."""
        scale = self.qk_dim**-0.5
        if self.rope_mscale_all_dim and self.rope_factor > 1:
            m = 0.1 * self.rope_mscale_all_dim * math.log(self.rope_factor) + 1.0
            scale *= m * m
        return scale

    @property
    def rope_attention_factor(self) -> float:
        """HF _compute_yarn_parameters with both mscale and mscale_all_dim set."""

        def mscale(m: float) -> float:
            return 0.1 * m * math.log(self.rope_factor) + 1.0 if self.rope_factor > 1 else 1.0

        if self.rope_mscale and self.rope_mscale_all_dim:
            return mscale(self.rope_mscale) / mscale(self.rope_mscale_all_dim)
        return mscale(1.0)


@dataclass(frozen=True)
class Attention:
    q_a: torch.Tensor  # [q_lora, hidden]
    q_a_norm: torch.Tensor  # [q_lora]
    q_b: torch.Tensor  # [n_heads * qk_dim, q_lora]
    kv_a: torch.Tensor  # [kv_lora + rope, hidden]
    kv_a_norm: torch.Tensor  # [kv_lora]
    kv_b: torch.Tensor  # [n_heads * (nope + v_dim), kv_lora]
    o: torch.Tensor  # [hidden, n_heads * v_dim]
    idx_wq_b: torch.Tensor  # [index_heads * index_dim, q_lora]
    idx_wk: torch.Tensor  # [index_dim, hidden]
    idx_k_norm: torch.Tensor  # layer norm weight [index_dim]
    idx_k_norm_b: torch.Tensor  # layer norm bias [index_dim]
    idx_weights: torch.Tensor  # [index_heads, hidden]


@dataclass(frozen=True)
class Dense:
    gate: torch.Tensor  # [inter, hidden]
    up: torch.Tensor
    down: torch.Tensor  # [hidden, inter]


@dataclass(frozen=True)
class Moe:
    router: torch.Tensor  # [n_experts, hidden]
    router_bias: torch.Tensor  # [n_experts] fp32 (e_score_correction_bias)
    gate_up: torch.Tensor  # [n_experts, hidden, 2 * moe_inter]: gate half then up half
    down: torch.Tensor  # [n_experts, moe_inter, hidden]
    shared: Dense


@dataclass(frozen=True)
class Layer:
    attn_spec: AttnSpec
    ln_1: torch.Tensor
    attn: Attention
    ln_2: torch.Tensor
    mlp: Dense | Moe


@dataclass(frozen=True)
class Mtp:
    """NextN head: eh_proj(cat(enorm(embed(next token)), hnorm(trunk hidden))) -> a decoder
    layer -> norm; logits through the trunk's lm_head."""

    enorm: torch.Tensor
    hnorm: torch.Tensor
    eh_proj: torch.Tensor  # [hidden, 2 * hidden]
    layer: Layer
    norm: torch.Tensor


@dataclass(frozen=True)
class DeepseekV32:
    embed: torch.Tensor  # [vocab, hidden]
    layers: tuple[Layer, ...]
    mtp: tuple[Mtp, ...]
    ln_f: torch.Tensor
    lm_head: torch.Tensor  # [vocab, hidden]


def attn_specs(cfg: DeepseekV32Config) -> list[AttnSpec]:
    """Trunk layers then MTP layers: the MTP layer is one more member of the same group."""
    return [attn_spec(cfg) for _ in range(cfg.n_layers + cfg.n_mtp)]


def attn_spec(cfg: DeepseekV32Config) -> AttnSpec:
    return MLA(
        cfg.kv_lora,
        cfg.rope,
        indexer=IndexerSpec(cfg.index_heads, cfg.index_dim, cfg.index_topk),
    )


def forward(  # noqa: PLR0913, PLR0917
    w: DeepseekV32, cfg: DeepseekV32Config, batch: StepBatch, kv: list[KV], state: None, ops
) -> tuple[torch.Tensor, list[KV], None]:
    """-> (logits [padded_num_reqs, 1 + K, vocab] at each request's accept_index rows, kv,
    state). No per-request state: every layer's cache is a member of the one group."""
    assert state is None, "deepseek_v32 keeps no per-request state"
    x, kv = hidden_states(w, cfg, batch, kv, ops)
    last = ops.rms_norm(x[batch.accept_index.long()], w.ln_f, cfg.eps)
    return last @ w.lm_head.T, kv, None


def hidden_states(
    w: DeepseekV32, cfg: DeepseekV32Config, batch: StepBatch, kv: list[KV], ops
) -> tuple[torch.Tensor, list[KV]]:
    """(trunk output before the final norm, [padded_num_tokens, hidden] -- what the MTP head
    eats, kv)."""
    groups, layer_caches = derive_groups(attn_specs(cfg), itemsize=w.embed.element_size())
    assert len(kv) == len(groups), (len(kv), len(groups))
    x = embed_tokens(w.embed, batch)
    rope = rope_tables(cfg, batch, x.dtype)
    for layer, refs in zip(w.layers, layer_caches[: cfg.n_layers], strict=True):
        x, kv = decoder_layer(x, layer, cfg, refs, batch, kv, rope, ops)
    return x, kv


def mtp_forward(  # noqa: PLR0913, PLR0917  -- (w, cfg, batch, kv, ops, hidden, next_ids)
    w: DeepseekV32,
    cfg: DeepseekV32Config,
    batch: StepBatch,
    kv: list[KV],
    ops,
    hidden: torch.Tensor,
    next_ids: torch.Tensor,
    which: int = 0,
) -> tuple[torch.Tensor, list[KV]]:
    """MTP head `which` over the trunk's `hidden` (hidden_states) and `next_ids`
    [padded_num_tokens]: for row t (token at position p) the id of the token at p + 1 (the next
    prompt token, or the token just sampled at a request's last row). Writes the MTP layer's own
    latent + indexer members (layer_caches[n_layers + which]) and returns (logits
    [padded_num_reqs, 1 + K, vocab] at each request's accept_index rows: the draft for position
    p + 2, kv)."""
    groups, layer_caches = derive_groups(attn_specs(cfg), itemsize=w.embed.element_size())
    assert len(kv) == len(groups), (len(kv), len(groups))
    mtp = w.mtp[which]
    e = ops.rms_norm(w.embed[next_ids.long()], mtp.enorm, cfg.eps)
    h = ops.rms_norm(hidden, mtp.hnorm, cfg.eps)
    x = torch.cat([e, h], dim=-1) @ mtp.eh_proj.T
    rope = rope_tables(cfg, batch, x.dtype)
    refs = layer_caches[cfg.n_layers + which]
    x, kv = decoder_layer(x, mtp.layer, cfg, refs, batch, kv, rope, ops)
    last = ops.rms_norm(x[batch.accept_index.long()], mtp.norm, cfg.eps)
    return last @ w.lm_head.T, kv


def rope_tables(
    cfg: DeepseekV32Config, batch: StepBatch, dtype: torch.dtype
) -> tuple[torch.Tensor, torch.Tensor]:
    return yarn_rope_tables(
        batch.positions,
        cfg.rope,
        cfg.rope_theta,
        cfg.rope_factor,
        cfg.rope_beta_fast,
        cfg.rope_beta_slow,
        cfg.rope_original_max,
        True,
        dtype,
        attention_factor=cfg.rope_attention_factor,
    )


def decoder_layer(  # noqa: PLR0913, PLR0917  -- (x, layer, cfg, refs, batch, kv, rope, ops)
    x: torch.Tensor,
    layer: Layer,
    cfg: DeepseekV32Config,
    refs: list[tuple[int, int]],
    batch: StepBatch,
    kv: list[KV],
    rope: tuple[torch.Tensor, torch.Tensor],
    ops,
) -> tuple[torch.Tensor, list[KV]]:
    """One pre-norm block. refs = this layer's [(group, member)] from derive_groups: the latent
    member first, the indexer K member second, both on the same group's table. -> (x, kv)."""
    (g, _), (g_idx, _) = refs
    assert g == g_idx, "latent and indexer K of one layer share a table"
    h = ops.rms_norm(x, layer.ln_1, cfg.eps)
    a, kv_g = attention(h, layer.attn, cfg, refs, batch, kv[g], rope, ops)
    kv = [kv_g if j == g else kv_j for j, kv_j in enumerate(kv)]
    x = x + a
    h = ops.rms_norm(x, layer.ln_2, cfg.eps)
    if isinstance(layer.mlp, Moe):
        return x + moe(h, layer.mlp, cfg, ops), kv
    return x + dense(h, layer.mlp, ops), kv


def attention(  # noqa: PLR0913, PLR0917  -- (h, a, cfg, refs, batch, kv, rope, ops)
    h: torch.Tensor,
    a: Attention,
    cfg: DeepseekV32Config,
    refs: list[tuple[int, int]],
    batch: StepBatch,
    kv: KV,
    rope: tuple[torch.Tensor, torch.Tensor],
    ops,
) -> tuple[torch.Tensor, KV]:
    """MLA (HF DeepseekV32Attention) with the DSA indexer choosing the keys. The per-token latent
    row is cat(kv_a_norm(latent), rotated k_rope); the indexer K row is the rotated, layer-normed
    wk(h). Both are written to their member of the layer's group `kv` before scoring.
    -> (out, kv)."""
    (g, m_lat), (_, m_idx) = refs
    cos, sin = rope
    t = h.shape[0]

    q_resid = ops.rms_norm(h @ a.q_a.T, a.q_a_norm, cfg.eps)  # [T, q_lora]
    q = (q_resid @ a.q_b.T).view(t, cfg.n_heads, cfg.qk_dim)
    q_rope = ops.rope_interleaved(q[..., cfg.nope :], cos, sin)
    q = torch.cat([q[..., : cfg.nope], q_rope], dim=-1)

    ckv = h @ a.kv_a.T  # [T, kv_lora + rope]
    latent = ops.rms_norm(ckv[:, : cfg.kv_lora], a.kv_a_norm, cfg.eps)
    k_rope = ops.rope_interleaved(ckv[:, None, cfg.kv_lora :], cos, sin)[:, 0]
    kv = ops.write_cache(kv, m_lat, torch.cat([latent, k_rope], dim=-1), batch.slot_mapping[g])

    iq = (q_resid @ a.idx_wq_b.T).view(t, cfg.index_heads, cfg.index_dim)
    iq = torch.cat([ops.rope(iq[..., : cfg.rope], cos, sin), iq[..., cfg.rope :]], dim=-1)
    ik = ops.layer_norm(h @ a.idx_wk.T, a.idx_k_norm, a.idx_k_norm_b, 1e-6)[:, None]
    ik = torch.cat([ops.rope(ik[..., : cfg.rope], cos, sin), ik[..., cfg.rope :]], dim=-1)[:, 0]
    iw = (h @ a.idx_weights.T).float() * cfg.index_heads**-0.5
    kv = ops.write_cache(kv, m_idx, ik, batch.slot_mapping[g])
    topk = ops.dsa_topk(iq, iw, batch, kv, m_idx, g, cfg.index_topk)

    out = ops.mla_attention(
        q,
        batch,
        kv,
        m_lat,
        a.kv_b,
        (cfg.kv_lora, cfg.nope, cfg.rope, cfg.v_dim),
        cfg.softmax_scale,
        group=g,
        topk=topk,
    )
    return out @ a.o.T, kv


def dense(h: torch.Tensor, m: Dense, ops) -> torch.Tensor:
    return ops.silu_mul(h @ m.gate.T, h @ m.up.T) @ m.down.T


def moe(h: torch.Tensor, m: Moe, cfg: DeepseekV32Config, ops) -> torch.Tensor:
    """Routed experts (HF DeepseekV32TopkRouter + Experts) plus the shared expert MLP."""
    t = h.shape[0]
    weights, expert_idx = route(h, m, cfg)  # [T, k] each
    expert = expert_idx.reshape(-1)
    order = torch.argsort(expert, stable=True)
    counts = torch.bincount(expert, minlength=cfg.n_experts).tolist()  # host sync (reference)
    token = order // cfg.top_k
    x = h[token]
    gate_up = ops.grouped_mm(x, m.gate_up, None, counts)
    act = ops.silu_mul(gate_up[:, : cfg.moe_intermediate], gate_up[:, cfg.moe_intermediate :])
    y = ops.grouped_mm(act, m.down, None, counts)
    y = y * weights.reshape(-1)[order, None].to(y.dtype)
    out = torch.zeros(t, cfg.hidden, dtype=h.dtype, device=h.device)
    out.index_add_(0, token, y.to(h.dtype))
    return out + dense(h, m.shared, ops)


def route(h: torch.Tensor, m: Moe, cfg: DeepseekV32Config) -> tuple[torch.Tensor, torch.Tensor]:
    """noaux_tc: sigmoid scores + correction bias pick top `topk_group` groups (by the sum of each
    group's top-2), then top-k experts inside them; weights are the raw sigmoid scores of the
    chosen experts, normalized, times routed_scale. fp32 like HF."""
    scores = torch.sigmoid(h.float() @ m.router.float().T)  # [T, E]
    for_choice = scores + m.router_bias
    per_group = cfg.n_experts // cfg.n_group
    group_scores = for_choice.view(-1, cfg.n_group, per_group).topk(2, dim=-1)[0].sum(-1)
    group_idx = group_scores.topk(cfg.topk_group, dim=-1, sorted=False)[1]
    group_mask = torch.zeros_like(group_scores).scatter_(1, group_idx, 1)
    score_mask = (
        group_mask[:, :, None].expand(-1, cfg.n_group, per_group).reshape(-1, cfg.n_experts)
    )
    for_choice = for_choice.masked_fill(~score_mask.bool(), float("-inf"))
    idx = for_choice.topk(cfg.top_k, dim=-1, sorted=False)[1]
    weights = scores.gather(1, idx)
    if cfg.norm_topk:
        weights = weights / (weights.sum(-1, keepdim=True) + 1e-20)
    return weights * cfg.routed_scale, idx


# ---- loading ---------------------------------------------------------------------------------


def load(
    model_id: str = MODEL_ID,
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float32,
) -> tuple[DeepseekV32, DeepseekV32Config]:
    cfg_path, st_paths = resolve_hf(model_id)
    with open(cfg_path) as f:
        cfg = config_from_hf(json.load(f))
    return from_state_dict(load_safetensors(st_paths), cfg, device, dtype), cfg


def config_from_hf(c: Mapping[str, Any]) -> DeepseekV32Config:
    rope = c.get("rope_scaling") or c.get("rope_parameters") or {}
    n_layers = c["num_hidden_layers"]
    n_dense = min(c.get("first_k_dense_replace", 0), n_layers)
    mlp_types = c.get("mlp_layer_types") or ["dense"] * n_dense + ["sparse"] * (n_layers - n_dense)
    return DeepseekV32Config(
        n_layers=n_layers,
        n_mtp=c.get("num_nextn_predict_layers", 0),
        n_heads=c["num_attention_heads"],
        hidden=c["hidden_size"],
        q_lora=c["q_lora_rank"],
        kv_lora=c["kv_lora_rank"],
        nope=c["qk_nope_head_dim"],
        rope=c["qk_rope_head_dim"],
        v_dim=c["v_head_dim"],
        index_heads=c["index_n_heads"],
        index_dim=c["index_head_dim"],
        index_topk=c["index_topk"],
        intermediate=c["intermediate_size"],
        moe_intermediate=c["moe_intermediate_size"],
        n_experts=c["n_routed_experts"],
        top_k=c["num_experts_per_tok"],
        n_group=c["n_group"],
        topk_group=c["topk_group"],
        n_shared=c["n_shared_experts"],
        routed_scale=c["routed_scaling_factor"],
        norm_topk=c["norm_topk_prob"],
        mlp_types=tuple(mlp_types[:n_layers]),
        vocab=c["vocab_size"],
        eps=c["rms_norm_eps"],
        rope_theta=c.get("rope_theta") or rope["rope_theta"],
        rope_factor=rope.get("factor", 1.0),
        rope_beta_fast=rope.get("beta_fast", 32.0),
        rope_beta_slow=rope.get("beta_slow", 1.0),
        rope_original_max=rope.get(
            "original_max_position_embeddings", c["max_position_embeddings"]
        ),
        rope_mscale=rope.get("mscale", 0.0),
        rope_mscale_all_dim=rope.get("mscale_all_dim", 0.0),
        eos_token=c["eos_token_id"],
    )


def from_state_dict(
    sd: Mapping[str, torch.Tensor],
    cfg: DeepseekV32Config,
    device: torch.device | str,
    dtype: torch.dtype,
) -> DeepseekV32:
    """HF DeepseekV32ForCausalLM names -> pytree. Expert weights come as HF's [E, 2I, H] /
    [E, H, I] and are stored transposed for grouped_mm. MTP layers read the checkpoint's
    `model.layers.{n_layers + j}` names (enorm/hnorm/eh_proj/shared_head.norm + a decoder layer);
    an HF-instantiated model has none, so cfg.n_mtp must be 0 for it."""

    def t(name: str, dt: torch.dtype = dtype) -> torch.Tensor:
        return sd[name].to(device=device, dtype=dt)

    def attention(p: str) -> Attention:
        a, i = f"{p}.self_attn", f"{p}.self_attn.indexer"
        return Attention(
            q_a=t(f"{a}.q_a_proj.weight"),
            q_a_norm=t(f"{a}.q_a_layernorm.weight"),
            q_b=t(f"{a}.q_b_proj.weight"),
            kv_a=t(f"{a}.kv_a_proj_with_mqa.weight"),
            kv_a_norm=t(f"{a}.kv_a_layernorm.weight"),
            kv_b=t(f"{a}.kv_b_proj.weight"),
            o=t(f"{a}.o_proj.weight"),
            idx_wq_b=t(f"{i}.wq_b.weight"),
            idx_wk=t(f"{i}.wk.weight"),
            idx_k_norm=t(f"{i}.k_norm.weight"),
            idx_k_norm_b=t(f"{i}.k_norm.bias"),
            idx_weights=t(f"{i}.weights_proj.weight"),
        )

    def dense_(p: str) -> Dense:
        return Dense(
            t(f"{p}.gate_proj.weight"), t(f"{p}.up_proj.weight"), t(f"{p}.down_proj.weight")
        )

    def mlp(p: str, kind: str) -> Dense | Moe:
        if kind == "dense":
            return dense_(f"{p}.mlp")
        e = f"{p}.mlp.experts"
        return Moe(
            router=t(f"{p}.mlp.gate.weight"),
            router_bias=t(f"{p}.mlp.gate.e_score_correction_bias", torch.float32),
            gate_up=t(f"{e}.gate_up_proj").transpose(1, 2).contiguous(),
            down=t(f"{e}.down_proj").transpose(1, 2).contiguous(),
            shared=dense_(f"{p}.mlp.shared_experts"),
        )

    def layer(i: int, kind: str) -> Layer:
        p = f"model.layers.{i}"
        return Layer(
            attn_spec=attn_spec(cfg),
            ln_1=t(f"{p}.input_layernorm.weight"),
            attn=attention(p),
            ln_2=t(f"{p}.post_attention_layernorm.weight"),
            mlp=mlp(p, kind),
        )

    def mtp(j: int) -> Mtp:
        p = f"model.layers.{cfg.n_layers + j}"
        return Mtp(
            enorm=t(f"{p}.enorm.weight"),
            hnorm=t(f"{p}.hnorm.weight"),
            eh_proj=t(f"{p}.eh_proj.weight"),
            layer=layer(cfg.n_layers + j, "sparse"),
            norm=t(f"{p}.shared_head.norm.weight"),
        )

    w = DeepseekV32(
        embed=t("model.embed_tokens.weight"),
        layers=tuple(layer(i, kind) for i, kind in enumerate(cfg.mlp_types)),
        mtp=tuple(mtp(j) for j in range(cfg.n_mtp)),
        ln_f=t("model.norm.weight"),
        lm_head=t("lm_head.weight"),
    )
    assert w.embed.shape == (cfg.vocab, cfg.hidden), w.embed.shape
    assert w.layers[0].attn.kv_a.shape == (cfg.kv_lora + cfg.rope, cfg.hidden)
    assert w.layers[0].attn.idx_wk.shape == (cfg.index_dim, cfg.hidden)
    for layer_ in w.layers:
        if isinstance(layer_.mlp, Moe):
            assert layer_.mlp.gate_up.shape == (cfg.n_experts, cfg.hidden, 2 * cfg.moe_intermediate)
    return w
