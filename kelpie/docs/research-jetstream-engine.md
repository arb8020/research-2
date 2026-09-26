# Research: XLA attention shapes, JetStream Engine protocol, and the priority cascade

2026-09-08. Findings from a survey of MaxText, JetStream, jetstream-pytorch, vLLM-neuron, and
kelpie's own torch_xla spike (spike/torch-xla). Decisions at the bottom.

## 1. The variable-length KV problem on XLA

TPU and Trainium chips cannot execute individual ops one at a time. The XLA compiler takes a
*graph* of ops, compiles it into a single binary (an HLO program), and the chip runs that binary.
Every distinct tensor *shape* in the graph produces a distinct binary. If the shape changes, the
compiler runs again: seconds on TPU, minutes on Trainium's neuronx-cc. A serving process that
recompiles on the hot path is unusable.

Kelpie's `StepShape` bucket ladder already fixes the *batch* shapes (pad tokens to 16/32/64/…,
requests to 1/2/4/…). The forward, the sampler, the taps, the norms — all of these have shapes
determined entirely by the bucket. The *one* exception is attention, because each request attends
over a different number of past KV tokens (`seq_lens[r]`), and the reference implementation reads
that as a Python integer, slices the KV cache by it (`kv[:seq_lens[r]]`), and loops per request.
Under XLA tracing, a Python int that becomes a tensor dimension is a *shape*, not a value: a new
`seq_lens` tuple is a new HLO graph. The torch_xla spike measured this directly: 2 new programs
on the first real step after a 12-shape / 38-compile warm-up on both TPU and Trainium; every
decode step compiles because `seq_lens` grows by 1 (5.6–9.1 s per step on TPU, 111–141 s on
Trainium).

## 2. How production engines solve it

Every production TPU / Trainium engine pushes `seq_lens` into the program as **data** (a tensor
the kernel reads at runtime) rather than as a **shape** (a compile-time constant). The cache shape
is fixed; the mask is data.

| engine | framework | cache shape | seq_lens enters as | decode attention | mask |
|---|---|---|---|---|---|
| **MaxText** | JAX | fixed to `max_target_length` | data: `lengths = jnp.sum(segment_ids)` passed as a tensor into `ragged_mha` via `shard_map` | ragged Pallas kernel (Splash is prefill only; decode explicitly forbidden from flash) | ragged kernel uses `lengths`; dot-product uses additive float `[R, S]` |
| **jetstream-pytorch** | torch_xla | fixed to max; paged opt-in | data: `position`, `start`/`end`, `page_indices`, `lengths` | priority: ragged_mha (via `call_jax`) → flash → page_attention → dense with additive mask | additive `[R, S]` of 0 / -inf; values change, shape doesn't |
| **vLLM-neuron** | torch + neuronx-distributed-inference | fixed; paged via NxDI | data: block tables + lengths as tensors | NxDI's compiled paged kernel | handled inside the kernel |
| **kelpie JAX arm** | JAX | paged (block tables) | data: `seq_lens` as a `jax.Array` inside the RPA/NKI kernel | RPA (TPU Pallas) / NKI (Trainium) | inside the kernel |
| **kelpie reference** (the leaker) | torch | paged (block tables) | **shape**: Python int `host.seq_lens[r]` → `kv[:s]` slice in a `for r` loop | Python loop per request, SDPA per request | causal mask at variable size |

Sources: MaxText `layers/attention_op.py:1565-1610`; jetstream-pytorch `layers.py:441-514`;
JetStream `engine/engine_api.py`; kelpie spike/torch-xla report.

## 3. JetStream's Engine protocol

JetStream (`github.com/AI-Hypercomputer/JetStream`, `engine/engine_api.py`) defines an abstract
`Engine(abc.ABC)` with five methods:

```
prefill(params, existing_prefix, padded_tokens, true_length) -> (Prefix, ResultTokens)
generate(params, decode_state) -> (DecodeState, ResultTokens)
insert(prefix, decode_state, slot) -> DecodeState
free_resource(slot)
init_decode_state() -> DecodeState
```

`Params = Any`, `Prefix = Any` (result of prefill; often a batch-1 KV cache), `DecodeState = Any`
(the live decode batch; often a prefill + generate cache tuple). All deliberately opaque — the
implementation decides what they hold.

