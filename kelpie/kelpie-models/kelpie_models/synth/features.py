"""Static feature checklist for a HF config: what an implementation of this model must handle.

    cl = features(hf_config, modeling_source=inspect.getsource(modeling_module))
    print(cl.to_markdown())

Config-derived items are facts off config.json plus family facts keyed by model_type (qk-norm,
attention sinks) config.json does not carry. Modeling-derived items are every `config.X` /
`getattr(config, "X")` read that guards a branch in the given source, with this config's value.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from kelpie_models.synth.roll import depth, schedule

QK_NORM_FAMILIES = frozenset(
    {"qwen3", "qwen3_moe", "qwen3_next", "qwen3_5", "qwen3_5_moe", "olmo2", "glm4_moe"}
)
SINK_FAMILIES = frozenset({"gpt_oss", "deepseek_v4"})
MD_CELL = 120
MIN_REPS = 2
MIN_GETATTR_ARGS = 2


@dataclass(frozen=True)
class Item:
    name: str
    value: str
    source: str  # "config" | "family" | "modeling"


@dataclass(frozen=True)
class Checklist:
    model_type: str
    items: tuple[Item, ...]

    def get(self, name: str) -> str | None:
        return next((i.value for i in self.items if i.name == name), None)

    def to_markdown(self) -> str:
        lines = [f"# {self.model_type}", "", "| item | value | source |", "|---|---|---|"]
        lines += [f"| {i.name} | {_md(i.value)} | {i.source} |" for i in self.items]
        return "\n".join(lines) + "\n"


def features(hf_config: Mapping[str, Any], modeling_source: str | None = None) -> Checklist:
    cfg = dict(hf_config.get("text_config") or hf_config)
    items = config_items(cfg)
    if modeling_source is not None:
        items += modeling_items(cfg, modeling_source)
    return Checklist(str(cfg.get("model_type", "?")), tuple(items))


def config_items(cfg: Mapping[str, Any]) -> list[Item]:
    sched = schedule(cfg)
    n = depth(cfg)
    out: list[Item] = []
    add = lambda name, value, source="config": out.append(Item(name, str(value), source))  # noqa: E731

    add("layers", f"{n} trunk + {len(sched.layers) - n} mtp")
    add("layer_kinds", rle(sched.kinds))
    add(
        "transitions",
        ", ".join(
            f"{a}>{b}" for a, b in sorted(set(zip(sched.kinds[:-1], sched.kinds[1:], strict=False)))
        ),
    )
    _attention_items(cfg, sched.kinds, add)
    _moe_items(cfg, add)
    _rope_items(cfg, add)
    _norm_items(cfg, add)
    add("tied_embeddings", bool(cfg.get("tie_word_embeddings", False)))
    add("attention_sinks", cfg.get("model_type") in SINK_FAMILIES, "family")
    for k in ("final_logit_softcapping", "attn_logit_softcapping", "swiglu_limit"):
        if cfg.get(k) is not None:
            add(k, cfg[k])
    add("hidden_act", cfg.get("hidden_act") or cfg.get("activation_function"))
    add("attention_bias", cfg.get("attention_bias", cfg.get("model_type") == "gpt2"))
    _mtp_items(cfg, add)
    _indexer_items(cfg, add)
    _recurrent_items(cfg, add)
    _dsv4_items(cfg, add)
    add("vocab", cfg.get("vocab_size"))
    add("special_tokens", {k: v for k, v in cfg.items() if k.endswith("_token_id")})
    add("dtype", cfg.get("dtype") or cfg.get("torch_dtype"))
    return out


def _attention_items(cfg: Mapping[str, Any], kinds: list[str], add) -> None:
    attn_kinds = sorted({k.split("+")[0] for k in kinds})
    add("attention_kinds", ", ".join(attn_kinds))
    heads = cfg.get("num_attention_heads", cfg.get("n_head"))
    kv = cfg.get("num_key_value_heads", heads)
    add("heads", f"q {heads}, kv {kv}, head_dim {_head_dim(cfg)}")
    if "swa" in attn_kinds:
        n_swa = sum(1 for k in kinds if k.startswith("swa"))
        add("sliding_window", f"{cfg.get('sliding_window')} tokens on {n_swa} layers")
    if any(k in attn_kinds for k in ("mla", "dsa", "dsa.full", "dsa.shared")):
        add(
            "mla",
            f"q_lora {cfg.get('q_lora_rank')}, kv_lora {cfg.get('kv_lora_rank')}, "
            f"nope {cfg.get('qk_nope_head_dim')}, rope {cfg.get('qk_rope_head_dim')}, "
            f"v {cfg.get('v_head_dim')}",
        )
        for k in ("mla_use_nope", "mla_use_output_gate", "rope_interleave"):
            if k in cfg:
                add(k, cfg[k])


def _moe_items(cfg: Mapping[str, Any], add) -> None:
    n = cfg.get("n_routed_experts") or cfg.get("num_experts") or cfg.get("num_local_experts")
    if not n:
        add("moe", False)
        return
    topk = (
        cfg.get("num_experts_per_tok")
        or cfg.get("num_experts_per_token")
        or cfg.get("experts_per_token")
    )
    shared = cfg.get("n_shared_experts", cfg.get("num_shared_experts", 0))
    if cfg.get("shared_expert_intermediate_size"):
        shared = f"1 x {cfg['shared_expert_intermediate_size']}"
    add(
        "moe",
        f"{n} experts, top-{topk}, shared {shared}, "
        f"expert width {cfg.get('moe_intermediate_size')}",
    )
    add(
        "moe_routing",
        f"scoring {cfg.get('scoring_func', cfg.get('moe_router_activation_func', 'softmax'))}, "
        f"method {cfg.get('topk_method', 'topk')}, "
        f"groups {cfg.get('n_group', cfg.get('num_expert_group', 1))}, "
        f"topk_group {cfg.get('topk_group', 1)}, scale {cfg.get('routed_scaling_factor', 1.0)}, "
        f"norm_topk {cfg.get('norm_topk_prob', cfg.get('moe_renormalize'))}",
    )
    for k in (
        "first_k_dense_replace",
        "moe_layer_freq",
        "num_hash_layers",
        "moe_router_dtype",
        "latent_moe_use_norm",
        "routed_expert_hidden_size",
    ):
        if k in cfg:
            add(k, cfg[k])


def _rope_items(cfg: Mapping[str, Any], add) -> None:
    rp = cfg.get("rope_parameters") or cfg.get("rope_scaling") or {}
    if "n_positions" in cfg and not rp and "rope_theta" not in cfg:
        add("positions", f"learned absolute, {cfg['n_positions']}")
        return
    theta = cfg.get("rope_theta", rp.get("rope_theta") if isinstance(rp, dict) else None)
    kind = "default"
    if isinstance(rp, dict) and rp:
        kind = (
            rp.get("rope_type")
            or rp.get("type")
            or (
                "per-branch " + ",".join(rp)
                if all(isinstance(v, dict) for v in rp.values())
                else "default"
            )
        )
    add("rope", f"theta {theta}, type {kind}")
    scaling = (
        {k: v for k, v in rp.items() if k not in ("rope_type", "type", "rope_theta")}
        if isinstance(rp, dict)
        else {}
    )
    if scaling:
        add("rope_scaling", scaling)
    partial = cfg.get("partial_rotary_factor")
    if (
        partial is None
        and cfg.get("qk_rope_head_dim")
        and cfg.get("head_dim")
        and "qk_nope_head_dim" not in cfg
    ):
        partial = cfg["qk_rope_head_dim"] / cfg["head_dim"]
    add("partial_rotary", partial if partial is not None else "no (full head)")
    if "compress_rope_theta" in cfg:
        add("compress_rope_theta", cfg["compress_rope_theta"])


def _norm_items(cfg: Mapping[str, Any], add) -> None:
    if "rms_norm_eps" in cfg:
        add("norm", f"rmsnorm eps {cfg['rms_norm_eps']}")
    elif "layer_norm_epsilon" in cfg:
        add("norm", f"layernorm eps {cfg['layer_norm_epsilon']}")
    if "use_qk_norm" in cfg:
        add("qk_norm", cfg["use_qk_norm"])
    else:
        add("qk_norm", cfg.get("model_type") in QK_NORM_FAMILIES, "family")


def _mtp_items(cfg: Mapping[str, Any], add) -> None:
    n = cfg.get("num_nextn_predict_layers")
    if isinstance(cfg.get("mtp"), Mapping):
        n = cfg["mtp"].get("num_layers", n)
    add("mtp_layers", n or 0)


def _indexer_items(cfg: Mapping[str, Any], add) -> None:
    if not cfg.get("index_topk"):
        return
    it = cfg.get("indexer_types")
    shared = f", indexer_types full {it.count('full')} / shared {it.count('shared')}" if it else ""
    add(
        "indexer",
        f"topk {cfg['index_topk']}, heads {cfg.get('index_n_heads')}, "
        f"dim {cfg.get('index_head_dim')}{shared}",
    )
    for k in (
        "index_share_for_mtp_iteration",
        "indexer_rope_interleave",
        "index_topk_freq",
        "index_skip_topk_offset",
    ):
        if k in cfg:
            add(k, cfg[k])


def _recurrent_items(cfg: Mapping[str, Any], add) -> None:
    if "linear_num_value_heads" in cfg:  # gated delta net
        hk, hv = cfg["linear_num_key_heads"], cfg["linear_num_value_heads"]
        dk, dv = cfg["linear_key_head_dim"], cfg["linear_value_head_dim"]
        k = cfg.get("linear_conv_kernel_dim", 4)
        add(
            "recurrent_state",
            f"gdn temporal ({hv}, {dk}, {dv}) f32; conv ({k - 1}, {2 * hk * dk + hv * dv})",
        )
    lac = cfg.get("linear_attn_config")
    if isinstance(lac, Mapping) and lac.get("kda_layers"):
        h, d, k = lac["num_heads"], lac["head_dim"], lac.get("short_conv_kernel_size", 4)
        add("recurrent_state", f"kda temporal ({h}, {d}, {d}) f32; conv ({k - 1}, {3 * h * d})")
        for key in ("use_full_rank_gate", "gate_lower_bound"):
            if key in lac:
                add(f"kda.{key}", lac[key])


def _dsv4_items(cfg: Mapping[str, Any], add) -> None:
    if "compress_ratios" not in cfg:
        return
    add("compress_ratios", rle([str(r) for r in cfg["compress_ratios"]]))
    for k in ("hc_mult", "hc_sinkhorn_iters", "o_groups", "o_lora_rank", "expert_dtype"):
        if k in cfg:
            add(k, cfg[k])


def modeling_items(cfg: Mapping[str, Any], source: str) -> list[Item]:
    fields = branch_fields(source)
    return [Item(f"branch:{f}", str(cfg.get(f, "<absent>")), "modeling") for f in sorted(fields)]


def branch_fields(source: str) -> set[str]:
    """Config fields read in a condition, plus per-layer lists indexed anywhere
    (`config.layer_types[i]` is a branch too)."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            name = _config_field(node.value)
            if name:
                found.add(name)
        test = _condition(node)
        if test is None:
            continue
        for sub in ast.walk(test):
            name = _config_field(sub)
            if name:
                found.add(name)
    return found


