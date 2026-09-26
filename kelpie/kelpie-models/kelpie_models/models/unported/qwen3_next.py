"""Qwen3-Next forward over the StepBatch contract: Gated DeltaNet linear-attention layers 3:1
with gated full attention (partial RoPE, QK-norm), top-k MoE with a gated shared expert, and an
MTP head. Weights are a typed pytree.

Cache groups (docs/decisions.md): the full-attention layers (and the MTP layer) are members
of one per_token group; the GDN layers declare `Recurrent` and get NO core group -- their
temporal state and conv tail live in a request-slot ring (kelpie_models.state.StateRing) that
the forward receives as `state` and the ops index by the request slots; the ops return the
blobs they wrote and `put_blob` threads them (one shape of code with the traced path). The
scheduler never learns the ring exists.
"""

from __future__ import annotations

# ruff: noqa: E402 -- the raise is deliberately ABOVE the imports: this module's imports are
# the deleted pre-Plan path, so importing it must fail with a reason, not an ImportError.
raise NotImplementedError(
    "unported: needs batch.StepBatch, kv.KV, state.StateRing, facts; these were the pre-Plan path and were deleted "
    "2026-09-10. Port this model to forward(weights, config, tokens, requests, kv, taps) "
    "the way models/torch/qwen3.py is written; see docs/ladder.md for the order."
)

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

import torch
import torch.nn.functional as F

from kelpie_models.batch import StepBatch, embed_tokens
from kelpie_models.kernels.functional import rope_tables
from kelpie_models.sdk.groups import AttnSpec, FullAttn, Recurrent, derive_groups
from kelpie_models.sdk.hf import load_safetensors, resolve_hf
from kelpie_models.sdk.kv import KV
# TODO(2026-09-10): per_seq group view. The recurrent state / compressor rings are per_seq
# cache groups the core owns now (docs/brief-slab-pool-recurrent.md step 4); this unported model
# still calls the deleted kelpie_models.state ring. Porting it means reading the group's page
# view out of the plan instead. Until then these raise rather than silently doing nothing.
StateRing = Any


def _no_state_ring(fn: str) -> NoReturn:
    raise NotImplementedError(
        f"{fn}: kelpie_models.state is gone -- recurrent/compressor state is a per_seq cache "
        "group now (TODO(2026-09-10): per_seq group view)"
    )


def put_blob(*args: Any, **kwargs: Any) -> NoReturn:
    del args, kwargs
    _no_state_ring("put_blob")


MODEL_ID = "Qwen/Qwen3-Next-80B-A3B-Instruct"
CHECKPOINT = MODEL_ID  # kelpie_models.facts: the launch layer reads these, not a name table
CHAT_FAMILY = "default"
DTYPE = "bfloat16"
ADAPTER = None
TEMPORAL, CONV = "temporal", "conv"


@dataclass(frozen=True)
class Qwen3NextConfig:
    n_layers: int
    layer_types: tuple[str, ...]  # "linear_attention" | "full_attention"
    n_heads: int
    n_kv_heads: int
    head_dim: int
    rotary_dim: int  # head_dim * partial_rotary_factor
    hidden: int
    vocab: int
    eps: float
    rope_theta: float
    gdn_v_heads: int
    gdn_k_heads: int
    gdn_k_dim: int
    gdn_v_dim: int
    conv_kernel: int
    n_experts: int
    top_k: int
    norm_topk: bool
    expert_inter: int
    shared_inter: int
    tie_embeddings: bool
    eos_token: int
    n_mtp: int  # MTP layers loaded (0 when the checkpoint has none)

    @property
    def conv_dim(self) -> int:
        return 2 * self.gdn_k_heads * self.gdn_k_dim + self.gdn_v_heads * self.gdn_v_dim


@dataclass(frozen=True)
class Gdn:
    """Qwen3NextGatedDeltaNet weights."""

    in_qkvz: torch.Tensor  # [2*key_dim + 2*value_dim, hidden]
    in_ba: torch.Tensor  # [2*v_heads, hidden]
    conv_w: torch.Tensor  # [conv_dim, kernel]
    conv_b: torch.Tensor | None
    dt_bias: torch.Tensor  # [v_heads]
    a_log: torch.Tensor  # [v_heads]
    norm: torch.Tensor  # gated rms weight [v_dim]
    out: torch.Tensor  # [hidden, value_dim]


