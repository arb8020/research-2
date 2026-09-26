# Brief: greenfield glue (the SDK ladder)

Date: 2026-09-09. Owner: user. Executor: one agent (opus) on branch `sdk/ladder`, worktree.
Inputs: `docs/CODING_STANDARDS.md`, `docs/stepbatch-survey-2026-09-09.md`,
`~/research/docs/code_style/{casey_semantic_compression,casey_granularity,casey_worst_api,dune}.md`.

## Why

The Zig core (`kelpie-core/`) and the kernels (`kelpie_models/kernels/devices/`) are measured and
kept. The model forwards (`kelpie_models/models/`) are kept and re-signatured. Everything between
the core's `KelpiePlan` and `model.forward` (~4.5k lines: `plan/step/graph/runner/state/launch/
bridge/batch/groups/taps/multimodal`, `jax/bridge`, `kelpie/engine,_ffi,core,parallel`,
`kelpie_http/core`, the ticker classes in `server.py`, `cli.main`) is rewritten from the usage code
down. The old modules are not edited; they are deleted when the new path serves.

## The two fixed interfaces

1. `kelpie-core/include/kelpie.h` — `kelpie_create/submit/plan/commit/poll/cancel/set/
   attach_grammar/start_loop/stop_loop/swap_launch`, `KelpiePlan` (bucket-padded, `kinds`,
   `row_request`, `logit_mask`, `shape`), the event structs. Zig is not changed in this brief
   except to add `kelpie_sizeof(struct_id)` / `kelpie_offsetof(struct_id, field_id)` exports.
2. `model.forward(w, cfg, tokens, requests, kv, kernels) -> logits` plus `model.load(...)`,
   `model.attn_specs(cfg)`, and the kernel names the five forwards call on `kernels`
   (list them by reading the forwards; that list is the vendored library's API).

## The ladder (each rung written in terms of the rung below; every rung public)

```python
# rung 4 — CLI: argparse over serve; the only place strings exist
def main(argv):
    args = parser().parse_args(argv)
    serve(model_module(args.model), kernels.for_device(args.device, **parse(args.kernels)),
          port=args.port, **engine_args(args))                    # --model is required

# rung 3 — HTTP over a running engine
def serve(model, k, *, port=8000, tokenizer=None, chat=None, **engine):
    with run(model, k, **engine) as eng:
        uvicorn.run(create_app(eng, tokenizer or model.CHECKPOINT, chat), port=port)

# rung 2 — weights + kv + the Zig loop driving a Step
@contextmanager
def run(model, k, *, device="cpu", dtype=None, max_requests=8, kv_blocks=64,
        max_batch_tokens=1024, capture=None):
    w, cfg = model.load(device=device, dtype=dtype)
    eng = Engine(EngineConfig.from_model(cfg, max_requests, kv_blocks, max_batch_tokens))
    kv = alloc_kv(model.attn_specs(cfg), eng.config, device, dtype)
    step = Step(model, w, cfg, kv, k)
    if capture if capture is not None else device == "cuda":
        step = Captured(step, eng.buckets)
    eng.start_loop(step)
    try: yield eng
    finally: eng.close()          # drain -> stop_loop -> graph free -> kv -> sink -> destroy

# rung 1 — one step; what the Zig loop calls; what a notebook calls by hand
class Step:
    forward(plan) -> logits       # kv/state mutated IN PLACE, never rebound (assert identity)
    sample(logits, plan) -> tokens
    __call__(plan) = sample(forward(plan), plan)
    key_extras: (dtype, mode, flags, taps)      # runner half of the program key
    capturable(plan) -> bool                    # False iff plan carries an embeds override

class Captured:                   # wrapper; owns stream, pool, fixed Plan buffers per shape
    __call__(plan): eager fallback if not capturable; else copy_leaves + replay forward,
                    fill mask, replay sample, read tokens.  launch.c is the C twin.