def _condition(node: ast.AST) -> ast.AST | None:
    if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)):
        return node.test
    if isinstance(node, ast.comprehension):
        return ast.BoolOp(op=ast.And(), values=list(node.ifs)) if node.ifs else None
    return None


def _config_field(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and _is_config(node.value):
        return node.attr
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ("getattr", "hasattr")
    ):
        if (
            len(node.args) >= MIN_GETATTR_ARGS
            and _is_config(node.args[0])
            and isinstance(node.args[1], ast.Constant)
        ):
            return str(node.args[1].value)
    return None


def _is_config(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in ("config", "cfg", "text_config")
    if isinstance(node, ast.Attribute):
        return node.attr in ("config", "text_config")
    return False


def rle(seq: list[str]) -> str:
    """'a a b c b c b c' -> 'ax2, (b c)x3': earliest start, shortest period repeating twice+."""
    for start in range(len(seq)):
        for period in range(1, (len(seq) - start) // 2 + 1):
            unit = seq[start : start + period]
            end = start + period
            while seq[end : end + period] == unit:
                end += period
            if (end - start) // period >= MIN_REPS:
                run = (
                    f"({' '.join(unit)})x{(end - start) // period}"
                    if period > 1
                    else f"{unit[0]}x{(end - start) // period}"
                )
                return ", ".join(p for p in (", ".join(seq[:start]), run, rle(seq[end:])) if p)
    return ", ".join(seq)


def _head_dim(cfg: Mapping[str, Any]) -> int | None:
    if cfg.get("head_dim"):
        return int(cfg["head_dim"])
    if "qk_nope_head_dim" in cfg:
        return int(cfg["qk_nope_head_dim"]) + int(cfg["qk_rope_head_dim"])
    hidden = cfg.get("hidden_size", cfg.get("n_embd"))
    heads = cfg.get("num_attention_heads", cfg.get("n_head"))
    return int(hidden) // int(heads) if hidden and heads else None


def _md(v: str, limit: int = MD_CELL) -> str:
    v = v.replace("|", "\\|").replace("\n", " ")
    return v if len(v) <= limit else v[: limit - 3] + "..."
