"""Cache groups derived from each layer's `AttnSpec`: `caches` lowers a spec to `CacheSpec`s,
`derive_groups` dedupes them by lifetime key (kind, stride, retention, n_snapshots, cacheable);
members of different byte sizes share one table at distinct offsets. Recurrent / CSA / HCA
per-request recurrent state and the CSA/HCA compressor rings are per_seq cache groups the
core owns, not a Python-side ring.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["per_token", "per_seq"]


@dataclass(frozen=True)
class All:
    """Rows live for the whole request."""


@dataclass(frozen=True)
class Window:
    """Only rows covering the last `w` tokens matter; the core frees the rest as they slide out."""

    w: int


Retention = All | Window


@dataclass(frozen=True)
class FullAttn:
    heads: int
    dim: int


@dataclass(frozen=True)
class SlidingAttn:
    heads: int
    dim: int
    window: int
    cacheable: bool = True


@dataclass(frozen=True)
class IndexerSpec:
    """`heads` query heads score one `dim`-wide key per token, top-`topk` attended. shared:
    reuses another layer's K cache and owns no member."""

    heads: int
    dim: int
    topk: int
    shared: bool = False


@dataclass(frozen=True)
class MLA:
    """latent + rope per token (one member); an optional indexer K member on the same table.
    indexer: None, an IndexerSpec, or "full" / "shared" with `indexer_dim`."""

    latent: int
    rope: int
    indexer: IndexerSpec | Literal["full", "shared"] | None = None
    indexer_dim: int = 0

    def indexer_member_dim(self) -> int:
        if isinstance(self.indexer, IndexerSpec):
            return 0 if self.indexer.shared else self.indexer.dim
        return self.indexer_dim if self.indexer == "full" else 0


@dataclass(frozen=True)
class CSA:
    """Non-cacheable window ring (stride 1) plus, for ratio > 0, stride-`ratio` compressed KV
    and indexer K on one table, and the compressor projection ring as a per_seq group."""

    ratio: int
    window: int
    kv_bytes: int
    indexer_bytes: int = 0


@dataclass(frozen=True)
class HCA:
    """Window ring + stride-`ratio` KV, no indexer; compressor ring is a per_seq group."""

    ratio: int
    window: int
    kv_bytes: int


@dataclass(frozen=True)
class Recurrent:
    """Recurrent state blobs: a per_seq cache group the core owns (one unit = the whole blob
    set). state = ((name, shape, itemsize), ...); itemsize 4 is kept fp32. n_snapshots is the
    ring depth R; checkpoint_every is S, the checkpoint interval (0 = never checkpoint)."""

    state: tuple[tuple[str, tuple[int, ...], int], ...]
    n_snapshots: int = 1
    checkpoint_every: int = 0

    @property
    def nbytes(self) -> int:
        return sum(math.prod(shape) * isz for _, shape, isz in self.state)


@dataclass(frozen=True)
class NoCache:
    pass


AttnSpec = FullAttn | SlidingAttn | MLA | CSA | HCA | Recurrent | NoCache


@dataclass(frozen=True)
class CacheSpec:
    kind: Kind
    stride: int  # per_token: tokens per unit; per_seq: checkpoint interval (0 = never)
    bytes_per_unit: int
    retention: Retention
    n_snapshots: int = 1
    cacheable: bool = True
    unit_shape: tuple[int, ...] = ()  # (2, heads, dim) for KV; () = opaque bytes

    @property
    def key(self) -> tuple:
        return (self.kind, self.stride, self.retention, self.n_snapshots, self.cacheable)