The scheduler (JetStream's orchestrator) lives *entirely outside* this interface. It manages slot
assignment, prefill-vs-decode decisions, and request lifecycle; the Engine only exposes per-step
computational primitives. MaxText and jetstream-pytorch each provide a concrete `Engine` subclass.

`ResultTokens` packs tokens, validity, and lengths into one flat array (`engine_api.py:50-158`,
comment: "copying a single array to host is much faster") with index metadata; `get_result_at_slot`
slices per request.

## 4. Kelpie's equivalent today

Kelpie's engine shape maps onto JetStream's, split across three components:

| JetStream | kelpie | where |
|---|---|---|
| `prefill` | a `kelpie_plan` whose entries have `kind = prefill` → the launch fn runs `forward_step` over those rows, writing KV | Zig `scheduler.zig` decides the plan; Python `step.py` / `graph.py` execute |
| `generate` | a `kelpie_plan` whose entries have `kind = decode` → the same launch fn | same; the Zig loop calls the C launch fn pointer per step shape |
| `insert` | `kelpie_submit` → the scheduler reserves blocks and plans the request's first prefill chunk in the next `kelpie_plan` | `scheduler.zig:planWaiting`; no explicit "splice into a running decode batch" — the scheduler mixes prefill chunks and decodes in one plan |
| `free_resource` | `kelpie_commit` → the scheduler advances cursors and frees blocks for finished / preempted requests | `scheduler.zig:commitEntry` |
| `init_decode_state` | `launch.build` → `ModelState` + `ModelRunner` (graphs precaptured per StepShape) | `launch.py`, `runner.py` |
| `Params` | `ModelState` (weights + KV pool + state ring + kernels + backends) | `state.py` |
| `Prefix` | not separate — a prefill's KV is written in place into the paged pool, addressed by the scheduler's block tables | `kv.py`, `scheduler.zig` block allocation |
| `DecodeState` | the paged pool + the Zig scheduler's per-request state (cursors, block tables, grammar state) | distributed across `kv.py` and `scheduler.zig` |

Key differences:
- **No explicit `insert`.** JetStream's `insert` splices a prefill result into a specific decode
  slot. In kelpie, `submit` queues the request and the scheduler plans it — the "splice" is the
  first prefill chunk writing KV at the allocated blocks. There is no separate copy step.
- **`generate` is implicit.** JetStream's caller explicitly calls `generate(params, state)`.
  Kelpie's Zig loop calls the launch fn pointer on its own schedule; Python never calls "do a
  decode step" — it registers the fn and the loop drives it.
- **Prefill and decode are mixed in one plan.** JetStream's `prefill` and `generate` are separate
  methods called at separate times. Kelpie's `kelpie_plan` can contain both prefill chunks and
  decode entries in a single step (continuous batching with chunked prefill).

## 5. The priority cascade for kelpie's XLA attention

Decided 2026-09-08: match jetstream-pytorch's priority order, mapped to the kernel catalog.

| priority | kernel | catalog entry | status |
|---|---|---|---|
| 1 | ragged attention (Pallas on TPU, NKI on Neuron) | `devices/tpu_xla/attention.py` IMPLS `{"ragged": RaggedPallasAttention}` / `devices/neuron/attention.py` IMPLS `{"ragged": RaggedNKIAttention}` | not built; M7-class (= the JAX arm's RPA/NKI, ported to torch via `call_jax` or a torch custom op) |
| 2 | flash attention (if available per platform) | `IMPLS {"flash": ...}` | not built; depends on platform flash support |
| 3 | paged attention (fixed-shape gather by block table + mask) | `IMPLS {"paged": PagedAttention}` | not built; an intermediate step between 4 and 1 |
| 4 | dense with additive mask (gather full padded KV, mask as data) | `IMPLS {"dense_masked": DenseMaskedAttention}`, **DEFAULT on both XLA kinds** | the immediate deliverable: plain torch, answers the spike's bar 1, closes the recompile gap |

`DenseMaskedAttention` is the "option (a)" from the spike report: always gather `kv[:max_seq_len]`
per request (or the whole padded block table), build a `[R, T_q, T_kv]` additive mask from
`positions` and `seq_lens` (both tensors on device, no host ints), apply it to the attention
scores. One program per StepShape; `seq_lens` changes are invisible to XLA. Cost: reads O(R ×
max_blocks × block_size × L) KV per step instead of the live context. Fine for gpt2 at block
count 8; a cost at 32k context — which is when priority 1 or 3 pays for itself.

## 6. Open: should kelpie formalize an Engine protocol?

**Option A: a `typing.Protocol` that `ModelRunner` / `Graph` / the Zig loop implement.** Methods:
`build() -> EngineState`, `step(state, plan) -> (tokens, taps)`, `insert(state, request) ->
state`, `free(state, slot) -> state`. The protocol names the contract that `kelpie.engine.Engine`,
`ModelRunner.__call__`, and the Zig C ABI already implement in different vocabularies; formalizing
it would let a test assert "this thing is an engine" and would give the DFlash drafter (a second
runner) a type to implement. Cost: a new file, every existing caller is already correct and gains
nothing from the type, and `Params = Any` means the type checker can't actually verify the
interesting parts (KV layout, kernel set, graph table).

**Option B: keep the current implicit shape.** The Zig C ABI (`kelpie.h`) is the contract for the
scheduler; `ModelRunner`'s `__call__(plan) -> tokens` is the contract for the step; `launch.build`
is the composition root. No Protocol, no base class. The contract is documented in
`docs/model-contract.md` and `docs/decisions.md` and enforced by the test matrix. Cost: a new
engine variant (the DFlash drafter, the XLA graph flavor, a future disaggregated prefill worker)
must read the docs and match the shape by hand; nothing checks it structurally.

**Option C: JetStream's approach — opaque state, five methods.** The scheduler knows nothing about
KV, kernels, or graphs; it calls `prefill` / `generate` / `insert` on an opaque engine, and the
engine returns opaque state + a flat token array. Cost: kelpie's scheduler already knows about
blocks (it allocates them, evicts them, tracks prefix hashes); the opaque boundary would either
push block management into the engine (duplicating the Zig core's work) or leak block ids through
the opaque state (defeating the abstraction). JetStream can afford opaque state because its
scheduler doesn't manage paged memory — it delegates that to the engine. Kelpie's Zig core is the
page manager.
