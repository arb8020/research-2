# Speculative decoding across 5 engines: input to M4 questions

Checkouts (re-verify against these SHAs; paths are local scratch clones, not tracked in-repo):
`vllm` = `/tmp/vllm-sparse` @ `4ae6228284c4e9776f62d0867f543e621864176c`
`sglang` = `/tmp/spec-survey/sglang` (github.com/sgl-project/sglang) @ `edff717ef0106b4413b371bf7a05a5193ffeee85`
`tokenspeed` = `/tmp/tokenspeed-sparse` @ `5af23865b91afaf22d20f5d1172f3f1c45dc09ef`
`llama.cpp` = `/tmp/llamacpp-sparse` @ `d30500b83b0f3e39bf7679d94649b559408da892`
`mini-sglang` = `/tmp/mini-sglang-sparse` @ `9a91cfafe754aa85daee49998176275667eb58f2`
`nano-vllm` = `/tmp/nano-vllm-sparse` @ `bb823b3e06983d71485a8e1f23715ebd87d98ef8`

Scope: 6 engines checked, 4 have spec decode. mini-sglang and nano-vllm have none — exhaustive grep
(`speculat|draft|eagle|ngram|mtp|rejection`, case-insensitive, whole repo) turned up no matches beyond
unrelated words in both. The table below is vLLM / SGLang / TokenSpeed / llama.cpp only. Note this
vLLM/SGLang checkout (current upstream main, Sept 2026) is more elaborate than public docs describe —
DFlash, DSpark, suffix-decode, and frozen-KV MTP are recent additions layered onto what kelpie's design
doc was likely written against; "no privileged default" is current-main fact, not the historical baseline.

## The table

| | vLLM v1 | SGLang | TokenSpeed | llama.cpp |
|---|---|---|---|---|
| **1. Drafter** | Registry (`SpeculativeConfig.method`): EAGLE/EAGLE3, MTP, DFlash, DSpark, Medusa, ngram, suffix — no privileged default | Registry (`speculative_algorithm`): EAGLE/EAGLE3/NEXTN(MTP)/STANDALONE/NGRAM/DFLASH/DSPARK, `spec_info.py:38-45` | `BaseDrafter` ABC (`drafter/base.py:41`): EAGLE, MTP, DFLASH, DSPARK | Polymorphic (`common_speculative`, `speculative.cpp:2177`): separate draft model (Simple/MTP/Eagle3 variants), n-gram/lookup, synthetic |
| **2. K / shape** | `num_speculative_tokens`, no hardcoded default (`config.py:380`, `Field(default=None)`); **chain** — tree-forward-pass counting is a FIXME (`gpu_model_runner.py:1649`) | `speculative_num_steps` / `eagle_topk` / `num_draft_tokens`, all `None` at declaration, resolved per-algorithm; **tree** when `topk>1` (`build_tree_kernel_efficient`) | `speculative_num_steps=3`, `eagle_topk=1`; **tree explicitly rejected** at config validation (`server_args.py:742-745`) | `n_max=3, n_min=0` (`common.h:326-327`); **chain only**; n-gram path adapts draft length to observed acceptance rate at runtime (`speculative.cpp:2019`) |
| **3. Rejection sampling** | Separate stage: `RejectionSampler` (`rejection_sampler.py:38`), Triton kernels `rejection_greedy_sample_kernel`/`rejection_random_sample_kernel` (lines 715, 774), called from `_sample` (`gpu_model_runner.py:3742,3765`) after the verify forward, outside the model's CUDA-graph wrapper (wrapper scope is `self.model`, e.g. `gpu_model_runner.py:3406,3418,4092+`) | Separate stage, fused kernel: `verify_tree_greedy_triton` / `tree_speculative_sampling_target_only` (`eagle_utils.py:345-433`) on its own `plan_stream`; grammar mask applied before verify (`eagle_utils.py:716-718`) | Fused CUDA/Triton (`sampling_chain.cu`, `verify.py`) | CPU-side scalar loop, sampled-vs-draft-id comparison (`speculative-simple.cpp:227-262`) — no fusion, no kernel |
| **4. Draft batch shape** | Separate proposer classes per method (`llm_base_proposer.py:71`), own KV-cache-group tracking (`self.kv_cache_gid`, validated against target at `validate_same_kv_cache_group`, line 1712) — never a mode flag on the target runner | Separate `EagleDraftWorker`/`EAGLEWorkerV2`, own captured CUDA graph, own draft KV pool (`eagle_worker_v2.py:64-68,130,1056`) | Separate `draft_model_runner` object passed into `BaseDrafter` (`base.py:53`); dedicated `draft_page_staging.py` for draft KV | Fully separate `llama_context* ctx_dft` / `ctx_tgt` (`common.h:336-337`) — independent KV caches, independent graphs, potentially different vocab/arch |
| **5. Overlap/async** | Reserves max: `request.num_output_placeholders += 1+K` at schedule time (`async_scheduler.py:20-47`), corrected by `-= num_rejected` once accepted count is known (`scheduler.py:1916-1925`) | `FutureMap` stash/resolve across the async boundary (`scheduler.py:1503,3079,3768`) — architecturally the same reserve-then-true-up idea | Not traced to this depth (separate C++ scheduler) | None — draft→verify→next is synchronous, single sequence at a time in the spec path; no continuous-batching overlap to reconcile against |

