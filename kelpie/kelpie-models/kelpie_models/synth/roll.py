"""Roll a HF config.json down to the smallest model that keeps every layer kind and transition.

    rolled = roll(hf_config)             # rolled.config: dict, rolled.plan: RollPlan
    hc = HFConfigClass.from_dict(rolled.config)

Two steps, both recorded in the plan:

1. Depth: the smallest order-preserving subset of source layers whose kinds cover every source
   kind and whose adjacent pairs match the source's is kept, then every schedule field is
   rewritten for the new depth. A subset the config's own fields cannot express is rejected and
   the search continues.

2. Width: dims shrink to the smallest values that keep the structure legal (GQA ratio, head_dim
   floor, expert-group divisibility, vocab >= special token ids + 1, ...).

Fails closed: a schedule that cannot be re-expressed, or a plan that does not cover, raises.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

MIN_HEAD_DIM = 64
MIN_VOCAB = 256
MAX_GQA_RATIO = 4
MD_CELL = 60
SEARCH_BUDGET = 500_000  # DFS nodes per depth before giving up


@dataclass(frozen=True)
class Rewrite:
    field: str
    before: Any
    after: Any
    why: str


@dataclass(frozen=True)
class RollPlan:
    source_layers: tuple[str, ...]  # kind per source layer, main layers then MTP layers
    kept: tuple[int, ...]  # source indices kept, ascending
    n_main: int  # source main-trunk depth (MTP layers follow)
    rewrites: tuple[Rewrite, ...] = ()
    guesses: tuple[str, ...] = ()  # decisions the config gives no ground truth for

    def __post_init__(self) -> None:
        if not self.kept or list(self.kept) != sorted(set(self.kept)):
            raise ValueError("kept must be a non-empty ascending list of distinct source indices")
        missing_kinds = self.kinds - {self.source_layers[i] for i in self.kept}
        if missing_kinds:
            raise ValueError(f"roll plan does not cover kinds: {sorted(missing_kinds)}")
        if self.transitions != self.kept_transitions:
            raise ValueError(
                f"roll plan transitions {sorted(self.kept_transitions)} != "
                f"source transitions {sorted(self.transitions)}"
            )

    @property
    def kinds(self) -> frozenset[str]:
        return frozenset(self.source_layers)

    @property
    def transitions(self) -> frozenset[tuple[str, str]]:
        return adjacent_pairs(self.source_layers)

    @property
    def layers(self) -> tuple[str, ...]:
        return tuple(self.source_layers[i] for i in self.kept)

    @property
    def kept_transitions(self) -> frozenset[tuple[str, str]]:
        return adjacent_pairs(self.layers)

    @property
    def kept_main(self) -> tuple[int, ...]:
        return tuple(i for i in self.kept if i < self.n_main)

    @property
    def kept_mtp(self) -> tuple[int, ...]:
        return tuple(i for i in self.kept if i >= self.n_main)

    def to_markdown(self) -> str:
        lines = [
            f"source: {len(self.source_layers)} layers ({self.n_main} main), "
            f"{len(self.kinds)} kinds, {len(self.transitions)} transitions",
            f"kept: {list(self.kept)} -> {list(self.layers)}",
            "",
            "| field | before | after | why |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {r.field} | {_md(r.before)} | {_md(r.after)} | {r.why} |" for r in self.rewrites
        ]
        if self.guesses:
            lines += ["", "guesses:"] + [f"- {g}" for g in self.guesses]
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class RolledConfig:
    config: dict
    plan: RollPlan


def roll(hf_config: Mapping[str, Any], *, min_layers_per_kind: int = 1) -> RolledConfig:
    """Roll a hub config.json dict. Nested `text_config` (VLM wrappers) is rolled in place."""
    cfg = copy.deepcopy(dict(hf_config))
    if "text_config" in cfg and isinstance(cfg["text_config"], Mapping):
        inner = roll(cfg["text_config"], min_layers_per_kind=min_layers_per_kind)
        cfg["text_config"] = inner.config
        rw = list(inner.plan.rewrites)
        rw += _drop_quantization(cfg)
        guesses = inner.plan.guesses + (
            "wrapper config: only text_config is rolled; vision_config and siblings untouched",
        )
        plan = RollPlan(
            inner.plan.source_layers, inner.plan.kept, inner.plan.n_main, tuple(rw), guesses
        )
        return RolledConfig(cfg, plan)

    sched = schedule(cfg)
    rewrites: list[Rewrite] = []
    guesses = list(sched.guesses)

    kept = choose_layers(
        sched.kinds, min_layers_per_kind, lambda ks: _try_encode(sched, cfg, ks) is not None
    )
    encoded = _try_encode(sched, cfg, kept)
    assert encoded is not None, "choose_layers accepted a subset the encoder rejects"
    cfg, rewrites = encoded

    rewrites += shrink_dims(cfg, guesses)
    rewrites += _drop_quantization(cfg)
    plan = RollPlan(tuple(sched.kinds), tuple(kept), sched.n_main, tuple(rewrites), tuple(guesses))
    return RolledConfig(cfg, plan)


@dataclass(frozen=True)
class LayerKind:
    attn: str
    mlp: str
    tags: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return "+".join((self.attn, self.mlp, *self.tags))


@dataclass(frozen=True)
class Schedule:
    layers: tuple[LayerKind, ...]  # main trunk then MTP layers
    n_main: int
    guesses: tuple[str, ...] = ()

    @property
    def kinds(self) -> list[str]:
        return [layer.name for layer in self.layers]


def schedule(cfg: Mapping[str, Any]) -> Schedule:
    """Per-layer kinds from whatever fields the config uses; MTP layers appended with tag 'mtp'."""
    n = depth(cfg)
    guesses: list[str] = []
    attn = attention_kinds(cfg, n)
    mlp = mlp_kinds(cfg, n)
    n_mtp = int(cfg.get("num_nextn_predict_layers") or 0)
    if isinstance(cfg.get("mtp"), Mapping):
        n_mtp = int(cfg["mtp"].get("num_layers", n_mtp) or n_mtp)
    main = [LayerKind(a, m) for a, m in zip(attn[:n], mlp[:n], strict=True)]
    extra = attn[
        n:
    ]  # a schedule list longer than the trunk (dsv4 compress_ratios) names MTP layers
    mtp: list[LayerKind] = []
    for j in range(n_mtp):
        if j < len(extra):
            a = extra[j]
        else:
            a = attn[n - 1]
            guesses.append(
                f"MTP layer {j}: no schedule field names its attention kind; "
                f"assumed '{a}' (last trunk layer)"
            )
        mtp.append(LayerKind(a, mlp_kinds_mtp(cfg), ("mtp",)))
    return Schedule(tuple(main + mtp), n, tuple(guesses))


def depth(cfg: Mapping[str, Any]) -> int:
    for k in ("num_hidden_layers", "n_layer", "num_layers"):
        if k in cfg:
            return int(cfg[k])
    raise KeyError("config has no depth field (num_hidden_layers / n_layer)")


def attention_kinds(cfg: Mapping[str, Any], n: int) -> list[str]:
    """Attention kind per layer; may be longer than n when the schedule field lists MTP layers.
    First detector that recognises the config's schedule fields wins."""
    for detect in _ATTN_DETECTORS:
        kinds = detect(cfg, n)
        if kinds is not None:
            return kinds
    return ["full"] * n


