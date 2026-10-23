from pathlib import Path
from typing import Any

import anyio
import pytest

from tally import (
    EffectFailed,
    Handle,
    Ok,
    Step,
    StepCtx,
    at_most_once,
    derivation_state,
    effect_key,
    effect_row,
    load,
    open_async_store,
    open_store,
    pool,
    run,
    start,
)

NAME = "trial"
INPUTS = "x"


class StoreAborted(Exception):
    pass


async def crowd(root: Path, kind: str, outcome: str, callers: int, cancel: str | None) -> tuple[list[str | None], list[Any]]:
    calls: list[str | None] = []
    arrived = 0
    results: list[Any] = [None] * callers
    scopes = [anyio.CancelScope() for _ in range(callers)]
    left = [anyio.Event() for _ in range(callers)]
    all_in, started, release = anyio.Event(), anyio.Event(), anyio.Event()

    async def trial(ctx: Any, *, out: Path, idem_key: str | None = None) -> Any:
        calls.append(idem_key)
        started.set()
        await release.wait()
        if outcome == "raise": raise RuntimeError("boom")
        return Ok("v") if kind == "aeffect" else "v"

    async def caller(index: int, ctx: StepCtx) -> None:
        nonlocal arrived
        arrived += 1
        if arrived == callers: all_in.set()
        with scopes[index]:
            try:
                if kind == "aeffect": results[index] = await ctx.aeffect(NAME, trial, inputs=INPUTS, on_unknown=at_most_once)
                else: results[index] = await ctx.afetch(Step(trial, label=NAME))
            except Exception as error:
                results[index] = error
        if scopes[index].cancelled_caught: results[index] = "cancelled"
        left[index].set()

    cancelled = {"one": scopes[:1], "all": scopes}.get(cancel or "", [])
    async with anyio.create_task_group() as outside:
        try:
            async with open_async_store(root) as live:
                store = open_store(root) if cancel == "sync" else live
                for index in range(callers): outside.start_soon(caller, index, start(store))
                await all_in.wait()
                if cancel not in (None, "sync"): await started.wait()
                if cancel == "store": raise StoreAborted
                for scope in cancelled: scope.cancel()
                for index in range(len(cancelled)): await left[index].wait()
                release.set()
        except* StoreAborted:
            pass
    return calls, results


def describe(result: Any) -> Any:
    if isinstance(result, Handle): return load(result)
    return result if isinstance(result, str) else type(result).__name__


def record(root: Path, kind: str) -> tuple[str | None, bool]:
    store = open_store(root)
    if kind == "aeffect":
        key = effect_key(NAME, INPUTS)
        row = effect_row(store, key)
        return (row and row.state), (root / "effects" / f"{key}.pending").is_dir()
    step = Step(lambda: None, label=NAME)
    return derivation_state(store, step.key(step, (), {})), False


def check_crowd(root: Path, kind: str, outcome: str, cancel: str | None, seen: list[Any], state: tuple[str | None, bool]) -> None:
    callers = 4
    calls, results = anyio.run(crowd, root, kind, outcome, callers, cancel)
    assert len(calls) == (cancel != "sync"), (kind, outcome, cancel, calls)
    assert [describe(result) for result in results] == seen, (kind, outcome, cancel, results)
    if cancel is None:
        assert len({result if isinstance(result, Handle) else id(result) for result in results}) == 1, results
    assert record(root, kind) == state, (kind, outcome, cancel)


def test_concurrent_same_key_runs_once(tmp_path: Path) -> None:
    table = [
        ("aeffect", "ok", None, ["v"] * 4, ("done", False)),
        ("aeffect", "raise", None, ["RuntimeError"] * 4, ("intent", True)),
        ("afetch", "ok", None, ["v"] * 4, ("done", False)),
        ("afetch", "raise", None, ["RuntimeError"] * 4, ("pending", False)),
        ("aeffect", "ok", "one", ["cancelled"] + ["v"] * 3, ("done", False)),
        ("afetch", "ok", "one", ["cancelled"] + ["v"] * 3, ("done", False)),
        ("aeffect", "ok", "all", ["cancelled"] * 4, ("intent", True)),
        ("afetch", "ok", "all", ["cancelled"] * 4, ("pending", False)),
        ("aeffect", "ok", "store", ["StoreClosed"] * 4, ("intent", True)),
        ("afetch", "ok", "store", ["StoreClosed"] * 4, ("pending", False)),
        ("aeffect", "ok", "sync", ["RuntimeError"] * 4, (None, False)),
        ("afetch", "ok", "sync", ["RuntimeError"] * 4, (None, False)),
    ]
    for index, (kind, outcome, cancel, seen, state) in enumerate(table):
        check_crowd(tmp_path / str(index), kind, outcome, cancel, seen, state)


