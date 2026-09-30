"""Paged KV allocation: ONE flat byte arena, carved into per-member strided views.

Cache memory is one slab pool (docs/kv-groups.md, docs/slab-lcm-ladder.md): a single
`[num_slabs * slab_bytes]` uint8 tensor. Group `g` owns pages of `bytes_per_page[g]` inside it,
and member `m` of that group is a strided view

    [num_pages_g, block_size_g, *unit_shape_m]

whose page stride is `bytes_per_page[g]` and whose offset is the member's byte offset in a unit.
Nothing is copied and nothing is allocated per group: the whole point of the slab pool is that a
page of one group and a page of another are the same bytes, handed out by the core.

Two invariants make the `as_strided` view legal (ruling 2026-09-10):

  (i)  page ids are GROUP-LOCAL -- `id = slab * pages_per_slab[g] + index + 1` -- so the byte
       offset of group g's page `id` is `(id - 1) * bytes_per_page[g]`, affine in `id`, which
       is exactly what `as_strided` can express. With one shared id space it was not affine.
  (ii) a slab is tiled exactly, `pages_per_slab[g] * bytes_per_page[g] == slab_bytes`, so a
       group's pages run contiguously across the whole arena with no per-slab gap to skip.

A group is `KV = tuple[Tensor, ...]`, never a stacked [n_members, ...] array -- on the XLA path
slicing a member out of a stack copied the whole cache every step.

THE NULL PAGE, AND THE LAYOUT. Page 0 is the null page of every group: the core never hands it
out, and models point pad slots and slid-out window rows at it, so it must be REAL, WRITABLE
memory that nothing reads back (`c_api.zig`: "the model allocates [num_blocks] and leaves 0
unused"). So each group gets a contiguous region of `1 + num_slabs * pages_per_slab[g]` pages
and its view is simply `as_strided` over that region from its start: row 0 IS the null page,
row `id` is the page the core calls `id`, and the whole map stays the single affine expression
`base_g + id * bytes_per_page[g]` that `as_strided` can express.

Group regions are laid end to end in one arena. Every group's null page is its own page, so two
groups writing pad rows in the same step never race over one shared buffer.
"""

from __future__ import annotations

import torch
from kelpie_engine.sdk.engine import EngineConfig, GroupSpec

from kelpie_models.sdk.groups import (
    AttnSpec,
    Group,
    KVLayout,
    SlabPlan,
    choose_block_sizes,
    derive_groups,
    reference_kv_layout,
)

KV = tuple[torch.Tensor, ...]


def plan_of(specs: list[AttnSpec], itemsize: int) -> tuple[list[Group], SlabPlan]:
    """The groups a model's `attn_specs` derive, and the slab plan that sizes them."""
    groups, _ = derive_groups(specs, itemsize=itemsize)
    return groups, choose_block_sizes(groups)


def groups_of(specs: list[AttnSpec], itemsize: int) -> tuple[GroupSpec, ...]:
    """The cache groups the core must be told about, in `derive_groups` order -- the same order
    `alloc_kv` allocates in, so group g of the plan indexes group g of the kv. Each carries its
    OWN block size now (the slab plan picks one per group), not a single global constant."""
    groups, plan = plan_of(specs, itemsize)
    return tuple(
        GroupSpec(g.kind, bs, g.window, g.cacheable, g.stride)
        for g, bs in zip(groups, plan.block_sizes, strict=True)
    )


def bytes_per_page_of(specs: list[AttnSpec], itemsize: int) -> tuple[int, ...]:
    """The slab plan's per-group page size, for `EngineConfig.bytes_per_page`."""
    return plan_of(specs, itemsize)[1].bytes_per_page


