# Plugin feasibility

## Verdict

Feasible, if “plugin” means an independently packaged component discovered at startup and then passed explicitly into one composition root. It should not mean ambient self-registration. The existing model contract already has the right execution boundary—`forward(w, cfg, batch, kv, state, ops)`—and a backend is already an `Ops` constructor (`docs/model-contract.md:11-23,89-118`). The missing piece is declarative discovery and assembly. Do that before CUDA graphs freeze another name-based launch path.

## Current seams and leaks

**Model.** A torch model supplies typed weight/config dataclasses, `load`, `config_from_hf`, `attn_specs`, and `forward`; XLA currently needs a second, parallel model file (`docs/model-contract.md:3-7,15-41`). Adding a model also edits `runner.py` imports and `MODELS` (`kelpie-models/kelpie_models/runner.py@main:15-43`). The bridge otherwise derives groups, recurrent-state presence and EOS from that module (`kelpie-models/kelpie_models/bridge.py@main:197-231`), validates groups, builds Ops/KV/state, and binds the callable (`bridge.py@main:139-181`). This is good normalization, but the helper functions are name-driven. JAX has a separate, smaller `MODELS` table and assumes one full-attention group (`kelpie-models/kelpie_models/jax/bridge.py:20-34,128-140`).

HTTP adds more edits: `TOKENIZERS` and CLI choices (`kelpie-http/kelpie_http/server.py@main:55-69,627-650`), a gpt-oss dtype substring rule, backend environment branch, and calls to the three bridge helpers (`server.py@main:575-618`). VLM dispatch is an exact SmolVLM-name check (`server.py@main:621-624`). Chat family detection and parser construction are regex/conditional tables (`kelpie-http/kelpie_http/chat/__init__.py:50-68,71-113`). Thus tokenizer, aliases, dtype, chat codec, stop tokens, multimodal adapter, groups, EOS and runtime implementation are not one canonical model fact.

**Backend/kernel.** The seam is strong: models may call only fields of explicit `Ops`; backend files build one frozen value, overrides must match reference signatures, and kernel imports in models are forbidden (`docs/decisions.md`). A new torch kernel set still edits `kernels/__init__.py:9-17`; JAX edits its analogous `DEVICES` table (`kelpie-models/kelpie_models/jax/kernels/__init__.py:9-19`). A new op is additive but touches the reference `Ops` definition/implementation, every framework that exposes it, signature tests, and any backend override; v1 explicitly permits new Ops fields (`docs/model-contract.md:177-184`). A kernel implementation alone should touch only its backend file plus tests.

**Parallelism.** Sharding is deliberately not an Ops plugin: layout transitions/collectives remain visible in model code (`docs/model-contract.md:39-41`; `docs/decisions.md`). Role-to-axis bindings and presets are configuration seams. Today only gpt-oss is sharded, with model-adjacent conditional specs, and the rank-0 broadcast runner samples centrally. DP-attention would require multiple plans/per-rank cache ownership, hence scheduler/coordinator work, not a drop-in strategy.

**Sampler/grammar/spec decode.** Sampling is already an Ops field, so fused or alternative samplers fit backend construction; its fixed signature reserves masks and rejection sampling (`docs/model-contract.md:99-118`). There is no independent sampler-selection protocol. Grammar is designed as a host `Matcher` with four verbs plus a dynamic `logit_mask`, owned per request by `KelpieCore`; model forward stays unaware. Spec decode is not merely a sampler: it changes plan rows, commit payloads, allocation and state rings. Current Zig already exposes explicit entry kind and a struct commit boundary, but remains K=0 (`kelpie-core/src/scheduler.zig:324-368`; `kelpie-core/src/c_api.zig:63-75,287-309`). Strategy policy can be pluggable only above these fixed mechanics.

The design rules rejected vLLM/SGLang-style global backend registries and runtime per-call dispatch. They chose one explicit `Ops` value, built once by one backend file, with offline/static eligibility (`docs/decisions.md`). This is compatible with package entry-point discovery: discover once, reject duplicate IDs, select once, construct explicitly, then pass the value. It is incompatible with import-time mutation or lookup from model code.