def _attn_kimi(cfg: Mapping[str, Any], n: int) -> list[str] | None:
    lac = cfg.get("linear_attn_config")
    if not (isinstance(lac, Mapping) and "kda_layers" in lac):
        return None
    kda = {int(i) - 1 for i in lac["kda_layers"]}  # 1-indexed layer lists
    base = "dsa" if _is_dsa(cfg) else ("mla" if _is_mla(cfg) else "full")
    return ["kda" if i in kda else base for i in range(n)]


def _attn_compress_ratios(cfg: Mapping[str, Any], n: int) -> list[str] | None:
    if "compress_ratios" not in cfg:  # deepseek v4: 0 = sliding window, 4 = CSA, 128 = HCA
        return None
    return [_COMPRESS_RATIO_KIND.get(int(r), f"compress{r}") for r in cfg["compress_ratios"]]


def _attn_layer_types(cfg: Mapping[str, Any], n: int) -> list[str] | None:
    if not cfg.get("layer_types"):
        return None
    kinds = [_LAYER_TYPE_KIND.get(t, t) for t in cfg["layer_types"]]
    if _is_dsa(cfg):
        kinds = ["dsa" if k == "full" else k for k in kinds]
    return _with_indexer(cfg, kinds)


def _attn_interval(cfg: Mapping[str, Any], n: int) -> list[str] | None:
    if not cfg.get("full_attention_interval"):
        return None
    k = int(cfg["full_attention_interval"])
    return ["full" if (i + 1) % k == 0 else "linear" for i in range(n)]