def alloc_kv(
    specs: list[AttnSpec],
    cfg: EngineConfig,
    device: torch.device | str,
    dtype: torch.dtype,
    *,
    group_slice: slice | None = None,
) -> list[KV]:
    """One tuple of member views per group, all carved out of one arena.

    `cfg` must be the LIVE config (`Engine.config` after `kelpie_get_config`): `slab_bytes` and
    `num_slabs` are resolved by the core, never recomputed here, so Python and Zig can never
    disagree about how big the arena is or how many pages a group has.

    `group_slice`: when the engine has groups from multiple models (target + drafter), pass the
    slice of `cfg.groups` / `cfg.bytes_per_page` that THIS model owns. `alloc_kv` then uses the
    COMBINED slab plan (from cfg) but allocates only the sliced groups' regions. The slab_bytes
    and pages_per_slab come from the combined plan via cfg, so the drafter's arena tiles
    correctly even though its groups alone would compute a different slab plan.
    """
    if group_slice is None:
        groups, plan = plan_of(specs, dtype.itemsize)
        assert len(groups) == len(cfg.groups), (len(groups), len(cfg.groups))
        assert plan.bytes_per_page == tuple(cfg.bytes_per_page), (
            plan.bytes_per_page,
            cfg.bytes_per_page,
        )
        assert cfg.slab_bytes == plan.slab_bytes, (cfg.slab_bytes, plan.slab_bytes)
        block_sizes, bpp, pages_per_slab = plan.block_sizes, plan.bytes_per_page, plan.pages_per_slab
    else:
        # This model's groups alone would choose a different slab plan, so there is nothing to
        # recompute here: the caller cross-checks the COMBINED plan against cfg (run._assemble).
        groups, _ = derive_groups(specs, itemsize=dtype.itemsize)
        cfg_groups = cfg.groups[group_slice]
        bpp = tuple(cfg.bytes_per_page)[group_slice]
        assert len(groups) == len(cfg_groups), (len(groups), len(cfg_groups))
        block_sizes = tuple(g.block_size for g in cfg_groups)
        pages_per_slab = tuple(cfg.slab_bytes // p for p in bpp)
        assert all(k * p == cfg.slab_bytes for k, p in zip(pages_per_slab, bpp)), (
            "slab not tiled exactly", cfg.slab_bytes, bpp)
    assert cfg.num_slabs >= 1, cfg.num_slabs

    # One region per group: 1 null page + num_slabs * pages_per_slab[g] real ones, laid end to
    # end (see the module docstring). num_slabs * slab_bytes is the pool proper; the per-group
    # null pages are the only thing beyond it.
    pages_per_group = [cfg.num_slabs * k + 1 for k in pages_per_slab]
    sizes = [n * page for n, page in zip(pages_per_group, bpp, strict=True)]
    arena = alloc_arena(cfg.num_slabs, cfg.slab_bytes, device, total_bytes=sum(sizes))
    out = []
    at = 0
    for group, block_size, page, n_pages, size in zip(
        groups, block_sizes, bpp, pages_per_group, sizes, strict=True
    ):
        out.append(
            group_views(
                arena[at : at + size],
                num_pages=n_pages,
                block_size=block_size,
                bytes_per_page=page,
                layout=reference_kv_layout(group, dtype.itemsize),
                member_offsets=group.member_byte_offsets(),
                dtype=dtype,
            )
        )
        at += size
    assert at == arena.numel(), (at, arena.numel())
    assert len(out) == len(groups)
    return out


def alloc_arena(
    num_slabs: int,
    slab_bytes: int,
    device: torch.device | str,
    total_bytes: int | None = None,
) -> torch.Tensor:
    """The one byte arena every group's pages are carved out of.

    `total_bytes` is the whole allocation including each group's null page; it defaults to the
    pool proper, `num_slabs * slab_bytes`.
    """
    assert num_slabs >= 1 and slab_bytes > 0, (num_slabs, slab_bytes)
    want = num_slabs * slab_bytes if total_bytes is None else total_bytes
    assert want >= num_slabs * slab_bytes, (want, num_slabs, slab_bytes)
    return torch.zeros(want, dtype=torch.uint8, device=device)


def group_views(  # noqa: PLR0913, PLR0917
    arena: torch.Tensor,
    num_pages: int,
    block_size: int,
    bytes_per_page: int,
    layout: KVLayout,
    member_offsets: list[int],
    dtype: torch.dtype,
) -> KV:
    """Views of one group's members inside the arena.

    Member `m`'s unit occupies `[offset_m, offset_m + bytes_m)` of every unit, a unit is one row
    of a page, and a page is `bytes_per_page` bytes. `as_strided` expresses exactly that: page
    stride `bytes_per_page`, row stride `sum(member bytes)`, all in elements of `dtype`.
    """
    assert arena.dtype == torch.uint8, arena.dtype
    assert num_pages >= MIN_PAGES, num_pages  # page 0 is the null page
    rows_of = layout.rows
    itemsize = torch.empty(0, dtype=dtype).element_size()
    assert bytes_per_page % itemsize == 0, (bytes_per_page, itemsize)
    bytes_per_unit = sum(_row_bytes(rows, itemsize) for rows in rows_of)
    assert bytes_per_unit * block_size <= bytes_per_page, (
        bytes_per_unit,
        block_size,
        bytes_per_page,
    )
    assert num_pages * bytes_per_page <= arena.numel(), (
        num_pages,
        bytes_per_page,
        arena.numel(),
    )
    typed = arena.view(dtype)

    out = []
    for rows, offset in zip(rows_of, member_offsets, strict=True):
        assert offset % itemsize == 0, (offset, itemsize)
        row_strides = _row_strides(rows)
        page_s = bytes_per_page // itemsize
        unit_s = bytes_per_unit // itemsize
        if len(rows) >= 1 and rows[0] == 2:
            # KV member: layout is [pages, 2, block_size, heads, dim] (FlashInfer standard).
            # In memory a unit (one block row) is [2, heads, dim] contiguous, so:
            #   dim 0 (pages):      stride = page_s
            #   dim 1 (KV member):  stride = heads * dim  (skip one K or V slot)
            #   dim 2 (block_size): stride = unit_s        (next row of the block)
            #   dims 3+ (heads, dim): row-major within one K or V slot
            kv_rest = rows[1:]
            kv_rest_strides = _row_strides(kv_rest)
            kv_member_stride = 1
            for d in kv_rest:
                kv_member_stride *= d  # = heads * dim
            size = (num_pages, 2, block_size, *kv_rest)
            stride = (page_s, kv_member_stride, unit_s, *kv_rest_strides)
        else:
            size = (num_pages, block_size, *rows)
            stride = (page_s, unit_s, *row_strides)
        # as_strided's storage_offset is ABSOLUTE in the storage, not relative to `arena` (a slice
        # of the whole arena): without the slice's own offset every group's view started at the
        # arena's first byte, and groups of different page sizes aliased each other's pages.
        out.append(typed.as_strided(size, stride, typed.storage_offset() + offset // itemsize))
    assert len(out) == len(rows_of)
    return tuple(out)


# Page 0 is the null page, so a group needs at least one real page beyond it.
MIN_PAGES = 2


def _row_bytes(rows: tuple[int, ...], itemsize: int) -> int:
    n = 1
    for d in rows:
        n *= d
    return n * itemsize


def _row_strides(rows: tuple[int, ...]) -> tuple[int, ...]:
    """Row-major strides for one unit's shape."""
    out = []
    acc = 1
    for d in reversed(rows):
        out.append(acc)
        acc *= d
    return tuple(reversed(out))


def kv_bytes(kv: list[KV]) -> int:
    return sum(t.numel() * t.element_size() for group in kv for t in group)
