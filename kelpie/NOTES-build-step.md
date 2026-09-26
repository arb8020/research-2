# NOTES: build step (branch build/resolve-at-warm)

Working notes, not a design doc: the code is the source of truth. Judgement calls, uncertainties
and papercuts from implementing the six approved decisions.

## Judgement calls

- **Synthetic plans come from the core.** `kelpie_synthetic_plan` (Zig) fills n real entries whose
  rows are inert by value (scratch slot on null block 0, ZERO/SCRATCH state, emits 0), then runs
  the same `padPlan` + `stepShape` a real plan runs. The Python `plan.synthetic()` was a second
  writer of pad values and had already drifted (pad slot 0 instead of the scratch slot, a
  query_start_loc padPlan never writes). Deleted.
- **User-facing top_k** (user decision): HTTP `top_k` (absent / -1 = off) -> `Engine.submit(top_k=)`
  -> `kelpie_submit_top_k` (new export; wire version 2 carries it to followers) -> request -> plan
  `top_ks` -> the sampler keeps tokens >= the row's k-th value (ties at the k-th kept). Validated
  at submit (0 <= top_k <= vocab_size). The T=0 rule overrides it (T < eps -> T=1, top_k=1).
- **Pads are T=1, top_k=1** (the rewritten greedy form), so all_greedy holds over the padded width.
- **decide samples row 0 only; extra rows are argmax.** Drafts accept greedily and T>0 with extras
  is refused at submit, so sampling the extra rows would buy nothing and cost philox over
  R x (1+K) x V per step (a DFlash slowdown). Rejection sampling is a TODO.
- **Switches are device bools selected with `torch.where`.** Eagerly both sides run -- the same
  work the unswitched sampler did (it already computed the gumbel draw for greedy rows). The
  saving arrives with conditional-node capture (TODO in ops/sample.py).
- **`enumerate_steps(config)` takes no model.** Every model fact that sets a shape (max_seq_len,
  max_extra, batch limits) is already in `EngineConfig` via `from_model`.
- **decode_extra is keyed by TOKEN bucket (user decision 2a)** and warmed at every bucket from
  2 up to bucket(min(max_batch_tokens, max_batch_reqs x (1+K))), so a degraded plan (some entries
  without extra rows) lands on a warmed bucket. Synthetic splits prefer K extras per entry; buckets
  below 1+K use fewer (reachable for a caller asking fewer; DFlash, which always asks K, warms its
  target alone there). Warmed, not captured (its only user runs the bare Step).
- **Unwarmed shapes raise.** `Step.warmed` is set after freeze; a plan whose (family, bucket) is
  not in it raises BuildError (e.g. a batch limit raised with engine.set after build).
- **all_greedy / max_top_k are host values** read off the plan's numpy arrays (no device sync),
  so an all-greedy batch (every DFlash step, every greedy decode) draws no random number. This
  replaces the torch.where form of all_greedy; apply_mask stays a device bool.
- **toy_hybrid** (a host-loop oracle) skips entries whose rows are all on the null page (the
  synthetic ones) and still asserts real entries never touch it; without this, prove_state_lifecycle
  broke at the warm pass.
- **prefill(T) is split into the fewest equal requests of <= max_seq_len rows** that still pad
  to T. A real prefill of T tokens can be any split; the program (family, token bucket) is the
  same.
- **The warm pass runs the loop's stepper** (`Step.warm` / `DFlashStep.warm`), not just the target
  forward: gpt-oss never calls `silu_mul` but the DFlash drafter does, so warming the target alone
  would make the drafter's first step raise "first dispatched after build". DFlash gained an
  `inert` flag that flips its null-block asserts (real rows never on block 0; synthetic rows all).
- **Echo's warm is a no-op** (its forward would record a synthetic prefill as slot 0's prompt).
- **`build(buckets=...)` non-empty now raises NotImplementedError** (was silently ignored).
- **ProgramKey.capture** now records the resolved capture (was `bool(None)` = False on a default
  CUDA capture build). Provenance only; not the cache key.
- **Manifest SCHEMA 2**: `Entry.step` ("decode R=8") replaced `Entry.shape`. Graded/benched once
  per op (sample args do not depend on the step) and copied to every step row; TODO to grade at
  each step's real recorded args.
- **Multi-build scripts** now run each build in a fresh process (bind runs once per process).