## Per-question discussion

**1. Drafter.** Every actively-developed engine (vLLM, SGLang, TokenSpeed) now exposes the drafter as a
plugin registry, not a fixed mechanism: EAGLE/EAGLE3 and MTP-style shared-trunk heads are universal,
n-gram/prompt-lookup is the universal zero-extra-model fallback. None hardcodes a default — it's a
per-deployment config choice, made once at server-start (recapture required to change it), never
per-request. llama.cpp is the outlier only in mechanism, not shape: it also branches on drafter kind
(separate model vs. n-gram) via one polymorphic dispatch point.
Suggests for kelpie (flag: suggestion, not decision) — build the drafter as an interface from day one,
matching the design doc's §5 one-model/two-model split; you don't need registry breadth for M4, just the
seam that doesn't foreclose it.

**2. K / depth.** All four treat K as a static, engine-wide, recapture-required knob — this matches
kelpie's roadmap assumption ("1 + k with k small") directly; no engine makes K a genuinely dynamic
per-request value, only n-gram/lookup drafters vary how many tokens they *propose* (still capped by the
static K). Tree vs. chain is the real split: SGLang builds genuine trees when `topk>1`; TokenSpeed
explicitly rejects tree spec at config-validation time with a named error; llama.cpp is chain-only by
construction (single draft context, no branching structure); vLLM's tree-forward-pass counting is a
live FIXME in current main, i.e. more aspirational than shipped.
Suggests for kelpie (suggestion) — chain-only for M4 sits with the majority (2 of 4 shipped engines
reject or don't finish tree support), not an under-scoped choice.

**3. Rejection/verification sampling.** GPU engines fuse verify+reject into dedicated kernels
(`rejection_sampler.py`, `eagle_utils.py`'s tree-sampling kernels, TokenSpeed's `sampling_chain.cu`) but
run them as a **separate stage/launch** after the draft/verify forward — none of the three folds
rejection sampling into the same captured graph region as the model's forward pass. llama.cpp skips
fusion entirely: a plain CPU comparison loop, no kernel at all.
Suggests for kelpie (suggestion) — the design doc's framing ("rejection sampling inside the captured
`sample` graph, or a third graph") maps onto the GPU-engine consensus as the third-graph shape; full
fusion into one launch with the model forward isn't demonstrated anywhere surveyed, so treat "third
graph" as the well-trodden path and "fused into one launch" as the untested one.

**4. Draft batch shape.** Unanimous across all four: a **separate runner/worker object** for the
drafter, never a mode flag threaded through the same runner. KV handling splits by drafter kind —
MTP/shared-trunk drafters ride the target's block table as extra rows (kelpie's cache-groups-ladder
"draft as cache member"); two-model drafters (EAGLE, separate draft model, llama.cpp's `ctx_dft`) get
independently managed KV, up to and including a fully separate context object in llama.cpp's case. No
engine surveyed unifies these into one abstraction.
Suggests for kelpie (suggestion) — this is external validation, not just internal consistency, for the
design doc's §5 split (cache-member for one-model MTP, separate group via `derive_groups` for two-model)
and for rejecting a universal "draft group" the way TRT-LLM's `draft_kv_cache_manager` is rejected there.

**5. Overlap/async scheduling.** vLLM v1 is the sharpest, most legible precedent for kelpie's exact
question 5: it reserves the maximum lookahead (`num_output_placeholders = 1+K`) at plan time and trues
up once actual acceptance is known (`-= num_rejected`), never re-planning a step late. SGLang's
`FutureMap` stash/resolve is architecturally the same answer under a different name. Neither production
engine surveyed does "reserve 1 and re-plan a step late." llama.cpp has no overlap scheduling to
reconcile at all — useful as the cost-of-not-building-it baseline, not as a counterexample.
Suggests for kelpie (suggestion) — reserve-the-max is a two-engine consensus among the ones that
actually built async scheduling + spec decode together, not a marginal tradeoff; weight it heavily
against "reserve 1, re-plan late" for M4 question 5.

## Greedy-identity and grammar interaction

**Greedy == no-spec, bitwise.** All four gate temperature-0 acceptance on exact target-argmax match, so
greedy output is bitwise identical with spec on or off by construction, not just by test coverage: vLLM's
rejection kernel has an explicit greedy fast path (`rejection_sampler.py:435-468`); llama.cpp's verify
loop calls the same `common_sampler_sample` used without spec decode. No engine surveyed weakens this
guarantee for performance.

**Grammar interaction.** vLLM and SGLang both validate/mask draft tokens against the grammar
*before or during* verification rather than committing grammar state speculatively and rolling back on
rejection: vLLM's `structured_output/__init__.py:424,436` uses `num_output_placeholders` to track which
tokens are still in-flight vs. committed when applying the bitmask; SGLang applies the grammar mask to
verify-time logits before accept/reject and threads a `grammar_barrier` through `verify()`
(`eagle_utils.py:716-718`). Neither needs a rollback bound — they mask before commit instead. llama.cpp
has no grammar-awareness in its speculative path at all; the two features are orthogonal there, which is
informative as "rollback is not a solved problem in the simplest engine," not as a design to follow.
Suggests for kelpie (suggestion) — the two production multi-GPU engines sidestep needing a rollback
bound by masking pre-commit rather than rolling back post-commit. Worth weighing against roadmap.md's
"grammar's rollback bound must be >= K" framing as an alternative, not a replacement — the user's call
whether pre-commit masking composes as cleanly with kelpie's `publishFull`-after-rollback design as a
rollback bound does.

## Add llama.cpp to the reference list

llama.cpp is worth keeping alongside vLLM/SGLang/TRT-LLM in docs/decisions.md's reference points, but for
a different reason than the others: it's the simplicity baseline for the local/single-GPU case, not a
scale precedent. Three things fall out of not needing continuous batching or multi-tenant scheduling:
chain-only drafting (no tree machinery to build or reason about), CPU-side rejection sampling (a scalar
comparison loop, no fused kernel, no graph-boundary question at all), and fully independent draft/target
contexts (no KV-group unification problem — two `llama_context` objects, done). None of this scales to
kelpie's batched-GPU-serving case directly, but it's the answer to "what's the minimum viable spec decode
if you strip out everything overlap/batching-related" — useful as a lower bound when a design question's
complexity is being weighed against what it actually buys.
