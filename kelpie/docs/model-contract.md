# Model contract v1 (frozen; additive from here)

This is the reference for every model agent. A model is one file under `kelpie-models/kelpie_models/`
(torch) and, for the XLA family, one under `kelpie_models/jax/`, both reading line for line the same.
The code is the source of truth: `kelpie_models/plan.py` (batch), `kelpie_models/ops.py` and
`kelpie_models/jax/ops.py` (kernel seam), `kelpie_models/models/torch/gpt2.py` + `kelpie_models/models/jax/gpt2.py` (the
smallest complete model), `kelpie_models/runner.py` (`run_step`: what happens around a forward).

## 1. The forward

```python
forward(w, cfg, batch, kv, state, ops) -> (logits, kv, state)
```

| name | what | torch | jax |
|---|---|---|---|
| `w` | frozen dataclass pytree of weights (never a string-keyed dict); `load(model_id, device, dtype) -> (w, cfg)` is the only place HF names appear | tensors | the same dataclasses with jnp leaves (`jax/weights.py`) |
| `cfg` | frozen dataclass of the model's constants | same | same |
| `batch` | `StepBatch`: `StepShape` + device leaves (section 2) | leaves are tensors | leaves are jnp arrays (pytree; key is meta) |
| `kv` | `list[KV]`, one per cache group in `derive_groups` order; a `KV` is a `tuple` of per-**member** arrays, member `offset` from `derive_groups(...)[1][layer]` | same shapes | same shapes |
| `state` | the per-request `StateRing` for models with recurrent / compress rings (`groups.state_specs`), else `None` | `StateRing` | `None` today |
| `kernels` | the `Kernels` namespace (kelpie_models.kernels.for_device): the math a forward calls; the attention backend rides on the batch (`batch.attn[g]`). Section 3 below still describes the pre-seam `Ops` bag and is stale | `for_device("cuda")` | `for_device("tpu")` / `for_device(kind, **bridge.JNP)` (kelpie_models.jax.bridge.kernels_for) |
| `logits` | `[padded_num_reqs, 1 + K, vocab]` gathered at `batch.accept_index` (K = 0 today: `[R, 1, V]`) | | |

Rules:
- Parameter names are exactly `w, cfg, batch, kv, state, ops` (tests/test_seam.py checks every model
  file on both paths). A model with no ring asserts `state is None`.
- The forward **threads** `kv` and `state`: every op that writes returns what it wrote and the forward
  uses the returned value (`a, kv0 = attention(...)`; `state = put_blob(state, i, NAME, blob)`), then
  returns the list/ring it ended with. torch writes in place and returns the same objects; JAX returns
  new ones under `donate_argnames=("kv",)`. One shape of code for both worlds.
- No host reads inside the forward: nothing calls `.item()`, `len()` of a device array, or reads a
  Python int that changes per step. Shapes come from `batch.key` and array `.shape`.
- No allocation of scratch outputs: ops return fresh outputs (pad rows are zero). No `out` parameters.
- The embedding goes through `embed_tokens(table, batch)` (torch: `kelpie_models.batch`; jax:
  `kelpie_models.jax.batch`) so the multimodal override holds for every model.
- `x[batch.accept_index]` (`.long()` on torch) selects the rows whose logits are returned;
  `batch.last_token_index` is `accept_index[:, 0]`.
- Model files import their framework (torch / jax.numpy) for array ops only; never triton, flashinfer,
  aiter, torch.mps, pallas (tests/test_seam.py). Collectives are inline layout transitions in the
  forward (docs/decisions.md, Parallelism); they are not ops.

## 2. StepBatch = StepShape + device leaves (+ HostPlan beside it)

`kelpie_models/plan.py` is framework-free and both paths build their batch from its one `plan_step`
(torch `kelpie_models.batch.from_arrays`, jax `kelpie_models.jax.batch.from_arrays`; both return
`(batch, host)`).