- **Review fixes (independent subagent review of the diff):** the sampler SELECTS -inf for
  filtered/masked tokens instead of adding noise to them (Philox's uniform can round to 1.0,
  Gumbel +inf, -inf + inf = NaN, and argmax picks NaN: a greedy row in a mixed batch could emit a
  random token ~V/2^24 of the time; the masked-token half of it predates this branch). Ops on a
  device other than the bound one now raise instead of silently running the reference. A
  multimodal model must define `warm_payload(config)`; build encodes it once so the vision
  tower's ops resolve (SmolVLM's layer_norm/gelu run only for image requests). Prefill reach is
  min(max_batch_tokens, max_batch_reqs * max_seq_len) and the split handles non-power-of-two
  budgets. Captured's unsupported configs raise BuildError ("build with capture=False").
- **Row 0 keeps its dtype when wider than f32** (`promote_types(dtype, f32)`): bf16/f32 are
  unchanged; an fp64 model (the toy oracle) now argmaxes row 0 in fp64 (was f32), matching the
  extra rows.

- **Second review fixes:** build sets `engine.batch_ceiling` to the batch limits it warmed, and
  `Engine.set` refuses a raise past it (ValueError -> 400 on POST /v1/kelpie/config) instead of
  the step loop dying on the first unwarmed plan. A drafting engine (max_extra > 0) requires a
  power-of-two max_batch_tokens (BuildError otherwise; TODO: per-entry n_extra synthetic plans),
  because some buckets of a non-power-of-two budget are reachable only by mixed plans. The
  sample op's `samples` are now a mixed top_k batch so opcheck/compare exercise the draw.
  HTTP `top_k: null` / `5.0` are 400s (additive field, strict type).

## Uncertainties

- `compile=True` wraps the Step after warm, so the torch.compile trace happens at the first real
  step; it looked untested before this branch too (`torch.compile(step)` of a non-Module).
- The post-freeze message's step note comes from a ContextVar set in `Step.forward_device`; a
  caller loop that dispatches ops outside a forward (none today) would see a stale note.

- **Peak memory moved to build.** gpt-oss decode's "peak allocated" went 24.0 -> 47.5 GiB in
  prove_moe compare: the warm pass now runs prefill T=1024 (2 x 512 rows) through the reference
  attention, whose gather is O(T x context). A real 1024-token prefill costs the same on main; the
  branch pays it at build, where an OOM is a build error, not a serve one. Worth knowing for
  capacity planning; it is the argument for a real prefill attention kernel.

## Results (A100-80GB, volume kelpie-a1)

- gpt-oss-20b, capture=True: `shapes: decode[4]=1,2,4,8 prefill[11]=1..1024`,
  `kernels[cuda]: moe=marlin paged_attention=reference rms_norm=triton rope=triton sample=reference`,
  `captured 4 decode buckets`. build 20.3 s / 24.1 s (two runs) vs main 18.9 s (includes load).
- prove_moe compare --capture vs a main-recorded baseline: 8/8 prompts token-identical,
  teacher-forced worst 1.0 bf16 steps (gate 8).
- DFlash, run() native loop, math corpus, 256 new: PASSED, worst 1.0 bf16 steps, mean
  acceptance 4.33 (both runs).

- Round 2 (decode_extra by token, user top_k, all-greedy without RNG), same A100 runs: build
  22.3 s; prove_moe compare --capture 8/8 token-identical, worst 1.0 bf16 steps; DFlash native
  PASSED, worst 1.0, acceptance 4.33 (its plans all landed on warmed keys, or Step.warmed would
  have raised). DFlash config families: decode 4, decode_extra 7 (T=2..128), prefill 11.

## Papercuts

- `scripts/test` needs the xgrammar shim symlinked per worktree.
- Three commits' messages are off by a file: `git rm` staged deletions (examples/main.py,
  my_ln.py, sdk/accept.py) rode along in d27cb0e.
- Background shells are blocked by a hook; long Modal runs go through tmux.
- `/data/moe/baseline.json` on the kelpie-a1 volume no longer matches the corpus prove_moe
  encodes ("baseline was recorded on a different corpus"; prompt derivation is unchanged on this
  branch, so main's compare would trip the same assert), so the greedy
  comparison used a fresh baseline recorded on main (4ae5b7f):
  `/data/moe/baseline-main-4ae5b7f.json` (prove_moe record --capture).
- Every `uv run` rewrites `kelpie-engine/uv.lock`; restore it before committing.
