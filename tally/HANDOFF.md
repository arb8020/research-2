# tally handoff (2026-09-30)

Paused until there's a real build-system need. Branch `tally/slice-1`, worktree `research-2/worktrees/tally`.

## State
- `tally.py`: one flat module, ~870 lines. 33 tests pass; 4 examples pass (`01_bazel`, `02_nix`, `03_absurd`, `04_agent_trials`).
- Derivations (cached, key = user-owned `KeyFn(needs, fn)`, `keys.recipe` = Nix, `keys.bytes` = Bazel).
- Effects (recorded history: intent log, `Ok/Err/Pending`, raise = unknown, `rerun | reconcile | at_most_once`).
- Steps and top-level code hold a `StepCtx(fetch, load, effect, ran)`; `Store` never reaches steps.

## Slice 3 (branch `tally/slice-3`, 2026-10-23)
- Done: `Meta` / `Effects` / `LocalBlobStore` collapsed into `Store(db, root)` + plain functions. Cost: no backend
  swap point until a second backend (e.g. Modal volumes, which can't rename) actually exists.
- Done: effect keys `name@hash8`, effect bytes in `effects/<key>/` (via `.pending`, `effect.json` at commit),
  `afetch`/`aeffect` with in-process dedupe, `pool`/`hold`/`run`, `invalidate` + fetch edges, `04_agent_trials`.

## Open
- Cross-process: a live intent row from another process looks like a crash (no lease / owner / heartbeat yet).
- Cut candidates (ask first): `key_stability` subprocess check, `ast_fp`, `@step` sugar, `Serializer`, policy classes.
- KeyFn `needs` is all-or-nothing per KeyFn (TODO in docstring).
- Dynamic-deps precision (paper sec 3.5 sprsh2) needs verifying traces; known limit, marked in tests.
- Parked: live sandboxes as outputs (loom), worker loop that auto-resumes tasks, hermeticity.

## Next candidates (short-term use)
- Slice 3 as an experiment runner: config sweep -> train (epochs as steps) -> eval with LLM samples as effects,
  replay divergence detection.
- kelpie integration: per-op kernel builds as derivations. Known bug to fix via key: GPU arch/toolchain are
  recorded "for provenance, NOT the cache key" (kelpie-models/kelpie_models/sdk/run.py:80-84).
