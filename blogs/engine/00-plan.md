# inference engine: curriculum plan

<!-- wip: plan only. no prose yet -->

## chapters

### 0. DEFER: gpt2 in numpy, transformer intuition building (probably its own page)

### 1. model forward: gpt2

motivation: get the forward pass working

desc:
- torch functional forward + full-recompute `generate()`
- introduces the correctness machinery the whole series reuses: a reference, per-dtype tolerances, a shape / input sweep, and planted bugs (wrong attention scale, missing final layernorm, exact vs tanh GELU, causal mask off by one) showing which checks catch which
- the reader *uses* the machinery (given), and doesn't write it, for now; revisit later
- built as if an agent might write the candidate and try to game the check: pygpubench's shape (a trusted parent computes inputs + fp64 truth before importing the candidate; one untrusted spawned child runs it; results over a pipe; timeout). Vendor or reference pygpubench, tilde-research/popcorn, KernelGuard rules as needed; push the heavier hardening later only if it's really hard
- shape sweeps must cover code paths, not just a toy sample (kelpie's gap: one `randn(4,8)` per op). Python: `coverage.py` over the sweep, every line + branch hit. GPU kernels later: tile-remainder / alignment / specialization / autotune-config / algorithm-edge rules, sanitizers, and the full production shape list
- blocking: per-op checks (2x fp64 error budget) block by default, as do model-level checks; per-op blocking is toggleable (block / warn) per op or globally. Model-level always blocks
- per-deployment certification (from chapter 12, once buckets exist): the engine owns the bucket ladder and the model is fixed, so the production shape list is finite (~14 shapes per dense op; attention ~105 shapes x sampled length configs; low thousands of cases total per model / dtype / TP / GPU). Run it all against fp64 truth once per deployment; cache verdicts keyed by (op, impl, shape) that actually run

check:
- logits within tolerance of the HuggingFace reference on fixed prompts, fp32 on CPU (~1e-4 to 1e-3)
- greedy tokens + top-k logprobs vs HuggingFace, vLLM-style: each step's tokens match, or each is in the other's top-k (robust to near-ties; also works in bf16 on GPU)

arch notes:
- `forward` stays callable standalone from a script, no engine or HTTP needed (complaints.md #3)
- CPU; gpt2 is the only model the laptop rule allows
- checks: one suite per chapter behind `run_checks chN`; blog cells and harbor tasks both call it
- checks are language-agnostic (HuggingFace refs, HTTP, protocol, trace text); C++ is the blessed language with stubs and solutions

### 2. sampling + tokenization

motivation: users dont read logits

desc:
- temperature / top-k / top-p / min-p; per-request seeding
- tokenizer encode / decode

check:
- filtering, exact: masked + renormalized distribution == reference implementation on the same logits
- draw, statistical: fixed seed, ~100k draws from a small known distribution, chi-square at a strict threshold (p < 1e-6)
- temperature 0 == greedy; same seed -> same tokens
- tokenizer: ids == HuggingFace tokenizer; decode(encode(text)) == text

arch notes:
- sampling ends up in the worker (chapter 5); tokenization ends up in the frontend (chapter 3)

### 3. HTTP frontend + chat template

motivation: users want to hit a familiar API

desc:
- `/v1/completions` and `/v1/chat/completions`, non-streaming
- plain chat template (tools / thinking / harmony land with the model chapters that need them)

check:
- golden responses for the echo model over HTTP (completions + chat)
- rendered chat prompt == HuggingFace `apply_chat_template`, token for token (catches double BOS, a missing generation prompt)
- stop tokens end generation

arch notes:
- this becomes the frontend process (Python): HTTP, chat template, tokenize; later incremental detokenize and stop strings
- nothing with text ever reaches the engine; it sees token ids only

### 4. kv cache + streaming

motivation: reduce wasted work by the fwd pass

desc:
- KV cache (prefill / decode split), single request, contiguous
- SSE streaming; incremental detokenize; client disconnect

check:
- everything from before as usual
- incremental logits == full recompute, every step
- streamed tokens == non-streamed
- decode step time ratio (long prompt / short prompt) << the same ratio for full recompute
- detokenize cost per token stays flat as output grows (kelpie's is O(n²))
- SSE framing valid (`data:` lines, `[DONE]`)
- client disconnect mid-stream stops generation

arch notes:
- detokenize + stop strings live in the frontend; stop strings finish one step late (the frontend sends a cancel)
- precedent: crucible task 01 was "kv-cache-streaming" with the same three checks

### 5. engine process + worker + static batching

motivation: multiple users against the endpoint

desc:
- C++ engine process owns the step loop; Python worker = `forward(plan) -> tokens` + sampling
- frontend <-> engine: submit / cancel / token stream
- static batching: form a batch (wait for N or a timeout), pad to a rectangle
- `given`: process spawn, socket framing, frame encode / decode, the frontend side of the protocol
- reader writes: the engine loop, the plan (which KV slot + positions per request), the batching decision

check:
- harness plays a fake worker against the reader's engine over the protocol (plans well-formed, KV slots disjoint)
- each request's output in a batch == its output alone (greedy)
- 2 replica workers get the same plan and return identical tokens; a killed worker -> clean error, not a hang
- throughput with N concurrent users > N x sequential
- engine health from outside the process, from here on: fd count back to baseline after load, nothing in flight when idle, never crashed, low idle CPU

arch notes:
- three processes: frontend (Python) <-> engine (C++) <-> worker(s) (Python, torch; one per device group)
- engine loop, each step: read ops -> plan -> send plan to workers -> receive tokens -> commit -> stream token ids
- transport: Heinrich pattern (spawn + socketpair + memfd); binary framing (`magic | version | type | len`, fixed-capacity arrays with counts)
- the engine never touches CUDA and never imports Python; spawns workers before anything touches the GPU
- language rules: `~/dotfiles/docs/raw/cstyle_cpp.md` (C++20, always-on `ASSERT`, one owner + one teardown, Linux only)
- the engine takes a list of workers from the start (N = 1, plus the 2-replica check); multi-rank later only changes the worker
- plan arrays have fixed maximum capacities with explicit counts (buckets later = pad the counts)
- commit takes n tokens per request (always 1 until spec decode)
- scheduling checks use greedy decoding (the seed comes from slot ids otherwise)
- may split into two chapters later if too heavy

### 6. continuous batching

motivation: static batching is obviously wasteful throughputwise

desc:
- admit and finish requests every step; per-slot contiguous KV (`[max_slots, max_len]`); ragged forward
- the scheduler as a pure function: (state, ops) -> plan; commit(tokens)

check:
- text traces fed to the scheduler as data (basic traces)
- each request's output == alone (greedy)
- beats static under staggered arrivals; a short request isn't held hostage by a long one
- concurrency capped by slot count (sets up chapter 7)
- replay: two scheduler instances fed the same ops log -> identical plans (kept forever)

arch notes:
- scheduler core is sans-IO and deterministic:
  - no clocks, randomness or thread timing in planning; time arrives on ops
  - ops (submit / cancel / set knob) are an ordered log, applied at step boundaries
- these keep multi-host open later (central-over-TCP or replicated), along with: the plan is a wire format, never pointers; transport is swappable (shm local, TCP remote)
- continuous batching is scheduling; it works fine without paged KV (Orca)

### 7. paged KV

motivation: memory is being wasted, enables more concurrency

desc:
- block pool + free list + per-request block tables + slot mapping
- attention reads KV through the block table (gather-based torch reference first)

check:
- traces for block accounting: free count returns to full, no block has two owners
- paged == contiguous
- max concurrent requests in the same KV memory goes up vs chapter 6

arch notes:
- engine owns block ids, tables and slot mapping; the worker owns the KV tensor and never allocates
- block 0 reserved as the null block (pad rows write there, chapter 12)

### 8. kernel dispatch layer

motivation: we would like to vendor fast kernels

desc:
- a dispatch layer in the worker: per op, pick an implementation (paged attention from Triton / vLLM / FlashInfer; fused RMSNorm)

check:
- make sure we can set a kernel and it launches
- each dispatched kernel == the reference torch op (within tolerance); whole-model output unchanged
- attention / step time improves over the gather reference
- maybe: a little more complexity here with the triton cache / avoiding autotuning

arch notes:
- worker-side only; kernel builds use torch's C++20, separate from the engine build
- later chapters (SWA, MoE, spec decode) plug their kernels in here

### 9. admission + preemption

motivation: too many users

desc:
- admission: who starts this step (block availability, token budget, max running, reserve headroom)
- preemption: out of blocks -> evict a running request (youngest), free its blocks, requeue at the front, recompute later

check:
- traces: kv_stall, preemption, reserve_*
- under memory pressure every request finishes, output == solo
- all blocks free once idle

arch notes:
- mechanism vs policy: the mechanism validates every policy decision; a bad policy is slow, never wrong
- policy shape (struct of function pointers vs enum + switch) deferred; Python sets priority keys at submit, the engine sorts
- a policy simulator (no GPU, cost-model worker) could live here

### 10. chunked prefill

motivation: prefills slowing itl

desc:
- per-step token budget; long prompts split into chunks; prefill on top of existing KV

check:
- traces: chunked_prefill
- chunked == unchunked
- inter-token latency bounded while a long prompt arrives

arch notes:
- a partial chunk's sampled token is discarded
- chunks aligned to blocks

### 11. prefix cache

motivation: agentic coding/shared sys prompts

desc:
- hash token blocks (chain hash); refcounted shared blocks; LRU eviction of free cached blocks

check:
- traces: prefix_*
- hit == miss
- time to first token drops on a shared prefix

arch notes:
- the last prompt token is never matched (its logits are still needed)
- interacts with preemption (prefix_preempt, prefix_resurrect)

### 12. cuda graphs

motivation: cuda graphs/replaying is better than eager

desc:
- buckets: a ladder of batch sizes; the engine pads every plan up to the nearest bucket; pad rows inert (write to the null block)
- capture one CUDA graph per bucket in the worker; replay = copy inputs into fixed buffers + one launch
- plan transport: socket frames -> shared-memory ring, measured

check:
- padded == unpadded; graph replay == eager
- graphs actually replay (count replays vs eager fallbacks)
- step time at small batch drops
- per-step host time drops with the shm ring (bench: ~6.6 µs shm vs ~38 µs socket round trip)
- low idle CPU once the ring spin-waits

arch notes:
- before multi-rank: ranks must capture in the same order
- buckets also serve XLA (one compiled program per shape)
- MoE host syncs block capture
- shm ring rules (SPSC, release/acquire pairs, TSan): `cstyle_cpp.md`

### 13. multi rank

motivation: bigger models

desc:
- tensor parallelism: N workers, the engine broadcasts the plan, gathers rank 0's tokens
- weights sharded with named axes; all-reduce inside the forward; KV heads split per rank

check:
- TP2 tokens == TP1
- a dead rank is detected cleanly
- the model doesn't fit on one GPU but runs on two

arch notes:
- central scheduler: no digests, agreement or heartbeat; ranks can't disagree
- hardware: gloo on CPU for dev; `A100-80GB:2`
- model must not need SWA (that's chapter 15): a dense ~70B at TP2
- each worker inits its own CUDA + NCCL; rank 0's NCCL id travels over the control socket

### 14. XLA/AMD/Apple (dealer's choice)

motivation: heterogeneous backends

desc:
- a second worker kind against the same protocol

check:
- every earlier check passes with the worker swapped

arch notes:
- torch-xla is being replaced by TorchTPU (not public yet); vLLM's TPU path lowers through JAX (torchax). Options: TorchTPU once it ships, JAX / torchax, Trainium via Neuron, AMD ROCm, Apple MPS / MLX
- Colab TPU (v5e-1 / v6e-1, single chip) via `box --provider colab` for testing; multi-device needs GCP
- later chapters: CUDA required, other backends best-effort (checkbox per chapter)

### 15. cache groups/slab model/swa

motivation: gpt-oss

desc:
- per-group block tables; blocks that slide out of the window are freed; per-group block sizes; slab pool
- MoE forward (gpt-oss)

check:
- gpt-oss vs HuggingFace (tiny config, then 20b)
- traces: swa_window_prefix_cache, window_prefix_resume
- KV memory bounded by the window

arch notes:
- windowed prefix-hit rule + cross-group fixpoint (kelpie retrofitted these a week later; keep them in this chapter)

### 16. hybrid state and more models

motivation: model archs (qwen3 next or kimi linear or nemotron mamba layers?)

desc:
- per-sequence recurrent state slots as another kind of cache group; checkpoints so the prefix cache still works

check:
- traces: state_*, per_seq_*
- output vs HuggingFace

arch notes:
- generalizes chapter 15's cache groups

### 17. spec decode/dflash

motivation: goes even faster

desc:
- extra rows per request (1 + K drafts) inside the token budget; accept / reject; roll back rejected KV
- DFlash: a learned drafter on gpt-oss-20b

check:
- greedy spec == no-spec (exact)
- traces: extra_after_prefix_hit, extra_window_slide, extra_drop_before_preempt, extra_k3_per_*
- acceptance rate, tok/s

arch notes:
- n-token commit already in place since chapter 5
- graphs need decode-with-extras buckets
- DFlash depends on chapters 12 (graphs) and 15 (gpt-oss)

### 18. structured output

motivation: grammar masks/tool calling

desc:
- grammar masks (xgrammar) applied before sampling; tool calling

check:
- 100% of outputs parse against the schema
- permissive grammar == no grammar
- step time with grammar requests vs without, same batch size

arch notes:
- grammar lives in the worker: fill the bitmask on CPU while the GPU runs the forward, apply before sampling, advance the matcher after
- no xgrammar in the engine (it throws; no C API); the engine only sees a "grammar dead end" finish flag
- the matcher must advance through accepted draft tokens (chapter 17)
- multi-rank: only rank 0 samples and holds grammar state

### 19. multimodal

motivation: smolvlm

desc:
- image encoder in the worker; embeddings override inputs at the image positions

check:
- smolvlm vs HuggingFace
- traces: prefix_mm (same text, different image != hit)

arch notes:
- the frontend fetches the image and computes `mm_hash`; the engine folds it into the prefix chain (kelpie's engine submits 0 today, a bug)

## workspace + cells (decided 2026-10-09)

- cells are views onto real files in a per-reader workspace (a git repo in the reader's sandbox, reader's own Modal account)
- start with whole-file cells, one CodeMirror per cell (tabs / a file picker if a chapter needs several files); regions later, as display / jump-to rather than edit
- persistence: the repo lives on the sandbox disk; a `git bundle` is copied to a Modal Volume (reader's account) on every pass commit and restored at boot; unpassed drafts mirrored in browser localStorage
- reference code: layered chapter folders (`engine/ref/chNN/` holds only files that chapter adds or changes; materialize(chN) = ch1..chN stacked, later wins); a generator emits a tagged repo (`chN/start`, `chN/solution`) for harbor, Colab and reader workspaces; the last chapter materialized is kelpie
- checks: per-cell where a piece can be tested alone, plus a chapter-level end-to-end check (the harbor task runs the chapter check); `run_checks chN [cell]`
- gating: running a check builds the latest passing tree + only this cell's edits; pass -> commit + tag `pass/chN/<cell>`
- carrying code forward: splice. Chapter N+1 starts from the reference tree with the reader's passing files spliced in (reference fallback + a note if a cell was skipped or failed). Authoring rule: a later chapter never silently edits reader-owned code; it hands the file back as a cell
- output: like a Jupyter cell. Build + check output streams under the cell; `file:line` becomes a link that jumps the editor. Inline diagnostics later via LSP (`@codemirror/lsp-client` + clangd / pyright through `jupyter-lsp` in the sandbox)
- checks run as a background subprocess, so the kernel stays usable
- speed targets: cell checks under ~2-3 s (rebuild the changed file only, ccache, pure-function checks vs traces); chapter checks under ~30-60 s on CPU (debug + ASan for cell checks; release build only for perf checks); model weights cached on the Volume
- editor: CodeMirror (already integrated, light, good vim); revisit Monaco only if the editor becomes a full IDE pane
- deferred: local backend (`session.py` vs `connect_dev.py`; they're separate code paths today)

## open questions

- chapter 5: split into two if too heavy
- chapter 1 model: gpt2 only, or move to qwen3-0.6b
- "after the core": async / overlap, KV quantization, batch invariance, benchmarking
- scheduler policy shape (deferred)
- multi-host TPU: central-over-TCP vs replicated (deferred; door kept open)

## sources

- `kelpie/NOTES-slices.md`
- `kelpie/docs/decisions/overlap-removed.md` (on branch `kelpie/core-compress`)
- `kelpie-core/traces/`
- `~/dotfiles/docs/raw/cstyle_cpp.md`
- `~/dotfiles/docs/raw/how_to_test_matklad.md`
- `~/dotfiles/docs/raw/heinrich_multiprocessing.md`
- `~/silares_stuff/crucible/crucible/other/inference_curriculum/ROADMAP.md` (2026-08-27)