```python
StepShape(padded_num_tokens=T, padded_num_reqs=R, K=0, mode="plain", dtype="float32", flags=())
```
Static: every distinct key is a trace + compile on the XLA path (and a graph capture later on CUDA).
`mode` is `plain | verify | draft`, `flags` carries `"override"` when
embedding-override rows are attached. Bucket ladders: eager `BUCKETS` (powers of two), compiled
`XLA_TOKEN_BUCKETS` 16..1024 x `XLA_REQ_BUCKETS` 1..16.

Device leaves (T tokens, R requests, P blocks per request, K drafts, W mask words), all fixed-size:

| leaf | shape / dtype | pad value |
|---|---|---|
| `input_ids`, `positions` | i32[T] | 0 |
| `slot_mapping[g]` | i32[T] per group; flat slot of the token's row (stride groups: its unit) | the scratch slot: last slot of null block 0 (never -1) |
| `query_start_loc` | i32[R + 1] | tail repeats `num_tokens` (empty queries) |
| `seq_lens` | i32[R]: context incl. this step | 1 |
| `block_tables[g]` | i32[R, P] per group | 0 (null block) |
| `req_ids` | i32[R]: the core's request slots (ring index of per-request state) | 0 |
| `num_seqs` | i32[1]: the real request count | |
| `temperatures` | f32[R], > 0: the core rewrites T < eps to T=1, top_k=1 at submit | 1 |
| `top_ks` | u32[R]; 1 = greedy, 0 = whole vocab (nothing else is written yet) | 1 |
| `sample_key` | u32[2]: this step's PRNG key (consumed as device data on both paths) | |
| `logit_mask` | i32[R, W], W = ceil(vocab / 32); bit v of word v // 32 set = token v allowed; W = 0 means no mask | all bits set |
| `kind` | i32[R]: KELPIE_KIND_PREFILL (0) / DECODE (1), the core's per-request decision (scheduler.zig `kindOf`: by position, never by row count -- a one-token prompt's chunk and a chunked prefill's one-row tail are prefills); the references assert a decode is 1 + `num_drafts` rows ending at seq_len - 1, a prefill has no drafts | 0 (prefill) |
| `num_drafts` | i32[R]: drafts a decode verifies (its rows = 1 + `num_drafts`) | 0 |
| `draft_ids` | i32[R, K] | |
| `accept_index` | i32[R, 1 + K]: rows whose logits are returned; `[:, 0]` = each request's last row | a real row |
| `attn` | per cache group, `Attn(backend, workspace)`: the backend that prepared this step and what its `prepare_workspace` returned (`step.plan_batch`, both paths; on the XLA path the workspace is hashable and part of the program key -- never the HostPlan) | |
| `inputs_embeds_override`, `override_positions` | multimodal (section 5); `None` when absent | |

Padding is inert by value: a pad token writes the scratch slot and attends nothing; a pad request has
an empty query, context 1 on the null block. The forward never masks on the host.

`HostPlan` (Python ints, real requests only: `num_reqs`, `num_tokens`, `query_start_loc`, `seq_lens`,
`req_ids`, `max_query_len`, `max_seq_len`, `rows(r) -> (q0, q1)`) is what the runner keeps beside the
batch. It is never a StepBatch field (the XLA pytree would retrace every step). Ops that loop per
request on the host read it through `host_plan(batch)`: the torch reference `ops.plan` stores it in
`batch.attn_metadata`; a kernel set that keeps any reference op exposes it as `.host` of what its
own `plan` returns. Ops that need it (all eager reference, torch path only): `attention`, `dsa_topk`,
`mla_attention`, `causal_conv1d`, `gated_delta_net`, and the model-level per-request loops of
`deepseek_v4` (compressor rings). A JAX `plan` must never return the HostPlan.

## 3. The kernel seam (`Ops`)

