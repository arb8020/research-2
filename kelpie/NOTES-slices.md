# kelpie as an explainer series: slices (2026-10-09)

Research for a future session: turn kelpie into interactive chapters in the blogs format (one Markdown chapter,
reader-written cells, hidden solutions, plain-assert checks, gating; see `worktrees/blogs-flappy/blogs/HANDOFF.md`).
Read-only survey; nothing run. Paths relative to `kelpie/`. Some cited files (`verification-2026-10-06/`,
`HANDOFF-2026-09-26.md`, the `*-audit-2026-09-26.md` files) are untracked in the main checkout, not on `main`.

## Architecture

~10k lines Zig + ~24k Python (excluding .venv).

| package | size | owns |
|---|---|---|
| `kelpie-core/` (Zig, C ABI `include/kelpie.h`) | ~10k + 70 traces | `scheduler.zig` (1.7k: plan/commit per step, continuous batching, chunked prefill, preemption), `kv_pool.zig` (1.0k: slab + page pool, null page 0, full vs sliding-window groups), `prefix.zig` (0.5k: hash chain over full blocks), `request.zig`, `inputs.zig` (step-boundary inbox), `step_loop.zig` (native loop), `buckets.zig` (power-of-two shapes), `c_api.zig` (3.6k, 1.5k tests), `trace_test.zig` |
| `kelpie-engine/` (Python) | 2.4k | `sdk/engine.py` ctypes Engine (submit/poll/wait/cancel/plan/commit/start_loop/knobs), `sdk/plan.py`, `grammar.py` + `_xgrammar_ffi.py` |
| `kelpie-models/` (torch) | 16.6k | models (`models/torch/`: gpt2 188, qwen3 199, llama 202, gpt_oss 418, smolvlm 391, dflash 743, toy_hybrid 214; `models/unported/` deepseek/qwen3_next 1.7k); sdk (`run.py` 610: bind kernels, load, enumerate shapes, warm, freeze, capture; `step.py`, `captured.py` CUDA graphs, `decide.py` sampling + spec accept, `device.py`, `kv.py`, `groups.py`, `echo.py` fake model); kernels (`kernels/ops/` reference ops incl. `paged_attention.py` 447; `kernels/vendored/cuda/` Triton + vLLM 0.29.0 unified attention 1.7k); `shard/`, `synth/roll.py`, `bench/` |
| `kelpie-http/` | 5.1k | `sdk/app.py`, `sdk/serve.py` (OpenAI-shaped + SSE), `chat/render`, `chat/parse`, `dev/` CLI |
| `scripts/` | 5.5k | 18 check/prove/bench scripts |

Dependencies: http -> engine + models; models -> engine; engine -> libkelpie over ctypes.
Per step: Zig plans (requests, tokens, block tables, padded to a bucket) -> Python step (`Step` / `Captured` /
`DFlashStep`) runs `forward(weights, cfg, tokens, requests, kv, taps)` then `decide` -> Zig commits.
Full call tree: `verification-2026-10-06/gptoss-what-runs.md` §0, §2.

**"K models" does not exist.** No multi-model serving. The only second model is the DFlash drafter inside
`DFlashStep`; "K" in kelpie means draft depth (K=7). Serving several models would be new design.

## Maturity

Proven on main:
- Zig scheduler, paged KV, prefix cache, preemption, chunked prefill: 70 traces under `zig build test` + `scripts/check_core_loop.py` (exact oracle, random caller, laptop CPU, no model).
- gpt2, qwen3, gpt-oss, smolvlm, llama on the kernel seam.
- CUDA graphs, Triton, vendored vLLM attention: 0/248 failures vs fp64 on A100/H100 (`NOTES-attn.md`).
- HTTP chat/completions + SSE.
- gpt-oss-20b K=0 under graphs: 124 tok/s H100, 92.6 A100.
- DFlash K=7 under graphs: ~2-2.7x math, 1.3-2x raw prompts; teacher-forced PASS, captured == eager (`HANDOFF-2026-09-26.md`).

Shaky:
- `response_format` returns 500 (`vocab_words` not wired).
- `overlap=True` would panic on its first real step.
- `mm_hash` hard-coded 0: two images with the same text can share a prefix hit.
- No per-request seed: seed = FNV over (slot ids, seq_lens), so T>0 output depends on scheduling.
- Python request path ~1.3k tok/s vs ~5.5k for the Zig core alone.
- TP, TPU, Trainium partial/unverified.
- README Status marks DFlash `[ ]`; handoff says done. Resolve.

## Verification: why slices never felt defined

