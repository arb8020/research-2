# StepBatch: field × reader analysis

Survey of `StepBatch` (`kelpie-models/kelpie_models/plan.py:65-101`) — 21 fields, all `Any` —
against every reader in the tree. Read-only survey; no code changed.

Context taken as given (not re-derived): an earlier decision (the Zig core will emit a bucket-padded
plan; Python fill becomes a memcpy; Triton reads kinds/row_request on the GPU; `TritonWorkspace`
dies).

---

## 0. Two facts that reframe the question before the matrix

**There are three types called `StepBatch` in this repo**, not one:

| Type | File | Shape | Who fills it |
|---|---|---|---|
| **The wire batch** | `kelpie-py/kelpie/engine.py:91` — 19 fields | *unpadded* numpy views over Zig buffers, ints for the host values | `step_batch_from_plan` from `KelpiePlan` |
| **The device batch** (the subject) | `kelpie-models/kelpie_models/plan.py:65` — 21 fields, all `Any` | *padded* device leaves + `key` + late-attached `attn`/`taps` | `plan_step`/`build_batch` |
| — | `kelpie-models/kelpie_models/jax/batch.py` | **the same 21 fields**, no new type | pytree registration only |

**Item 6 answered directly:** `jax/batch.py` is *not* a second field set. It imports
`plan.StepBatch` and registers it as a pytree; `DATA_FIELDS = LEAF_FIELDS + OVERRIDE_FIELDS`,
aux = `(key, attn-as-content, taps-as-content)`. The only jax-specific divergence is that
`attn`/`taps` are unpacked-and-rebuilt by content because `Attn` is `eq=False` and `Taps` is
mutable — i.e. **jax already pays a tax specifically for `attn`/`taps` living inside the batch**.
It re-derives them at every unflatten. The real "second batch" is the wire one in `kelpie-py`,
and *that* one is the near-neighbor of the proposed partition (see §4).

Second fact: `StepShape.K` is **0 at every construction site in the repo** (`plan.py:34` default,
never overridden). So `draft_ids` is `i32[R, 0]`, `accept_index` is `i32[R, 1]`, and
`last_token_index == accept_index[:,0] == accept_index.squeeze()`. Every spec-decode field is
currently a zero-width placeholder. That matters for the partition: `draft_ids` / `num_drafts` /
`accept_index` are not exercised as independent data yet.

---

## 1. Field × reader matrix

`R` = read, `W` = written in place, `P` = passed through whole (`batch` handed on unread),
`·` = untouched. Test-only readers collapsed into one column.