`ops.<name>` is the only way a model reaches a kernel. `kelpie_models/ops.py` (torch) and
`kelpie_models/jax/ops.py` hold the reference implementation of each op and are the oracle every
override is golden-tested against; `kelpie_models/kernels/{reference,mps,cuda}.py` and
`kelpie_models/jax/kernels/{reference,tpu}.py` each export `make_ops(cfg) -> Ops` and are the only
writers (a kernel set overrides fields with signature-identical callables; `Ops.__post_init__` asserts
parameter names). A kernel set is chosen at the composition root and checked against the model at
build; there is no registry. Ops present on both paths take the same parameter names in the same order
(tests/test_seam.py):

```python
plan(batch, host, kv) -> attn_metadata          # before the forward; jax: static + hashable
attention(q, k, v, batch, kv, member, group=0, window=0, sinks=None) -> (out[T, H*D], kv)
write_kv(kv, member, k, v, slot_mapping) -> kv
sample(logits[R, 1, V], temperatures, top_ks, key, logit_mask) -> tokens[R, 1]
    # extra rows and the accept rule are sdk/decide.py (greedy); rejection sampling is a TODO
kv_layout(cfg, group, dtype) -> KVLayout        # the attention kernel owns the physical layout
```
torch-only today (eager reference; a JAX model needing them adds the jnp reference first):
`write_cache(kv, member, x, slot_mapping) -> kv`, `dsa_topk(q, weights, batch, kv, member, group, topk)`,
`mla_attention(q, batch, kv, member, kv_b, dims, scale, group=0, topk=None) -> out`,
`causal_conv1d(x, weight, bias, batch, conv_state) -> (out, conv_state)`,
`gated_delta_net(q, k, v, g, beta, batch, state) -> (out, state)`, `grouped_mm`, `rope_interleaved`,
`rope_pairs`, `pool_windows`, `index_topk`, `sink_attention`; `rms_norm`, `layer_norm`, `silu_mul`,
`gelu`, `rope` exist on both.

Sampling is an op so it can run inside the compiled program (one dispatch per step, only ids come
back) and so grammar masks / rejection sampling are a mask value / a K > 0, not a new parameter. The
step program is `logits = forward(...)` then `tokens = ops.sample(...)`; fusing them is a kernel-set
choice (the runner may launch them separately). The torch reference derives deterministic per-row
Gumbel-max draws from `sample_key` with device-side Philox-4x32-10; its counter tuple makes a future
Triton or JAX/Pallas implementation bitwise reproducible. It never reads the key on the host or seeds
a `torch.Generator`. It applies `logit_mask` before selection, reaches a greedy row's argmax through
its top-1 filter (the T=0 rule), and emits token id 0 for an all-masked row so the grammar layer can
report it.

## 4. KV cache and per-request state

- `derive_groups(attn_specs(cfg), itemsize)` (kelpie_models.groups) turns each layer's `AttnSpec`
  into cache groups the core sees (`kind, stride, retention, cacheable`) and gives every layer its
  `[(group, member)]`. Groups are keyed by lifetime only; members of different byte sizes share a
  group and a block table.
- `ops.kv_layout(cfg, group, dtype) -> KVLayout(rows)` decides, per member, the row shape after
  `[num_blocks, block_size]`; `alloc_kv(num_blocks, block_size, layout, dtype[, device])` allocates it
  (`kelpie_models.kv` / `kelpie_models.jax.weights`; `runner.alloc_model_kv` does the whole model). The
  reference layout on both paths: a KV member is `[num_blocks, block_size, 2 * Hkv, D]` with k on even
  and v on odd heads (the ragged_paged_attention layout); an opaque member (MLA latent, indexer K, DSV4
  rings and compressed entries) is `[num_blocks, block_size, width]`. The TPU kernel set pads heads /
  head_dim to what its kernel accepts. Never a stacked `[n_members, ...]` array.
- Block 0 is the null block: never allocated, the target of pad slots (its last slot is the scratch
  slot) and of slid-out window rows.