@dataclass(frozen=True)
class Attn:
    """Qwen3NextAttention weights; q is [2 * heads * head_dim, hidden] (query | output gate)."""

    q: torch.Tensor
    k: torch.Tensor
    v: torch.Tensor
    o: torch.Tensor
    q_norm: torch.Tensor  # [head_dim], stored as 1 + weight (HF Qwen3NextRMSNorm)
    k_norm: torch.Tensor


@dataclass(frozen=True)
class Moe:
    router: torch.Tensor  # [n_experts, hidden]
    gate_up: torch.Tensor  # [n_experts, hidden, 2 * expert_inter] (gate | up)
    gate_up_b: torch.Tensor  # zeros [n_experts, 2 * expert_inter]
    down: torch.Tensor  # [n_experts, expert_inter, hidden]
    down_b: torch.Tensor  # zeros [n_experts, hidden]
    shared_gate: torch.Tensor  # [shared_inter, hidden]
    shared_up: torch.Tensor
    shared_down: torch.Tensor  # [hidden, shared_inter]
    shared_gate_w: torch.Tensor  # [1, hidden]


@dataclass(frozen=True)
class Qwen3NextLayer:
    attn: AttnSpec
    ln_1: torch.Tensor  # 1 + weight
    mixer: Gdn | Attn
    ln_2: torch.Tensor
    mlp: Moe


@dataclass(frozen=True)
class Mtp:
    """The multi-token-prediction head: fc over [norm(embed(next)) | norm(hidden)], one
    full-attention decoder layer, final norm, then the trunk's lm_head."""

    fc: torch.Tensor  # [hidden, 2 * hidden]
    norm_embed: torch.Tensor
    norm_hidden: torch.Tensor
    layer: Qwen3NextLayer
    ln_f: torch.Tensor


@dataclass(frozen=True)
class Qwen3Next:
    embed: torch.Tensor  # [vocab, hidden]
    layers: tuple[Qwen3NextLayer, ...]
    ln_f: torch.Tensor
    lm_head: torch.Tensor  # [vocab, hidden]
    mtp: Mtp | None


def attn_specs(cfg: Qwen3NextConfig) -> list[AttnSpec]:
    """Trunk layers in order, then the MTP layer(s), which join the full-attention group."""
    return [attn_spec(cfg, t) for t in cfg.layer_types] + [full_spec(cfg)] * cfg.n_mtp


def attn_spec(cfg: Qwen3NextConfig, layer_type: str) -> AttnSpec:
    if layer_type == "linear_attention":
        return Recurrent(
            state=(
                (TEMPORAL, (cfg.gdn_v_heads, cfg.gdn_k_dim, cfg.gdn_v_dim), 4),
                (CONV, (cfg.conv_dim, cfg.conv_kernel - 1), 2),
            )
        )
    assert layer_type == "full_attention", layer_type
    return full_spec(cfg)


def full_spec(cfg: Qwen3NextConfig) -> FullAttn:
    return FullAttn(cfg.n_kv_heads, cfg.head_dim)


def forward(  # noqa: PLR0913, PLR0917
    w: Qwen3Next,
    cfg: Qwen3NextConfig,
    batch: StepBatch,
    kv: list[KV],
    state: StateRing,
    ops,
) -> tuple[torch.Tensor, list[KV], StateRing]:
    """-> (logits [padded_num_reqs, 1 + K, vocab] at each request's accept_index rows, kv,
    state). kv: one group (exactly one for this model); state: the recurrent ring, indexed by
    batch.req_ids."""
    logits, _, kv, state = forward_hidden(w, cfg, batch, kv, state, ops)
    return logits, kv, state


