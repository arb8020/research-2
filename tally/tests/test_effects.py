"""Every branch of effect(): recorded done/failed, intent x {rerun, reconcile, at_most_once}, Ok/Err/Pending/raise/bad."""
import re
from pathlib import Path
from typing import Any

import pytest

from tally import (
    EffectFailed,
    EffectPending,
    Err,
    Ok,
    Pending,
    Step,
    StepCtx,
    at_most_once,
    open_store,
    reconcile,
    rerun,
    start,
)

KEY = "send:1"


class World:
    """Counts calls and replays a scripted outcome per call; "raise" simulates dying mid-flight."""
    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.idem_keys: list[str] = []

    def __call__(self, ctx: StepCtx, payload: str, *, idem_key: str, out: Path) -> Any:
        self.idem_keys.append(idem_key)
        outcome = self.script.pop(0)
        if outcome == "raise": raise RuntimeError("died mid-flight")
        return outcome


def test_ok_is_recorded_and_never_rerun(tmp_path: Path) -> None:
    world = World(Ok({"id": 7}))
    ctx = start(open_store(tmp_path))
    handle = ctx.effect(KEY, world, "hi", on_unknown=rerun)
    assert ctx.load(handle) == {"id": 7}
    again = start(open_store(tmp_path)).effect(KEY, world, "hi", on_unknown=rerun)
    assert again == handle
    assert world.idem_keys == [KEY]  # idem key is the tally key; second call never reached the world
    assert ctx.ran == [KEY]


def test_err_is_recorded_forever_and_replays(tmp_path: Path) -> None:
    world = World(Err("card_declined"))
    ctx = start(open_store(tmp_path))
    with pytest.raises(EffectFailed) as first:
        ctx.effect(KEY, world, "hi", on_unknown=rerun)
    with pytest.raises(EffectFailed) as replay:
        start(open_store(tmp_path)).effect(KEY, world, "hi", on_unknown=rerun)
    assert (replay.value.key, replay.value.error) == (first.value.key, first.value.error) == (KEY, "card_declined")
    assert len(world.idem_keys) == 1


def test_pending_records_nothing_so_next_call_runs(tmp_path: Path) -> None:
    world = World(Pending("rate limited"), Ok(1))
    store = open_store(tmp_path)
    with pytest.raises(EffectPending, match="rate limited"):
        start(store).effect(KEY, world, "hi", on_unknown=at_most_once)
    assert store.effects.get(KEY) is None  # intent cleared: at_most_once never fires for a Pending
    ctx = start(store)
    assert ctx.load(ctx.effect(KEY, world, "hi", on_unknown=at_most_once)) == 1
    assert len(world.idem_keys) == 2


def test_raise_leaves_intent(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    with pytest.raises(RuntimeError, match="mid-flight"):
        start(store).effect(KEY, World("raise"), "hi", on_unknown=rerun)
    row = store.effects.get(KEY)
    assert row is not None
    assert row.state == "intent"
    assert list((tmp_path / "tmp").iterdir()) == []


def test_bad_return_type_is_a_type_error(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match=re.escape("Ok | Err | Pending")):
        start(open_store(tmp_path)).effect(KEY, World({"id": 7}), "hi", on_unknown=rerun)


def _crashed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        start(open_store(tmp_path)).effect(KEY, World("raise"), "hi", on_unknown=rerun)


def test_intent_rerun_calls_fn_again_with_same_idem_key(tmp_path: Path) -> None:
    _crashed(tmp_path)
    world = World(Ok("charged"))
    ctx = start(open_store(tmp_path))
    assert ctx.load(ctx.effect(KEY, world, "hi", on_unknown=rerun)) == "charged"
    assert world.idem_keys == [KEY]


def test_intent_reconcile_found_records_without_running(tmp_path: Path) -> None:
    _crashed(tmp_path)
    world = World()
    ctx = start(open_store(tmp_path))
    handle = ctx.effect(KEY, world, "hi", on_unknown=reconcile(lambda key: Ok({"found": key})))
    assert ctx.load(handle) == {"found": KEY}
    assert world.idem_keys == []
    assert ctx.ran == []


def test_intent_reconcile_not_found_runs(tmp_path: Path) -> None:
    _crashed(tmp_path)
    world = World(Ok("sent"))
    ctx = start(open_store(tmp_path))
    assert ctx.load(ctx.effect(KEY, world, "hi", on_unknown=reconcile(lambda key: None))) == "sent"
    assert world.idem_keys == [KEY]


def test_intent_reconcile_bad_lookup_is_a_type_error(tmp_path: Path) -> None:
    _crashed(tmp_path)
    with pytest.raises(TypeError, match="Ok or None"):
        start(open_store(tmp_path)).effect(KEY, World(), "hi", on_unknown=reconcile(lambda key: True))


def test_intent_at_most_once_fails_forever_without_running(tmp_path: Path) -> None:
    _crashed(tmp_path)
    world = World(Ok("sent"))
    for _attempt in range(2):
        with pytest.raises(EffectFailed, match="unknown after crash"):
            start(open_store(tmp_path)).effect(KEY, world, "hi", on_unknown=at_most_once)
    assert world.idem_keys == []


def test_bad_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="effect key"):
        start(open_store(tmp_path)).effect("../escape", World(Ok(1)), "hi", on_unknown=rerun)


def _step_with_effect(ctx: StepCtx, world: World, *, out: Path) -> Any:
    return ctx.load(ctx.effect(KEY, world, "hi", on_unknown=rerun))


def test_clearing_derivation_cache_leaves_effects(tmp_path: Path) -> None:
    world = World(Ok("charged"))
    store = open_store(tmp_path)
    wrapper = Step(lambda ctx, *, out: _step_with_effect(ctx, world, out=out), label="wrapper")
    first = start(store)
    assert first.load(first.fetch(wrapper)) == "charged"
    store.meta.db.execute("delete from derivations")  # the cache is disposable...
    ctx = start(store)
    assert ctx.load(ctx.fetch(wrapper)) == "charged"
    assert ctx.ran == ["wrapper"]                      # ...the derivation reran, the effect did not
    assert world.idem_keys == [KEY]
