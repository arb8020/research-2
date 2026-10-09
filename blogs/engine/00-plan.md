# inference engine: curriculum plan

<!-- wip: plan only. headings, facts and prose placeholders; no prose yet -->

<!-- write prose here: what the reader builds over the series, and that kelpie becomes this -->

## architecture

<!-- write prose here: the three processes and why the engine sits in the middle -->

- three processes:
  - frontend (Python): HTTP, chat templates, tokenizer
  - engine (systems language): single-threaded loop; central scheduler
  - worker(s) (Python, torch): `forward(plan) -> tokens`; one per device group
- engine loop, each step: read ops -> plan -> send plan to workers -> receive tokens -> commit -> stream tokens
- frontend <-> engine <-> worker(s)
- the engine never touches CUDA
- transport:
  - first: JSON lines over a socketpair
  - later (perf chapter): shared-memory ring
- process setup: Heinrich pattern (spawn + socketpair + memfd)
- engine language: Zig (tentative; C-style C++ considered)
  - checks are language-agnostic (protocol / HTTP / trace text), so a reader may bring another systems language
  - one blessed language gets stubs and solutions
- model forward: reader-written Python (torch functional); kernel dispatch is a later perf chapter

### scheduler core

<!-- write prose here: why the scheduler is sans-IO and deterministic, and what that buys later -->

- sans-IO and deterministic: `(state, ops) -> plan`; `commit(tokens)`
- door-open rules:
  - no clocks, randomness or thread timing in planning
  - ops are an ordered log, applied at step boundaries
  - the plan is a wire format, never pointers
  - transport is swappable (shm local, TCP remote)
- replay test, kept forever: two cores, same ops log -> identical plans
- scheduling checks use greedy decoding

## check boundaries

<!-- write prose here: what a check is in this series, and why each one sits at a boundary the reader's code can be swapped across -->

- `[HF]` vs the HuggingFace reference
- `[HTTP]` black box over HTTP
- `[proto]` the harness plays the other side of the wire protocol
- `[trace]` text traces (kelpie-core/traces) fed to the scheduler as data
- `[equiv]` feature on == feature off
- `[budget]` perf threshold on fixed hardware

## chapters

### 1. model forward

<!-- write prose here: chapter 1 intent -->

- writes: Python torch functional forward + full-recompute generate
- model / hardware: gpt2 -> qwen3-0.6b; CPU
- checks:
  - `[HF]` logits within tolerance on fixed prompts
  - `[HF]` 32 greedy tokens identical

### 2. sampling

<!-- write prose here: chapter 2 intent -->

- writes: temperature / top-k / top-p; per-request seed
- checks:
  - `[equiv]` temperature 0 == greedy
  - same seed -> same tokens
  - chi-square vs the reference distribution

### 3. HTTP frontend

<!-- write prose here: chapter 3 intent -->

- writes: OpenAI `/v1/completions` + chat; SSE; disconnect
- model: echo model, then the chapter 1 generate
- checks:
  - `[HTTP]` goldens for echo
  - SSE framing
  - disconnect stops work

### 4. engine process + worker

<!-- write prose here: chapter 4 intent -->

- writes:
  - engine owns the step loop
  - worker = `forward(plan) -> tokens`
  - frontend <-> engine: submit / cancel / token stream
- checks:
  - `[proto]` fake worker vs the reader's engine; fake engine vs the reader's worker
  - `[HTTP]` end-to-end tokens == chapter 1
  - killed worker -> clean error, not a hang

### 5. KV cache + streaming

<!-- write prose here: chapter 5 intent -->

- writes: single request, contiguous KV
- checks:
  - `[equiv]` incremental logits == full recompute
  - `[budget]` decode step ~flat in prompt length

### 6. multi-rank (TP)

<!-- write prose here: chapter 6 intent -->

- writes: N workers, engine broadcasts the plan; weights sharded + all-reduce in forward
- hardware: gloo on CPU for dev; A100-80GB:2 later
- checks:
  - `[equiv]` TP2 tokens == TP1
  - `[proto]` dead rank detected cleanly