def _attn_sliding_pattern(cfg: Mapping[str, Any], n: int) -> list[str] | None:
    pat = cfg.get("sliding_window_pattern")  # gemma2/3 style: int period or "LLLLLG"
    if not pat:
        return None
    if isinstance(pat, str):
        return ["full" if pat[i % len(pat)] == "G" else "swa" for i in range(n)]
    return ["full" if (i + 1) % int(pat) == 0 else "swa" for i in range(n)]


def _attn_max_window_layers(cfg: Mapping[str, Any], n: int) -> list[str] | None:
    if not (cfg.get("use_sliding_window") and cfg.get("sliding_window")):  # qwen2 style
        return None
    mwl = int(cfg.get("max_window_layers", 0))
    return ["swa" if i >= mwl else "full" for i in range(n)]


def _attn_uniform(cfg: Mapping[str, Any], n: int) -> list[str] | None:
    if _is_dsa(cfg):
        return _with_indexer(cfg, ["dsa"] * n)
    if _is_mla(cfg):
        return ["mla"] * n
    if cfg.get("sliding_window"):
        return ["swa"] * n
    return None


_ATTN_DETECTORS = (
    _attn_kimi,
    _attn_compress_ratios,
    _attn_layer_types,
    _attn_interval,
    _attn_sliding_pattern,
    _attn_max_window_layers,
    _attn_uniform,
)


def mlp_kinds(cfg: Mapping[str, Any], n: int) -> list[str]:
    if cfg.get("mlp_layer_types"):
        return [_MLP_TYPE_KIND.get(t, t) for t in cfg["mlp_layer_types"]][:n]
    if not _is_moe(cfg):
        return ["dense"] * n
    k_dense = int(cfg.get("first_k_dense_replace", 0))
    freq = int(cfg.get("moe_layer_freq", 1))
    step = int(cfg.get("decoder_sparse_step", 1))
    only = {int(i) for i in (cfg.get("mlp_only_layers") or [])}
    n_hash = int(cfg.get("num_hash_layers", 0))
    out = []
    for i in range(n):
        moe = i >= k_dense and i % freq == 0 and (i + 1) % step == 0 and i not in only
        out.append("dense" if not moe else ("hash_moe" if i < n_hash else "moe"))
    return out


def mlp_kinds_mtp(cfg: Mapping[str, Any]) -> str:
    return "moe" if _is_moe(cfg) else "dense"


_LAYER_TYPE_KIND = {
    "full_attention": "full",
    "sliding_attention": "swa",
    "linear_attention": "linear",
    "chunked_attention": "chunked",
    "deepseek_sparse_attention": "dsa",
    "compressed_sparse_attention": "csa",
    "heavily_compressed_attention": "hca",
}
_COMPRESS_RATIO_KIND = {0: "swa", 4: "csa", 128: "hca"}
_MLP_TYPE_KIND = {"dense": "dense", "sparse": "moe", "moe": "moe", "hash_moe": "hash_moe"}
_MOE_COUNT_FIELDS = ("n_routed_experts", "num_experts", "num_local_experts")