| # | field | model forwards<br>(gpt2/qwen3/llama/gpt_oss/smolvlm, jax/gpt2, jax/qwen3) | attn backends<br>(kernels/attention, backend, cuda/_triton, tpu/_pallas, neuron/_dense, jax/attention, mla, dsa) | sampler<br>(step.SamplerInputs, jax/bridge.program) | step.py | runner.py / graph.py | multimodal / grammar | tests+scripts |
|---|---|---|---|---|---|---|---|---|
| 1 | `key` | · | · | · | R (`key.K`, `key.taps`) | R (`shape_for` compare, `copy_leaves` gate) | · | R |
| 2 | `input_ids` | **R** (`embed_tokens`; gpt_oss `.device`) | · | · | · | R (fill/copy) | · | R |
| 3 | `positions` | **R** (all 7) | R (`check_kinds` only) | · | · | R (fill) | · | R |
| 4 | `slot_mapping` | · | **R** (every backend: `write_kv`) | · | · | W (graph warmup `fill_`) | · | R |
| 5 | `query_start_loc` | · | **R** (jax/attn, neuron, tpu, triton, `.device`) | · | · | R (fill) | · | R |
| 6 | `seq_lens` | · | **R** (jax/attn, tpu, triton) | · | · | R (fill) | · | R |
| 7 | `block_tables` | · | **R** (every backend) | · | · | W (graph warmup `zero_()`) | · | R |
| 8 | `req_ids` | · | · | · | · | fill only | · | R (tests) |
| 9 | `num_seqs` | · | R (**tpu/_pallas, jax/attention only**) | · | · | fill only | · | R |
| 10 | `temperatures` | · | · | **R** | R (`SamplerInputs.of`) | fill only | · | R |
| 11 | `sample_key` | · | · | **R** | R | fill only | · | R |
| 12 | `logit_mask` | · | · | **R** | R | **W** (`fill_logit_mask`) | W (grammar) | R |
| 13 | `kind` | · | **R** (`check_kinds`, triton `prepare_workspace`) | · | · | fill only | · | R |
| 14 | `num_drafts` | · | R (`check_kinds`, triton) | **R** | R | fill only | · | R |
| 15 | `draft_ids` | · | · | **R** | R | fill only | · | R |
| 16 | `accept_index` | **R** (all 7: `x[accept_index]`) | · | · | · | fill only | · | R |
| 17 | `attn` | **R** (`batch.attn[g].backend.forward`) | **R** (`batch.attn[g].workspace`) | · | W (`plan_batch`) | R (`copy_workspace` pairs) | · | R |
| 18 | `taps` | **R** (`taps.put`) | · | · | W + assert | R (`graph.taps`) | · | R |
| 19 | `inputs_embeds_override` | R (gpt2 via `embed_tokens`, gpt_oss inline) | · | · | W (`set_override`) | · | R | · |
| 20 | `override_positions` | R (same two) | · | · | W | · | R | · |
| 21 | — properties — | | | | | | | |
| p1 | `padded_num_tokens` | · | R (triton, tpu, gdn) | · | R (`taps.check_complete`) | · | · | R |
| p2 | `padded_num_reqs` | · | R (triton, backend asserts, gdn) | · | R (logits assert) | · | · | R |
| p3 | `last_token_index` | · | · | · | · | · | · | **R (test_golden only)** |

### Dead / near-dead on the real path

- **`req_ids` (device leaf)**: read by **zero** production readers. It is staged by `launch.c`
  (`SRC` slot 6), copied by `copy_leaves`, and read only by tests. Everything that actually wants
  request identity uses `host.req_ids` (a `HostPlan` tuple of ints) or `plan.req_ids` (the wire
  batch, via `sample_key` and `multimodal.overrides`). **Cost: one device leaf carried through
  every step for nobody.**
- **`last_token_index`**: one reader, `tests/test_golden.py:116`.
- **`num_seqs`**: two readers, both XLA-only (`tpu/_pallas.py:100`, `jax/attention.py:97`). The
  torch path never reads it; it exists because Pallas's `ragged_paged_attention` wants `i32[1]`.
  It is a *device-resident copy of `host.num_reqs`*.
- **`draft_ids`**: shape `[R, 0]` at every site. Reaches the sampler as an always-empty tensor.

---

## 2. Writers

