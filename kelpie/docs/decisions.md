# Decisions

A dated log, cut 2026-09-10 to an index (every ruling with a grep-confirmed code home, one line)
plus orphans (rulings with no code home: no general DAG, Trainium framework, kelpie-tune, and
`history`-tagged choices kept only as record). Full prose lived here back to 2026-09-01; it drifted
from the code and is deleted rather than kept alongside a supposedly-authoritative index — that
would be a second writer of the same fact (`docs/CODING_STANDARDS.md` rule 18). Dated history is in
`BREADCRUMBS.md` and the handoffs. The rules distilled from these decisions live in
`docs/CODING_STANDARDS.md`.

Rulings whose named files/symbols were confirmed gone from the live tree entirely (a test file only
in the archived suite (tag pre-archive-tests), a bare `kelpie/*.py` path superseded by `kelpie-engine/kelpie_engine/*.py`, a
deleted doc, a deleted module) are removed outright, not indexed and not kept as orphans — their
history is in `BREADCRUMBS.md` and old commits, not here.

---

## Index (ruling -> code)
- ABI additive-only, asserted at load (sizeof tripwire) -> `kelpie-core/src/abi_ids.zig`, `kelpie-engine/kelpie_engine/_ffi.py:check_abi`
- Cache memory = one Zig slab pool (slab = largest page, floor + slack, block_size search <=25%); recurrent/compressor state = per_seq groups; StateRing deleted -> `kelpie-core/src/kv_pool.zig:Pool`, `kelpie-models/kelpie_models/groups.py:choose_block_sizes`