def _is_mla(cfg: Mapping[str, Any]) -> bool:
    return bool(cfg.get("kv_lora_rank"))


def _is_dsa(cfg: Mapping[str, Any]) -> bool:
    return bool(cfg.get("index_topk")) and "compress_ratios" not in cfg


def _is_moe(cfg: Mapping[str, Any]) -> bool:
    return any(int(cfg.get(k) or 0) > 0 for k in _MOE_COUNT_FIELDS)


def _with_indexer(cfg: Mapping[str, Any], kinds: list[str]) -> list[str]:
    it = cfg.get("indexer_types")
    if not it:
        return kinds
    return [f"{k}.{t}" if k == "dsa" else k for k, t in zip(kinds, it, strict=False)]


def choose_layers(
    kinds: list[str], min_per_kind: int, expressible: Callable[[list[int]], bool]
) -> list[int]:
    """Smallest ascending index subset covering every kind (>= min_per_kind times) whose adjacent
    pairs equal the source's adjacent pairs, and that `expressible` accepts. Lexicographically
    first among equals, so the trunk head (dense prefix, first period) is preferred."""
    n = len(kinds)
    need_kinds = {k: min_per_kind for k in set(kinds)}
    trans = adjacent_pairs(kinds)
    for length in range(1, n + 1):
        found = _dfs(kinds, trans, need_kinds, length, expressible)
        if found is not None:
            return found
    raise ValueError("no layer subset covers the source kinds and transitions")


def adjacent_pairs(seq: tuple[str, ...] | list[str]) -> frozenset[tuple[str, str]]:
    return frozenset(zip(seq[:-1], seq[1:], strict=False))


def _dfs(
    kinds: list[str],
    trans: frozenset[tuple[str, str]],
    need_kinds: dict[str, int],
    length: int,
    expressible: Callable[[list[int]], bool],
) -> list[int] | None:
    n = len(kinds)
    dead: set[tuple] = set()  # (last, depth, need_k, need_t) with no covering completion
    budget = [SEARCH_BUDGET]

    def rec(seq: list[int], need_k: dict[str, int], need_t: frozenset) -> list[int] | None:
        budget[0] -= 1
        if budget[0] < 0:
            raise ValueError(f"roll search exceeded {SEARCH_BUDGET} nodes at depth {length}")
        remaining = length - len(seq)
        if remaining == 0:
            covered = not need_t and all(v <= 0 for v in need_k.values())
            return list(seq) if covered and expressible(seq) else None
        if len(need_t) > remaining or sum(max(v, 0) for v in need_k.values()) > remaining:
            return None
        key = (seq[-1] if seq else -1, remaining, tuple(sorted(need_k.items())), need_t)
        if key in dead:
            return None
        start = seq[-1] + 1 if seq else 0
        for j in range(start, n - remaining + 1):
            if seq and (kinds[seq[-1]], kinds[j]) not in trans:
                continue
            nk = dict(need_k)
            nk[kinds[j]] -= 1
            nt = need_t - {(kinds[seq[-1]], kinds[j])} if seq else need_t
            seq.append(j)
            out = rec(seq, nk, nt)
            seq.pop()
            if out is not None:
                return out
        dead.add(key)
        return None

    return rec([], dict(need_kinds), trans)


class NotExpressible(Exception):
    """The chosen subset cannot be written back with the config's own schedule fields."""


def _try_encode(sched: Schedule, cfg: dict, kept: list[int]) -> tuple[dict, list[Rewrite]] | None:
    try:
        return encode_schedule(sched, cfg, kept)
    except NotExpressible:
        return None


