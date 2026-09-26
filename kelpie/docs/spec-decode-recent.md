# Recent spec-decode methods beyond EAGLE-2/MTP/n-gram

Checkouts: `vllm`=`/tmp/vllm-sparse`@`4ae6228`, `sglang`=`/tmp/spec-survey/sglang`@`edff717`.
Additive to spec-decode-survey.md. Deep dive on DFlash/DSpark per priority; rest is a
shorter pass. Kelpie's DeepSeek-V4 module: `kelpie-models/kelpie_models/models/unported/deepseek_v4.py`.

## DFlash — deep dive

**Mechanism.** Not autoregressive: the draft model fills a whole block of
`block_size` future positions in one forward, each position seeded with a
`mask_token_id` (config field, `dflash_utils.py:493-495`, resolved in
`parse_dflash_draft_config`, `dflash_utils.py:562-655`). It is a small trained
transformer (its own `num_hidden_layers`, own attention, own conv/selector
layers — `DFlashDraftConfig` also carries `conv_kernel_size`, `selector_rank`,
`selector_top_k`, `dflash_utils.py:484-492`), not a classifier head. Verify is
linear/chain, explicitly not tree (`DFlashVerifyInput.topk: int = 1` — "DFLASH
verify is linear", `sglang/srt/speculative/dflash_info.py:38-41`).

**What it needs from the target forward, precisely.** A configurable subset of
intermediate target layers — `target_layer_ids`, resolved from the draft
checkpoint's `dflash_config.target_layer_ids` against `num_target_layers`
(`dflash_utils.py:508-520`) — captured at `CaptureHiddenMode.FULL`
(`dflash_info.py:33`, `dspark_worker_v2.py:445-452` reuses the same capture
mode). This is hidden states only, not attention weights and not raw KV: the
target runs its normal forward, and the runner additionally returns the
requested layers' post-block residual stream at every position, concatenated
along the feature dim (vLLM: `gpu_model_runner.py:5307-5324`, gated by
`use_aux_hidden_state_outputs`, `gpu_model_runner.py:683-700,4556-4562`). The
draft model does **not** read the target's KV cache or attention states.

**Draft-step control flow (SGLang `dflash_worker_v2.py`, mirrors
`dspark_worker_v2.py`'s decode path since DSpark subclasses DFlash's block
machinery — `dspark_draft.py:23` imports `dflash_info_v2.DFlashDraftInputV2`):
two launches per decode step**, same shape as EAGLE:
1. **Draft launch** — one forward of the small draft model over the whole
   masked block (`_prepare_dflash_draft_block_unchecked` kernel,
   `dflash_worker_v2.py:12-15`), producing `block_size` draft tokens at once.
   Feeds on: last accepted token(s) + aux hidden states from the *previous*
   verify launch.
2. **Verify launch** — target model runs one forward over the linear block
   (`ForwardMode.TARGET_VERIFY`, all `block_size+1` positions in one pass,
   `dflash_info.py:29-33`), returning logits for every position plus (via
   `capture_hidden_mode=FULL`) the aux hidden states to seed the *next* draft
   launch. Accept-length comes from this single verify forward — no separate
   kernel launch beyond standard sampling comparison
   (`_compute_dflash_accept_bonus_triton_unchecked`, `dflash_worker_v2.py:12-14`).

Nothing is fed back mid-launch — the two launches are strictly sequential
(draft depends on prior-step's hidden states; verify depends on this step's
draft tokens), so it composes with CUDA graphs like EAGLE (captured draft
graph, captured verify graph).

**Engine additions, file:line.**
- vLLM: `pass_hidden_states_to_model=True` on `DFlashProposer`
  (`vllm/v1/spec_decode/dflash.py:35`); separate context KV buffers so the
  query-buffer addresses stay CUDA-graph-stable (`dflash.py:49-60`); a new
  `copy_and_expand_dflash_inputs_kernel` (`vllm/v1/spec_decode/utils.py`,
  imported at `dflash.py:16`); registry entries `DFlashModelTypes`,
  auto-detection from checkpoint name/architecture
  (`vllm/config/speculative.py:66,1286-1290`).
- SGLang: new `SpecInputType`/`ForwardMode.TARGET_VERIFY` variants
  (`dflash_info.py`), a dedicated `RaggedVerifyLayout` for the linear-block
  verify shape, and mask-token-aware draft-block construction kernels under
  `sglang/kernels/ops/speculative/dflash/`.

**Published heads.** vLLM's docs mention `dflash` only generically (listed
alongside EAGLE/MTP, `docs/README.md:50`); no HF repo for Qwen3-0.6B/30B-A3B
or gpt-oss is named in either checked-out repo. Third-party reports (web
research, unconfirmed against either engine's own docs) mention Qwen3-8B/27B
and Qwen3-Coder-30B-A3B DFlash checkpoints — treat as unconfirmed for kelpie's
exact targets.

## DSpark — deep dive

**Mechanism.** DFlash's masked block-drafting (`DraftBlockProposer` at
`dspark_components/dspark_draft.py:167`, literally builds on
`DFlashDraftInputV2`, `dspark_draft.py:23`) plus two additional trained pieces:
a **Markov head** (`markov_rank`, `markov_head_type` ∈ {vanilla, gated, rnn},
`dspark_config.py:56-97`) that models intra-block token dependence instead of
drafting all `gamma` positions independently, and an optional **confidence
head** producing per-position survival-probability estimates
(`DraftProposal.confidence`, `dspark_draft.py:75-80`). `gamma` (draft block
size) is read from the checkpoint's `dspark_block_size` or overridden by
`--speculative-num-draft-tokens` (`dspark_config.py:44-49,86-107`).