- Per-request state (recurrent blobs, compress rings) is NOT a core group: `alloc_state_ring(specs,
  max_requests, dtype, device)` builds one `StateRing` indexed by the request slot (`batch.req_ids`,
  read on the host through `HostPlan.req_ids` / `request_slots(batch)`); ring depth R = 1 + K later.
  Lifecycle is derived from the batch: a chunk starting at context 0 is fresh. Such a model runs with
  `prefix_cache=False` (kelpie_models.bridge.bind asserts it).

## 5. Multimodal (as built: SmolVLM-256M, kelpie_models/models/torch/smolvlm.py)

- Placeholder token ids fill the prompt at image positions; the core sees only ids. `mm_hash: u64`
  (+ `mm_start`) rides the request through submit/plan and forks the prefix chain from the first image
  block (prefix.zig).
- `set_override(batch, host, rows, emb) -> batch` attaches `[n_override, hidden]` embeddings at flat
  rows (`StepShape.flags` gains `"override"`); `embed_tokens` applies `x[rows] = emb`.
- Encoder scheduling (`kelpie_models.multimodal.EncoderScheduler`) is model-agnostic: the payload is
  attached per request id right after submit and detached at finish / cancel (`kelpie.KelpieCore`);
  each step the placeholder positions that fall in a planned chunk become override rows; the encoder
  runs once per request and is cached until consumed. Not on the XLA path yet (would need a fixed
  `[n_override_bucket, hidden]` leaf).

## 6. What surrounds a forward (`ModelState` + `ModelStep`)

Resources are owned by one object; the step is a separate artifact per `StepShape`:

```python
state = ModelState(w, cfg, ops, engine_cfg=cfg, device=..., dtype=...)   # allocates kv + ring
step  = capture_model_step(ModelStep.shape_for(plan, state), state, mode="eager")  # tier 1
step.fill(plan, seed=(0, n))          # copies the plan into the leaves; runs ops.plan
step.launch_forward()                 # mod.forward(w, cfg, batch, kv, state, ops)
step.launch_sample()                  # ops.sample -- separate: grammar writes logit_mask here
step.wait(); tokens = step.read_tokens()   # u32[num_reqs]
commit(tokens, ...)                   # kelpie-py Engine.commit payload
state.close()                         # frees kv + ring; never touches w
```
`kelpie_models.runner.run_step` is the rung beneath: the same plan -> forward -> sample in one
call, and what the eager `ModelStep` is tested equal to (`tests/test_launch_shape.py`).
The bridge (`kelpie_models.bridge`, `kelpie_models.jax.bridge`) binds a loaded model to a kelpie-py
`EngineConfig`: checks the engine's groups against `derive_groups`, allocates KV in the kernel set's
layout and the state ring, and exposes `model_fn(plan) -> u32[num_reqs]` to `kelpie.KelpieCore`.
`kelpie_models.launch.build(module, checkpoint, kernels, engine_cfg, device, dtype)` is the one
composition function `examples/main.py` and `kelpie serve` both call.

## 7. Correctness

`tests/oracle/`: BudgetTolerance against an HF fp64 truth, synthetic rolled-config models
(`test_synthetic.py`), the frozen real-checkpoint corpus `tests/oracle/corpus/<model>/<case>.npz`
(StepBatch arrays + HF fp32 logits; a model without files is reported UNVALIDATED). Every model keeps:
golden logits vs HF eager, chunked == one-shot, decode through the returned kv, padding inert by value,
greedy text == `hf.generate`; the JAX models run the SAME corpus (`tests/test_jax_corpus.py`).

## 8. Additive from here (v1 frozen)

Everything above is used by eight models and two paths; changes are additive only: new `Ops` fields
(with a reference on the path that adds them), new `StepBatch` leaves with an inert default, new
`StepShape` fields with a default, new `AttnSpec` kinds, a `StateRing` field. Reserved and shaped
already: `K > 0` (`draft_ids`, `accept_index[:, 1:]`, `num_drafts`, rejection sampling in `sample`,
`mode=verify|draft`, ring depth 1 + K), grammar masks (`logit_mask` values), sharding annotations on
the weight dataclasses' fields, the multimodal override on the XLA path.
