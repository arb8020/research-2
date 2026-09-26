# kelpie

An inference engine as a library: a Zig scheduler, Python model files you can read, and an
OpenAI-shaped HTTP front. You write `main()`, `forward`, `load`; kelpie schedules, pages the KV,
captures the step, and serves. Spec: `docs/complaints.md`. Rules: `docs/CODING_STANDARDS.md`.
Decisions: `docs/decisions.md`. Plan: `docs/roadmap.md`. Models: `docs/ladder.md`.
Decisions in order: `BREADCRUMBS.md`. Debt: `PAPERCUTS.md`.

## Status

Legend: `[x]` on main and proven on its device, `[~]` built on a branch / partly true, `[ ]` not started.

### Core (Zig, `kelpie-core`)
- [x] continuous batching: plan / commit per step, one loop, no prefill/decode split in the model
- [x] chunked prefill mixed with decodes, block-aligned chunks
- [x] paged KV with cache groups (full, sliding, per-group block tables), null block, scratch slot
- [x] prefix cache (hash chain over blocks)
- [x] preemption by eviction order; skip/rotate while a plan is outstanding
- [x] explicit entry `kind` (prefill / decode) + `n_drafts`, decided by position
  - [~] `kind` / `n_drafts` read below the ABI (`feat/kind-from-core`: StepBatch leaves, reference asserts, Triton partitions on kind)
- [x] native Zig step loop calling a C launch pointer per step shape; Python stepper deleted
- [x] one-step overlap in Zig (bitwise == off; default off, within noise at 0.6B)
- [x] grammar matching in Zig (xgrammar vendored, extern-C shim), logit mask into the step
  - [ ] serve wires `vocab_words` (every `response_format` request 500s today; `prove_json_schema` catches it)
  - [ ] grammar compile-only in Python; delete the Python matcher (`TODO(grammar-artifact)`)
- [x] live knobs (tier 0: pick another graph; tier 1: recapture; tier 2: drain + swap launch)
  - [ ] tiered config beyond tier 0 (`[kernels]` TOML, per-request seed, ...)
- [ ] per-request sample `seed` through submit / ABI / plan
- [ ] recurrent-state snapshots for prefix cache on hybrid models (StateRing stays Python-owned until a model needs a branch)

### Models (`kelpie-models`)
- [x] one `forward(w, cfg, batch, kv, state, k)` per model file; no host reads; padding inert by value
- [x] CUDA graph capture: forward + sample graphs on fixed leaves, bucket ladder, precapture at build
- [x] tp / ep sharding as explicit collectives in the forward (shardlib strings; torch + JAX)
- [x] multimodal via embedding override at the boundary (SmolVLM slice)
- [x] kernel seam (catalog flattened 2026-09-09): kernels are values on `ModelState`, `k = for_device(device, **overrides)` where an override is a VALUE, one plain `kernels/devices/<dev>.py` per device overlaying the reference by name, signature-checked at build; three op kinds (math / tables / backend)
  - [x] gpt2, gpt_oss, qwen3, llama, smolvlm ported; `--kernels '{"layer_norm":"my_ln.layer_norm"}'`
  - [ ] deepseek_v32 / v4 on `mla_attention` + `dsa_attention` (reference)
  - [ ] qwen3_next on `attention` + `gdn` (groupless workspace slot to decide)
  - [ ] JAX twin (`jax/attention.py`: RPA / NKI) + the four CUDA scripts
  - [ ] verified on CUDA (Triton), Trainium, TPU; merged to main
- [x] activation taps (merged): `resid_post` per layer, layout asserted replicated, `StepShape.taps` in the program key, forward returns `(logits, kv, state, taps)`, `--taps`
  - [ ] taps proven captured on CUDA (pending)
- [x] Triton kernels on cuda: paged attention (prefill + decode), rms_norm, rope, silu_mul, sample
- [x] Metal `layer_norm` / `gelu` on mps (opt-in demo; slower than the fused MPS op)
- [ ] MLA / DSA / GDN / KDA kernels (M7); today reference only
- [ ] ladder rungs 03/04/06/08/09 (`docs/ladder.md`)
- [ ] `torch.export` / AOTI artifact per StepShape (the artifact DAG)

### Serving (`kelpie-http`, `kelpie-engine`)
- [x] OpenAI chat + completions, SSE streaming, JSON mode (`response_format`), `/v1/kelpie/{config,stats}`, `/metrics`, `/health`
- [x] chat templates + tool-call / reasoning parsers with streaming deltas
- [x] `kelpie serve --model <module> --device --kernels --taps [--dev] [--native-loop]`
- [x] events: StepEvent / RequestEvent JSONL, per-step `config_hash`
- [ ] Python request path is the throughput gap (serve ~1.3k tok/s vs Zig core ~5.5k on Qwen3-0.6B / B200; vLLM 4.2k e2e)
- [ ] usage / logprobs on streams; O(n) incremental detokenization

### Spec decode (M4) -- one engine path, three drafters, in target-readiness order
- [ ] engine path: `1+K` rows reserved at plan, refunded at commit; verify = the sample step over `[R, 1+K, V]`; drafter = a second `ModelRunner`; overlap off with K > 0
- [ ] DFlash on gpt-oss-20b (`z-lab/gpt-oss-20b-DFlash`: K = 7, taps at layers 1, 6, 11, 16, 21)
  - [ ] `dflash.py` draft module (8-layer Qwen3-shaped, cross-context K/V from the fc'd target residuals)
  - [ ] proof: greedy ids == no-spec; acceptance length vs the card (~4-5); tok/s gain on B200
- [ ] DSpark mechanics on Qwen3-8B (`deepseek-ai/dspark_qwen3_8b_block7`: Markov + confidence heads, anchors)
- [ ] DFlash 2 (`z-lab/Qwen3.8-27B-DFlash2`: conv + candidate selector) once Qwen3.8-27B is onboarded
- [ ] DSpark on DeepSeek-V4-Flash (drafter fused in the checkpoint; after M7 kernels + the deepseek port)

### Devices
- [x] nvidia (B200) -- captured, Triton
- [x] apple mps -- eager `--dev`, reference + Metal demo
- [x] tpu v6e (JAX, RPA) -- all JAX suites passed post launch-shape (2026-09-02); re-verify after the seam
- [ ] trainium trn2 (JAX, NKI) -- verified 2026-09-02; JAX ported to the seam 2026-09-09 but nki@neuron rows UNVERIFIED there (run killed: 422 compiles / 24 tests, docs/friction-2026-09-09.md §4b)

### Training (`integrate/train-step`, unmerged)
- [ ] train step over the same forward; merge after the seam (dedupe list: `docs/audit-train-merge-2026-09-06.md`)

### Tests / tooling
- [x] matrix rows = device x chosen kernels (`cpu, mps, cuda, cuda-functional, jax_reference, rpa, nki`), skipped loudly never dropped
- [x] oracle corpus (frozen HF logits) + synthetic models + HF-parity tests per model
- [x] `scripts/test` (one entry point, per-section timing, loud skips)
- [ ] main green on CUDA (9 failures listed in `docs/handoff-2026-09-06.md`); test-suite cleanup (`docs/audit-tests.md`)
- [ ] `mimir breadcrumb` -> OptMem scopes