| Site | Constructs / mutates | Fields `None` or degenerate at that point |
|---|---|---|
| `plan.py:214 build_batch` | constructs, `key=` + 17 leaves | `attn=None`, `taps=None`, both override fields `None` |
| `jax/batch.py:111 _unflatten` | reconstructs from pytree | rebuilds `attn` from `(backend, workspace)` pairs, `taps` from the wanted set — every jit trace |
| `step.py:78 batch_for` | `replace(key=replace(key, taps=...))` | still unplanned |
| `plan.py:246 with_override` | `replace(key=…flags+override, override_positions, inputs_embeds_override)` | still `attn=None`, `taps=None` |
| `step.py:101 plan_batch` | `replace(attn=…, taps=…)` — **the only place the batch becomes usable** | asserts `taps is None` first (confusion-map #4) |
| `graph.py:73/112` | calls `plan_batch`, then `copy_leaves` into the captured `self.inputs` | — |
| tests (`test_cuda_triton_attention`, `prove_paged_attn`, `spike_paged_attn`) | `replace(batch, attn=(Attn(backend, ws),)*n)` | they hand-build the planned half to compare two backends |

Note the writer asymmetry: **17 fields are written once, at construction, and never again. 4
fields (`attn`, `taps`, the two override fields) are written in a second pass, by a different
module, and are `None` in between.** That is confusion-map #4 stated as a write-frequency fact
rather than a type fact.

---

## 3. Frame table — the Casey test

Real request path: `ModelRunner.__call__` → `_step` → (`run_step` | `Graph.fill/launch`) →
`plan_batch` → `mod.forward` → `sample_step`.

| Frame | Reads from the **wire** plan | Reads from `StepBatch` | Reads from `HostPlan` |
|---|---|---|---|
| `runner.__call__` (`runner.py:332`) | `plan.num_reqs` | — | — |
| `graph.shape_for` (`graph.py:39`) | `query_start_loc`, `num_reqs` | — | — |
| `runner._step` (`runner.py:359`) | `req_ids`, `seq_lens` (→`sample_key`) | — | — |
| `runner._override` → `multimodal.overrides` | `num_reqs`, `req_ids`, `query_start_loc`, `positions`, `n_work` | — | — |
| `step.batch_for` (`step.py:51`) | all 10 core arrays | writes all 17 leaves | builds it |
| `step.plan_batch` (`step.py:83`) | — | `taps` (assert), `key.taps`, **passes `batch` whole** to `prepare_workspace` | passes whole |
| `backend.prepare_workspace` | — | `block_tables`, `slot_mapping`, `kind`, `num_drafts`, `positions`, `query_start_loc`, `padded_num_*` | `num_reqs`, `num_tokens`, `seq_lens`, `rows()` |
| `mod.forward` (gpt2/qwen3/llama/gpt_oss) | — | `taps`, `input_ids`, `positions`, `accept_index`, `attn[g].backend`, (+ 2 override fields) — **6 of 21** | — |
| `backend.forward` (inside the layer loop) | — | `slot_mapping[g]`, `block_tables[g]`, `seq_lens`, `query_start_loc`, `attn[g].workspace`, (`num_seqs` on XLA) — **6 of 21** | via `host_plan(batch)` on the reference path |
| `step.sample_step` | — | `temperatures`, `sample_key`, `logit_mask`, `draft_ids`, `num_drafts` — **5 of 21**, already extracted into `SamplerInputs` |
| `graph.fill` / `copy_leaves` | — | **all 17 leaves**, by name, blindly | `num_reqs` |
| `step.read_tokens` | — | — | `num_reqs` |

**The verdict this table gives:** no frame reads more than 6 of the 21 fields, and the three
reader frames (forward / backend.forward / sample) have **near-disjoint** field sets. The only
frame that touches all 21 is `copy_leaves` — which touches them *as an undifferentiated list of
tensors to memcpy*, not as named fields. That is exactly the "fields don't travel together"
signal: after decision 5 lands, `copy_leaves` becomes one memcpy of a contiguous region and stops
being a field-by-field reader at all, at which point **nothing** in the codebase reads all 21
together.

`SamplerInputs` (`step.py:31`) is the partition already half-done and already proven: someone
extracted the sampler's 5 fields *because the CUDA graph needed to hold them separately across a
capture boundary*. It travels as a real value; the split cost nothing.

---

## 4. Proposed partition (as data)

Clustering the 21 fields by the frames of §3:

**(a) What the forward reads — 4 + 2 optional**
`input_ids`, `positions`, `accept_index`, `taps`; `inputs_embeds_override`, `override_positions`.
Confirmed. Every one of the 7 forwards reads exactly this set and nothing else. `kind` is **not**
here (refuted — no forward reads `kind`). The attn handle is here only as a *routing* value
(`batch.attn[g].backend`), not as data.

**(b) What attention backends read — 6**
`slot_mapping`, `query_start_loc`, `seq_lens`, `block_tables`, `kind`, `num_drafts`, plus
`num_seqs` (XLA only) and `positions` (`check_kinds` only). `attn[g].workspace` is the handle.
Confirmed, with two leaks named below.

**(c) What the sampler reads — 5**
`temperatures`, `sample_key`, `logit_mask`, `draft_ids`, `num_drafts`.
**Confirmed and already implemented** as `SamplerInputs`. `req_ids` is **not** here (refuted —
the sampler never sees request identity; ordering is positional).

**(d) What only fill/runner reads — 2**
`req_ids` (nobody reads it at all), `num_seqs` (only two XLA readers, and it duplicates
`host.num_reqs`). Confirmed, and stronger than the hypothesis: this cluster is not
"runner-only", it is **"nobody"**.

**(e) The per-runner half of `key`** — `dtype`, `mode`, `flags`, `taps`. Confirmed; handoff
decision 5 already carves `StepShape` this way (the core supplies
`padded_num_tokens`/`padded_num_reqs`, the runner supplies the rest).

### Cross-cluster fields — the hard ones

| field | clusters | why it crosses |
|---|---|---|
| **`num_drafts`** | (b) **and** (c) | the backend reads it to decide "decode with 0 drafts → skip"; the sampler reads it to bound acceptance. Genuinely two consumers, genuinely the same number. Today `K=0` makes it all-zeros, so the duplication is invisible. |
| **`positions`** | (a) **and** (b) | forwards use it for RoPE/wpe (real data); backends use it *only inside `check_kinds`*, an assertion. If the assert moved to the plan builder, `positions` would be cluster (a) alone. |
| **`kind`** | (b) only, but **also crosses process boundary** | the Zig core computes kinds, the wire batch carries them, the device leaf carries them, and per decision 5 Triton reads them on the GPU. It is the one field whose whole point is to travel from the core to a kernel untouched by anything in between. |
| **`query_start_loc` / `seq_lens`** | (b) **and** `HostPlan` | each exists twice — as a device leaf *and* as a tuple of Python ints in `HostPlan`, which reaches kernels through `attn[0].workspace` (confusion-map #10). Two representations, two travel routes, one meaning. |
| **`taps`** | (a) **and** `key` | `key.taps` is the wanted set (part of the program identity); `batch.taps` is the collector. Same word, two things. |
| **`attn`** | (a) **and** (b) | (a) reads `.backend` to dispatch; (b) reads `.workspace` for data. One field serving as both a vtable and a data pointer. |

### The shape the data actually suggests

Not 5 structs — **3 device-data structs + 2 handles**:

```
Tokens   { input_ids, positions, accept_index }          # T-shaped, per-token
Requests { query_start_loc, seq_lens, block_tables,      # R-shaped, per-request
           slot_mapping, kind, num_drafts }
Sampling { temperatures, sample_key, logit_mask, draft_ids }   # == SamplerInputs, minus num_drafts
Attn     { backend, workspace } per group                # already exists
Taps                                                     # already exists
```

with `key` outside as the program identity, the two override fields as an optional `Embeds` on
`Tokens`, and `req_ids` / `num_seqs` / `last_token_index` deleted (the first has no reader; the
second is `host.num_reqs` on device and belongs in the XLA backends' workspace; the third is a
property with one test reader).

`num_drafts` is the one field this doesn't cleanly place — it is honestly per-request *and*
honestly a sampler input. The matrix says duplicate it or put it in `Requests` and let `Sampling`
reference `Requests`; it does not say which.

---

## 5. Usage-code pair — gpt2 forward

**Today** (verbatim structure from `gpt2.py:80-111`, condensed):

```python
def forward(w, cfg, batch: StepBatch, kv, state, kernels):
    k, taps = kernels, batch.taps                  # field 18 of 21
    x = embed_tokens(w.wte, batch) + w.wpe[batch.positions.long()]
    #   ^ embed_tokens reads batch.input_ids, batch.inputs_embeds_override,
    #     batch.override_positions — three more, invisibly, through the whole batch
    kv0 = kv[0]
    for i, layer in enumerate(w.layers):
        h = k.layer_norm(x, layer.ln_1.w, layer.ln_1.b, cfg.eps)
        qkv = h @ layer.attn_qkv.w + layer.attn_qkv.b
        q, kk, v = (t.view(-1, cfg.n_heads, cfg.head_dim) for t in qkv.split(cfg.hidden, -1))
        o, kv0 = batch.attn[0].backend.forward(q, kk, v, batch, kv0, i)
        #   ^ hands the WHOLE batch down; the backend reaches into 6 more fields
        #     and, on the reference path, into host_plan(batch.attn[0].workspace)
        x = x + o @ layer.attn_proj.w + layer.attn_proj.b
        h = k.layer_norm(x, layer.ln_2.w, layer.ln_2.b, cfg.eps)
        x = x + k.gelu(h @ layer.fc.w + layer.fc.b) @ layer.proj.w + layer.proj.b
        taps.put("resid_post", i, x, "T D")
    last = k.layer_norm(x[batch.accept_index.long()], w.ln_f.w, w.ln_f.b, cfg.eps)
    return last @ w.wte.T, [kv0], None, taps
```

The forward touches 6 fields and passes 21 to a callee twice.

**Against the clusters** (sketch, no implementation):

```python
def forward(w, cfg, tok: Tokens, reqs: Requests, attn: Attn, taps: Taps, kv, state, kernels):
    k = kernels
    x = tok.embed(w.wte) + w.wpe[tok.positions.long()]   # override lives inside Tokens
    kv0 = kv[0]
    for i, layer in enumerate(w.layers):
        h = k.layer_norm(x, layer.ln_1.w, layer.ln_1.b, cfg.eps)
        qkv = h @ layer.attn_qkv.w + layer.attn_qkv.b
        q, kk, v = (t.view(-1, cfg.n_heads, cfg.head_dim) for t in qkv.split(cfg.hidden, -1))
        o, kv0 = attn.forward(q, kk, v, reqs, kv0, i)     # backend gets exactly what it reads
        x = x + o @ layer.attn_proj.w + layer.attn_proj.b
        h = k.layer_norm(x, layer.ln_2.w, layer.ln_2.b, cfg.eps)
        x = x + k.gelu(h @ layer.fc.w + layer.fc.b) @ layer.proj.w + layer.proj.b
        taps.put("resid_post", i, x, "T D")
    last = k.layer_norm(x[tok.last_rows.long()], w.ln_f.w, w.ln_f.b, cfg.eps)
    return last @ w.wte.T, [kv0], None, taps
```

The signature grows from 6 params to 8 and the body loses nothing. What changes is that the two
`batch`-passed-whole calls become calls that name their inputs, and the model author reading this
signature learns the whole contract without reading `plan.py`. The `Requests` struct — 6 fields,
`T`/`R`-shaped, produced by the core — is close to what the wire `StepBatch` already is.

---

## 6. Three things I'm least sure of

1. **Whether `num_seqs` can actually be deleted.** It is `i32[1]` on device with two readers
   (`tpu/_pallas.py:100`, `jax/attention.py:97`). Under jit, `host.num_reqs` is a Python int and
   would bake into the trace — which is fine given the bucket ladder makes it constant per
   program, but `_pallas.py`'s docstring says the Pallas kernel wants it as a device array
   specifically so rows past `cu_q_lens[num_seqs]` can be masked at runtime. I did not confirm
   whether Pallas would accept a static int there. If it needs the array, `num_seqs` belongs in
   the TPU backend's workspace rather than the batch — but that is a claim about Pallas, not
   about this repo.

2. **Whether `attn` can leave the batch.** `plan.py:217 host_plan(batch)` and confusion-map #10
   both flag that `HostPlan` rides inside `attn[0].workspace`, with a stated caveat that the
   workspace object may be the only thing whose *address* survives CUDA graph capture.
   `graph.py:114-118` does `copy_workspace(old.workspace, new.workspace)` into the captured
   object, which is consistent with that constraint being real. If it is, `attn` cannot become a
   plain parameter without a separate fix for capture-time identity, and my partition's "Attn as
   a handle passed alongside" is under-specified about where the handle is stored between
   `plan_batch` and the forward.

3. **Whether the spec-decode fields are genuinely three fields.** `K == 0` everywhere, so
   `draft_ids` is `[R,0]`, `accept_index` is `[R,1]`, `num_drafts` is all-zeros, and
   `last_token_index` is a trivial view. I clustered them from their *declared* semantics and
   from `check_kinds` / `_triton.prepare_workspace`, not from live data — no test in the tree
   exercises `K > 0`. If spec-decode lands with a different shape (per-request K, ragged drafts),
   the (b)/(c) split of `num_drafts` and the placement of `accept_index` in cluster (a) could
   both move.
