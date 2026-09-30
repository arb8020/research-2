"""
Spreadsheets from Mokhov, Mitchell, Peyton Jones, "Build Systems a la Carte" (ICFP 2018).
Input cells are plain args; formula cells are Steps.
"""
from pathlib import Path

from tally import Handle, KeyFn, Step, StepCtx, assert_matches_clean, keys, open_store, start


# section 3.2 (sprsh1, Tasks Applicative):
#   A1: 10   B1: A1 + A2
#   A2: 20   B2: B1 * 2
def b1_sum(ctx: StepCtx, a1: int, a2: int, *, out: Path) -> int:
    return a1 + a2


def b2_double(ctx: StepCtx, b1: Handle, *, out: Path) -> int:
    return ctx.load(b1) * 2


def sprsh1(key: KeyFn) -> tuple[Step, Step]:
    return Step(b1_sum, key=key), Step(b2_double, key=key)


def build1(ctx: StepCtx, key: KeyFn, a1: int, a2: int) -> tuple[Handle, Handle]:
    B1, B2 = sprsh1(key)
    b1 = ctx.fetch(B1, a1, a2)
    return b1, ctx.fetch(B2, b1)


def test_sprsh1_values_and_rebuild_only_dependents(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    ctx = start(store)
    b1, b2 = build1(ctx, keys.recipe, 10, 20)
    assert (ctx.load(b1), ctx.load(b2)) == (30, 60)  # matches the paper's GHCi session in 3.3
    assert ctx.ran == ["b1_sum", "b2_double"]
    build1(ctx, keys.recipe, 10, 20)
    assert ctx.ran == ["b1_sum", "b2_double"]  # nothing new
    b1, b2 = build1(ctx, keys.recipe, 11, 20)
    assert ctx.load(b2) == 62
    assert ctx.ran[2:] == ["b1_sum", "b2_double"]
    assert_matches_clean(lambda c: build1(c, keys.recipe, 11, 20), store)


def test_sprsh1_early_cutoff_bytes_vs_recipe(tmp_path: Path) -> None:
    # A1+A2 still 30 after 10,20 -> 15,15: B1 reruns, B2 is cut off only under bytes keys.
    for key, expect in [(keys.bytes, ["b1_sum"]), (keys.recipe, ["b1_sum", "b2_double"])]:
        store = open_store(tmp_path / key.needs)
        ctx = start(store)
        build1(ctx, key, 10, 20)
        n = len(ctx.ran)
        _, b2 = build1(ctx, key, 15, 15)
        assert ctx.load(b2) == 60
        assert ctx.ran[n:] == expect, key.needs
        assert_matches_clean(lambda c, key=key: build1(c, key, 15, 15), store)


# section 3.5 (sprsh2, Tasks Monad): dependencies depend on C1.
#   A1: 10   B1: IF(C1=1,B2,A2)
#   A2: 20   B2: IF(C1=1,A1,B1)
#   C1: 1
# Statically B1 <-> B2 is a cycle; dynamically it is not.
def b1_if(ctx: StepCtx, a1: int, a2: int, c1: int, *, out: Path) -> int:
    return ctx.load(ctx.fetch(B2, a1, a2, c1)) if c1 == 1 else a2


def b2_if(ctx: StepCtx, a1: int, a2: int, c1: int, *, out: Path) -> int:
    return a1 if c1 == 1 else ctx.load(ctx.fetch(B1, a1, a2, c1))


B1, B2 = Step(b1_if), Step(b2_if)


def test_sprsh2_dynamic_deps_flip_with_c1(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    ctx = start(store)
    assert ctx.load(ctx.fetch(B1, 10, 20, 1)) == 10  # B1 -> B2 -> A1
    assert ctx.ran == ["b2_if", "b1_if"]
    assert ctx.load(ctx.fetch(B1, 10, 20, 2)) == 20  # B1 -> A2, B2 not touched
    assert ctx.ran[2:] == ["b1_if"]
    assert ctx.load(ctx.fetch(B2, 10, 20, 2)) == 20  # B2 -> B1 (cached)
    assert ctx.ran[3:] == ["b2_if"]
    assert_matches_clean(lambda c: (c.fetch(B1, 10, 20, 2), c.fetch(B2, 10, 20, 2)), store)


def test_sprsh2_known_limit_not_minimal(tmp_path: Path) -> None:
    # With C1=2, B1 = A2 does not read A1, yet A1 is an arg so it is in B1's key.
    # Pre-run keys over-approximate dynamic deps (paper 2.2: "minimality" needs recorded traces).
    ctx = start(open_store(tmp_path))
    ctx.fetch(B1, 10, 20, 2)
    ctx.fetch(B1, 99, 20, 2)
    assert ctx.ran == ["b1_if", "b1_if"]