### 7. multiple users: static batching

<!-- write prose here: chapter 7 intent -->

- writes: pad to a rectangle
- checks:
  - `[equiv]` each request's batched output == solo
  - `[budget]` throughput > N sequential

### 8. continuous batching

<!-- write prose here: chapter 8 intent -->

- writes: admit / finish each step; per-slot KV; ragged forward; scheduler as a pure function
- checks:
  - `[trace]` basic traces
  - `[equiv]` batched == solo
  - `[budget]` beats static under staggered arrivals

### 9. paged KV + block tables

<!-- write prose here: chapter 9 intent -->

- checks:
  - `[trace]` block accounting (free count returns, no double owner)
  - `[equiv]` paged == dense
  - more concurrent requests in the same memory

### 10. admission + preemption

<!-- write prose here: chapter 10 intent -->

- checks:
  - `[trace]` kv_stall, preemption, reserve_*
  - `[equiv]` under memory pressure, all finish == solo

### 11. chunked prefill

<!-- write prose here: chapter 11 intent -->

- writes: per-step token budget
- checks:
  - `[trace]` chunked_prefill
  - `[equiv]` chunked == unchunked
  - `[budget]` inter-token latency bounded while a long prompt arrives

### 12. prefix cache

<!-- write prose here: chapter 12 intent -->

- checks:
  - `[trace]` prefix_*
  - `[equiv]` hit == miss
  - `[budget]` TTFT drops on a shared prefix

### 13. cache groups / SWA + MoE

<!-- write prose here: chapter 13 intent -->

- model: gpt-oss tiny config, then 20b
- checks:
  - `[HF]` gpt-oss
  - `[trace]` window traces
  - KV memory bounded by the window

### 14. multimodal

<!-- write prose here: chapter 14 intent -->

- model: smolvlm
- writes: encoder in the worker; mm_hash folded into the prefix chain
- checks:
  - `[HF]`
  - `[trace]` prefix_mm (same text, different image != hit)

### 15. buckets, kernel dispatch, CUDA graphs

<!-- write prose here: chapter 15 intent -->

- writes: buckets -> kernel dispatch -> CUDA graphs; plan transport JSON -> shm ring, measured
- checks:
  - `[equiv]` padded == unpadded
  - `[budget]` step time
  - graphs replay

### 16. structured output

<!-- write prose here: chapter 16 intent -->

- writes: grammar masks
- checks:
  - 100% of outputs parse against the schema
  - `[equiv]` permissive grammar == no grammar

### 17. spec decode

<!-- write prose here: chapter 17 intent -->

- writes: n-gram drafter -> DFlash
- checks:
  - `[equiv]` greedy spec == no-spec
  - `[budget]` acceptance, tok/s

### 18. hybrid / recurrent state

<!-- write prose here: chapter 18 intent -->

- model: qwen3-next or kimi-linear
- checks:
  - `[trace]` state_*, per_seq_*
  - `[HF]`

### 19. another backend

<!-- write prose here: chapter 19 intent -->

- writes: torch-xla worker (TPU / Trainium)
- checks:
  - every earlier check() passes with the worker swapped

## open questions

- multi-rank at chapter 6 vs right after chapter 4
- split chapter 4 (engine split + two protocols + first Zig) into two
- chapter 1 model: gpt2 only, or move to qwen3-0.6b
- an "after the core" section: async/overlap, KV quantization, batch invariance, benchmarking
- engine language, final pick: Zig vs C-style C++
- multi-host TPU: central-over-TCP vs replicated (deferred; door kept open)

## sources

- `kelpie/NOTES-slices.md`
- `kelpie/docs/decisions/overlap-removed.md` (on branch `kelpie/core-compress`)
- `kelpie-core/traces/`
- `~/dotfiles/docs/raw/how_to_test_matklad.md`
- `~/dotfiles/docs/raw/heinrich_multiprocessing.md`
- `~/work/crucible/crucible/other/inference_curriculum/ROADMAP.md` (2026-08-27)