def encode_schedule(sched: Schedule, src: dict, kept: list[int]) -> tuple[dict, list[Rewrite]]:
    """Rewrite every schedule field of `src` for the kept layers. Raises NotExpressible."""
    cfg = copy.deepcopy(src)
    rw: list[Rewrite] = []
    main = [i for i in kept if i < sched.n_main]
    mtp = [i for i in kept if i >= sched.n_main]
    layers = [sched.layers[i] for i in main]

    def set_(key: str, value: Any, why: str, holder: dict | None = None) -> None:
        h = cfg if holder is None else holder
        if h.get(key) != value:
            rw.append(Rewrite(key, h.get(key), value, why))
        h[key] = value

    _encode_lists(cfg, main, mtp, set_)
    _encode_counts(cfg, layers, set_)
    _check_periods(cfg, layers)
    if cfg.get("indexer_types") and "index_topk_freq" in cfg:
        _encode_indexer_offset(cfg, set_)
    return cfg, rw


def _encode_lists(cfg: dict, main: list[int], mtp: list[int], set_: Callable) -> None:
    """Depth and explicit per-layer lists: restrict / renumber to the kept layers."""
    for k in ("num_hidden_layers", "n_layer", "num_layers"):
        if k in cfg:
            set_(k, len(main), "depth = kept trunk layers")
    for k in ("layer_types", "mlp_layer_types", "indexer_types"):
        if cfg.get(k):
            set_(k, [cfg[k][i] for i in main], "per-layer list restricted to kept layers")
    if "compress_ratios" in cfg:
        kept = main + mtp
        set_("compress_ratios", [cfg["compress_ratios"][i] for i in kept], "kept trunk + MTP")
    if "num_nextn_predict_layers" in cfg:
        set_("num_nextn_predict_layers", len(mtp), "kept MTP layers")
    if isinstance(cfg.get("mtp"), Mapping) and "num_layers" in cfg["mtp"]:
        set_("num_layers", len(mtp), "kept MTP layers", holder=cfg["mtp"])
    if cfg.get("mlp_only_layers"):
        only = set(cfg["mlp_only_layers"])
        set_("mlp_only_layers", [j for j, i in enumerate(main) if i in only], "renumbered")
    lac = cfg.get("linear_attn_config")
    if isinstance(lac, Mapping) and "kda_layers" in lac:
        kda = {int(i) - 1 for i in lac["kda_layers"]}
        new_kda = [j + 1 for j, i in enumerate(main) if i in kda]
        new_full = [j + 1 for j, i in enumerate(main) if i not in kda]
        set_("kda_layers", new_kda, "1-indexed, renumbered", lac)
        set_("full_attn_layers", new_full, "1-indexed, renumbered", lac)


def _encode_counts(cfg: dict, layers: list[LayerKind], set_: Callable) -> None:
    """Count-shaped fields are recounted over the kept layers."""
    if "first_k_dense_replace" in cfg or "num_hash_layers" in cfg:
        _encode_prefix_counts(cfg, layers, set_)
    if "max_window_layers" in cfg:
        n_full = (
            sum(1 for layer in layers if layer.attn != "swa")
            if cfg.get("use_sliding_window")
            else len(layers)
        )
        set_("max_window_layers", n_full, "layers before the sliding window starts (count)")


def _check_periods(cfg: dict, layers: list[LayerKind]) -> None:
    """Period-shaped fields are kept as-is; the kept layers must fit them."""
    n_new = len(layers)
    attn = [layer.attn for layer in layers]
    if cfg.get("full_attention_interval"):
        k = int(cfg["full_attention_interval"])
        if attn != ["full" if (i + 1) % k == 0 else "linear" for i in range(n_new)]:
            raise NotExpressible("full_attention_interval")
    if cfg.get("sliding_window_pattern") and not cfg.get("layer_types"):
        pat = cfg["sliding_window_pattern"]
        want = (
            ["full" if pat[i % len(pat)] == "G" else "swa" for i in range(n_new)]
            if isinstance(pat, str)
            else ["full" if (i + 1) % int(pat) == 0 else "swa" for i in range(n_new)]
        )
        if attn != want:
            raise NotExpressible("sliding_window_pattern")