- Zig 0.14.1 pin -> `kelpie-core/build.zig.zon`, `scripts/zig`
- Config tiers -> `kelpie-core/src/scheduler.zig:Tier` (Python side: `build()` argument groups, follow-up brief)
- Core owns indices only, kernel set owns the KV tensor -> `kelpie-core/src/scheduler.zig`, `kelpie-models/kelpie_models/kernels/backend.py`
- Model contract fixed-first: bucketed/padded shapes, plan before forward -> `docs/model-contract.md`, `kelpie-models/kelpie_models/plan.py`
- Attention receives the batch as an explicit argument -> `kelpie-models/kelpie_models/kernels/backend.py`, `kelpie-models/kelpie_models/kernels/attention.py`
- One block table per cache group; per_token/per_seq; block 0 is null -> `kelpie-core/src/scheduler.zig`, `kelpie-models/kelpie_models/groups.py`
- Step order running-first; decode reserve = reserve_ratio * max_new_tokens -> `kelpie-core/src/scheduler.zig`
- Preemption victim: youngest running request, no sort -> `kelpie-core/src/scheduler.zig`
- Chunking: dynamic, to the bucket, block_size-aligned -> `kelpie-core/src/scheduler.zig`
- Prefix cache: hash chain over blocks, not a radix tree -> `kelpie-core/src/scheduler.zig`
- Cancel releases the slot immediately except a plan-held request -> `kelpie-core/src/scheduler.zig`
- Weights are typed dataclass pytrees, not string-keyed dicts -> `kelpie-models/kelpie_models/models/torch/gpt2.py:GPT2`
- Sharding: seqax notation, htdym roles, `{unreduced}` marker -> `kelpie-models/kelpie_models/shard/{spec,mesh,ops,weights}.py`
- Cache groups declared by the model, dedup'd into engine groups -> `kelpie-models/kelpie_models/groups.py`
- Parallelism as three rungs (tensor layout, roles, presets) -> `kelpie-models/kelpie_models/shard/{spec,mesh}.py`, `kelpie-engine/kelpie_engine/parallel.py`
- `set(knob, value)` applies at the next plan boundary -> `kelpie-engine/kelpie_engine/sdk/engine.py:set`, `kelpie-core/src/scheduler.zig`
- Cache memory = one Zig slab pool, groups carve pages; recurrent state is a per_seq group; StateRing to be deleted -> `kelpie-core/src/kv_pool.zig:Pool`, `kelpie-models/kelpie_models/groups.py:derive_groups` (spike zig/cache-spike)
- Slab = largest page; other pages pad to a divisor; per-group block_size searched for <=25% padding -> `kelpie-core/src/kv_pool.zig:Pool`, `kelpie-models/kelpie_models/groups.py:derive_groups`
- Zig HTTP is the end state; Python is wire-contract implementation #1 -> `kelpie-http/kelpie_http/sdk/serve.py`, `docs/wire-contract.md`
- Tool calling: free tool calling first, grammar as backstop -> `kelpie-http/kelpie_http/chat/`, `kelpie-core/src/xgrammar.zig`
- StepBatch = StepShape + device leaves; kv group is a tuple of per-member arrays -> `kelpie-models/kelpie_models/plan.py`
- Model contract v1 frozen: additive-only from here -> `docs/model-contract.md`, `kelpie-models/kelpie_models/plan.py`
- Overlap cursor advances by accepted count, not by n_work -> `kelpie-core/src/scheduler.zig`
- Entries carry an explicit kind (prefill/decode), never inferred from row count
- `sample` has one signature: logits, temperatures, key, logit_mask -> `kelpie-models/kelpie_models/ops.py:sample`
- `ModelState` is the one resource-owning class; `close()` frees kv/state only -> `kelpie-models/kelpie_models/state.py:ModelState`
- `Graph`/`launch_forward`/`launch_sample` are separate calls -> `kelpie-models/kelpie_models/graph.py:Graph`
- Model facts (`CHECKPOINT`, `CHAT_FAMILY`, `DTYPE`, `ADAPTER`) live in the model module -> `kelpie-models/kelpie_models/facts.py`
- `--model` is a dotted module path; short names are sugar -> `kelpie-models/kelpie_models/launch.py`
- One composition function takes the kernel set as a value -> `kelpie-models/kelpie_models/launch.py:build`
- `kelpie serve` is sugar over the SDK, not a second implementation -> `kelpie-http/kelpie_http/cli.py`
- Eager is a capture-count-0 runner, not a mode flag
- Batch invariance is tested for, not assumed; sample key is per-request -> `docs/references.md`
- Eager refused outside `--dev` -> `kelpie-http/kelpie_http/cli.py:check_capture`
- Launch ABI shape is a deterministic u32; mode/dtype/flags are per-program constants -> `kelpie-core/src/step_loop.zig`, `kelpie-models/kelpie_models/kernels/devices/cuda/launch.c`
- Zig is the sole panic owner on a launch failure -> `kelpie-core/src/step_loop.zig`
- Tier-1/tier-2 swap is one primitive, `kelpie_swap_launch` -> `kelpie-core/src/c_api.zig`, `kelpie-engine/kelpie_engine/engine.py`
- Overlap is exactly one step deep, off by default -> `kelpie-engine/kelpie_engine/engine.py:EngineConfig`
- "Backend" is the wrong word: device vs kernel set -> `kelpie-models/kelpie_models/kernels/devices/`
- CUDA eager-prefill fallback removed from the production path -> `kelpie-models/kelpie_models/kernels/attention.py`
- Append-only logs merge with `merge=union` -> `.gitattributes`
- xgrammar vendored, built shared, not the pip wheel's static copy -> `kelpie-core/src/xgrammar.zig`, `kelpie-core/xgrammar_shim/`
- `MeshConfig` accepts any bound role; `ROLES` is a typo guard only -> `kelpie-models/kelpie_models/shard/mesh.py:ROLES`
- Naming: `plan`->`prepare_workspace`, `attn_metadata`->`attn_workspace` -> `kelpie-models/kelpie_models/kernels/backend.py`
- Math ops are plain functions (`functional.py`); backend-shaped ops are layer kinds -> `kelpie-models/kelpie_models/kernels/functional.py`, `kelpie-models/kelpie_models/kernels/backend.py`
- The catalog is device x op x named implementation, `for_device` -> `kelpie-models/kelpie_models/launch.py:build`, `kelpie-models/kelpie_models/kernels/devices/`
- A tap is a declared output of the program; part of the program key -> `kelpie-models/kelpie_models/taps.py`, `kelpie-models/kelpie_models/step.py`
- `kind`+`n_drafts` cross the C ABI as StepBatch leaves -> `kelpie-models/kelpie_models/plan.py`, `kelpie-models/kelpie_models/kernels/devices/cuda/launch.c`
- Testing policy: heavy tails on remote GPUs, local is fast smoke only -> `scripts/test`, `CLAUDE.md`
- Ladder trimmed to 6 models; three quarantined in `unported/` -> `kelpie-models/kelpie_models/models/unported/`
- `export_native` asserts the C fill equals `Graph.fill` byte-for-byte -> `kelpie-models/kelpie_models/runner.py`
- `kelpie.h` keeps both `kelpie_step_event` and `kelpie_next_commit` -> `kelpie-core/include/kelpie.h`
- Ladder rung 03 is the V3.2 file (MLA + DSA indexer); V3 is a config delta -> `docs/ladder.md`, `kelpie-models/kelpie_models/models/unported/deepseek_v32.py`
- No JAX model mirror; torch forwards only, TPU/Trainium via torchax -> `kelpie-models/kelpie_models/models/torch/`
- Package rename `kelpie-py` -> `kelpie-engine` -> `kelpie-engine/`
- Engine exposes `step_fd`; fan-out lives in the trio app, no Engine thread -> `kelpie-engine/kelpie_engine/sdk/engine.py:step_fd`, `kelpie-http/kelpie_http/sdk/app.py`
- HTTP on trio via hypercorn, not FastAPI/asyncio -> `kelpie-http/kelpie_http/sdk/serve.py`
- Kernels come from torch; missing ops are `torch.library.custom_op`s bound once in `ops.bind` -> `kelpie-models/kelpie_models/ops.py:bind`
- `build()` separate from `run()`; cache/`ProgramKey`/`allow_build` (not yet implemented) -> `kelpie-models/kelpie_models/sdk/run.py:build,ProgramKey`
- `roll(hf_config)` shrinks a config to the smallest config covering every layer kind -> `kelpie-models/kelpie_models/synth/roll.py:roll`
- `facts_of`/`ModelFacts` is the negative naming example, not positive -> `docs/CODING_STANDARDS.md`