def forward_hidden(  # noqa: PLR0913, PLR0917
    w: Qwen3Next,
    cfg: Qwen3NextConfig,
    batch: StepBatch,
    kv: list[KV],
    state: StateRing,
    ops,
) -> tuple[torch.Tensor, torch.Tensor, list[KV], StateRing]:
    """(logits at the accept_index rows, trunk hidden [padded_num_tokens, hidden] before the
    final norm -- what the MTP head reads, kv, state)."""
    _, layer_caches = derive_groups(attn_specs(cfg))
    assert len(kv) == 1, f"one per_token group; the GDN state is not a group ({len(kv)})"
    assert state is not None, "qwen3_next keeps its GDN state in the request-slot ring"
    x = embed_tokens(w.embed, batch)
    rope = rope_tables(batch.positions, cfg.rotary_dim, cfg.rope_theta, x.dtype)
    kv0 = kv[0]
    for i, layer in enumerate(w.layers):
        h = rms_norm(x, layer.ln_1, cfg.eps, ops)
        if isinstance(layer.mixer, Gdn):
            a, state = gated_delta_net(h, layer.mixer, cfg, i, batch, state, ops)
        else:
            ((_, offset),) = layer_caches[i]
            a, kv0 = attention(h, layer.mixer, cfg, offset, batch, kv0, rope, ops)
        x = x + a
        h = rms_norm(x, layer.ln_2, cfg.eps, ops)
        x = x + moe(h, layer.mlp, cfg, ops)
    last = rms_norm(x[batch.accept_index.long()], w.ln_f, cfg.eps, ops)
    return last @ w.lm_head.T, x, [kv0], state


def forward_mtp(  # noqa: PLR0913, PLR0917
    w: Qwen3Next,
    cfg: Qwen3NextConfig,
    batch: StepBatch,
    kv: list[KV],
    state: StateRing,
    ops,
    hidden: torch.Tensor,
    next_ids: torch.Tensor,
) -> tuple[torch.Tensor, list[KV]]:
    """MTP head: for every row t of the batch, predict token t+2 from the trunk hidden at t and
    the embedding of token t+1 (`next_ids[t]`, one per padded row). -> (logits
    [padded_num_tokens, vocab], kv). The MTP layer's KV is member n_layers of the
    full-attention group (attn_specs); the ring is untouched (no GDN layer here)."""
    del state
    assert w.mtp is not None and cfg.n_mtp == 1, "checkpoint has no MTP head"
    assert next_ids.shape == (hidden.shape[0],), (next_ids.shape, hidden.shape)
    _, layer_caches = derive_groups(attn_specs(cfg))
    ((_, offset),) = layer_caches[cfg.n_layers]
    mtp, layer = w.mtp, w.mtp.layer
    assert isinstance(layer.mixer, Attn)
    e = rms_norm(w.embed[next_ids.long()], mtp.norm_embed, cfg.eps, ops)
    x = torch.cat([e, rms_norm(hidden, mtp.norm_hidden, cfg.eps, ops)], dim=-1) @ mtp.fc.T
    rope = rope_tables(batch.positions, cfg.rotary_dim, cfg.rope_theta, x.dtype)
    h = rms_norm(x, layer.ln_1, cfg.eps, ops)
    a, kv0 = attention(h, layer.mixer, cfg, offset, batch, kv[0], rope, ops)
    x = x + a
    h = rms_norm(x, layer.ln_2, cfg.eps, ops)
    x = x + moe(h, layer.mlp, cfg, ops)
    return rms_norm(x, mtp.ln_f, cfg.eps, ops) @ w.lm_head.T, [kv0]


def rms_norm(x: torch.Tensor, weight: torch.Tensor, eps: float, ops) -> torch.Tensor:
    """HF Qwen3NextRMSNorm: fp32 normalize and scale (weight already holds 1 + w), cast once."""
    return ops.rms_norm(x.float(), weight, eps).to(x.dtype)