`verification-2026-10-06/verification-decisions.md` defines levels (a) op per shape, (b) teacher-forced model step,
(c) greedy/serve output, (d) task score, plus gates, a verdict cache keyed on what executes, and goldens. But
"first-slice scope" is still open; `probe_what_runs.py` is drafted, never run; `gptoss-what-runs.md` §6 lists 13
things that execute without a hash (cuBLAS algo, model glue source, unpinned weight revisions). Scripts are organised
by subject, not level, so nothing ties a script to a level.

Scripts (`scripts-audit-2026-09-26.md` §1): `check_core_loop` (CPU, exact), `prove_state_lifecycle` (CPU fp64),
`check_serve` (CPU rows: gpt2 golden, echo, rolled tiny gpt_oss batched == solo, stale_cancel, smolvlm == HF),
`bench_attention` / `bench_moe` (GPU, fp64 truth + error budget), `prove_dflash` / `check_spec_teacher_forced` /
`prove_moe` (GPU, gpt-oss-20b, greedy with tie tolerance), `check_endpoint` (task score, no reference yet).
`scripts/test` runs only Zig tests, ruff (advisory), import smoke; pytest suite parked.

Known holes: `bench_moe` always exits 0; `build(check=True)` grades each op once at a toy shape and copies the verdict
to every shape; an `error` verdict gets past serve; `TIE_ULPS=8` guessed (spec says 2); in `prove_dflash` a tie hides
every later token; `check_run_wrapped_step` stale; `check_dflash_drafter_cpu` dead, exits 0; vendored
`tpu/_pallas.py`, `neuron/_dense.py` import deleted modules; `tiny()` in `models/torch/tiny.py` raises
NotImplementedError while `check_serve` uses a separate `roll:` path.

Proposal: let chapter checks be the levels.
V0 core traces (exists) · V1 core random oracle (exists) · V2 op vs fp64 per shape (exists, toy shape only) ·
V3 model teacher-forced vs HF (`kelpie-models/scripts/make_corpus.py`) · V4 greedy + batched == solo (`check_serve`) ·
V5 spec == no-spec (`prove_dflash`, teacher-forced) · V6 task score (no reference).

## Slices, smallest first

CPU = laptop with gpt2 (124M fp32) or no weights.

| # | concept | kelpie code | reader writes | check | hw |
|---|---|---|---|---|---|
| 1 | forward + greedy loop, full recompute | `models/torch/gpt2.py` | gpt2 forward, dense | logits allclose HF; greedy "The capital of France is" == `" the capital of the French Republic"` (`check_serve.py:99`) | CPU |
| 2 | KV cache, one request, contiguous | n/a (kelpie is paged from the start) | append K/V, decode 1 token | incremental == full-recompute logits; same string | CPU |
| 3 | sampling: temperature, top-k, seeded Gumbel | `kernels/ops/sample.py`, `sdk/decide.py` | `sample(logits, T, top_k, key)` | T->0 = argmax; nothing outside top-k; freqs match softmax within 0.01 | CPU |
| 4 | ragged batching (`query_start_loc`, `seq_lens`, positions, `last_rows`) | `sdk/device.py`, `kelpie_engine/sdk/plan.py` | batched forward | batched == solo per request | CPU |
| 5 | paged KV: pool, block tables, slot_mapping, null block 0 | `kv_pool.zig`, `sdk/kv.py`, `ops/paged_attention.py` | allocator + paged attention | paged == dense on random input; pad rows zero; free count returns; no block has two owners | CPU |
| 6 | continuous batching: plan/commit, token budget, chunked prefill, EOS/max_new | `scheduler.zig`, `request.zig`, `kelpie-core/traces/*.txt` | pure-Python `plan()`/`commit()` | replay `single_request`, `decode_two_steps`, `chunked_prefill`, `eos`, `two_requests_*`; echo model turns a wrong plan into wrong text | CPU, no torch |
| 7 | admission, reservation, preemption | same + `kv_stall`, `preemption`, `reserve_*` | eviction order, recompute | trace replay; random-caller oracle (outputs equal across pool sizes) | CPU |
| 8 | prefix cache (last token never matched) | `prefix.zig`, `prefix_*` traces | match/insert/release | cache on == off; hits > 0; `prefix_shared`, `prefix_preempt` | CPU |
| 9 | engine loop + API: submit/poll/cancel, generation ids, SSE | `engine.py`, `kelpie-http/sdk/app.py` | thread loop + tiny HTTP | streamed == non-streamed; stale-cancel row | CPU (echo) |
| 10 | shape buckets, inert padding | `buckets.zig`, `sdk/shapes.py`, `run.py` `_warm` | pad to power-of-two | padded real rows == unpadded | CPU |
| 11 | CUDA graphs | `sdk/captured.py` | capture decode buckets | replay bitwise == eager; tok/s floor | GPU (small, gpt2) |
| 12 | a Triton kernel vs reference | `kernels/vendored/cuda/_triton.py`, `bench/correctness.py` | one kernel | error <= `error_budget` vs fp64 across bucket shapes; µs budget | GPU |
| 13 | cache groups: sliding window + full, sinks (gpt-oss) | `groups.py`, `two_groups_*`, `swa_*` traces | per-group block tables | rolled tiny gpt_oss (`roll:`) batched == solo; window traces | CPU (config.json only) |
| 14 | spec decode mechanics: 1+K rows, verify `[R,1+K,V]`, cumprod accept, KV refund | `decide.py:87`, `extra_*` traces, `prove_state_lifecycle` (oracle drafter K=3) | verify + accept with toy drafter (oracle or n-gram) | greedy spec == no-spec exactly (fp32/64); accepted > 0 | CPU |
| 15 | real drafter: DFlash on gpt-oss-20b | `models/torch/dflash.py`, `prove_dflash.py`, `check_spec_teacher_forced.py` | probably reference only | teacher-forced within N bf16 steps of row max; speedup reported | GPU 80 GB |
| 16 | recurrent state (hybrid), per-seq checkpoints | `toy_hybrid.py`, `state_*` traces | state ring | paged == dense, exact fp64 | CPU |
| 17 | structured output: grammar mask | `grammar.py`, xgrammar | mask from a tiny grammar | every output parses; all -inf row handled (open papercut) | CPU |
| 18 | verification itself (levels, tie tolerance) | `verification-2026-10-06/`, `docs/correctness/reference.md` | teacher-forced grader | catches planted mutants (wrong slot, lost KV row) | CPU (gpt2) |
| — | multi-model, TP sharding | none / `shard/` | — | — | new / multi-GPU |