## Orphans (no code home yet)

Kept in full: no code exists to point the index at, or the ruling is `history` (a choice with no
code residue, kept only as record).

- **HiCache / P-D disaggregation not built.** A shared request state `kv_in_transit` (blocks
  reserved before compute, `prefix.match` returning `(resident_hits, remote_hits)`) would cover
  both, but neither a second tier nor a second engine exists yet to force it.
- **`kelpie-tune` queued, not built.** Replay a recorded workload (the `RequestEvent` log) against
  the running engine while searching tier-0 knobs with no restarts; score TTFT/ITL/throughput;
  output best config + per-knob sensitivity. The two halves it depends on (`kelpie-engine/kelpie_engine/events.py`,
  `engine.set`) exist; the search loop does not.
- **Trainium framework choice: torch-neuronx over torchax.** torchax has no Neuron story; Pallas/NKI
  stay as vendored kernel sources. No `devices/tpu_xla` in the tree.
- **DP-attention rejected above the scheduler.** N schedulers + a lockstep coordinator would need
  the scheduler to partition the batch per DP rank; not built.
- **[later] Self-tuning is queued, not built.** Kelpie has both halves (typed tiered knobs, `StepEvent`/
  `RequestEvent`) but no search loop yet; see `kelpie-tune` above.
- **Overlays follow the Nix model — rejected, superseded.** `Overlay(cfg, device, Ops) -> Ops`
  composed once at the root was tried and `kernels/overlay.py` is deleted; the kernel catalog
  replaced it.
- **TOML `[kernels]` config deferred to the tiered-config work.** Rejected inventing a config-file
  mechanism to satisfy a brief that did not need one yet.
- **The XLA family recompiles per call, not per program** (422 modules for ~24 tests on Trainium). The
  0-recompile bar is decided and unenforced.
- **Kernel libraries survey (2026-09-09), not a build.** FlashInfer for CUDA paged attention /
  sampling / MoE (the only library with `FLASHINFER_DISABLE_JIT` fail-on-miss and
  `build_jit_specs` precompile); vendored per-op Triton from liger-kernel / flash-linear-attention
  for norms, rope, swiglu, `chunk_gated_delta_rule`; flash-attention optional as a pinned wheel.
  Rejected for now: CUTLASS/CuTe DSL, TensorRT-LLM, quack. History only — none of these are
  dependencies of this tree yet (`kernels/adapters/{liger,fla,flashinfer}.py` name the gap).
- **Model test set for the kernel/build system, partly wired.** gpt2, Qwen3-0.6B, gpt-oss-20b,
  SmolVLM-256M, Kimi-Linear-48B-A3B, DeepSeek-V4-Flash, plus `deepseek_v4_tiny` /
  `kimi_linear_tiny` (`roll(hf_config)` over each real config, random weights) put the CSA/DSA and
  KDA classes on one chip. No DSA checkpoint under ~280B exists (survey 2026-09-09);
  GLM-5.3-Flash (320B-A18B, indexer on 11/45 layers) is rung 03's smaller stand-in, B200 only.
  `kelpie-models/kelpie_models/synth/roll.py:roll` and `models/torch/tiny.py` exist; the two tiny configs are not
  yet wired into a test set (none exists live — see `## Where things run` below).
- **Check functions (matklad, per ladder rung) not yet defined.** The candidate kernel check would
  use `popcorn.bench.compare` (fp64 truth / native-dtype budget / candidate, verdict `err <=
  max(2*budget, floor*scale)`) as a pip dependency first — only `compare`/`grid`/`fingerprint`, not
  its dispatcher/tuner. `popcorn` is not yet a dependency; no rung has a check function.
