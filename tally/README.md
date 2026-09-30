# tally

A tiny build system + (eventually) durable execution SDK, derived from
"Build Systems à la Carte" (Mokhov, Mitchell, Peyton Jones, ICFP 2018).
Slice 1: derivations (cached pure steps). Slice 2: effects (durable execution). Stdlib only (sqlite3).

## The four core types

- `Handle(key, digest, path)` — pointer to a stored output. `key` = how it was made,
  `digest` = content hash of what it is, `path` = where the bytes live.
- `Fingerprint` — `fp(thing) -> str`. Built-ins: `file_fp`, `ast_fp` (comments/formatting ignored), `value_fp`.
- `KeyFn` — `key(step, args, kwargs) -> Key`. User-owned; must be computable pre-run, sound, stable.
  Built-ins: `keys.recipe` (Nix: Handle args contribute `.key`, no early cutoff) and
  `keys.bytes` (Bazel: Handle args contribute `.digest`, early cutoff).
- `Step(fn, key, code_fp, serialize)` — `fn(step_ctx, *args, out=Path, **kw)` writes into `out` and/or returns a JSON value.

## Who holds what

- `Store(meta, blobs)` — persists across builds; belongs to the build system. `open_store(root)`.
- `Build(active, ran)` — per-build scratch (cycle detection, what executed); thrown away.
- `StepCtx(fetch, load, effect, ran)` — all a step or top-level code ever holds. `start(store)` makes a fresh
  Build and returns its StepCtx. Steps never see Store or Build (paper: tasks get only `fetch`).
- Module-level functions: `fetch(store, build, step, *args)`, `effect(store, build, key, fn, *args, on_unknown)`,
  `digest(store, handle)`, `load(handle)`.

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

Store: sqlite `Meta` (key -> pending | done) + `LocalBlobStore` (tmp dir -> atomic rename to `blobs/<key>`).
Only `done` rows are hits. Debug helpers: `assert_matches_clean(build, store)` (paper Def. 3.1: same as a
build from an empty store; `build` takes a StepCtx) and `key_stability("module:STEP", args)` (keys across processes / hash seeds).

## Effects

Derivations are a cache (sqlite table `derivations`, disposable). Effects are history (table `effects`,
never GC'd): `key -> intent | done(path) | failed(error)`, keyed by a readable user-named string.

```python
ctx.effect(f"charge:{order_id}:{attempt}", charge, order, on_unknown=rerun)
# charge(ctx, order, *, idem_key, out) -> Ok(value) | Err(error) | Pending(reason)
```

- `done` -> recorded handle, never re-run. `failed` -> raise `EffectFailed` (retry = new key).
- none -> write `intent`, then call fn. `Ok` -> record done. `Err` -> record failed, raise.
  `Pending` -> clear intent, raise `EffectPending` (tally never retries itself). fn raises -> intent stays.
- `intent` found = crashed mid-flight, world state unknown -> `on_unknown` decides:
  `rerun` (other side dedupes idem_key), `reconcile(lookup)` (ask the world: `Ok` = happened, `None` = run),
  `at_most_once` (mark failed, raise; a human decides).

Exactly once = tally's intent log + the other side deduping the idempotency key; neither alone is enough.

## Run

```sh
uv run pytest -q
uv run python examples/01_bazel.py   # key=bytes: early cutoff on a comment-only header edit
uv run python examples/02_nix.py     # key=recipe: same steps, no cutoff; bazel vs nix table; one-lookup plan
uv run python examples/03_absurd.py  # effects: order fulfillment with crashes, declines, and three on_unknown policies
```
