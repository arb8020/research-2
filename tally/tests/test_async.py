import asyncio
from pathlib import Path
from typing import Any

import pytest

from tally import (
    EffectFailed,
    Handle,
    Ok,
    Step,
    at_most_once,
    derivation_state,
    effect_key,
    effect_row,
    load,
    open_store,
    pool,
    run,
    start,
)

NAME = "trial"
INPUTS = "x"


async def crowd(root: Path, kind: str, outcome: str, callers: int, cancel: str | None) -> tuple[list[str | None], list[Any]]:
    calls: list[str | None] = []
    arrived = 0
    all_in, release = asyncio.Event(), asyncio.Event()
    leader: list[asyncio.Task] = []

    async def trial(ctx: Any, *, out: Path, idem_key: str | None = None) -> Any:
        calls.append(idem_key)
        leader.append(asyncio.current_task())
        await release.wait()
        if outcome == "raise": raise RuntimeError("boom")
        return Ok("v") if kind == "aeffect" else "v"

    ctx = start(open_store(root))

    async def caller() -> Handle:
        nonlocal arrived
        arrived += 1
        if arrived == callers: all_in.set()
        if kind == "aeffect": return await ctx.aeffect(NAME, trial, inputs=INPUTS, on_unknown=at_most_once)
        return await ctx.afetch(Step(trial, label=NAME))

    tasks = [asyncio.create_task(caller()) for _ in range(callers)]
    await all_in.wait()
    cancelled = None
    if cancel == "leader": cancelled = leader[0]
    if cancel == "follower": cancelled = next(task for task in tasks if task is not leader[0])
    if cancelled is not None: cancelled.cancel()
    release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return calls, [result for task, result in zip(tasks, results, strict=True) if task is not cancelled]


def describe(result: Any) -> Any:
    return load(result) if isinstance(result, Handle) else type(result).__name__


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
    calls, results = asyncio.run(crowd(root, kind, outcome, callers, cancel))
    assert len(calls) == 1, (kind, outcome, cancel, calls)
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
        ("aeffect", "ok", "follower", ["v"] * 3, ("done", False)),
        ("afetch", "ok", "follower", ["v"] * 3, ("done", False)),
        ("aeffect", "ok", "leader", ["CancelledError"] * 3, ("intent", True)),
        ("afetch", "ok", "leader", ["CancelledError"] * 3, ("pending", False)),
    ]
    for index, (kind, outcome, cancel, seen, state) in enumerate(table):
        check_crowd(tmp_path / str(index), kind, outcome, cancel, seen, state)


def test_cancelled_leader_leaves_unknown_for_next_run(tmp_path: Path) -> None:
    table = [
        ("aeffect", 0, ["EffectFailed"], ("failed", False)),
        ("afetch", 1, ["v"], ("done", False)),
    ]
    for kind, calls_next, seen_next, state_next in table:
        root = tmp_path / kind
        asyncio.run(crowd(root, kind, "ok", 2, "leader"))
        calls, results = asyncio.run(crowd(root, kind, "ok", 1, None))
        assert (len(calls), [describe(result) for result in results], record(root, kind)) == (calls_next, seen_next, state_next), kind
        if kind == "aeffect": assert isinstance(results[0], EffectFailed) and results[0].error == "unknown after crash"


async def limited(root: Path, limit: int, need: int, tasks: int) -> tuple[int, list[Any]]:
    in_use = peak = entered = 0
    waves = [asyncio.Event()]

    async def trial(ctx: Any, index: int, *, idem_key: str, out: Path) -> Ok[int]:
        nonlocal in_use, peak, entered
        entered += 1
        in_use += need
        peak = max(peak, in_use)
        wave = waves[-1]
        if limit - in_use < need or entered == tasks:
            asyncio.get_running_loop().call_soon(wave.set)
            waves.append(asyncio.Event())
        await wave.wait()
        in_use -= need
        return Ok(index)

    ctx, slots = start(open_store(root)), pool({"docker": limit})
    handles = await asyncio.gather(*(
        run(ctx, slots, f"t{index}", trial, index, needs={"docker": need}, inputs=index, on_unknown=at_most_once)
        for index in range(tasks)
    ))
    return peak, [load(handle) for handle in handles]


def check_limits(root: Path, limit: int, need: int, tasks: int, peak: int) -> None:
    assert asyncio.run(limited(root, limit, need, tasks)) == (peak, list(range(tasks))), (limit, need, tasks)


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
        await run(start(open_store(tmp_path)), pool({"docker": 1}), "t", lambda: None, needs=needs, inputs=0, on_unknown=at_most_once)

    for needs in ({"docker": 2}, {"gpu": 1}):
        with pytest.raises(ValueError, match="needs exceed limits"):
            asyncio.run(attempt(needs))