@dataclass(frozen=True)
class Group:
    kind: Kind
    stride: int
    retention: Retention
    n_snapshots: int
    cacheable: bool
    members: tuple[CacheSpec, ...] = field(default=())

    @property
    def window(self) -> int:
        return self.retention.w if isinstance(self.retention, Window) else 0

    @property
    def bytes_per_unit(self) -> int:
        return sum(m.bytes_per_unit for m in self.members)

    def bytes_per_block(self, block_size: int) -> int:
        return block_size * self.bytes_per_unit

    def member_byte_offsets(self) -> list[int]:
        offs, acc = [], 0
        for m in self.members:
            offs.append(acc)
            acc += m.bytes_per_unit
        return offs

    def blocks_for(self, n_tokens: int, block_size: int) -> int:
        """Blocks a request holds in steady state after `n_tokens`."""
        if self.kind == "per_seq":
            return self.n_snapshots if n_tokens > 0 else 0
        rows = math.ceil(n_tokens / (self.stride * block_size))
        if isinstance(self.retention, Window):
            return min(rows, math.ceil((self.retention.w - 1) / block_size) + 1)
        return rows


LayerCaches = list[list[tuple[int, int]]]  # per layer: [(group index, member offset)]


def caches(  # noqa: PLR0911, PLR0912, C901
    spec: AttnSpec, max_spec_tokens: int = 0, itemsize: int = 2
) -> list[CacheSpec]:
    """Member caches in the fixed order the kernel reads positionally."""
    match spec:
        case FullAttn(heads, dim):
            return [kv_spec(heads, dim, All(), itemsize)]
        case SlidingAttn(heads, dim, window, cacheable):
            return [kv_spec(heads, dim, Window(window + max_spec_tokens), itemsize, cacheable)]
        case MLA(latent, rope):
            width = latent + rope
            out = [CacheSpec("per_token", 1, width * itemsize, All(), unit_shape=(width,))]
            if dim := spec.indexer_member_dim():
                out.append(CacheSpec("per_token", 1, dim * itemsize, All(), unit_shape=(dim,)))
            return out
        case CSA(ratio, window, kv_bytes, indexer_bytes):
            out = [CacheSpec("per_token", 1, kv_bytes, Window(window + max_spec_tokens), 1, False)]
            if ratio > 0:
                out.append(CacheSpec("per_token", ratio, kv_bytes, All()))
                if indexer_bytes:
                    out.append(CacheSpec("per_token", ratio, indexer_bytes, All()))
                out.append(compressor_spec(ratio, kv_bytes, indexer_bytes, max_spec_tokens))
            return out
        case HCA(ratio, window, kv_bytes):
            return [
                CacheSpec("per_token", 1, kv_bytes, Window(window + max_spec_tokens), 1, False),
                CacheSpec("per_token", ratio, kv_bytes, All()),
                compressor_spec(ratio, kv_bytes, 0, max_spec_tokens, overlap=False),
            ]
        case Recurrent():
            return [recurrent_spec(spec, spec.n_snapshots, max_spec_tokens)]
        case NoCache():
            return []
    raise TypeError(f"unknown attention spec {spec!r}")


def compressor_spec(
    ratio: int,
    kv_bytes: int,
    indexer_bytes: int,
    max_spec_tokens: int = 0,
    overlap: bool = True,
) -> CacheSpec:
    """The CSA/HCA compressor ring as a per_seq cache group.

    The compressor's input is a per-layer `(kv | gate)` projection of the hidden states
    (`deepseek_v4.py`: `raw = cat(h @ comp.kv.T, h @ comp.gate.T)`), not raw K/V rows -- there is
    no other group holding it, so it is a group of its own. CSA keeps `2 * ratio` rows because
    entry `j` reads the previous window's rows too (the Ca overlap); HCA keeps `ratio`.

    stride = ratio so its checkpoints land on the same boundaries as the C-group's units, which
    is what lets the cross-group hit fixpoint agree on a resume point.
    """
    assert ratio > 0, ratio
    # A row is the (kv | gate) pair, so twice the branch width. CSA's outer compressor is itself
    # double width (the Ca/Cb series), giving 4 * kv_bytes per row against HCA's 2 * kv_bytes;
    # the indexer rings its own pair alongside. This reproduces the byte count the StateRing
    # this group replaces used (`state_specs`: 2 * ratio rows of 4 * kv_bytes for CSA).
    rows = 2 * ratio if overlap else ratio
    row_bytes = (4 if overlap else 2) * kv_bytes + (4 if overlap else 2) * indexer_bytes
    # The per_seq window is checkpoints kept (the core's ring), independent of K: extra rows
    # write their own units at the step, not into the ring (docs/design-core-option2.md 2.5).
    del max_spec_tokens
    return CacheSpec("per_seq", ratio, rows * row_bytes, Window(COMPRESSOR_CHECKPOINTS))