def gated_delta_net(  # noqa: PLR0913, PLR0917
    h: torch.Tensor,
    m: Gdn,
    cfg: Qwen3NextConfig,
    i: int,
    batch: StepBatch,
    state: StateRing,
    ops,
) -> tuple[torch.Tensor, StateRing]:
    """One GDN layer: projections -> causal conv (tail in the ring) -> gated delta rule (S in
    the ring) -> gated RMSNorm -> out. Layer i's ring blobs are state.blob(i, name); each op
    returns the blob it wrote and `put_blob` threads it back. -> (out, state)."""
    t = h.shape[0]
    hk, hv, dk, dv = cfg.gdn_k_heads, cfg.gdn_v_heads, cfg.gdn_k_dim, cfg.gdn_v_dim
    ratio = hv // hk
    qkvz = (h @ m.in_qkvz.T).view(t, hk, 2 * dk + 2 * ratio * dv)
    q, k, v, z = torch.split(qkvz, [dk, dk, ratio * dv, ratio * dv], dim=-1)
    b, a = torch.split((h @ m.in_ba.T).view(t, hk, 2 * ratio), [ratio, ratio], dim=-1)
    z, b, a = z.reshape(t, hv, dv), b.reshape(t, hv), a.reshape(t, hv)

    mixed = torch.cat([q.reshape(t, -1), k.reshape(t, -1), v.reshape(t, -1)], dim=-1)
    mixed, conv = ops.causal_conv1d(mixed, m.conv_w, m.conv_b, batch, state.blob(i, CONV))
    state = put_blob(state, i, CONV, conv)
    q, k, v = torch.split(mixed, [hk * dk, hk * dk, hv * dv], dim=-1)
    q = q.view(t, hk, dk).repeat_interleave(ratio, dim=1)
    k = k.view(t, hk, dk).repeat_interleave(ratio, dim=1)
    v = v.view(t, hv, dv)

    beta = b.sigmoid()
    g = -m.a_log.float().exp() * F.softplus(a.float() + m.dt_bias)
    o, temporal = ops.gated_delta_net(q, k, v, g, beta, batch, state.blob(i, TEMPORAL))
    state = put_blob(state, i, TEMPORAL, temporal)
    o = ops.rms_norm(o.view(t, hv, dv).float(), m.norm, cfg.eps) * F.silu(z.float())
    return o.to(h.dtype).reshape(t, hv * dv) @ m.out.T, state


def attention(  # noqa: PLR0913, PLR0917
    h: torch.Tensor,
    m: Attn,
    cfg: Qwen3NextConfig,
    offset: int,
    batch: StepBatch,
    kv: KV,
    rope: tuple[torch.Tensor, torch.Tensor],
    ops,
) -> tuple[torch.Tensor, KV]:
    """Gated GQA: q_proj yields (query | sigmoid gate) per head; QK-norm; RoPE on the first
    rotary_dim dims only; paged attention through member `offset` of the full-attention group.
    -> (out, kv)."""
    cos, sin = rope
    t = h.shape[0]
    q, gate = (h @ m.q.T).view(t, cfg.n_heads, 2 * cfg.head_dim).chunk(2, dim=-1)
    k = (h @ m.k.T).view(t, cfg.n_kv_heads, cfg.head_dim)
    v = (h @ m.v.T).view(t, cfg.n_kv_heads, cfg.head_dim)
    q = rms_norm(q, m.q_norm, cfg.eps, ops)
    k = rms_norm(k, m.k_norm, cfg.eps, ops)
    q = partial_rope(q, cos, sin, cfg.rotary_dim, ops)
    k = partial_rope(k, cos, sin, cfg.rotary_dim, ops)
    o, kv = ops.attention(q, k, v, batch, kv, offset)
    o = o * torch.sigmoid(gate.reshape(t, -1))
    return o @ m.o.T, kv


def partial_rope(
    x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor, rotary_dim: int, ops
) -> torch.Tensor:
    rot = ops.rope(x[..., :rotary_dim], cos, sin)
    return torch.cat([rot, x[..., rotary_dim:]], dim=-1)


