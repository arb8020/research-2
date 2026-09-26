# DeepSeek-V4.1-Flash: architecture, engine support, and kelpie fit

Sources: HF `deepseek-ai/DeepSeek-V4.1-Flash` model card and
`config.json` (https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash,
https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/raw/main/config.json), HF
`deepseek-ai/DeepSeek-V4-Flash-0731/raw/main/config.json` for the diff; vLLM PR #56201
(https://github.com/vllm-project/vllm/pull/56201, closed, superseded by #56214) and its sibling
PRs #56214, #56227, #56224, #56220, #56219, #56221, #56222, #56223, #56208, #56215, issue #56217;
SGLang PR #38798 (https://github.com/sgl-project/sglang/pull/38798, open) and #38802
(https://github.com/sgl-project/sglang/pull/38802, merged, docs-only cookbook), issue #38819.
Fetched 2026-09-10.

## Part 1 — the model

### config.json, V4.1-Flash vs V4-Flash-0731

V4.1's `text_config` (`model_type: deepseek_v41_text`, `architectures: ["DeepseekV41ForCausalLM"]`):
`num_hidden_layers: 40`, `hidden_size: 5120` (up from V4's 4096), `num_attention_heads: 64`,
`num_key_value_heads: 1`, `head_dim: 512`, `qk_rope_head_dim: 64`, `q_lora_rank: 1280` (V4: 1024),
new `o_lora_rank: 1024` / `o_groups: 8` (also present in V4), `n_routed_experts: 384` (V4: 256),
`n_shared_experts: 1`, `num_experts_per_tok: 6`, `moe_intermediate_size: 2304` (V4: 2048),
`vocab_size: 129280`, `sliding_window: 128`, `rope_theta: 10000` with yarn scaling factor 16
(unchanged from V4), `compress_rope_theta: 160000`.

**`compress_ratios` is the load-bearing diff.** V4-Flash-0731 (43 entries):
`[0,0, 4,128,4,128,... alternating ×20, 4, 0,0,0]` — only three ratio values (0/4/128).
V4.1-Flash (43 entries despite `num_hidden_layers: 40` — see discrepancy below):
`[0,0, 2×18, 1×21, 0,0,0]`. Two new ratio values, **1 and 2**, replace the alternating 4/128
pattern entirely; no layer in V4.1 runs ratio 4 or 128. This is confirmed operative, not
cosmetic, by SGLang PR #38798's `get_compress_state_ring_size` diff
(`python/sglang/srt/mem_cache/deepseek_v4_memory_pool.py`, new `compress_ratio == 2` branch):
ratio 2 keeps a ring of size 2 non-speculative, `1 << (num_draft_tokens+1).bit_length()`
speculative, addressed by `position % ring_size`; ratio 1 is not shown as a distinct ring case
in the diff hunk pulled, consistent with ratio-1 layers reading another layer's already-compressed
KV rather than compressing their own (see `kv_source_layer_ids` below).

**Layer-count discrepancy**: `text_config.num_hidden_layers = 40` but `compress_ratios` has 43
entries and `dspark_target_layer_ids: [37, 38, 39]` indexes up to 39 (0-based, consistent with
40 real layers) while V4's own `dspark_target_layer_ids: [40, 41, 42]` indexed into its 43-entry
array. Read together with the model card's "40-layer Transformer, 20-layer causal encoder
followed by a 20-layer decoder": V4.1 folds the old 43-slot layout (40 backbone + 3 NextN/DSpark
draft layers counted separately in V4) into `num_hidden_layers=40` proper, and `compress_ratios`
still carries 43 entries because 3 of them describe the DSpark draft stage's own compression,
not real decoder layers. This is a checkpoint-format change, not just a config field rename — a
loader keyed on `len(compress_ratios) == num_hidden_layers` (true for V4) breaks silently on
V4.1.

**New top-level fields absent from V4's config, all confirmed live in the PRs**:
- `kv_source_layer_ids: [2, 8, 14, 20]` — layers whose compressed KV is *read by* other layers
  rather than recomputed; SGLang PR #38798 added `kv_source_layers: Sequence[int]` to
  `DeepSeekV4MemoryPool.__init__` and `sources_by_ratio = self._collect_sources_by_ratio()`.
  This is the model card's "CSA2 Reuse mode" — a static per-layer choice of Full / Reindex /
  Reuse, where Reuse means "this layer's attention reads a *different* layer's compressed KV
  table, write nothing of its own." V4 has no such field; every V4 layer with a nonzero ratio
  compresses and stores its own KV.
- `index_source_layer_ids: [2, 8, 14, 20, 24, 28, 32, 36]`, `candidate_source_layer_id: 20`,
  `candidate_topk_blocks: 2048`, `candidate_block_size: 8` — the "Hierarchical Sparse Indexer."
  Layer 20's indexer scores produce a `candidate_topk_blocks`-sized pool of `candidate_block_size`
  ‑token blocks; the later `index_source_layer_ids` (24..36) run their own top-k *restricted to
  that candidate pool* rather than over the full sequence, bounding indexer cost independent of
  context length. V4's DSA indexer (`index_topk: 512`, `index_n_heads: 64`) has no source-layer
  hierarchy or candidate-block prefilter — every indexed layer scores the full KV. V4.1 also
  drops `index_n_heads` to 32 (from 64) and keeps `index_head_dim: 128`, `index_topk: 512`.
- `hc_mult: 4`, `hc_sinkhorn_iters: 20`, `hc_eps: 1e-6` — these three keys already exist in V4's
  config (unchanged), so "mHC" (multi-head Hadamard/Sinkhorn residual mixing per the model card's
  "Single-Pass mHC") predates V4.1; V4.1's addition is the *kernel*, not the field: vLLM PR #56201
  adds `vllm/model_executor/kernels/mhc/{tilelang,tilelang_kernels,torch,triton,warmup}.py` (a
  new kernel directory) and `vllm/model_executor/warmup/deepseek_v4_mhc_warmup.py`.
- `engram_layer_ids: [1, 14]`, `engram_num_embeddings: [384006168, 384016682]`,
  `engram_max_ngram_size: 4`, `engram_vocab_size: 16000000`, `engram_n_heads: 8`,
  `engram_head_dim: 256`, `engram_compressed_vocab_size: 99092` — wholly new, absent from V4.
  "Engram conditional memory" (model card: 196B params, sparsely accessed via token lookup) is an
  n-gram hash table indexed by recent token history, not attention over any KV cache: vLLM PR
  #56201 adds `vllm/config/engram.py` (54 lines) and SGLang PR #38798 adds
  `python/sglang/srt/layers/engram.py` (954 lines, the single largest new file in that PR) plus
  three new Triton ops `engram_gate.py`, `engram_gather.py`, `engram_hash.py`
  (`python/sglang/kernels/ops/embeddings/`). This sits beside the transformer stack, not inside
  attention, and needs no per-token/per-seq KV cache group at all — its state is a static
  384M-row embedding table plus a request-scoped lookback buffer (vLLM PR #56224, "Preserve
  lookback inputs across microbatches").
- `dspark_target_layer_ids: [37, 38, 39]`, `dspark_block_size: 5`, `dspark_noise_token_id: 128799`,
  `dspark_markov_rank: 256`, `dspark_n_routed_experts: 128`, `dspark_num_experts_per_tok: 3` — the
  three fields `dspark_n_routed_experts` / `dspark_num_experts_per_tok` / `dspark_markov_rank` are
  new relative to V4 (V4 has `dspark_target_layer_ids`, `dspark_block_size`,
  `dspark_noise_token_id`, `dspark_markov_rank` only, no separate MoE shape for the draft). V4.1's
  DSpark draft head is therefore its own small MoE (128 experts, top-6→3 of them), not a dense
  head riding the target model's MoE. `num_nextn_predict_layers: 3` (matches V4's
  `num_nextn_predict_layers: 1` scaled up — V4.1 ships 3 NextN/MTP layers, not 1). The model card's
  "DSpark: semi-autoregressive draft generation with confidence-scheduled verification, block
  size 5" — `dspark_block_size: 5` tokens are drafted per DSpark step, and unlike a single MTP
  head chained autoregressively, DSpark reads `dspark_target_layer_ids: [37,38,39]` — three
  *target*-model layers, not just the last hidden state — per the ladder doc's rung 09 note
  ("DSpark head reads 3 target layers").

**Quantization**: V4.1 top-level `quantization_config` is `{quant_method: fp8, weight_block_size:
[32,32], scale_fmt: ue8m0, expert_dtype: fp4, activation_scheme: dynamic}` — block size 32×32,
down from V4's `128×128`. `expert_dtype: fp4` is unchanged from V4. The model card's "FP4 main KV
caching (E2M1 format) ... 890 bytes/token, 1/4 of V4-Flash" is a *cache* quantization, separate
from the weight `quantization_config` block — confirmed by SGLang PR #38798's
`DeepSeekV4IndexerPool.use_fp4_indexer` / `get_index_k_fp4` / `get_index_k_dequant`
(`python/sglang/srt/mem_cache/deepseek_v4_memory_pool.py`), which packs indexer K as 4-bit codes
(2 values/byte) plus one e8m0 exponent per 32 values, and vLLM PR #56201's new
`csrc/libtorch_stable/fused_deepseek_v4_qnorm_rope_kv_insert_kernel.cu` (rewritten, +76/-58) and
`tests/kernels/test_fused_indexer_q_rope_quant.py` (+359 lines). This FP4 *cache* path is new in
V4.1; V4-Flash-0731 stored KV at higher precision (the ladder doc's 584 B/tok estimate for
V4-Flash's compressed KV, vs. V4.1's reported 890 B for the *whole* cache, aligns with V4.1
paying less per byte but storing more member types per token, per the ladder note "1/4 of
V4-Flash").

**RoPE**: unchanged — yarn scaling (`factor: 16`, `beta_fast: 32`, `beta_slow: 1`,
`original_max_position_embeddings: 65536`), `rope_theta: 10000`, plus the separate
`compress_rope_theta: 160000` for the compressed-KV path, both present in V4 too.

**Vision**: `vision_config.model_type: deepseek_v41_vision`, 32 layers, hidden 1024, 2D-RoPE
(`rope_theta: 10000`), 3×3 pixel-unshuffle (`downsample_ratio: 3`) — the model card's "DeepSeek-ViT."
No `vision_config` block appears in the V4-Flash-0731 config fetched; V4.1 is natively
multimodal where V4-Flash was text-only, per SGLang PR #38804 ("Allow DP attention with
DeepSeek V4.1 vision checkpoints", merged) and vLLM PR #56201's diff to
`vllm/models/deepseek_v4/common/vision.py`.

### Per-layer attention taxonomy (V4.1, 40 real layers + 3 DSpark draft layers)

Every layer, draft included, carries a 128-token SWA ring (`sliding_window: 128`), matching V4.
Beyond that, per `compress_ratios`:
- Layers 0–1: ratio 0, full/uncompressed KV, presumably `kv_source_layer_ids`-adjacent setup
  layers (matches V4's own layers 0–1 at ratio 0).
- Layers 2–19 (18 layers): ratio 2 — new. Each keeps a 2-token compress-state ring; per the
  SGLang diff this is the smallest possible compression stride, essentially "pairs of tokens
  compressed together," a finer grain than V4's coarsest compressed tier (ratio 4).
- Layers 20–40 (21 layers): ratio 1 — new, and semantically distinct from "no compression": a
  ratio-1 "compressed" layer is a `DeepSeekV4LayerItem(compress_ratio=1, compress_layer_id=...)`
  entry (SGLang diff, `Literal[0, 1, 2, 4, 128]`) whose `compress_layer_id` is shared with the
  `kv_source_layer_ids` layer that actually wrote it — i.e., ratio-1 layers do not compress their
  own KV at all; they are the CSA2 "Reuse" layers reading a `kv_source_layer_ids` layer's table.
- Last 3 entries (indices 40–42 of the 43-length array): ratio 0, the DSpark draft stage.

This is architecturally new relative to both V4 and kelpie's modeled taxonomy: V4's `CSA`/`HCA`
split (ratio 4 vs 128, both self-compressing) becomes, in V4.1, a three-way split of
self-compress-fine (ratio 2) / read-another-layer's-compressed-KV (ratio 1, "Reuse") /
full (ratio 0), plus a *separate* hierarchical indexer that itself has a source/candidate-pool
split independent of the KV compression split.

### MTP / spec-decode

`num_nextn_predict_layers: 3` (V4: 1) feeding a DSpark draft (`dspark_block_size: 5` tokens/step,
its own 128-expert/top-3 MoE, reading 3 target layers). This is not V4's plain NextN single-token
MTP head; it is materially larger (3 predict layers instead of 1, block drafting instead of
chained single-token, its own MoE).

## Part 2 — engines

### vLLM

Primary tracking PR: **#56214, "[Model] Support DeepSeek-V4.1-Flash"**
(https://github.com/vllm-project/vllm/pull/56214, open) — supersedes the closed **#56201**
(https://github.com/vllm-project/vllm/pull/56201, same title, +20,031/-542 across 96 files,
closed in favor of #56214 per GitHub's PR-diff-too-large 406 on #56201's own diff, so #56201's
file list stands as the actual content even though the branch moved).

Split into companion PRs, all open as of fetch:
- **#56228** "[Model] DeepSeek-V4.1-Flash Model Definitions"
- **#56227** "[Feat][Model] Support SWA-bounded replay for DeepSeek-V4.1-Flash" (supersedes
  closed #56205, same title)
- **#56224** "[Model][Engram] Preserve lookback inputs across microbatches in DeepSeek-V4.1"
- **#56220** "[Perf][Model][Engram] Overlap embedding lookup with decoder compute in
  DeepSeek-V4.1"
- **#56219** "[Perf][Model][Engram] Use all-to-all for sequence-parallel embedding exchange in
  DeepSeek-V4.1"
- **#56221** "[Model][PP] Validate layer-sharing dependencies before stage construction in
  DeepSeek-V4.1" — pipeline-parallel-aware validation that a `kv_source_layer_ids`
  reader and its writer land on the same PP stage.
- **#56223** "[Model][PP] Support cross-stage KV and index sharing in DeepSeek-V4.1" — when they
  don't land on the same stage, ship the KV/indexer across stages.
- **#56222** "[Model] Support sequence-parallel stage boundaries under pipeline parallelism in
  DeepSeek-V4.1"
- **#56208** "[Model][Frontend] Support DeepSeek-V4.1-Flash in Rust and Python frontends" — tool
  call / reasoning parser support (`rust/src/chat/src/renderer/deepseek_v41/`,
  `rust/src/parser/src/tool/deepseek_dsml/deepseek_v41.rs`).
- **#56215** "[Kernel] Optional Q-norm in fused DSv4 MLA epilogue; group_size=32 for packed FP8
  quant" (merged) — the weight_block_size 128→32 change from Part 1 lands here as a kernel change
  to the fused MLA epilogue, not a config-only tweak.
- Tracking issue **#56217** "[Feature]: DeepSeek-V4.1-Flash kernels integration."

From #56201's file list, files touched by kind:
- **Model files**: `vllm/models/deepseek_v4_1/__init__.py` (new, +20),
  `vllm/models/deepseek_v4_1/amd/{__init__.py,dspark.py (+546, new),model.py (+1087, new)}` —
  AMD gets its own full model + DSpark file; an `nvidia/` counterpart is implied by
  `vllm/models/deepseek_v4/nvidia/model.py` (+51/-15, shared with V4) but no
  `deepseek_v4_1/nvidia/` path appears in this truncated slice (#56228 likely carries it, not
  fetched in full — file list not re-verified beyond #56201's diff).
- **Attention/indexer kernel**: `vllm/model_executor/kernels/attention/dsa/candidate_blocks.py`
  (new, +234) — this is the hierarchical-indexer candidate pool from Part 1
  (`candidate_source_layer_id`, `candidate_topk_blocks`, `candidate_block_size`); new file, no V4
  equivalent. `vllm/model_executor/layers/sparse_attn_indexer.py` (+97/-4, extended not replaced).
- **MoE/quant kernels**: `vllm/model_executor/kernels/linear/mxfp8/{deep_gemm.py (new, +128),
  flashinfer.py (+38/-14)}` — **DeepGEMM is a newly wired backend** for the mxfp8 linear path (not
  present as a `deep_gemm.py` kernel file before this PR by its diff being entirely additions);
  FlashInfer's existing mxfp8 kernel path is extended, not replaced.
- **mHC kernels**: `vllm/model_executor/kernels/mhc/{tilelang.py (new, +200), tilelang_kernels.py
  (+67/-18), torch.py (new, +42), triton.py (+45/-1), warmup.py (new, +74)}` — TileLang is a new
  kernel backend for mHC alongside a Torch reference and a Triton path.
- **Cache manager**: `vllm/config/speculative.py` (+40/-8, DSpark's 3-target-layer draft needs new
  speculative-config plumbing), `vllm/config/vllm.py` (+27, new), `vllm/config/engram.py` (+54,
  new — a wholly new config *kind*, engram is not modeled as a cache group at all, it is a
  side-table), `tests/v1/core/test_contiguous_kv_packing.py` (+102, new) and
  `tests/kernels/test_compressor_kv_cache.py` (+432, new). No new `KVCacheSpec` subclass (e.g. no
  `CompressedKVSpec` file) appears in this diff slice — vLLM's existing `SlidingWindowSpec`
  machinery plus a new compressor-aware pool test suggests the compressed-KV grouping rides
  existing spec kinds with new packing logic rather than a new `kv_cache_interface.py` class; not
  confirmed without reading `#56227`/`#56228`'s own diffs (not fetched — 56201's diff was already
  at the 20k-line API cap).
- **Rough line counts** (#56201 alone): +20,031/-542 across 96 files. Kernel/op code
  (`csrc/`, `kernels/`) is a small fraction (~500 lines); the bulk is Rust frontend/parser
  (~1,200 lines) and the two AMD model files (~1,600 lines) plus tests (~4,000 lines).

### SGLang

**#38798, "[Model] Add DeepSeek V4.1 support"** (https://github.com/sgl-project/sglang/pull/38798,
open, +15,141/-907 across ~110 files; supersedes closed #38797, same title). Companion PR
**#38802, "Add DeepSeek-V4.1 Flash cookbook"** (merged, docs-only, 6 files) — confirms via its own
description that V4.1-Flash "has not shipped in a release" as of the PR, ships on
`lmsysorg/sglang:dev-dsv41` preview images, and that DSpark ("the model's bundled three-stage
draft") is the low-latency speculative option while H200 instead uses "decoder SWA bounded
replay" for its second operating point — i.e. SWA-bounded-replay and DSpark are presented as
alternative levers, not both-always-on. **#38804, "Allow DP attention with DeepSeek V4.1 vision
checkpoints"** (merged) adds vision-model DP-attention support. Tracking issue **#38819**,
"[Feature] End-to-end PD disaggregation + DSpark support for DeepSeek-V4.1" (open) — confirms
DSpark support is still incomplete for prefill/decode-disaggregated serving.

From #38798's diff, files touched by kind:
- **New kernels, CUDA (`.cuh`)**: `python/sglang/kernels/jit/csrc/deepseek_v4/{c1.cuh (new,
  +296), c2.cuh (new, +390), fp4_rope.cuh (new, +458)}`, plus edits to `topk_v2.cuh` (+7/-31) and
  two new small-GEMM headers `gemm/small/{n128k512.cuh (new, +151), n32k5120.cuh (new, +169)}`
  and a `gemm/tiny_gemm.cuh` rewrite (+4/-19). `c1`/`c2` are almost certainly the ratio-1/ratio-2
  compress paths new in V4.1 (naming matches `compress_ratio in [1,2,4,128]` from the memory-pool
  diff below); `fp4_rope.cuh` is the FP4 indexer-K RoPE-and-quant fusion. These are **own Triton/
  CUDA kernels**, not FlashInfer or DeepGEMM wrappers — SGLang vendors and hand-writes them under
  `sglang/kernels/jit/`.
- **New kernels, Python wrappers**: `python/sglang/kernels/ops/attention/dsv4/{c1.py (new, +95),
  c2.py (new, +152), fp4_rope.py (new, +166), metadata_kernel.py (new, +60), pair_pool_decode.py
  (new, +158), rmsnorm_fp32.py (new, +39), rope_fake_quant_fp4.py (new, +130),
  rope_pack_indexer.py (new, +138), sm90_fp4_indexer.py (new, +151), wo_a_bf16_gemv.py (new,
  +44)}` — ten new op files for the ratio-1/2 compress paths, FP4 indexer packing, and an
  SM90-specific FP4 indexer variant (Hopper path distinct from the general one).
- **Engram kernels**: `python/sglang/kernels/ops/embeddings/{engram_gate.py (new, +76),
  engram_gather.py (new, +80), engram_hash.py (new, +247)}` and model layer
  `python/sglang/srt/layers/engram.py` (new, +954) — the largest single new file in the PR.
- **mHC kernels**: `python/sglang/kernels/ops/layernorm/{mhc.py (new, +315), mhc_post_split_h.py
  (new, +47)}`.
- **Attention backend**: `python/sglang/srt/layers/attention/deepseek_v4_backend.py` (+2,084/-132,
  by far the largest edit to an existing file — this is the main attention dispatch, extended in
  place, not replaced), `deepseek_v4_backend_hip_radix.py` (+15/-17, AMD variant),
  `dsv4/dsv41_sparse.py` (new, +288, the sparse-attention path presumably wiring the hierarchical
  indexer's candidate pool into attention), `dsv4/indexer.py` (+27, new), `dsv4/metadata.py`
  (+40/-2), `dsv4/torch_quant.py` (new, +62).
- **Cache manager — this is the notable extension**: `python/sglang/srt/mem_cache/
  deepseek_v4_memory_pool.py` (+414/-122) adds `compress_ratio == 2` as a **new ring-size case**
  in `get_compress_state_ring_size` (ring size 2 non-speculative, next-power-of-2 above
  `num_draft_tokens+1` speculative — quoted in Part 1), extends `DeepSeekV4LayerItem.compress_ratio`
  from `Literal[0, 4, 128]` to `Literal[0, 1, 2, 4, 128]`, and adds `kv_source_layers` +
  `sources_by_ratio = self._collect_sources_by_ratio()` to `DeepSeekV4MemoryPool.__init__` — a
  genuinely new pool-construction concept (a layer's pool entry can point at *another layer's*
  pool rather than owning storage), matching the "Reuse" CSA2 mode. This is **not** a wholly new
  cache-group kind in SGLang's terms — it reuses the existing `DeepSeekV4SingleKVPool` /
  `DeepSeekV4IndexerPool` classes — but the *indexing* into those pools (by `kv_source_layer_ids`
  rather than by the reading layer's own id) is new plumbing threaded through
  `DeepSeekV4LayerItem.compress_layer_id`.
- **New file entirely for the model-card "SWA Bounded Replay" feature**:
  `python/sglang/srt/mem_cache/dsv41_request_window.py` (new, +234) — a `RequestWindow` class
  keyed by `(req, pos % capacity)` with `capacity = sliding_window + draft_tokens`, storing a
  packed `[576-wide KV | 8-wide indexer]` row per slot (`copy_packed_tokens`'s two `(width, base)`
  pairs — 576 matches the ladder doc's ~584 B/tok CSA row estimate, 8 matches indexer packing),
  and a `history_valid` mask that raises `RuntimeError("SWA history is missing: replay or window
  ownership is invalid")` if a read misses a tag it expects — i.e. this ring asserts contiguity
  exactly like kelpie's `state.ring_rows` assertion (`docs/cache-groups-ladder.md` line ~234,
  `test_ring_rejects_a_resume_it_never_saw`). It is activated only when
  `get_exec().features.enable_encoder_swa_bounded_replay` is set (line ~697 of the diff), as an
  alternative to the existing `_unified_kv` path — confirming, with #38802's cookbook description,
  that SWA-bounded-replay is opt-in and mutually exclusive with the plain unified-KV SWA pool for
  a given deployment.
- **Hybrid allocator wiring**: `python/sglang/srt/mem_cache/hybrid_cache/hybrid_pool_assembler.py`
  (new, +90), `kv_cache_configurator.py` (+20/-2), `kv_cache_builder.py` (+5/-1),
  `pool_configurator.py` (+230/-63, the biggest existing-file cache edit besides the memory pool
  itself), `kv_index_translator.py` (+2/-1) — the hybrid allocator (SGLang's `HybridReqToTokenPool`
  family, referenced in kelpie's `kv-groups.md` line 68) grows a new assembler path rather than a
  new manager class.
- **Spec-decode**: no `speculative_v4.py`-named file appears; DSpark plumbing is spread across
  `arg_groups/deepseek_v4_hook.py` (+119/-5), `model_executor/model_runner_components/
  ngram_embedding_manager.py` (+67/-10, likely misnamed for this PR's purposes — "ngram" here is
  Engram's hash table, not n-gram spec-decode), and the two `c1.py`/`c2.py` compress kernels feed
  both the real forward and DSpark's draft forward per the model card's "reads 3 target layers."
- **Rough line counts** (#38798): +15,141/-907 across ~110 files. Kernel code (`kernels/jit/csrc`
  + `kernels/ops`) is roughly 3,400 lines; the attention backend edit alone is 2,084 lines; Engram
  is ~1,280 lines (layer + 3 kernels); mHC ~360 lines; the new SWA-replay cache file 234 lines;
  memory-pool/hybrid-cache plumbing ~760 lines.

## Part 3 — kelpie

Read: `docs/cache-groups-ladder.md`, `docs/kv-groups.md`, `docs/ladder.md`,
`kelpie-models/kelpie_models/models/torch/deepseek_v4_flash.py`,
`kelpie-models/kelpie_models/sdk/ops.py`, `kelpie-core/src/kv_pool.zig`. Note: there is no
`kelpie_models/groups.py` at that exact path — the group taxonomy referenced by
`cache-groups-ladder.md` (`FullAttn`, `SlidingAttn`, `MLA`, `CSA`, `HCA`, `Recurrent`, `NoCache`,
`CacheSpec`, `derive_groups`) is *specified* in that doc but not found as a standalone
`groups.py` module in the tree at this path; `deepseek_v4_flash.py`'s docstring and `attn_specs`
stub reference the same taxonomy, so it is either inlined elsewhere or not yet materialized as
that exact file — this claim needs a follow-up `find` if the file matters to the next task.

Kelpie already tracks **DeepSeek-V4-Flash** (the `-0731` checkpoint, V4 not V4.1) as ladder rung
09, `docs/ladder.md:40`, and has designed (not built) its cache groups in
`docs/cache-groups-ladder.md:72-82` (W128/C4/C128/S4/S128) and a stub model file
`kelpie-models/kelpie_models/models/torch/deepseek_v4_flash.py` whose `attn_specs`, `load`, and
`forward` all `raise NotImplementedError`. **V4.1-Flash is a materially different checkpoint from
what's stubbed**: same family name, different `compress_ratios` values (1/2 vs 4/128), a new
cross-layer KV-reuse mode, a new hierarchical indexer, Engram, mHC kernels, and a 3-layer DSpark
draft vs 1-layer NextN. Below, per requirement, whether kelpie's existing group taxonomy /
attention-op seam expresses it.

**Ratio-2 compress layers (18 of them, `compress_ratios` values of 2).** Kelpie's
`CacheSpec.stride` is already a free integer (`docs/cache-groups-ladder.md:19`,
`kelpie-core/src/kv_pool.zig`'s `PoolGroup`/pool design takes `bytes_per_page` and
`pages_per_slab` per group with no hardcoded stride set), and `docs/cache-groups-ladder.md:198-207`
("As built (derisk/dsv4): stride groups") states `GroupSpec.stride` was added generically and
"nothing beyond `stride` was needed in the core" when V4's 4/128 grains were added. A ratio-2
group is `derive_groups`-distinct from ratio-4/128 only by its `stride` value, per the same
keying rule (`kind, stride, retention, n_snapshots, cacheable`, `docs/cache-groups-ladder.md:29`).
**Already expressed — no new group kind or op needed for the stride itself.** What is not yet
built: the ratio-2 group's *ring size* (SGLang's `get_compress_state_ring_size(ratio=2)`, a
2-entry non-speculative ring) needs the S-group family's `n_snapshots`/ring math extended with a
new stride value (S2 alongside S4/S128), a data change to `deepseek_v4_flash.attn_specs`'s
`NotImplementedError` message, not a schema change.

**Ratio-1 "Reuse" layers (21 of them) reading another layer's compressed KV
(`kv_source_layer_ids`).** This is the one requirement kelpie's taxonomy does not express. Every
existing group kind (`FullAttn`, `SlidingAttn`, `MLA`, `CSA`, `HCA`, `Recurrent`, `NoCache`) is
declared *per layer that owns storage* — `derive_groups` assigns each layer's caches to a group
by its own spec (`docs/cache-groups-ladder.md:5-27`), and `layer_caches: list[list[(group,
offset)]]` (`docs/cache-groups-ladder.md:93,147`) already supports a layer pointing at a *member*
of a group it does not "own" in the sense of GLM-5.2's shared-indexer layers (`layer_caches[6] =
[(F, 6), (F, 79+3)]`, same doc). **This is close but not identical**: GLM-5.2's shared indexer is
one layer writing its own indexer member that happens to share a *table*; V4.1's ratio-1 reuse is
a layer that writes **nothing** and reads a **different, specific** layer's already-written
member — the offset it needs is not `(layer, cache-order)` but `kv_source_layer_ids[nearest]`, an
explicit mapping the doc's `derive_groups` ordering rule doesn't cover. **Needs a small schema
addition**: `layer_caches` entries need a `reads_from: layer_id | None` (or the offset tuple
itself needs to be able to name another layer's offset directly) rather than a new group kind —
the group and its C4-style byte layout are unchanged, only the *layer→offset* assignment gains a
non-identity case. File:line: `docs/cache-groups-ladder.md:93-96` (Q2, "Multi-cache layers") is
where this rule lives and would need a third bullet; `kelpie_models/models/torch/
deepseek_v4_flash.py:70-79` (`attn_specs` docstring) is the model-file site that would encode it.

**Hierarchical sparse indexer (`index_source_layer_ids`, `candidate_source_layer_id`,
`candidate_topk_blocks`, `candidate_block_size`).** Kelpie's `dsa_indexer_topk` op
(`kelpie-models/kelpie_models/sdk/ops.py:405-425`) takes `q, indexer_member, ..., topk` and
returns a flat top-k over one layer's own indexer cache — it has no notion of "restrict the
search to a `candidate_topk_blocks`-sized pool computed by a *different* layer." **Needs a new
op** (or a materially new argument set on `dsa_indexer_topk`): the op signature at
`kelpie-models/kelpie_models/sdk/ops.py:406-414` would need a `candidate_indices` tensor input
(the pool from `candidate_source_layer_id`'s own top-k) and the pool-producing call itself is a
*second* indexer invocation with different semantics (score `candidate_topk_blocks` blocks of
`candidate_block_size` tokens, not `topk` individual tokens) — this second shape does not exist
in `ops.py` at all today. The cache group question (does the candidate pool need a slab-pool
entry) is separate and smaller: SGLang's implementation (Part 2) stores it as workspace, not a
persisted per-request cache, so it likely needs no new `GroupSpec`, just a transient buffer, which
kelpie's `kv_pool.zig` doesn't manage (it manages persisted per-request KV, not scratch tensors —
`kelpie-core/src/kv_pool.zig:1-25` header scopes the pool to "cache group" pages specifically).

**SWA Bounded Replay.** This is exactly kelpie's `window(W, cacheable=False)` group — confirmed
by the two implementations converging: SGLang's `RequestWindow` (Part 2) keyed by
`(req, pos % capacity)` with a `history_valid` contiguity assertion is the same shape as kelpie's
existing DSV4 W128 group (`docs/cache-groups-ladder.md:76`, "W128 ... cacheable=false ... window
128") and the same correctness argument kelpie already derived independently
(`docs/cache-groups-ladder.md:222-227`, "window(W, cacheable=False) must hit 0, not t-W ... Only
a cached window or a full recompute is exact"). The one gap: V4.1's replay `capacity =
sliding_window + draft_tokens` (SGLang diff) generalizes kelpie's plain `window(W)` to a ring
wider than the live window to hold speculative lookahead — this is already anticipated verbatim
by `docs/cache-groups-ladder.md:89` ("Spec-dependent unit size: `caches(spec, max_spec_tokens)`
... Not a new field, a parameter") and `:72` ("Spec adds `max_spec_tokens` to the ring"). **Fully
expressed already, including the spec-decode-width generalization** — file:line
`docs/cache-groups-ladder.md:72,89`.

**Engram (n-gram conditional memory, no attention).** Not a cache group in any sense kelpie's
taxonomy models — it is a static hash-table lookup keyed on token history, no per-token or
per-seq *cache* semantics (nothing is written incrementally and read back with a retention
policy; SGLang's `engram.py` and `engram_hash.py` build a gather index from raw token ids, not
KV). **Needs neither a new group kind nor a new attention op** — it needs a wholly separate
mechanism outside the `CacheSpec`/`attention-as-family-of-ops` seam entirely: an embedding-table
lookup op (closer to `kelpie::silu_mul`'s "torch has no fused op for this" category,
`kelpie-models/kelpie_models/sdk/ops.py:66-76`, than to any attention op) plus request-scoped
lookback state that is *not* KV (vLLM PR #56224's "preserve lookback inputs across microbatches"
is exactly this: a small per-request buffer of recent token ids, not per-layer KV). Kelpie's
`kv_pool.zig` and `cache-groups-ladder.md` are silent on non-KV per-request state by design (the
`Recurrent` state ring, `docs/cache-groups-ladder.md:13`, comes closest but is declared as
attention-adjacent layer state, and Engram is not attention at all — it doesn't participate in
`layer_caches`). This is the one requirement that stresses kelpie's abstractions **outside their
stated scope**, not a gap inside them.

**mHC (Hadamard/Sinkhorn residual mixing kernel).** Not a cache or attention concern at all — a
pointwise/matmul-shaped op on the residual stream between layers (vLLM's `mhc/{tilelang,torch,
triton}.py`, no KV argument in any of those files' names). Maps cleanly to kelpie's existing
"custom op for math torch doesn't fuse" pattern (`ATEN_OPS`/`KELPIE_OPS` split,
`kelpie-models/kelpie_models/sdk/ops.py:40-45`) — would be a new `kelpie::mhc_mix`-style entry in
`KELPIE_OPS` (`kelpie-models/kelpie_models/sdk/ops.py:34-38`), no cache implications. **Needs a
new op, no new group kind.**

**DSpark (3-layer draft, block size 5, own 128-expert MoE, reads 3 target layers).** Kelpie's
`docs/ladder.md:23` already names DSpark as the spec-decode axis for rung 09 ("spec-decode head
... 09 (DSpark)") and the ladder's engine-axis table treats "spec-decode head" as
`kind`/`n_drafts` plumbing plus verify sampling, not a new cache kind — MTP/draft layers already
join the target's group as another member (`docs/cache-groups-ladder.md:91`, "a 'draft' kind ...
not needed ... MTP joins the target group as another member; verify rewrites its slots"). V4.1's
DSpark is bigger (3 draft layers instead of 1, its own MoE) but not a different *shape* of cache
requirement — it needs `grouped_mm_mxfp4` (already stubbed,
`kelpie-models/kelpie_models/sdk/ops.py:493-515`) called for the draft's own smaller MoE, and the
S-groups' `n_snapshots`/ring sizing doubled for `max_spec_tokens` (already the documented pattern,
`docs/cache-groups-ladder.md:72`, "doubles the compress-state rings (8->16, 128->256)").
**Already expressed as a pattern; needs data (3 layers instead of 1, block_size 5) not schema.**

**FP4 indexer-K cache packing (E2M1, 2 values/byte + e8m0 exponent per 32).** Kelpie's
`CacheSpec.bytes_per_unit` (`docs/cache-groups-ladder.md:20`) is already an opaque byte count "or
(heads, dim, dtype) sugar," and the doc explicitly notes byte packing is a Python-side concern
("Python owns `caches(spec)`, byte packing and offsets," `docs/cache-groups-ladder.md:130`) that
the Zig core never sees (`kelpie-core/src/kv_pool.zig`'s header: "the core owns tables, admission,
and hit lengths; it must know shape and lifetime, never dtype or layout" — paraphrased from
`docs/cache-groups-ladder.md:129`, consistent with `kv_pool.zig`'s `PoolGroup{bytes_per_page,
pages_per_slab}` taking an opaque byte count). **Already expressed — FP4 packing is a
`bytes_per_unit` computation change in `kelpie_models`, invisible to `kv_pool.zig`.**

## Table

| requirement | vLLM did | SGLang did | kelpie has / needs |
|---|---|---|---|
| ratio-2 compress layers (18) | folded into existing compressed-KV path, weight_block_size 128→32 kernel change (#56215) | new `compress_ratio == 2` branch in `get_compress_state_ring_size`, `deepseek_v4_memory_pool.py` (+414/-122) | **has**: `GroupSpec.stride` is generic (`docs/cache-groups-ladder.md:198-207`); needs only a new stride value + ring-size data, no schema change |
| ratio-1 "Reuse" layers reading another layer's KV (21) | cross-PP-stage sharing: #56221 (validate), #56223 (ship KV/index across stages) | `kv_source_layers` + `sources_by_ratio` added to `DeepSeekV4MemoryPool.__init__`; `compress_layer_id` now points at another layer's pool | **needs**: `layer_caches` needs a `reads_from: layer_id` case; current `(layer, cache-order)` offset rule (`docs/cache-groups-ladder.md:93-96`) doesn't name another layer directly |
| hierarchical indexer (source layers + candidate pool) | new file `kernels/attention/dsa/candidate_blocks.py` (+234); `sparse_attn_indexer.py` extended (+97/-4) | new `dsv4/dsv41_sparse.py` (+288), `sm90_fp4_indexer.py` (+151) | **needs a new op**: `dsa_indexer_topk` (`ops.py:405-425`) has no candidate-pool input or second-shape (block-level top-k) call |
| SWA bounded replay | #56227/#56205, "SWA-bounded replay" companion PR | new file `mem_cache/dsv41_request_window.py` (+234), opt-in via `enable_encoder_swa_bounded_replay` | **fully has**: is exactly `window(W, cacheable=False)` + `max_spec_tokens` ring widening, both already documented (`docs/cache-groups-ladder.md:72,89,222-227`) |
| Engram conditional memory | new `vllm/config/engram.py` (+54); #56224/#56220/#56219 for lookback/perf | new `srt/layers/engram.py` (+954, largest new file) + 3 kernels (~400 lines) | **outside scope**: not KV, not attention; needs a lookup op + non-KV per-request lookback state, neither modeled by `CacheSpec`/`kv_pool.zig` |
| mHC residual mixing | new `kernels/mhc/{tilelang,torch,triton,warmup}.py` (~380 lines) | new `kernels/ops/layernorm/{mhc,mhc_post_split_h}.py` (~360 lines) | **needs a new op** (`KELPIE_OPS` entry), no cache implication |
| DSpark (3 draft layers, own MoE, block 5) | speculative config plumbing (`config/speculative.py` +40/-8) | spread across `arg_groups/deepseek_v4_hook.py` etc.; c1/c2 kernels feed both real + draft forward | **has the pattern**: MTP-as-member-of-target-group already documented (`docs/cache-groups-ladder.md:91`); needs data update (1→3 layers) + `grouped_mm_mxfp4` call for draft's own MoE (already stubbed, `ops.py:493-515`) |
| FP4 indexer-K cache (890 B/tok) | fused kernel rewrite `fused_deepseek_v4_qnorm_rope_kv_insert_kernel.cu` | `get_index_k_fp4`/`get_index_k_dequant` pack/unpack in `deepseek_v4_memory_pool.py` | **fully has**: `bytes_per_unit` is opaque to the Zig core by design (`kv_pool.zig` header, `docs/cache-groups-ladder.md:129-130`) |
| layer-count/config mismatch (`num_hidden_layers=40` vs 43-entry `compress_ratios`) | n/a (their loader reads both fields explicitly per-PR) | n/a | **needs care in `config_from_hf`**: `deepseek_v4_flash.py:60-73`'s `config_from_hf` reads `compress_ratios` length-agnostically already (`tuple(...)`), so no crash, but `attn_specs` (currently `NotImplementedError`) must not assume `len(compress_ratios) == n_layers` |