- **[deferred: training (branch integrate/train-step)] Trained/client shape choices (branch work, 2026-09-05), history only.** Explicit
  `inference_forward`/`training_forward` sharing math helpers, not a train/infer union on
  `StepBatch`. One session-scoped mutable `Model` handle plus immutable `WeightVersion` snapshots,
  not a Tinker-style workers split. Shard collectives need layout-aware Megatron adjoints
  (encodable, no backward-parity test yet; `shard/` ops are forward-only today).
- **[deferred: M8] HTTP implementation #2 in Zig, not started.** Rejected a JS runtime + IPC-per-token
  alternative. History only.
- **Above-the-scheduler DP-attention / Dynamo-style routing, not built.** A map of what stays above
  vs. moves inside the scheduler, not a change; no code to point at.

---

## Where things run (operational)
- Mac: editing, git, Zig unit tests, and the fast local suites with only Qwen3-0.6B + SmolVLM-256M cached.
  Zig is pinned to 0.14.1 (see "Language" above); if the system `zig` is a different version, get
  0.14.1 into `~/.local/zig/0.14.1/` (or `zvm`/`zigup`) and build through `scripts/zig` (resolution
  order in the script's header) instead of bare `zig` — it's the door every build/doc command uses.
- Remote hosts (the B200 boxes, the Trainium and TPU hosts) and the SSH tooling that reaches them
  are not in this repo; GPU runs go through `box` (Modal).
- Recurrent models (Qwen3-Next verified; Kimi K3 expected): per-seq state ring outside the core held; prefix caching
  must be OFF for them (a hit would resume at a block boundary with no recurrent state), enforced engine-wide via the
  bridge -- moot once recurrent state is a real Zig per_seq group (2026-09-10 slab-pool ruling, see the Index).

This is operational, not a decision: `scripts/zig` is the door, and its header is the truth if
this drifts.

---

## Open

Undone work, carried from the superseded "order of work" sections. Everything not listed here that
those sections named is done.

1. **Graphs + one real kernel.** A real paged-attention kernel whose metadata is device buffers,
   plus a capture-safe sampler, THEN capture per bucket; measure tok/s vs vLLM on the same B200.
   Not "capture what exists": the 09-02 spike proved the reference CUDA kernel set is uncapturable.
2. **Overlap**, now that the forward is ~1 ms against ~0.7 ms of glue. Default stays off until it wins.
3. **Grammar-constrained sampling** end to end: `serve` still does not wire `vocab_words` (every
   `response_format` request 500s); the Python matcher is not yet deleted.
4. **Speculative decoding / MTP**: `n_work = 1 + k` drafts, rollback in commit, per-seq rings R > 1,
   draft group members, the reference scheduler updated, an acceptance-length gate
   (TRT-LLM `min_al = 0.95 * ref_al`). The DFlash answers above are its design.
5. **Tiered config beyond tier 0**: the `[kernels]` TOML table, per-request seed.
6. **The remaining ports**: `deepseek_v32` / `deepseek_v4` on `mla_attention` + `dsa_attention`,
   `qwen3_next` on `attention` + `gdn`, the JAX twin, the four CUDA scripts.
7. **Not started (features)**: chat templates and tool-calling parsers beyond what exists;
   incremental detokenization (O(n²) per stream today); usage/logprobs in stream chunks; logprobs,
   top-k/top-p/penalties, stop strings, n>1, echo.
8. **The XLA family recompiles per call, not per program** (422 modules for ~24 tests on Trainium). The
   0-recompile bar is decided and unenforced.
9. **`kelpie-tune`** (queued, above): replay a recorded workload against the running engine while
   searching tier-0 knobs.

## Session pointers (conversations to reopen)

- **bench/ = check functions + verifiers, referencing crucible** — deferred to its own session. Context: Claude session `session_01FxBbid2UdQUjvn5f92ysKT` (2026-09-09/10), grep the transcript for `KELPIE-BENCH-SESSION-POINTER` or "compile.py, and why popcorn has a per-call dispatcher". Decisions already taken there: op-per-file layout (popcorn), `source=` + backend pins, `fingerprint`, `kelpie build` = warm every bound op per bucket shape into a read-only Triton cache + `manifest.json` (fingerprint, compare verdict, timing), serve fails closed on miss/changed/incorrect, warn on timing regression vs previous manifest; forward-only ops with `register_autograd` raising (training deferred); `torch.compile` opt-in later; no Dispatcher/tuner/ContextVar/compile.py/hub from popcorn. Open: the check function signatures per rung (Zig traces, check_serve, check_kernel/compare, HF oracle rows) and how crucible's `kernel_lib`/`BudgetTolerance` become the base.
