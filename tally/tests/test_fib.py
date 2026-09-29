from pathlib import Path

import pytest

from tally import Ctx, Step, assert_matches_clean, open_ctx, step


@step
def fib(ctx: Ctx, n: int, *, out: Path) -> int:
    if n < 2: return n
    return ctx.load(ctx.fetch(fib, n - 1)) + ctx.load(ctx.fetch(fib, n - 2))


def test_memoized_within_one_build(tmp_path: Path) -> None:
    ctx = open_ctx(tmp_path)
    assert ctx.load(ctx.fetch(fib, 10)) == 55
    assert ctx.ran == ["fib"] * 11  # fib(0..10) once each, not exponential


def test_rerun_is_all_hits_and_extends_incrementally(tmp_path: Path) -> None:
    ctx = open_ctx(tmp_path)
    first = ctx.fetch(fib, 10)
    ctx2 = open_ctx(tmp_path)  # new process, same store
    assert ctx2.fetch(fib, 10) == first
    assert ctx2.ran == []
    assert ctx2.load(ctx2.fetch(fib, 12)) == 144
    assert ctx2.ran == ["fib", "fib"]  # only fib(11), fib(12)
    assert_matches_clean(lambda c: c.fetch(fib, 12), ctx2)


def test_self_fetch_is_a_cycle(tmp_path: Path) -> None:
    def loop(ctx: Ctx, n: int, *, out: Path) -> int:
        return ctx.load(ctx.fetch(LOOP, n))
    LOOP = Step(loop)
    ctx = open_ctx(tmp_path)
    with pytest.raises(AssertionError, match="cycle"):
        ctx.fetch(LOOP, 1)
