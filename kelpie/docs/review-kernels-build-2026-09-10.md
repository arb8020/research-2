# Review: chore/kernels-build (sonnet review, checked by fable) — 2026-09-10

Branch: `chore/kernels-build`, 5 commits off `6d8ae6d`, worktree `worktrees/kernels-build`. Unmerged.
Executor report: verified `scripts/test`, gpt2/echo rows byte-identical, on-device reference attention
within 4.8e-7 of the old host loop over 40 random plans, build -> `kelpie cache` -> serve round trip,
empty cache and tampered fingerprint refused. No CUDA run.

## Needs the user's decision (not verification)
1. **KV layout.** Ruling E: K and V are two members, each `[pages, block, Hkv, D]`. Built: one member of
   unit shape `(2, Hkv, D)` -> `[pages, block, 2, Hkv, D]` (`kernels/ops/paged_attention.py:22`,
   `sdk/groups.py:reference_kv_layout`). Property wanted (two contiguous non-interleaved views, no `0::2`)
   holds. Reversing it changes `Group` member counts, `check_groups`, every `layer_caches` index, and
   fingerprint/manifest/cache assume the shape transitively. Decide before merge.
2. **Warm runs one shape, not the bucket ladder** (`sdk/run.py:_warm`, `del buckets`). Needs a synthetic
   padded plan without a request = branch `engine/padded-plan`. Until then `buckets=` is accepted and
   ignored; manifest has one shape row per op; serve at any other shape is unverified. Merge with the TODO,
   or block on padded-plan?
3. **Attention family ships reference-only on CUDA.** flashinfer/triton/pallas/nki adapters for
   `paged_attention` all raise NotImplementedError; `devices.py` defaults cuda `rms_norm/rope/silu_mul=triton`,
   attention+sample=reference. Expected (adapters are docs/brief-adapters.md), confirm.

## Real findings (fix before or at merge)
- `check` verdict for `paged_attention` grades one degenerate `sample_args` shape: t=2, 1 head, 1 request,
  no pad row, no window, no sinks (`ops/paged_attention.py:174-189`). A multi-request/window/sinks bug
  passes `--check`. Add a second sample case (>=2 requests, pad row, window>0, sinks) — the differential
  test the executor ran by hand should be that case.
- `KV_MEMBERS = 2` declared in `ops/paged_attention.py:22` and again in `sdk/groups.py` (comment says the
  op file owns it; code re-declares). Import it.
- `reset_for_test()` (`kernels/op.py:264`) is a second writer of the bind-once global, guarded by a comment.
- Counting shim wraps every impl (`op.py:180-193`, registered via `register_kernel`). Under CUDA graphs it
  runs once per capture (fine). Under `compile=True` it may break the graph — untested.
- `Any`-typed `op` in `bench/compare.py` and `bench/distribution.py` without a site comment; six
  `noqa: PLR0913` in `sdk/run.py` instead of a request bundle; `op.py:227-235` docstring is history.
- Triton JIT-refusal hook (`sdk/cache.py:88-113`) guesses kwarg names, never fired (no triton locally).
- `torch.compile` path and `bench=True` timing/regression-warning path never executed.

## False alarm
- Review said `kelpie cache <dir>` missing; it exists (`kelpie_http/sdk/serve.py:237`).

## CUDA (B200) before merge
    kelpie doctor && scripts/test && python scripts/check_serve.py
    kelpie build --model gpt2 --device cuda --cache /tmp/kcuda --check --bench   # triton defaults exercised
    kelpie serve --cache /tmp/kcuda    # request; then delete one manifest entry -> expect JIT refusal, not a silent compile
    kelpie cache /tmp/kcuda
    build(gpt2, device="cuda", compile=True)    # graph break with the counting shim?
    gpt_oss tiny row with --check after the second sample case (window + sinks + 2 requests)
    a request at a shape other than the warmed one -> what happens today