def moe(h: torch.Tensor, m: Moe, cfg: Qwen3NextConfig, ops) -> torch.Tensor:
    """Softmax router over all experts (fp32), top-k renormalized, experts as two grouped
    matmuls over tokens sorted by expert, plus a sigmoid-gated shared expert (HF
    Qwen3NextSparseMoeBlock)."""
    t = h.shape[0]
    probs = torch.softmax(h @ m.router.T, dim=-1, dtype=torch.float32)
    top_v, top_i = torch.topk(probs, cfg.top_k, dim=-1)
    if cfg.norm_topk:
        top_v = top_v / top_v.sum(dim=-1, keepdim=True)
    weights = top_v.to(h.dtype)
    expert = top_i.reshape(-1)
    order = torch.argsort(expert, stable=True)
    counts = torch.bincount(expert, minlength=cfg.n_experts).tolist()  # host sync (reference)
    token = order // cfg.top_k
    x = h[token]
    gate_up = ops.grouped_mm(x, m.gate_up, m.gate_up_b, counts)
    act = ops.silu_mul(gate_up[..., : cfg.expert_inter], gate_up[..., cfg.expert_inter :])
    y = ops.grouped_mm(act, m.down, m.down_b, counts) * weights.reshape(-1)[order, None]
    out = torch.zeros(t, cfg.hidden, dtype=h.dtype, device=h.device)
    out.index_add_(0, token, y.to(h.dtype))
    shared = ops.silu_mul(h @ m.shared_gate.T, h @ m.shared_up.T) @ m.shared_down.T
    return out + torch.sigmoid(h @ m.shared_gate_w.T) * shared


# ---- loading ---------------------------------------------------------------------------------


def load(
    model_id: str = MODEL_ID,
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.bfloat16,
) -> tuple[Qwen3Next, Qwen3NextConfig]:
    cfg_path, st_paths = resolve_hf(model_id)
    sd = load_safetensors(st_paths)
    with open(cfg_path) as f:
        cfg = config_from_hf(json.load(f), n_mtp=int("mtp.fc.weight" in sd))
    return from_state_dict(sd, cfg, device, dtype), cfg


def config_from_hf(c: Mapping[str, Any], n_mtp: int = 0) -> Qwen3NextConfig:
    """The hub config.json (or a rolled one). n_mtp: MTP layers present in the weights (the
    config carries no field for it)."""
    n = c["num_hidden_layers"]
    if c.get("layer_types"):
        layer_types = tuple(c["layer_types"][:n])
    else:
        interval = c.get("full_attention_interval", 4)
        layer_types = tuple(
            "linear_attention" if (i + 1) % interval else "full_attention" for i in range(n)
        )
    assert not c.get("mlp_only_layers") and c.get("decoder_sparse_step", 1) == 1, (
        "dense MLP layers: TODO"
    )
    rope = c.get("rope_parameters") or {}
    return Qwen3NextConfig(
        n_layers=n,
        layer_types=layer_types,
        n_heads=c["num_attention_heads"],
        n_kv_heads=c["num_key_value_heads"],
        head_dim=c["head_dim"],
        rotary_dim=int(c["head_dim"] * c.get("partial_rotary_factor", 0.25)),
        hidden=c["hidden_size"],
        vocab=c["vocab_size"],
        eps=c["rms_norm_eps"],
        rope_theta=c.get("rope_theta") or rope["rope_theta"],
        gdn_v_heads=c["linear_num_value_heads"],
        gdn_k_heads=c["linear_num_key_heads"],
        gdn_k_dim=c["linear_key_head_dim"],
        gdn_v_dim=c["linear_value_head_dim"],
        conv_kernel=c["linear_conv_kernel_dim"],
        n_experts=c["num_experts"],
        top_k=c["num_experts_per_tok"],
        norm_topk=c.get("norm_topk_prob", True),
        expert_inter=c["moe_intermediate_size"],
        shared_inter=c["shared_expert_intermediate_size"],
        tie_embeddings=c.get("tie_word_embeddings", False),
        eos_token=c["eos_token_id"],
        n_mtp=n_mtp,
    )