**What it needs from the target forward, precisely — and it's more than
DFlash.** Same aux-hidden-state capture as DFlash (`target_layer_ids`,
`CaptureHiddenMode.FULL`), **plus** the target's per-position hidden state is
**written into the draft model's own KV cache** after every verify (and every
prefill), not just read: `TargetHiddenKvInjector.inject_target_hidden`
(`dspark_kv_inject.py:35-94`) computes cache locations/positions and calls
`draft_model.write_target_hidden_kv(...)` against the draft model's own KV
pool (`dspark_kv_inject.py:81-91`, MLA variant at `dspark_kv_inject.py:96-135`
handles DeepSeek-V4's MLA/SWA-ring cache layout specifically). This means the
draft model attends, at its next draft launch, over K/V rows that hold
*target*-produced hidden states at prior positions, not its own recomputed
ones — a KV-cache write path that DFlash does not have. Also required:
`enable_adaptive_verification` needs a startup-time, per-CUDA-graph-shape cost
profile (`docs/features/speculative_decoding/adaptive_verification.md`) and
device-decided (not CPU-decided) query lengths in the attention backend.

**Draft-step control flow (`dspark_worker_v2.py:_forward_decode`,
lines 555-650+): still two model launches per decode step, with extra
device-side scheduling work between them:**
1. Draft launch (`self._proposer.propose(...)`, `dspark_worker_v2.py:610-618`)
   — one block-parallel forward, same shape as DFlash, producing
   `draft_block_ids`/`draft_tokens` plus `confidence`.
2. **On-device verify-window planning** (no target forward yet): confidence
   feeds `_verify_planner.resolve_verify_token_budget` and
   `schedule_layout` (`dspark_worker_v2.py:626-644`) to pick a **per-request,
   per-step variable verify width** — this is new relative to DFlash/EAGLE,
   which always verify the full static K.
3. Verify launch — target forward over the (now variably-sized) block,
   `verify_ids_2d = cat(draft_block_ids[:, :1], draft_tokens)`
   (`dspark_worker_v2.py:646-648`).
4. **KV injection** (`_kv_injector.inject_target_hidden`, called from both
   `_forward_prefill` at line ~497 and after decode-verify) writes the
   target's hidden states for every *committed* position into the draft
   model's KV pool before the next draft launch reads it — this is the extra
   step beyond DFlash's flow, and it happens **before** the scheduler is
   allowed to touch radix/out_cache_loc for that batch (comment: "Must inject
   before prefill returns: the scheduler may update radix afterward,
   invalidating out_cache_loc", `dspark_worker_v2.py:471-472`).

So: 3 device-side stages plus 2 model launches per step (draft forward →
verify-window planning → target forward → KV injection), vs. DFlash's 2
launches with no injection/dynamic-width planning.

**Is DSpark part of the DeepSeek-V4 checkpoint, or a separately trained
head?** Separately trained, not part of DSV4's own weights. Evidence:
- `draft_is_deepseek_v4()` (`dspark_config.py:29-40`) loads the **draft
  model's own HF config** from `speculative_draft_model_path` and checks
  `is_deepseek_v4(draft_hf_config)` — i.e. DSpark's DeepSeek-V4 variant is
  itself a separate checkpoint at a separate path, not a flag read off the
  target model's config.
- `checkpoint_bundles_dspark_draft()` (`dspark_config.py:180-190`) checks for
  `dspark_*`-prefixed keys (`dspark_block_size`, `dspark_markov_rank`,
  `dspark_noise_token_id`, `dspark_target_layer_ids`) on a config — this is
  the "bundled" case where a single checkpoint's config carries both the base
  model fields and the DSpark fields, but it's still a distinct checkpoint
  object from the *target* being served, loaded via `draft_model_config`
  (`vllm/config/speculative.py:1200-1212`), never read off
  `target_model_config`.
- Kelpie's own `deepseek_v4.py` `config_from_hf()` (line 555) parses none of
  `dspark_block_size`/`dspark_markov_rank`/`dspark_noise_token_id`/
  `dspark_target_layer_ids`/`target_layer_ids` — confirmed by grep, zero
  matches. `attn_specs()`/`attn_spec()` (lines 147-158) build attention specs
  purely from `cfg.layer_types`/`cfg.csa_ratio`/`cfg.hca_ratio`/
  `cfg.sliding_window` — nothing DSpark-shaped. `forward()` (line 163) returns
  only final post-`ln_f` logits (`last`, ~line 199), no raw intermediate
  hidden states or aux-layer list — kelpie's DSV4 module could not feed a
  DFlash/DSpark drafter without a code change exposing `target_layer_ids`
  residual streams.
- vLLM's `adaptive_verification.md` example serves
  `deepseek-ai/DeepSeek-V4-Flash-DSpark` as both target and draft `model` in
  one `--speculative-config`, consistent with a bundled checkpoint (one repo,
  `dspark_*`-prefixed config keys alongside base model fields), not DSV4's
  mainline weights training in a DSpark head by default. Paper: arXiv
  2607.05147 (per web research, not independently verified against a PDF).

**Published heads for Qwen3/gpt-oss.** `deepseek-ai/dspark_qwen3_8b_block7` is
named directly in vLLM's own auto-detection comment
(`vllm/config/speculative.py:1279`) — a DSpark head for **Qwen3-8B**, not
0.6B or 30B-A3B. `Qwen3DSparkModel`/`Gemma4DSparkModel` architecture strings
are recognized (`speculative.py:1293,1296`), so Qwen3-family and Gemma-4-family
DSpark heads exist as a supported *class*, but no 30B-A3B-specific repo is
named in either checkout. No gpt-oss DSpark head found in either repo.

## Rest of the methods (shorter pass)

| Method | Mechanism | Needs from target | Trained? | Chain/tree | Published heads for kelpie models |
|---|---|---|---|---|---|
| Suffix decoding (arxiv 2411.04975, Snowflake/CMU, NeurIPS'25 Spotlight) | Per-prompt suffix-automaton cache over prior outputs; no model | token history only | no | tree, ragged per-request width | n/a (no checkpoint) |
| Frozen-KV MTP (SGLang) | MTP head reads target KV **read-only**, writes none of its own (`frozen_kv_mtp_worker_v2.py:14-19`); logical→physical layer map (`frozen_kv_mtp_info.py:28-40`) | target hidden state + read-only KV view | yes (MTP head) | chain | none named |
| Medusa (arxiv 2401.10774) | K independent per-position heads on final hidden state, argmax per head in this impl (`vllm/v1/spec_decode/medusa.py:44-54`) | final-layer hidden state only | yes (K heads) | chain here; tree+typical-acceptance in paper | Llama-2/Vicuna legacy only; none for Llama-3/Qwen3/gpt-oss/DeepSeek-V3.2 |
| HASS (arxiv 2408.15766) | Harmonized training objective/context for EAGLE-2 heads; same architecture as EAGLE-2 | same as EAGLE-2 | yes (training-time only) | tree (inherits EAGLE-2) | Llama-family only, per paper |
| EAGLE-3 vs EAGLE-2 | EAGLE-3 fuses multiple intermediate target layers (`aux_hidden_states`) instead of one final layer; some heads (`nvidia/gpt-oss-120b-Eagle3-v2`) opt out and behave like EAGLE-1/2 (`llm_base_proposer.py:1696-1710`) | 1 layer (EAGLE-2) vs config-selected multiple layers (EAGLE-3) | yes | tree | `nvidia/gpt-oss-120b-Eagle3-v2`, `RedHatAI/Llama-3.1-8B...eagle3`; gpt-oss-120b and Qwen3-30B-A3B/8B EAGLE-3 heads reported to exist per web research, Qwen3-0.6B and DeepSeek-V3.2 not confirmed |
| PLD / n-gram (`vllm/v1/spec_decode/ngram_proposer.py`) | Literal n-gram match + replay against token history | token history only | no | chain | n/a |
| PARD (arxiv 2504.18583) | Parallel (non-autoregressive) draft model, `parallel_drafting: true` flag on `draft_model` method | none beyond token history fed to draft model | yes | parallel block | `amd/PARD-Qwen3-0.6B` (targets Qwen3-8B, not 30B-A3B) |
| Hidden State Extraction | Not a drafter — saves aux hidden states via KV-transfer connector for offline EAGLE-style training | all requested layers (saved, not consumed live) | no | n/a | n/a |

## What a runner abstraction must expose to support all of these

- **Selectable intermediate-layer hidden-state output from the target
  forward**: DFlash/DSpark/EAGLE-3 all need a config-selected subset of
  layers, returned as a second output alongside normal logits
  (`gpu_model_runner.py:4556-4562,683-700`). Kelpie's `deepseek_v4.py
  forward()` currently returns only final post-norm logits — no seam for this
  today.
- **A drafter-owned KV write path into its own pool, fed by target hidden
  states, not just a read**: DSpark's `TargetHiddenKvInjector` writes into the
  *draft* model's KV cache after every verify/prefill
  (`dspark_kv_inject.py:35-94`) — a third KV-sharing shape beyond "drafter has
  its own KV" and "drafter reads target's KV read-only" (frozen-KV MTP).
- **Injection must run before the scheduler mutates cache-location state for
  that batch** (`dspark_worker_v2.py:471-472` — explicit ordering
  dependency), so the abstraction needs a hook point between verify-commit and
  scheduler cache reuse, not just before/after the whole step.
- **Per-request, per-step variable verify width driven by a confidence
  signal**: DSpark's planner needs device-decided query lengths in the
  attention backend and a startup-profiled per-shape cost model
  (`adaptive_verification.md`) — a runner that only supports a static K
  cannot host this without backend changes.
- **Host-side token/output history independent of any forward pass**: suffix
  decoding and n-gram need nothing from the target model.
- **Checkpoint-driven (not code-driven) shape selection**: block size, mask
  token id, target layer ids, and Markov/confidence head presence are all read
  from the draft checkpoint's HF config at load time
  (`dspark_config.py`, `dflash_utils.py:484-520`), not hardcoded per method.