COMPRESSOR_CHECKPOINTS = 2


def recurrent_spec(
    spec: Recurrent, n_snapshots: int, max_spec_tokens: int = 0
) -> CacheSpec:
    """Recurrent state as a per_seq group: one unit is the whole state blob set for the layer.

    Checkpoint every S = `checkpoint_every` tokens and keep `n_snapshots` of them (the core's
    per_seq window, K-independent: docs/design-core-option2.md 2.5). S = 0 means never
    checkpoint, and such a group never enters the prefix index (Q3, "per_seq, stride 0").
    """
    del max_spec_tokens
    stride = spec.checkpoint_every
    assert stride == 0 or n_snapshots >= 1, (stride, n_snapshots)
    retention: Retention = All() if stride == 0 else Window(n_snapshots)
    return CacheSpec("per_seq", stride, spec.nbytes, retention, n_snapshots, stride > 0)


KV_UNIT_SHAPE_RANK = 3
# K and V: two members of one KV unit (kernels/ops/paged_attention.py owns this fact).
KV_MEMBERS = 2


def kv_spec(
    heads: int, dim: int, retention: Retention, itemsize: int, cacheable: bool = True
) -> CacheSpec:
    shape = (2, heads, dim)
    return CacheSpec("per_token", 1, math.prod(shape) * itemsize, retention, 1, cacheable, shape)


def derive_groups(
    layers: list[AttnSpec], max_spec_tokens: int = 0, itemsize: int = 2
) -> tuple[list[Group], LayerCaches]:
    """Groups in first-seen order; layer_caches[i] lists (group, offset) per member of layer i."""
    groups: list[Group] = []
    members: list[list[CacheSpec]] = []
    index: dict[tuple, int] = {}
    layer_caches: LayerCaches = []
    for spec in layers:
        refs: list[tuple[int, int]] = []
        for c in caches(spec, max_spec_tokens, itemsize):
            g = index.get(c.key)
            if g is None:
                g = len(groups)
                index[c.key] = g
                groups.append(Group(c.kind, c.stride, c.retention, c.n_snapshots, c.cacheable))
                members.append([])
            refs.append((g, len(members[g])))
            members[g].append(c)
        layer_caches.append(refs)
    groups = [
        Group(g.kind, g.stride, g.retention, g.n_snapshots, g.cacheable, tuple(m))
        for g, m in zip(groups, members, strict=True)
    ]
    assert len(layer_caches) == len(layers)
    assert sum(len(g.members) for g in groups) == sum(len(r) for r in layer_caches)
    return groups, layer_caches


def check_groups(groups: list[Group], engine_groups: tuple[Any, ...]) -> None:
    assert len(groups) == len(engine_groups), (groups, engine_groups)
    for g, e in zip(groups, engine_groups, strict=True):
        assert (g.kind, g.window, g.cacheable, g.stride) == (
            e.kind,
            e.window,
            e.cacheable,
            getattr(e, "stride", 1),
        ), (g, e)


@dataclass(frozen=True)
class KVLayout:
    """Member m of a group's cache is an array [num_blocks, block_size, *rows[m]]."""

    rows: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        assert self.rows