def test_cancelled_run_leaves_unknown_for_next_run(tmp_path: Path) -> None:
    table = [
        ("aeffect", "all", 0, ["EffectFailed"], ("failed", False)),
        ("aeffect", "store", 0, ["EffectFailed"], ("failed", False)),
        ("afetch", "all", 1, ["v"], ("done", False)),
        ("afetch", "store", 1, ["v"], ("done", False)),
    ]
    for kind, cancel, calls_next, seen_next, state_next in table:
        root = tmp_path / f"{kind}-{cancel}"
        anyio.run(crowd, root, kind, "ok", 2, cancel)
        calls, results = anyio.run(crowd, root, kind, "ok", 1, None)
        assert (len(calls), [describe(result) for result in results], record(root, kind)) == (calls_next, seen_next, state_next), (kind, cancel)
        if kind == "aeffect": assert isinstance(results[0], EffectFailed) and results[0].error == "unknown after crash"


async def rejoin(root: Path, kind: str) -> tuple[int, int, list[Any]]:
    entered = inside = peak = 0
    results: list[Any] = [None, None]
    scope = anyio.CancelScope()
    started, unwinding, unwind, arriving, left, late = (anyio.Event() for _ in range(6))

    async def trial(ctx: Any, *, out: Path, idem_key: str | None = None) -> Any:
        nonlocal entered, inside, peak
        entered += 1
        inside += 1
        peak = max(peak, inside)
        try:
            if entered == 1:
                started.set()
                try:
                    await anyio.Event().wait()
                except anyio.get_cancelled_exc_class():
                    unwinding.set()
                    with anyio.CancelScope(shield=True): await unwind.wait()
                    raise
            return Ok("v") if kind == "aeffect" else "v"
        finally:
            inside -= 1

    async def call(ctx: StepCtx) -> Any:
        try:
            if kind == "aeffect": return await ctx.aeffect(NAME, trial, inputs=INPUTS, on_unknown=at_most_once)
            return await ctx.afetch(Step(trial, label=NAME))
        except Exception as error:
            return error

    async def first(ctx: StepCtx) -> None:
        with scope: results[0] = await call(ctx)
        if scope.cancelled_caught: results[0] = "cancelled"
        left.set()

    async def second(ctx: StepCtx) -> None:
        arriving.set()
        results[1] = await call(ctx)
        late.set()

    async with open_async_store(root) as store, anyio.create_task_group() as group:
        group.start_soon(first, start(store))
        await started.wait()
        scope.cancel()
        await left.wait()
        await unwinding.wait()
        group.start_soon(second, start(store))
        await arriving.wait()
        unwind.set()
        await late.wait()
    return entered, peak, results


def test_caller_arriving_while_cancelled_run_unwinds_waits_then_replans(tmp_path: Path) -> None:
    table = [
        ("aeffect", 1, ["cancelled", "EffectFailed"], ("failed", False)),
        ("afetch", 2, ["cancelled", "v"], ("done", False)),
    ]
    for kind, entered, seen, state in table:
        root = tmp_path / kind
        calls, peak, results = anyio.run(rejoin, root, kind)
        assert (calls, peak, [describe(result) for result in results], record(root, kind)) == (entered, 1, seen, state), kind
        if kind == "aeffect": assert results[1].error == "unknown after crash"


async def limited(root: Path, limit: int, need: int, tasks: int) -> tuple[int, list[Any]]:
    in_use = peak = entered = 0
    waves = [anyio.Event()]

    async def trial(ctx: Any, index: int, *, idem_key: str, out: Path) -> Ok[int]:
        nonlocal in_use, peak, entered
        entered += 1
        in_use += need
        peak = max(peak, in_use)
        wave = waves[-1]
        if limit - in_use < need or entered == tasks:
            wave.set()
            waves.append(anyio.Event())
        await wave.wait()
        in_use -= need
        return Ok(index)

    slots = pool({"docker": limit})
    handles: dict[int, Handle] = {}

    async def one(ctx: StepCtx, index: int) -> None:
        handles[index] = await run(ctx, slots, f"t{index}", trial, index, needs={"docker": need}, inputs=index, on_unknown=at_most_once)

    async with open_async_store(root) as store, anyio.create_task_group() as group:
        for index in range(tasks): group.start_soon(one, start(store), index)
    return peak, [load(handles[index]) for index in range(tasks)]


def check_limits(root: Path, limit: int, need: int, tasks: int, peak: int) -> None:
    assert anyio.run(limited, root, limit, need, tasks) == (peak, list(range(tasks))), (limit, need, tasks)


def test_run_never_exceeds_limits_and_fills_them(tmp_path: Path) -> None:
    table = [
        (3, 1, 7, 3),
        (4, 2, 5, 4),
        (5, 2, 5, 4),
        (1, 1, 3, 1),
    ]
    for index, (limit, need, tasks, peak) in enumerate(table):
        check_limits(tmp_path / str(index), limit, need, tasks, peak)


def test_run_rejects_needs_over_limits(tmp_path: Path) -> None:
    async def attempt(needs: dict[str, int]) -> None:
        async with open_async_store(tmp_path) as store:
            await run(start(store), pool({"docker": 1}), "t", lambda: None, needs=needs, inputs=0, on_unknown=at_most_once)

    for needs in ({"docker": 2}, {"gpu": 1}):
        with pytest.RaisesGroup(pytest.RaisesExc(ValueError, match="needs exceed limits")):
            anyio.run(attempt, needs)