# rung 0 — primitives
Engine        ctypes over kelpie.h; the ONE runtime object (15 members, derisk-one-engine §6)
Plan          typed view over KelpiePlan: .tokens / .requests / .sampling (derisk-plan-abi §4)
EngineConfig  .from_model(model_cfg, ...) — one writer per field (derisk-one-engine §3)
alloc_kv      from attn_specs + engine config
kernels.*     modules; for_device(dev, **overrides) with overrides as VALUES, not strings
```

## Order of work (each step ends with a commit and `examples/main.py` running on CPU)

1. **rung 0+1+2, gpt2, CPU, eager**: `examples/main.py` becomes the three lines
   (`model = gpt2; k = kernels.for_device("cpu", layer_norm=my_ln.layer_norm); kelpie.serve(model, k, ...)`)
   and serves one `/v1/completions` through the Zig loop. `Plan` is hand-written ctypes for now,
   with the `sizeof/offsetof` tripwire asserted at import (cffi/generated header is a follow-up).
2. **echo Step**: `Step` whose forward/sample echoes reversed prompt tokens; `kelpie serve --model echo`
   replaces `--model stub`; `StubCore`, `Stepper`, `Ticker`, `Core.step()`, `ContractCore` are
   not ported.
3. **qwen3, CPU** (GQA, RoPE, RMSNorm): proves `Requests` is what attention needs.
4. **rung 3 + 4**: `create_app(eng, tokenizer, chat)` over the 15-member `Engine`; `cli.main`
   as argparse over `serve`. Config constants live once (`from_model`; `max_seq_len` from the
   HF config, not a constant).
5. **Captured** on the box (qwen3 CUDA): `launch.c` bound to the new `Plan` buffers; the
   `copy_workspace` residue resolved (derisk-captured-step §2 — confirm on GPU whether any
   backend still needs a host-derived workspace).
6. **delete** the old glue wholesale (list in "Why"), the reference scheduler
   (`kelpie/reference/`), `facts.py`, the kernels catalog + 4-line stub files.
7. Follow-ups, each its own brief: taps output channel; VLM override (smolvlm); grammar mask
   rung; DFlash K>0; JAX runner ported to the settled shape; TP/EP; cffi/generated header.

## Rules for the executor

- **Write the code; do not test it.** No test files, no pytest, no proofs, no ad-hoc verification
  scripts. The testing boundaries and invariants get defined once the code reads right (user's
  call, later). The only checks are `scripts/test` (zig build + ruff + imports) and
  `examples/main.py` starting and answering one curl on CPU — that is a "does it run", not a test.
- Write it straight first; pull out a function/object only when the same lines appear twice
  (semantic compression). Report where objects appeared, not where this brief said they would.
- A struct exists only if its fields travel together through the same frames. `Plan`'s three
  views are the survey's finding, not a requirement — if a forward needs a fourth, say so.
- One name per value, one writer per value. No `Any` params; no `-> None` unless the function
  is a lifecycle verb. No dotted-string indirection outside rung 4.
- Do not run pytest or anything that loads weights bigger than gpt2 on the laptop. `scripts/test`
  (zig + ruff + imports, locked) after every edit; `examples/main.py` on CPU is the smoke.
  Box runs only at step 5.
- Do not take the simpler option silently. If a rung can't be written as sketched, stop and
  report the obstacle with the code that shows it.
- Commit after every step; `mimir breadcrumb -a sdk-ladder "..."` for judgment calls;
  `mimir papercut` for frictions. Final report: LoC before/after per package, what got
  deleted, the kernel-name list, where each of the four extras (taps/override/mask/K) ended up.

## Open (user to rule, not the executor)

- `Engine` no-Zig mode: none. The echo Step runs on the real core.
- `n_cached`: fixed in the new path (the core knows it; expose it on the request event) or
  preserved as 0? Default: fixed, since the field would otherwise lie.
- `_lock` in KelpieCore: keep only around the Python dicts unless reading Zig shows otherwise.