def from_state_dict(
    sd: Mapping[str, torch.Tensor],
    cfg: Qwen3NextConfig,
    device: torch.device | str,
    dtype: torch.dtype,
) -> Qwen3Next:
    """HF Qwen3NextForCausalLM (transformers 5, fused experts) parameter names -> pytree.
    RMSNorm weights are stored as 1 + w. The MTP head is `mtp.*` (the hub layout)."""

    def t(name: str, dt: torch.dtype = dtype) -> torch.Tensor:
        return sd[name].to(device=device, dtype=dt)

    def norm1(name: str) -> torch.Tensor:
        return 1.0 + t(name, torch.float32)

    def gdn(p: str) -> Gdn:
        conv_b = t(f"{p}.conv1d.bias") if f"{p}.conv1d.bias" in sd else None
        return Gdn(
            in_qkvz=t(f"{p}.in_proj_qkvz.weight"),
            in_ba=t(f"{p}.in_proj_ba.weight"),
            conv_w=t(f"{p}.conv1d.weight").squeeze(1),
            conv_b=conv_b,
            dt_bias=t(f"{p}.dt_bias", torch.float32),
            a_log=t(f"{p}.A_log", torch.float32),
            norm=t(f"{p}.norm.weight", torch.float32),
            out=t(f"{p}.out_proj.weight"),
        )

    def attn(p: str) -> Attn:
        return Attn(
            q=t(f"{p}.q_proj.weight"),
            k=t(f"{p}.k_proj.weight"),
            v=t(f"{p}.v_proj.weight"),
            o=t(f"{p}.o_proj.weight"),
            q_norm=norm1(f"{p}.q_norm.weight"),
            k_norm=norm1(f"{p}.k_norm.weight"),
        )

    def moe_w(p: str) -> Moe:
        gate_up = t(f"{p}.experts.gate_up_proj").transpose(1, 2).contiguous()
        down = t(f"{p}.experts.down_proj").transpose(1, 2).contiguous()
        return Moe(
            router=t(f"{p}.gate.weight"),
            gate_up=gate_up,
            gate_up_b=torch.zeros(gate_up.shape[0], gate_up.shape[2], dtype=dtype, device=device),
            down=down,
            down_b=torch.zeros(down.shape[0], down.shape[2], dtype=dtype, device=device),
            shared_gate=t(f"{p}.shared_expert.gate_proj.weight"),
            shared_up=t(f"{p}.shared_expert.up_proj.weight"),
            shared_down=t(f"{p}.shared_expert.down_proj.weight"),
            shared_gate_w=t(f"{p}.shared_expert_gate.weight"),
        )

    def layer(p: str, layer_type: str) -> Qwen3NextLayer:
        linear = layer_type == "linear_attention"
        return Qwen3NextLayer(
            attn=attn_spec(cfg, layer_type),
            ln_1=norm1(f"{p}.input_layernorm.weight"),
            mixer=gdn(f"{p}.linear_attn") if linear else attn(f"{p}.self_attn"),
            ln_2=norm1(f"{p}.post_attention_layernorm.weight"),
            mlp=moe_w(f"{p}.mlp"),
        )

    mtp = None
    if cfg.n_mtp:
        assert cfg.n_mtp == 1, "one MTP layer (Qwen3-Next ships one)"
        mtp = Mtp(
            fc=t("mtp.fc.weight"),
            norm_embed=norm1("mtp.pre_fc_norm_embedding.weight"),
            norm_hidden=norm1("mtp.pre_fc_norm_hidden.weight"),
            layer=layer("mtp.layers.0", "full_attention"),
            ln_f=norm1("mtp.norm.weight"),
        )
    embed = t("model.embed_tokens.weight")
    if "lm_head.weight" in sd:
        lm_head = t("lm_head.weight")
    else:
        assert cfg.tie_embeddings, "no lm_head and embeddings not tied"
        lm_head = embed
    w = Qwen3Next(
        embed=embed,
        layers=tuple(layer(f"model.layers.{i}", lt) for i, lt in enumerate(cfg.layer_types)),
        ln_f=norm1("model.norm.weight"),
        lm_head=lm_head,
        mtp=mtp,
    )
    assert w.embed.shape == (cfg.vocab, cfg.hidden), w.embed.shape
    assert w.layers[0].mlp.gate_up.shape == (cfg.n_experts, cfg.hidden, 2 * cfg.expert_inter)
    return w