Possible cut: minimal engine 1-5 · scheduler 6-10 · speed 11-12 (GPU) · model variety 13, 16 · spec decode 14-15 ·
serving extras 9, 17 · verification 18 threaded through every chapter.

## Hardware

- CPU, no weights: echo (`sdk/echo.py`, downloads gpt2 tokenizer only), toy_hybrid (fp64 random), trace DSL, `check_core_loop`.
- CPU, rolled tiny configs: config.json only.
- CPU, small real: gpt2 (`examples/run_gpt2.py`), SmolVLM-256M, Qwen3-0.6B (slow; mps eager works).
- GPU: gpt-oss-20b ~24 GiB build peak + ~12 GiB converted experts; A100-80GB (Marlin MoE) or H100 (triton_kernels MoE); DFlash drafter +1.6 GB. Qwen3-0.6B throughput numbers are B200.
- `CLAUDE.md`: never run model tests on the laptop; GPU via `kelpie remote` / box on Modal. Fits "readers bring their own Modal workspace".

## Trace DSL as checks

The 70 traces in `kelpie-core/traces/` are language-neutral: the best ready-made check asset for a reader-written
pure-Python scheduler (slices 6-8). Caveat: an earlier Python reference scheduler failed 5 of 28 traces before it was
deleted (`PAPERCUTS.md`); traces may encode Zig choices (`reserve_ratio`, slab model) a minimal scheduler shouldn't
have to match. Picking the subset is the author's call.

## Constraints

- **Greedy only where scheduling is involved.** Seed comes from slot ids + seq_lens, so T>0 isn't reproducible across schedules. Either keep those checks greedy or add a per-request seed first.
- **Forward seam drift:** `docs/model-contract.md` says `forward(w,cfg,batch,kv,state,ops)`; code says `forward(weights, config, tokens, requests, kv, taps)`.
- **Speed budgets:** CPU gpt2 tok/s maps to blogs' "absolute budgets on a pinned machine"; GPU budgets need a pinned SKU, and Modal "H100" may be SXM or PCIe (`gptoss-what-runs.md` §6.6).
- **Docs in flux:** ~69 docs, `docs-audit-2026-09-26.md` proposes deleting 22; handoff has five decisions waiting. Chapters shouldn't link to doomed docs.
- Unchecked: whether `models/unported/` or `kelpie_models.state` import; whether the rolled `gpt_oss_tiny` `check_serve` row passes today.

## Open questions for the author

1. Reader language: pure Python for slices 1-10 with kelpie as reference (recommended by the survey), or lower level?
2. Which traces count as the spec for a reader's scheduler?
3. "K models": did you mean multi-model serving (new design) or spec-decode draft depth?
4. Tie tolerance: 8 (guessed) or 2 (spec)? Is `prove_dflash` or the teacher-forced gate "the" spec-decode check?
5. Teach kelpie's forward seam or a simpler one?
6. Which parts of kelpie do you feel least close to? Those might set the order.