def _encode_prefix_counts(cfg: dict, layers: list[LayerKind], set_: Callable) -> None:
    mlps = [layer.mlp for layer in layers]
    n_dense = next((i for i, m in enumerate(mlps) if m != "dense"), len(mlps))
    if "first_k_dense_replace" in cfg:
        set_("first_k_dense_replace", n_dense, "leading dense layers (count)")
    if "num_hash_layers" in cfg:
        n_hash = sum(1 for m in mlps if m == "hash_moe")
        if mlps[n_dense : n_dense + n_hash] != ["hash_moe"] * n_hash:
            raise NotExpressible("num_hash_layers must be a prefix of the MoE layers")
        set_("num_hash_layers", n_hash, "leading hash-routed MoE layers (count)")
    if cfg.get("mlp_layer_types"):
        return  # explicit list carries the rest
    freq = int(cfg.get("moe_layer_freq", 1))
    step = int(cfg.get("decoder_sparse_step", 1))
    for i, m in enumerate(mlps):
        want_moe = i >= n_dense and i % freq == 0 and (i + 1) % step == 0
        if (m != "dense") != want_moe:
            raise NotExpressible("moe_layer_freq / decoder_sparse_step")


def _encode_indexer_offset(cfg: dict, set_: Callable) -> None:
    """GLM: indexer_types is explicit and wins in HF; keep freq/offset telling the same story."""
    freq = max(int(cfg.get("index_topk_freq", 1)), 1)
    it = cfg["indexer_types"]
    for offset in range(len(it) + 1):
        want = ["full" if max(i - offset + 1, 0) % freq == 0 else "shared" for i in range(len(it))]
        if want == list(it):
            set_(
                "index_skip_topk_offset",
                offset,
                "first indexer-full layer after the prefix (count)",
            )
            return
    raise NotExpressible("index_topk_freq / index_skip_topk_offset")


def shrink_dims(cfg: dict, guesses: list[str]) -> list[Rewrite]:
    """Smallest legal widths, in place. Returns the rewrites."""
    rw: list[Rewrite] = []

    def set_(key: str, value: Any, why: str, holder: dict | None = None) -> None:
        h = cfg if holder is None else holder
        if key in h and h[key] != value:
            rw.append(Rewrite(key, h[key], value, why))
            h[key] = value

    new_heads = _shrink_heads(cfg, set_, guesses)
    head_dim = _shrink_head_dim(cfg, set_)
    hidden_key = _first(cfg, "hidden_size", "n_embd", "d_model")
    if hidden_key:
        implied = cfg.get("head_dim") is None  # then hidden must equal heads * head_dim
        set_(hidden_key, new_heads * head_dim if implied else MIN_HEAD_DIM, "smallest hidden")
    for k in ("q_lora_rank", "kv_lora_rank", "o_lora_rank"):
        if cfg.get(k):
            set_(k, MIN_HEAD_DIM, "low-rank projection floor")
    if cfg.get("o_groups"):
        groups = math.gcd(int(cfg["o_groups"]), new_heads)
        set_("o_groups", groups, "must divide num_attention_heads")
        guesses.append("dsv4 o_groups: assumed to divide num_attention_heads")
    _shrink_ffn(cfg, set_)
    _shrink_moe(cfg, set_, guesses)
    _shrink_recurrent(cfg, set_)
    _shrink_indexer(cfg, set_)
    _shrink_rope(cfg, set_, head_dim)
    vocab_key = _first(cfg, "vocab_size", "n_vocab")
    if vocab_key:
        vocab = min(int(cfg[vocab_key]), max(MIN_VOCAB, special_token_ceiling(cfg)))
        set_(vocab_key, vocab, "special ids + 1")
    for k in _SEMANTIC_KEPT:
        if cfg.get(k):
            guesses.append(f"{k}={cfg[k]} kept: semantic, not a width")
    return rw


_SEMANTIC_KEPT = (
    "sliding_window",
    "index_topk",
    "hc_mult",
    "max_position_embeddings",
    "n_positions",
    "n_ctx",
)