## Wave 3

1. **Graphs:** helps backend/kernel plugins by proving the first real override, but hardens buffer ownership and program keys. Before it starts, freeze a `CompiledProgram`/`StepProgram` protocol: static key, owned input/output buffers, `plan`, `forward`, separately launchable `sample`, completion/synchronization, and capture invalidation. Grammar requires forward/sample separability; masks must be persistent copied graph inputs.
2. **Zig-owned loop:** improves a stable endpoint but makes Python-callable strategies harder. Freeze a narrow C launch ABI with opaque plugin context and completion/token buffers; do not make Zig know model/backend names. This item explicitly removes Python from plan→launch→commit (`docs/decisions.md`).
3. **Overlap:** helps program plugins only if synchronization is explicit; otherwise it couples the core to CUDA. Cursor advancement must occur at commit by accepted count, not optimistically at plan (`docs/decisions.md`). Grammar needs split forward/sample launch for useful overlap.
4. **Grammar:** helps grammar-provider plugins: compile before submit, store only the four-verb matcher per request, and feed masks as values. It should not add a Zig grammar type.
5. **Spec decode:** enables proposer/verifier policy plugins after the non-pluggable scheduler mechanics land. Preserve explicit kind, structured commit, K/mode leaves, ring snapshots and `caches(..., max_spec_tokens)`.

Because v1 is additive-only, the reserved `StepBatch`, `ProgramKey`, sampler and commit shapes should be treated as fixed (`docs/model-contract.md:177-184`). The unresolved pre-graphs decision is the launch/program ABI and buffer ownership; also decide whether grammar masks are always rank-3 `[R,1+K,W]` now, or document the later reshape.

## Comparison (uncertain)

From prior knowledge, not verified in this repository: nano-vllm is intentionally small and commonly extends models through centralized architecture mappings; mini-sglang similarly exposes recognizable model-runner/backend modules but retains framework-owned dispatch. Neither is known here to offer a stable third-party entry-point contract. Treat this as directional, not a factual competitive audit. Kelpie’s explicit Ops and data-only cache groups are a cleaner potential extension boundary; its current duplicated name tables are worse ergonomically. No clones or external source checks were performed, per request.

## Recommended surface and order

Define structural protocols plus immutable specs:

```python
ModelPlugin(id, aliases, tokenizer, chat_family, eos, dtype,
            torch_model, jax_model=None, multimodal_adapter=None)
BackendPlugin(id, framework, devices, make_ops, compile_program)
GrammarProvider.compile(spec, tokenizer) -> Matcher
SpecStrategy.prepare/commit(...)  # policy only; scheduler owns invariants
```

Expose Python package entry-point groups, but resolve them into an immutable `Catalog` at startup. Pass the chosen `ModelPlugin` and `BackendPlugin` into the bridge; never consult the catalog during a step. Keep `AttnSpec`/`derive_groups` as the model-to-core data seam (`docs/model-contract.md:120-139`), Ops as the kernel seam, mesh role bindings as the parallel configuration seam, and `KelpieCore` as owner of per-request host effects.

Ranked work:

1. **Program/launch ABI and graph buffer contract — large.** Required before graphs; covers split sampling, completion and opaque context.
2. **`ModelPlugin` + startup catalog — medium.** Collapse `MODELS`, `TOKENIZERS`, bridge helpers, dtype/VLM/chat dispatch; retain CLI overrides.
3. **Backend discovery returning explicit Ops/program factories — small–medium.** Replace two local backend dicts without introducing runtime lookup.
4. **Grammar-provider protocol — medium.** The designed Matcher contract is nearly sufficient; lifecycle and HTTP compilation are missing.
5. **Spec strategy policy — large.** Do only after fixed Zig/ABI mechanics; proposer choice can then remain outside core.
6. **Parallel strategy plugins — large/experimental.** TP/EP presets can be data plugins now; DP-attention cannot until plan/cache ownership is generalized.

Uncertainty: effort assumes packaging and API tests, not migration compatibility for third-party plugins, because none exist in-tree.