def reference_kv_layout(group: Group, itemsize: int) -> KVLayout:
    """KV member as (2, heads, dim): K and V are two members of the unit. The final tensor
    is [pages, 2, block, heads, dim] (FlashInfer NHD standard) — the `2` comes before
    `block_size` in the tensor shape, done by `kv.py:group_views`. The layout is stated once,
    by `kernels/ops/paged_attention.py`'s contract; this allocates to it. Opaque member as
    (width,)."""
    # per_seq: a page is one unit (block size 1) and its members are opaque blobs.
    assert group.kind == "per_token" or all(len(m.unit_shape) != KV_UNIT_SHAPE_RANK for m in group.members), group
    rows: list[tuple[int, ...]] = []
    for m in group.members:
        if len(m.unit_shape) == KV_UNIT_SHAPE_RANK:
            two, heads, dim = m.unit_shape
            assert two == KV_MEMBERS, m.unit_shape
            rows.append((KV_MEMBERS, heads, dim))
        else:
            assert m.bytes_per_unit % itemsize == 0, (m.bytes_per_unit, itemsize)
            rows.append((m.bytes_per_unit // itemsize,))
    assert len(rows) == len(group.members)
    return KVLayout(tuple(rows))


PAGE_QUANTUM = 4096
# Every page stays 16-byte aligned: slab_bytes is a multiple of lcm(pages_per_slab) * 16.
PAGE_ALIGN = 16
MAX_WASTE = 0.25
BLOCK_RANGE = range(8, 65)


@dataclass(frozen=True)
class SlabPlan:
    """How the groups of one model fill a slab (docs/slab-lcm-ladder.md).

    A slab is tiled EXACTLY: `pages_per_slab[g] * bytes_per_page[g] == slab_bytes` for every
    group, no slack (ruling 2026-09-10, replacing the slack rule of earlier the same day). The
    construction that makes exact tiling satisfiable even for DSV4's near-coprime per_seq pages:

      1. `slab0` is the largest RAW page over the chosen block sizes.
      2. `k_g = floor(slab0 / raw page_g)` -- how many of group g's pages a slab holds.
      3. `slab_bytes` is `slab0` rounded UP to a multiple of `lcm(k_g) * 16`, so every `k_g`
         divides it (and the 16 keeps pages 16-byte aligned).
      4. `bytes_per_page[g] = slab_bytes / k_g`, exact by construction and >= the raw page.

    So the old SLACK becomes per-page PADDING, which is what the 25% guard already measures.
    `rounding` is how much step 3 grew `slab0`; it is asserted small (< 5%) on the ladder.
    """

    slab_bytes: int
    block_sizes: tuple[int, ...]
    bytes_per_page: tuple[int, ...]
    pages_per_slab: tuple[int, ...]
    padding: tuple[float, ...]
    rounding: float

    def __post_init__(self) -> None:
        for page, k in zip(self.bytes_per_page, self.pages_per_slab, strict=True):
            assert page * k == self.slab_bytes, (page, k, self.slab_bytes)

    @property
    def worst_padding(self) -> float:
        return max(self.padding, default=0.0)

    @property
    def worst_waste(self) -> float:
        return self.worst_padding


def _pad_to_quantum(nbytes: int, quantum: int = PAGE_QUANTUM) -> int:
    return -(-nbytes // quantum) * quantum


def _block_candidates(group: Group) -> list[int]:
    """A per_seq group holds one unit per page; a per_token group's block size is free."""
    if group.kind == "per_seq":
        return [1]
    return list(BLOCK_RANGE)


def _fit(groups: list[Group], slab0: int) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    """Per-group (block_size, k) for a candidate `slab0`, or None if some group has no page
    that fits in it.

    `k_g = floor(slab0 / raw page)` is how many of group g's pages a slab holds. The block size
    is chosen to make `slab0 / k_g` as close to the raw page as possible -- that difference is
    the padding step 4 will bake in -- and among block sizes within one percentage point of the
    best the SMALLEST wins, because prefix-cache grain matters more than the last percent.
    """
    blocks: list[int] = []
    ks: list[int] = []
    for group in groups:
        best = None
        for block_size in _block_candidates(group):
            raw = group.bytes_per_block(block_size)
            if raw > slab0:
                continue
            k = slab0 // raw
            # What step 4 will charge, approximated at slab0 (the lcm rounding only grows it).
            pad_frac = (slab0 / k - raw) / (slab0 / k)
            better = best is None or pad_frac < best[0] - 1e-12
            finer = best is not None and pad_frac <= best[0] + 0.01 and block_size < best[1]
            if better or finer:
                best = (pad_frac, block_size, k)
        if best is None:
            return None
        blocks.append(best[1])
        ks.append(best[2])
    return tuple(blocks), tuple(ks)


def _round_to_lcm(slab0: int, ks: tuple[int, ...], align: int = PAGE_ALIGN) -> int:
    """`slab0` rounded up so every `k` divides it AND every resulting page is `align`-aligned.

    A multiple of `lcm(k) * align` is not enough on its own: `slab_bytes / k` must itself be a
    multiple of `align`, which needs `slab_bytes` to be a multiple of `k * align` for each k.
    So the step is `lcm_g(k_g * align)`.
    """
    step = align
    for k in ks:
        step = step // math.gcd(step, k * align) * (k * align)
    return -(-slab0 // step) * step


def choose_block_sizes(
    groups: list[Group],
    quantum: int = PAGE_QUANTUM,
    max_waste: float = MAX_WASTE,
) -> SlabPlan:
    """Pick `slab_bytes` and a block size per group so pages tile a slab EXACTLY.

    Ruling 2026-09-10 (docs/slab-lcm-ladder.md), Jenga invariant (ii). Candidate slabs are the
    raw pages of every group at every block size (option A: the slab is some group's page). For
    each candidate the four steps in `SlabPlan`'s docstring run; padding must clear `max_waste`
    for every group. The smallest slab that clears it wins: slab size is spent only to clear the
    guard, never to shave the last percent, because a bigger slab is a coarser eviction unit.
    Raises naming the worst group when nothing clears it.
    """
    assert groups, "a model with no cache groups has no slab plan"
    candidates = sorted(
        {g.bytes_per_block(bs) for g in groups for bs in _block_candidates(g)}
    )
    best_over = None
    for slab0 in candidates:
        fitted = _fit(groups, slab0)
        if fitted is None:
            continue
        blocks, ks = fitted
        slab_bytes = _round_to_lcm(slab0, ks)
        pages = tuple(slab_bytes // k for k in ks)
        assert all(page % PAGE_ALIGN == 0 for page in pages), (slab_bytes, ks, pages)
        raws = tuple(g.bytes_per_block(bs) for g, bs in zip(groups, blocks, strict=True))
        assert all(p >= r for p, r in zip(pages, raws, strict=True)), (pages, raws)
        padding = tuple((p - r) / p for p, r in zip(pages, raws, strict=True))
        worst = max(padding)
        if worst <= max_waste:
            return SlabPlan(
                slab_bytes=slab_bytes,
                block_sizes=blocks,
                bytes_per_page=pages,
                pages_per_slab=ks,
                padding=padding,
                rounding=(slab_bytes - slab0) / slab0,
            )
        if best_over is None or worst < best_over[0]:
            best_over = (worst, slab_bytes, groups, blocks, padding)
    assert best_over is not None, f"no slab fits every group: {[g.kind for g in groups]}"
    worst, slab_bytes, _, blocks, padding = best_over
    culprit = max(range(len(groups)), key=lambda i: padding[i])
    g = groups[culprit]
    raise ValueError(
        f"no slab size keeps per-page padding under {max_waste:.0%}: best is {worst:.1%} on "
        f"group {culprit} ({g.kind} stride {g.stride}, {g.bytes_per_unit} B/unit) at "
        f"slab_bytes={slab_bytes}, block_size={blocks[culprit]}"
    )