def _shrink_heads(cfg: dict, set_: Callable, guesses: list[str]) -> int:
    """-> new head count. kv heads: 1 under GQA (ratio kept, capped), else equal to heads."""
    heads_key = _first(cfg, "num_attention_heads", "n_head")
    heads = int(cfg[heads_key]) if heads_key else 1
    kv = int(cfg.get("num_key_value_heads") or heads)
    ratio = max(heads // max(kv, 1), 1)
    mla = _is_mla(cfg) or "qk_nope_head_dim" in cfg  # kv heads field is nominal under MLA
    if mla or ratio == 1:
        new_heads, new_kv = 2, 2
    else:
        new_heads, new_kv = min(ratio, MAX_GQA_RATIO), 1
        if ratio > MAX_GQA_RATIO:
            guesses.append(f"GQA ratio {ratio} capped to {MAX_GQA_RATIO} (heads {new_heads}, kv 1)")
    if heads_key:
        set_(heads_key, new_heads, "smallest head count keeping the GQA ratio (capped)")
    set_("num_key_value_heads", new_kv, "GQA divisibility")
    return new_heads


def _shrink_head_dim(cfg: dict, set_: Callable) -> int:
    """-> new head_dim. Keeps the MLA nope/rope split and the dsv4 partial-rotary fraction."""
    heads_key = _first(cfg, "num_attention_heads", "n_head")
    head_dim = _floor64(_head_dim(cfg, heads_key))
    if "qk_nope_head_dim" in cfg:  # MLA split: rope stays >= 64, nope shrinks to the floor
        set_("qk_nope_head_dim", _floor64(cfg["qk_nope_head_dim"]), "MLA nope part")
        set_("qk_rope_head_dim", _floor64(cfg["qk_rope_head_dim"]), "MLA rope part")
        set_("v_head_dim", _floor64(cfg["v_head_dim"]), "MLA value part")
        head_dim = cfg["qk_nope_head_dim"] + cfg["qk_rope_head_dim"]
        if "qk_head_dim" in cfg:
            set_("qk_head_dim", head_dim, "nope + rope")
        if cfg.get("head_dim") is not None:
            set_("head_dim", cfg["qk_rope_head_dim"], "MLA: HF points head_dim at the rope slice")
        return head_dim
    if "qk_rope_head_dim" in cfg and "head_dim" in cfg:  # dsv4: partial rotary inside head_dim
        partial = cfg["qk_rope_head_dim"] < cfg["head_dim"]
        rope = _floor64(cfg["qk_rope_head_dim"])
        set_("qk_rope_head_dim", rope, "rope part")
        head_dim = max(head_dim, 2 * rope) if partial else rope
    if cfg.get("head_dim") is not None:
        set_("head_dim", head_dim, f"head_dim floor {MIN_HEAD_DIM} when source >= {MIN_HEAD_DIM}")
    return head_dim


def _shrink_ffn(cfg: dict, set_: Callable) -> None:
    for k in ("intermediate_size", "n_inner", "shared_expert_intermediate_size"):
        if cfg.get(k):
            set_(k, 2 * MIN_HEAD_DIM, "dense FFN width")
    for k in ("moe_intermediate_size", "routed_expert_hidden_size"):
        if cfg.get(k):
            set_(k, MIN_HEAD_DIM, "expert FFN width")


def _shrink_moe(cfg: dict, set_: Callable, guesses: list[str]) -> None:
    ek = _first(cfg, *_MOE_COUNT_FIELDS)
    if not ek or not int(cfg[ek] or 0):
        return
    topk_key = _first(cfg, "num_experts_per_tok", "num_experts_per_token", "experts_per_token")
    topk = min(int(cfg[topk_key]), 2) if topk_key else 1
    groups = int(cfg.get("n_group") or cfg.get("num_expert_group") or 1)
    topk_group = int(cfg.get("topk_group") or 1)
    per_group = max(
        2, math.ceil(topk / max(min(topk_group, groups), 1))
    )  # noaux_tc sums top-2 per group
    experts = max(groups * per_group, 2 * topk)
    for k in _MOE_COUNT_FIELDS:
        if k in cfg:
            set_(k, experts, f"{groups} groups x {per_group}; >= 2*topk")
    for k in ("num_experts_per_tok", "num_experts_per_token", "experts_per_token"):
        if k in cfg:
            set_(k, topk, "top-k")
    if cfg.get("topk_group", 0) > groups:
        set_("topk_group", groups, "<= n_group")
    if "n_shared_experts" in cfg or "num_shared_experts" in cfg:
        guesses.append("shared expert count kept (semantic)")


def _shrink_recurrent(cfg: dict, set_: Callable) -> None:
    if "linear_num_value_heads" in cfg:  # qwen3-next GDN
        kh, vh = int(cfg["linear_num_key_heads"]), int(cfg["linear_num_value_heads"])
        r = max(vh // max(kh, 1), 1)
        set_("linear_num_key_heads", 1, "GDN key heads")
        set_("linear_num_value_heads", r, "GDN value heads keep the value/key ratio")
        set_("linear_key_head_dim", _floor64(cfg["linear_key_head_dim"]), "GDN key dim")
        set_("linear_value_head_dim", _floor64(cfg["linear_value_head_dim"]), "GDN value dim")
    lac = cfg.get("linear_attn_config")
    if isinstance(lac, dict):  # kimi KDA
        if "num_heads" in lac:
            set_("num_heads", 2, "KDA heads", lac)
        if "head_dim" in lac:
            set_("head_dim", _floor64(lac["head_dim"]), "KDA head dim", lac)


def _shrink_indexer(cfg: dict, set_: Callable) -> None:
    if cfg.get("index_n_heads"):
        set_("index_n_heads", 2, "indexer heads")
    if cfg.get("index_head_dim"):
        set_("index_head_dim", _floor64(cfg["index_head_dim"]), "indexer head dim")


def _shrink_rope(cfg: dict, set_: Callable, head_dim: int) -> None:
    """Keep the rope_scaling / rope_parameters shape; re-fit mrope sections to the rotary dim."""
    for key in ("rope_scaling", "rope_parameters"):
        rp = cfg.get(key)
        if not isinstance(rp, dict) or "mrope_section" not in rp:
            continue
        frac = float(cfg.get("partial_rotary_factor") or rp.get("partial_rotary_factor") or 1.0)
        half = int(head_dim * frac) // 2
        sec = [int(s) for s in rp["mrope_section"]]
        total = sum(sec)
        new = [max(1, s * half // total) for s in sec]
        new[0] += half - sum(new)
        set_("mrope_section", new, f"sections sum to rotary_dim//2 = {half}", rp)


def special_token_ceiling(cfg: Mapping[str, Any]) -> int:
    ids: list[int] = []
    for k, v in cfg.items():
        if not k.endswith("_token_id"):
            continue
        vals = v if isinstance(v, list) else [v]
        ids += [int(x) for x in vals if isinstance(x, int) and not isinstance(x, bool)]
    return max(ids, default=-1) + 1


def _drop_quantization(cfg: dict) -> list[Rewrite]:
    if "quantization_config" not in cfg:
        return []
    before = cfg.pop("quantization_config")
    return [
        Rewrite("quantization_config", before, None, "synthetic weights are random, not quantized")
    ]


def _head_dim(cfg: Mapping[str, Any], heads_key: str | None) -> int:
    if cfg.get("head_dim"):
        return int(cfg["head_dim"])
    hidden_key = _first(cfg, "hidden_size", "n_embd", "d_model")
    if hidden_key and heads_key:
        return int(cfg[hidden_key]) // int(cfg[heads_key])
    return MIN_HEAD_DIM


def _floor64(v: Any) -> int:
    v = int(v)
    return MIN_HEAD_DIM if v >= MIN_HEAD_DIM else v


def _first(cfg: Mapping[str, Any], *keys: str) -> str | None:
    return next((k for k in keys if k in cfg), None)


def _md(v: Any) -> str:
    s = str(v).replace("|", "\\|")
    return s if len(s) <= MD_CELL else s[: MD_CELL - 3] + "..."
