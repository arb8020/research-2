# tally

A tiny build system + (eventually) durable execution SDK, derived from
"Build Systems à la Carte" (Mokhov, Mitchell, Peyton Jones, ICFP 2018).
Slice 1: derivations (cached pure steps). Slice 2: effects (durable execution). Slice 3: async, resource-limited
runner, invalidate. Stdlib only (sqlite3, asyncio).

## The four core types

- `Handle(key, digest, path)` — pointer to a stored output. `key` = how it was made,
  `digest` = content hash of what it is, `path` = where the bytes live.
- `Fingerprint` — `fp(thing) -> str`. Built-ins: `file_fp`, `ast_fp` (comments/formatting ignored), `value_fp`.
- `KeyFn` — `key(step, args, kwargs) -> Key`. User-owned; must be computable pre-run, sound, stable.
  Built-ins: `keys.recipe` (Nix: Handle args contribute `.key`, no early cutoff) and
  `keys.bytes` (Bazel: Handle args contribute `.digest`, early cutoff).
- `Step(fn, key, code_fp, serialize)` — `fn(step_ctx, *args, out=Path, **kw)` writes into `out` and/or returns a JSON value.

## Who holds what

- `Store(db, root, inflight)` — persists across builds; belongs to the build system. `open_store(root)`.
- `Build(chain, ran)` — per-build scratch (this call chain, for cycles and fetch edges; what executed); thrown away.
- `StepCtx(fetch, afetch, load, effect, aeffect, ran)` — all a step or top-level code ever holds. `start(store)` makes
  a fresh Build and returns its StepCtx. Steps never see Store or Build (paper: tasks get only `fetch`).
- Module-level functions: `fetch`/`afetch(store, build, step, *args)`, `effect`/`aeffect(store, build, name, fn, *args,
  inputs, on_unknown)`, `digest(store, handle)`, `load(handle)`, `invalidate(store, keys, downstream=True)`.

```python
from tally import open_store, start, step

@step
def fib(ctx, n, *, out):
    if n < 2: return n
    return ctx.load(ctx.fetch(fib, n - 1)) + ctx.load(ctx.fetch(fib, n - 2))

store = open_store(Path("store"))
ctx = start(store)
ctx.load(ctx.fetch(fib, 10))   # 55; ctx.ran lists what actually executed
```

Store: sqlite `meta.sqlite` holds state (schema version, `derivations` key -> pending | done, `effects`, fetch `edges`);
the filesystem holds bytes (derivations: tmp dir -> atomic rename to `blobs/<key>`; effects: `effects/<key>/`).
Only `done` rows are hits. Debug helpers: `assert_matches_clean(build, store)` (paper Def. 3.1: same as a
build from an empty store; `build` takes a StepCtx) and `key_stability("module:STEP", args)` (keys across processes / hash seeds).

## Effects

Derivations are a cache (sqlite table `derivations`, disposable). Effects are history (table `effects`,
never GC'd): `key -> intent | done(outcome) | failed(outcome)` plus input hash, inputs and timestamps.
key = `<name>@<sha(inputs)[:8]>`: a readable name plus a hash of the declared inputs (Handles count by digest).
Different inputs = different key = a new run; old results stay. An attempt index in the name reruns on purpose.

```python
ctx.effect(f"charge:{order_id}:{attempt}", charge, order, inputs=order, on_unknown=rerun)
# charge(ctx, order, *, idem_key, out) -> Ok(value) | Err(error) | Pending(reason)
```

Bytes: fn writes into `out = effects/<key>.pending/`; on Ok/Err tally writes `value.json` (Ok) and `effect.json`
(a one-time copy of the row) and renames it to `effects/<key>/`, immutable after that.

- `done` -> recorded handle, never re-run. `failed` -> raise `EffectFailed` (retry = new key).
- none -> write `intent`, then call fn. `Ok` -> record done. `Err` -> record failed, raise.
  `Pending` -> clear intent and `.pending`, raise `EffectPending` (tally never retries itself). fn raises -> intent and `.pending` stay.
- `intent` found = crashed mid-flight, world state unknown -> `on_unknown` decides:
  `rerun` (other side dedupes idem_key; fn gets the old `.pending` dir back), `reconcile(lookup)` (ask the world,
  `lookup(key, out)` may read `.pending`: `Ok` = happened, `None` = run), `at_most_once` (mark failed, raise; a human decides).

## Async, limits, invalidate

- `afetch` / `aeffect`: same as `fetch` / `effect`, awaiting an async fn. Concurrent calls with one key in one
  process run once (`store.inflight`); the rest await the leader's result or exception.
- `pool(limits)`, `hold(pool, needs)`, `run(ctx, pool, name, fn, *args, needs, inputs, on_unknown)`: `run` is
  `hold` around `ctx.aeffect`, nothing more, so dropping down to own the control flow is always possible.
- `invalidate(store, keys, downstream=True)`: moves effect dirs and derivation blobs to `invalidated/<ts>/` with a
  `manifest.json` (the rows), then drops the rows. `downstream` follows the `edges` table: consumer -> every Handle
  it received, and caller -> everything it fetched. `downstream_of(store, keys)` lists that set without moving anything.

Exactly once = tally's intent log + the other side deduping the idempotency key; neither alone is enough.

## Run

```sh
uv run pytest -q                     # if uv_build refuses the flat module: uv run --no-project --with pytest python -m pytest -q
uv run python examples/01_bazel.py   # key=bytes: early cutoff on a comment-only header edit
uv run python examples/02_nix.py     # key=recipe: same steps, no cutoff; bazel vs nix table; one-lookup plan
uv run python examples/03_absurd.py  # effects: order fulfillment with crashes, declines, and three on_unknown policies
uv run python examples/04_agent_trials.py  # async trials under limits, gated rungs, reuse, invalidate one task
```
