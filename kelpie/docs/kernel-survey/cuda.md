# CUDA kernel survey

Checked out sparse under `/tmp/kernel-survey/<name>` (`--filter=blob:none`): flashinfer, flash-linear-attention
(fla), DeepGEMM, TensorRT-LLM, Liger-Kernel, tilelang, cutlass, flash-attention, quack, tokenspeed. vLLM and
SGLang were surveyed by web search only (blog posts + issue trackers), not cloned — cite URLs for those claims.

Kelpie's contract, for reference (`kelpie-models/kelpie_models/sdk/ops.py`): `paged_attention` K and V are
two members, each `[pages, block, Hkv, D]`; plan = dense `block_table[R,P]`, `seq_lens[R]`, `query_start_loc[R+1]`,
`slot_mapping`, `n_reqs` (only the first `n_reqs` rows of the padded views are real); `window` > 0 means query
at position p sees keys `[p-window+1, p]`; `sinks[H]` is one extra per-head logit inside the softmax, dropped
after. `grouped_mm_mxfp4`: `x[T,K]` rows pre-sorted by expert, partitioned by `expert_counts: list[int]` (no
per-row id needed), `weights`/`scales` packed MXFP4 per expert, `bias[E,N]`.

---

## rope

`rope(x[T,H,D], cos[T,D], sin[T,D]) -> [T,H,D]`, rotate-half (HF) convention (`sdk/ops.py:52-66`).

| Library | Symbol | Signature | Layout vs kelpie | Dtypes | Alignment | Build | License | Min version |
|---|---|---|---|---|---|---|---|---|
| flashinfer | `flashinfer.rope.apply_rope_with_cos_sin_cache` | `apply_rope_with_cos_sin_cache(positions, query, key, head_size, cos_sin_cache, is_neox=True)` (`rope.py:1159`; in-place sibling `apply_rope_with_cos_sin_cache_inplace`, `rope.py:1228`) | Math identical to kelpie's rotate-half when `is_neox=True` (`include/flashinfer/pos_enc.cuh:129-146`). Takes separate flat `query`/`key` `(nnz, H*D)` vs kelpie's one `x[T,H,D]`. `cos_sin_cache` is ONE table `(max_seq_len, rotary_dim)` with cos in the first half of the row, sin in the second (`rope.py:1198-1199`), indexed by `positions` — kelpie's cos/sin are per-token `[T,D]` with halves already duplicated; adapting means building `cat([cos[:,:D/2], sin[:,:D/2]], -1)` and `positions=arange(T)`. | q/k fp16/bf16 only (`csrc/rope.cu:149`); `cos_sin_cache` must be fp32 (`rope.py:1224-1225`, `csrc/rope.cu:154`) | none found generically | JIT, nvcc, first-use compile (`rope.py:43-44` `gen_*_module().build_and_load()`); cache at `$FLASHINFER_CACHE_DIR/<version>/<arch>/cached_ops` (`jit/env.py:157,162`), base dir `$FLASHINFER_WORKSPACE_BASE` default `$HOME` (`jit/env.py:59,62`) | Apache-2.0 (`LICENSE:1-3`) | flashinfer-python 0.6.18 (`version.txt`, `pyproject.toml:16,58`) |
| liger-kernel | `liger_kernel.ops.rope.rope_forward` | `rope_forward(q, k, cos, sin)` (`src/liger_kernel/ops/rope.py:117`) | Batched `[B,S,H,D]` (transposed internally from `[B,H,S,D]`) vs kelpie's flat `[T,H,D]`; `cos`/`sin` `[1 or B, S, D]` full head_dim, not `[T,D]`. Same rotate-half math (kernel comment `y = [x1,x2]*[cos,cos] + [-x2,x1]*[sin,sin]`). Standalone functional API, distinct from the `transformers/` monkey-patch layer. | not confirmed in this pass | none found | prebuilt Triton, no separate JIT cache mechanism beyond Triton's own | BSD-2-Clause (`LICENSE`) | 0.8.2 (`pyproject.toml`) |

`silu_mul`/`clamped_swiglu`/`sample`/`grouped_mm_mxfp4` aside, no other surveyed library exposes a plain
`rope(x,cos,sin)` matching kelpie's exact un-batched shape; both above need a reshape/cos-sin-repack adapter,
not new math.

---

## silu_mul / clamped_swiglu

`silu_mul(gate, up) -> silu(gate)*up` (`sdk/ops.py:73-80`). `clamped_swiglu(gate_up[...,2I] interleaved,
limit, alpha) -> [...,I]`: gate clamped above at `limit`, up clamped to `[-limit,limit]`,
`(up+1)*gate*sigmoid(alpha*gate)`, `alpha=1.702` (gpt-oss) (`sdk/ops.py:280-320`).

| Library | Symbol | Signature | Layout vs kelpie | Dtypes | Build | License | Min version |
|---|---|---|---|---|---|---|---|---|
| liger-kernel | `liger_kernel.ops.swiglu.swiglu_forward` | `swiglu_forward(a, b, gate_multiplier=1.0)` -> `(a,b,c)`, `c=silu(a*gate_multiplier)*b` (`src/liger_kernel/ops/swiglu.py:170`) | Matches `silu_mul` exactly at `gate_multiplier=1.0` (mod extra autograd-cache return elements). Also `swiglu_fused_gate_up_forward(y)` (`swiglu.py:~285`) for one `[..., 2I]` tensor, but gate/up **concatenated**, not interleaved like kelpie's `clamped_swiglu` layout. | not confirmed | prebuilt Triton | BSD-2-Clause | 0.8.2 |
| liger-kernel | — | **not found**: grepped `src/liger_kernel/` for `gpt_oss\|gptoss\|clamp`; only hit is `transformers/model/gpt_oss.py`, a cross-entropy loss wrapper, not a kernel. No `limit`/`alpha`/clamp parameter anywhere in `swiglu.py`. | — | — | — | — | — |
| flashinfer | `flashinfer.activation` (module present) | not surveyed in depth (out of the two-agent split's assigned scope) — has silu-and-mul-style fused activations, no gpt-oss clamped variant confirmed | — | — | JIT (see rope row) | Apache-2.0 | 0.6.18 |

**Nothing covers `clamped_swiglu`.** This confirms the `sdk/ops.py:296-298` comment's plan (vendor from
liger-kernel) does not hold against liger's current source — it isn't there. It needs a from-scratch Triton
kernel, adapted from `swiglu_forward`'s structure plus the clamp/alpha math, or a different upstream source
not in this survey's list.

---

## sample

`sample(logits[R,1,V], temperatures[R], key u32[2], logit_mask[R,W] i32) -> tokens[R,1] i32`; Philox-4x32-10
gumbel sampling keyed by `(row,0,token,0)` counter (`sdk/ops.py:83-160`).

| Library | Symbol | Signature | Layout vs kelpie | Dtypes | Build | License | Min version |
|---|---|---|---|---|---|---|---|---|
| flashinfer | `flashinfer.sampling.sampling_from_logits` | `sampling_from_logits(logits, indices=None, deterministic=True, generator=None, check_nan=False, seed=None, offset=None)` (`sampling.py:795`) | Gumbel-max over raw logits (`include/flashinfer/sampling.cuh:733`, gumbel via `-log(-log(u))` at `:679-728`) — same shape of computation as kelpie's `sample`. **RNG is cuRAND `curandStatePhilox4_32_10_t` seeded by `curand_init(seed, subsequence, offset)`** (`sampling.cuh:22,683,788,860`), NOT kelpie's raw `(row,0,token,0)` counter + `u32[2]` key — cuRAND's internal key/counter derivation differs, so bit-exact reproduction of kelpie's stream is impossible through this API. No `temperature` param (lives on a separate `softmax(logits, temperature=)`, `sampling.py:74-75,739`); no `logit_mask` bitmask param anywhere. | not confirmed | JIT (see rope row) | Apache-2.0 | 0.6.18 |
| flashinfer | `flashinfer.sampling.top_k_top_p_sampling_from_logits` | `top_k_top_p_sampling_from_logits(logits, top_k, top_p, indices=None, filter_apply_order="top_k_first", deterministic=True, generator=None, check_nan=False, seed=None, offset=None)` (`sampling.py:1421`) | Same RNG caveat as above. Extends `sample` with a rejection-loop top-k/top-p filter (`filter_apply_order="joint"`, `sampling.py:1426`) kelpie's op doesn't have. | not confirmed | JIT | Apache-2.0 | 0.6.18 |

**Recommendation**: keep kelpie's own Philox gumbel kernel (it's the source of determinism the op contract
promises); borrow flashinfer's top-k/top-p rejection-loop *algorithm* if/when kelpie extends `sample` past
`K=0`, applying `logit_mask` before it. Full flashinfer sampler adoption forfeits caller-keyed determinism.

---

## paged_attention (window, sinks)

`paged_attention(q[T,H,D], k/v[T,Hkv,D], kv_member, query_start_loc[R+1], seq_lens[R], block_table[R,P],
slot_mapping, n_reqs, window, sinks[H])` (`sdk/ops.py:163-256`). K/V two separate `[pages, block, Hkv, D]`
members (contract being fixed to match — current reference body interleaves by accident,
`docs/brief-kernels-build-tiers.md` section E).

| Library | Symbol | Signature | Layout vs kelpie | Dtypes | Alignment | Build/cache | License | Min version |
|---|---|---|---|---|---|---|---|---|
| flashinfer | `flashinfer.prefill.BatchPrefillWithPagedKVCacheWrapper` | `plan(qo_indptr, paged_kv_indptr, paged_kv_indices, paged_kv_last_page_len, num_qo_heads, num_kv_heads, head_dim_qk, page_size, head_dim_vo=None, ..., causal=False, window_left=-1, ..., block_tables=None, seq_lens=..., cum_seq_lens_q=..., cum_seq_lens_kv=...)` (`prefill.py:2214`); `run(..., sinks=None, window_left=None)` (`prefill.py:2786/2808/2830`) | Native form is CSR: `qo_indptr[R+1]` (== kelpie's `query_start_loc` exactly), `paged_kv_indptr[R+1]`, `paged_kv_indices[nnz_pages]`, `paged_kv_last_page_len[R]` (`prefill.py:2256-2266`). **Also accepts kelpie's dense form directly** via optional `block_tables`/`seq_lens`/`cum_seq_lens_q`/`cum_seq_lens_kv` kwargs (`prefill.py:690-733,876-883`) — flashinfer itself converts dense->CSR internally (`_build_block_tables_from_paged_kv_indices`, `prefill.py:1554`), so no adapter-side conversion needed if the dense path is exercised (not verified which attention backends accept it). K/V: separate `(k_cache, v_cache)` each `[num_pages, page_size, Hkv, D]` NHD — **matches kelpie's intended two-member contract exactly**; also accepts fused `[num_pages, 2, page_size, Hkv, D]`. No cache-write step inside attention — `slot_mapping`-style scatter is kelpie's own `flashinfer.page.append_paged_kv_cache(append_key, append_value, batch_indices, positions, paged_kv_cache, kv_indices, kv_indptr, kv_last_page_len, kv_layout="NHD")` (`page.py:580`), addressed by `(batch_index, position)` through the CSR table rather than a flat slot — kelpie's own flat `index_copy_` scatter works fine and needs no flashinfer call. `window_left`: "left (inclusive) window size; -1 = full" (`prefill.py:2298-2300`) = kelpie's `window - 1` (off-by-one to encode). `sinks[num_qo_heads]` fp32, same semantics as kelpie: "additional virtual token whose logit is `sinks[head_idx]`, appended to the softmax denominator" (`prefill.py:2892-2895`). | q/k/v default fp16; fp8 kv supported (`prefill.py:2233-2236`); cute-dsl backend adds bf16/e4m3 (`prefill.py:5401-5403`) | no generic page-size power-of-2 assertion found in `prefill.py`/`decode.py`; backend-specific constraints (e.g. trtllm-gen) not enumerated in this pass | JIT (see rope row) | Apache-2.0 | 0.6.18 |
| flashinfer | `flashinfer.decode.BatchDecodeWithPagedKVCacheWrapper` | `plan(...)` (`decode.py:1355`) | Decode-only sibling of the prefill wrapper; same CSR `indptr/indices/last_page_len`; adds `window_right` (cute-dsl only, `decode.py:1390-1393`) | fp16/bf16 | not enumerated | JIT | Apache-2.0 | 0.6.18 |
| TensorRT-LLM | — (no bare op found) | attention_sinks threads through `attention/attention.py` (fields at lines 88, 827, 937, 1031), explicit guard "Attention sinks are only supported with attn_backend='TRTLLM'" (`attention.py:1082-1084`); `AttentionForwardArgs.attention_window_size`/`.attention_sinks` (`attention/backends/interface.py:917,919`) | Not exposed as a discrete `torch.ops.trtllm.*` symbol — grepped and found only a capability-query stub `torch.ops.trtllm.attention_supports_nvfp4_output` (`trtllm.py:1693`), not the kernel call. Real call is inside compiled C++ not reached from the Python layer surveyed. Deeply coupled to `TrtllmAttentionMetadata`/`KVCacheManager`/CUDA-graph capture state — not usable standalone. | — | — | AOT compiled `.so` via `scripts/build_wheel.py`, no JIT cache | Apache-2.0 (`LICENSE`) | v1.3.0rc26 (`tensorrt_llm/version.py:15`) |
| vLLM (secondary; via flash-attention / flashinfer) | Blackwell: FlashInfer; Hopper: `vllm-flash-attn` (vLLM's own fork of FA3) | not cloned; per vLLM's gpt-oss blog: "vLLM has integrated special GPU kernels from FlashInfer (Blackwell) and FlashAttention 3 (Hopper)" | On Blackwell the true upstream owner is genuinely FlashInfer (natively supports sinks — confirmed by a regression bug about the FlashInfer backend losing sinks support, implying it has the feature). On Hopper, sinks support was added by the vLLM/OpenAI team to their **own vendored FA3 fork** (`github.com/vllm-project/flash-attention`, PR vllm-project/vllm#12093) specifically for the gpt-oss launch (Aug 2025) — this predates and is separate from upstream Dao-AILab/flash-attention's own (still incomplete) sink support (Dao-AILab/flash-attention issues #1797, #1895, #1810 open). Do not treat vLLM's Hopper sink kernel as "from flash-attention upstream" — it is a vLLM patch. | — | — | — | — | — |
| SGLang (secondary) | not distinguished from vLLM in this pass | not cloned | not surveyed separately; assume same FlashInfer/FA3-fork split as vLLM pending a dedicated pass | — | — | — | — | — |

Sources for the vLLM/SGLang row: `https://blog.vllm.ai/2025/08/05/gpt-oss.html`,
`https://github.com/vllm-project/vllm/pull/12093`, `https://github.com/vllm-project/vllm/issues/30919`,
`https://github.com/vllm-project/vllm/issues/22279`, `https://github.com/Dao-AILab/flash-attention/issues/1797`,
`/1895`, `/1810`, `https://docs.vllm.ai/en/v0.11.1/api/vllm/v1/attention/backends/flashinfer/`.

---

## mla_attention

`mla_attention(q, latent, kv_member, query_start_loc, seq_lens, block_table, slot_mapping, n_reqs)` — DeepSeek
MLA over a compressed per-token latent cache (`sdk/ops.py:387-424`).

| Library | Symbol | Signature | Layout vs kelpie | Dtypes | Build | License | Min version |
|---|---|---|---|---|---|---|---|---|
| flashinfer | `flashinfer.mla._batch_mla._wrapper.BatchMLAPagedAttentionWrapper` | `plan(...)` (`_wrapper.py:372`), `run(...)` (`_wrapper.py:693-780`) | `plan()` accepts **both** CSR (`qo_indptr, kv_indptr, kv_indices, kv_len_arr`) and **dense** (`cum_seq_lens_q, block_tables, seq_lens`, `_wrapper.py:389-390`, dispatched via `MLAPlanMetadata.csr/.dense/.dual`) — the dense form is kelpie's `(query_start_loc, block_table, seq_lens)` directly, no conversion needed. Latent cache is **two tensors**, not kelpie's one `latent` member: `ckv_cache[num_pages, page_size, head_dim_ckv]` (compressed latent, no head axis) and `kpe_cache[num_pages, page_size, head_dim_kpe]` (RoPE part) (`csrc/batch_mla_run.cu:39-40`, `csrc/batch_mla_sm90_run.cu:38-39`); `run()` takes `query=(q_nope,q_pe)`, `kv_cache=(ckv,kpe)` or packed last-dim (`_wrapper.py:693-698,822-829`) — kelpie's single `latent` would need splitting (or a packed layout) plus `head_dim_ckv`/`head_dim_kpe` plan ints. No cache-write step, same as `paged_attention` above — kelpie's own scatter stands. | via `q_data_type`/`kv_data_type` | no page-size assertion found in `_wrapper.py`/`_contracts.py` (test suite uses 32) | JIT (see rope row) | Apache-2.0 | 0.6.18 |
| TensorRT-LLM | family of fragment ops: `load_paged_kv_cache_for_mla`, `load_chunked_kv_cache_for_mla`, `mla_rope_append_paged_kv_assign_q`, `merge_chunked_attention_for_mla`, `mla_rope_generation` | called from `TrtllmAttention.forward` (`attention/backends/trtllm.py:1773`, calls at `2148-2383`) | No single standalone op — each does one piece (KV load, RoPE+append, merge, generation) and only composes correctly assembled inside `TrtllmAttention.forward`, coupled to `TrtllmAttentionMetadata`/`KVCacheManager`/CUDA-graph capture (fragility documented by a testing-only `skip_mla_rope_generation` branch at `trtllm.py:~1855`). Exact `m.def` schema strings for these five ops not verified to file:line in this pass. | — | — | AOT `.so` | Apache-2.0 | v1.3.0rc26 |

---

## dsa_indexer_topk

`dsa_indexer_topk(q, indexer_member, query_start_loc, seq_lens, block_table, slot_mapping, n_reqs, topk) ->
[T,topk] i32` — DeepSeek's lightning indexer (`sdk/ops.py:427-460`).

| Library | Symbol | Signature | Layout vs kelpie | Dtypes | Build | License | Min version |
|---|---|---|---|---|---|---|---|---|
| TensorRT-LLM | `trtllm::indexer_topk_decode` | `indexer_topk_decode(Tensor logits, Tensor seq_lens, Tensor indices, int next_n, int index_topk=2048, int compress_ratio=1, Tensor? radix_aux_indices=None, Tensor? radix_aux_logits=None) -> ()` (in-place void; `TORCH_LIBRARY_FRAGMENT` registration `cpp/tensorrt_llm/thop/IndexerTopKOp.cpp:187-208`, C++ impl `:38-77`) | **Topk-selection only** — takes a precomputed `logits`/score matrix, does NOT compute `q · indexer_member` itself. `seq_lens.size(0) * next_n == logits.size(0)`. The actual score computation is a separate call into **DeepGEMM** (`fp8_mqa_logits`/`fp8_paged_mqa_logits`, imported at `tensorrt_llm/_torch/attention/backends/sparse/dsa/indexer.py:29-34`) — so kelpie's single op would need to be assembled from two libraries, not one. | logits fp32/bf16/fp16 (checked `IndexerTopKOp.cpp:71-74`) | none found in this pass | AOT `.so` | Apache-2.0 | v1.3.0rc26 |
| TensorRT-LLM | `trtllm::indexer_topk_prefill` | `indexer_topk_prefill(Tensor logits, Tensor row_starts, Tensor row_ends, Tensor indices, int index_topk) -> ()` (`IndexerTopKOp.cpp:145-179`, calls `tk::invokeIndexerTopKPrefill`) | `row_starts`/`row_ends` is CSR-style per-row variable-length ranges into a flat logits buffer, differs from kelpie's dense `block_table[R,P]`. `logits` hardcoded fp32 in this path (`logits.data_ptr<float>()`). | fp32 only | none found | AOT `.so` | Apache-2.0 | v1.3.0rc26 |
| DeepGEMM (via TRT-LLM's own dependency, and named directly by vLLM/SGLang) | `fp8_mqa_logits` / `fp8_paged_mqa_logits` / `get_paged_mqa_logits_metadata` | not directly inspected in this DeepGEMM checkout pass (found only via the TensorRT-LLM survey's import trace) | This is the true origin of the indexer *scoring* step for both TRT-LLM and, per vLLM/SGLang's own release blogs, for them too: "vLLM integrates with the lightning indexer CUDA kernels in DeepGEMM ... including paged versions" (vllm.ai/blog/2025-09-29-deepseek-v3-2); SGLang: "Indexer logit kernels (including paged versions) are available in DeepGEMM" (lmsys.org/blog/2025-09-29-deepseek-V32). | — | K alignment 128 (fp8/fp4 path) or 256 (bf16 path) on DeepGEMM's grouped-gemm entrypoints generally (`csrc/apis/gemm.hpp:326,433`) — not confirmed specifically for the MQA-logits kernels | JIT, `DG_JIT_CACHE_DIR` env var confirmed present (`grep -rhoE 'DG_[A-Z_]+'` across `csrc/`, `deep_gemm/`, `README.md`); default path not resolved in this checkout (JIT python module `deep_gemm/jit/` was not present in the tree slice searched) | MIT (`LICENSE`: "Copyright (c) 2025 DeepSeek") | untagged — `setup.py` derives `__version__` from git, no fixed minimum found |
| vLLM/SGLang sparse-attention-over-selected-KV (secondary, adjacent to `compressed_kv_attention` below) | — | not cloned | Both vLLM's and SGLang's blogs credit **FlashMLA** (`deepseek-ai/FlashMLA`) for the sparse-attention compute step that consumes the indexer's top-k output — this is `compressed_kv_attention`'s upstream, not `dsa_indexer_topk`'s, but the two are pipeline neighbors and FlashMLA was not in the original source list, worth adding to a follow-up survey. | — | — | — | — | — |
| — | topk selection itself | — | No external upstream owner confirmed for the **selection** step alone in either vLLM or SGLang — SGLang's own writeup calls out optimizing "small-kernel overhead in `_get_topk_paged`" as engine-local work, implying it is NOT vendored from DeepGEMM/FlashMLA/flashinfer. | — | — | — | — | — |

Sources: `https://vllm.ai/blog/2025-09-29-deepseek-v3-2`, `https://www.lmsys.org/blog/2025-09-29-deepseek-V32`,
`https://github.com/sgl-project/sglang/issues/15025`, `https://github.com/deepseek-ai/DeepGEMM`,
`https://github.com/flashinfer-ai/flashinfer/issues/3111` (flashinfer's own from-scratch "HiSparse" DSA kernel
for Blackwell, in progress, not yet what vLLM/SGLang ship).

---

## compressed_kv_attention

`compressed_kv_attention(q,k,v,kv_member,indices,query_start_loc,seq_lens,block_table,slot_mapping,n_reqs,
ratio)` — DeepSeek-V4-Flash CSA/HCA over stride-`ratio` compressed KV gathered at `indices`
(`sdk/ops.py:463-495`).

| Library | Symbol | Layout vs kelpie | Build | License |
|---|---|---|---|---|
| TensorRT-LLM | `attention/backends/sparse/{dsa,deepseek_v4,qsa,minimax_m3,rocket}/` — e.g. `deepseek_v4/flash_mla.py`, `deepseek_v4/indexer.py`, `deepseek_v4/flashinfer.py`, `deepseek_v4/cache_manager.py` | Directory structure confirms these exist as separate backend implementations, but exact op signature within `deepseek_v4/flash_mla.py` was not read to file:line in the time budget of this pass — same caution as `mla_attention`: everything under `attention/backends/sparse/` is written against the shared `AttentionMetadata`/backend interface (`attention/backends/interface.py`), not exposed as bare torch ops with a documented plain-tensor contract. Flag for a follow-up pass specifically on this directory. | AOT `.so` | Apache-2.0 |
| FlashMLA (`deepseek-ai/FlashMLA`) | not in original source list, discovered via vLLM/SGLang blogs as the true upstream for this op's compute | Both vLLM and SGLang credit FlashMLA by name for "sparse attention kernels" over the indexer's selected KV. Not cloned or read directly in this survey — **add to a follow-up survey pass**, it is very likely the single best source for this op. | — | — |

---

## chunk_gated_delta_rule

`chunk_gated_delta_rule(q, k, v, gate, state)` mutates `state` in place — KDA/GDN recurrence (Kimi-Linear,
qwen3_next GDN) (`sdk/ops.py:329-352`).

| Library | Symbol | Signature | Layout vs kelpie | Dtypes | Build | License | Min version |
|---|---|---|---|---|---|---|---|---|
| fla | `fla.ops.gated_delta_rule.chunk.chunk_gated_delta_rule` | `chunk_gated_delta_rule(q, k, v, g, beta, scale=None, initial_state=None, output_final_state=False, use_qk_l2norm_in_kernel=False, use_beta_sigmoid_in_kernel=False, allow_neg_eigval=False, state_v_first=False, cu_seqlens=None, cu_seqlens_cpu=None, chunk_indices=None, cp_context=None, **kwargs)` (`chunk.py:397`) | `q,k` `[B,T,H,K]`, `v` `[B,T,HV,V]`, `g` `[B,T,HV]` log-space decay — kelpie's single `gate` doesn't carry the **separate required `beta[B,T,HV]`** tensor this op needs (`chunk.py:415-459`). **State is returned, not mutated**: `return o, final_state` (`chunk.py:335`) — kelpie's `mutates_args=("state",)` wrapper needs a `state.copy_(final_state)` after the call. `cu_seqlens[N+1]` FlashAttention-style, requires `B=1` (`chunk.py:461-462,551-555`) — equals kelpie's `query_start_loc`. Chunk size kwarg `{16,32,64}`, default 64 (`chunk.py:537-539`). | not confirmed in this pass | Triton JIT (no separate cache dir found; relies on Triton's own cache) | MIT (`LICENSE`) | fla 0.6.0 (`fla/__init__.py`) |
| fla | `fla.ops.kda.chunk.chunk_kda` | superset signature adding `safe_gate, lower_bound, disable_recompute, return_intermediate_states, use_graph, max_num_seqs` (`kda/chunk.py:197-217`) | Same state-return and `beta`-tensor caveats as above; this is the KDA-specific variant (Kimi-Linear's 20 layers) — kelpie's "one op covers KDA and GDN" plan means dispatching between `chunk_gated_delta_rule` and `chunk_kda`, not one shared symbol. | not confirmed | Triton JIT | MIT | 0.6.0 |
| fla | `fla.ops.gated_delta_rule.fused_recurrent.fused_recurrent_gated_delta_rule` / `fla.ops.kda.fused_recurrent.fused_recurrent_kda` | `fused_recurrent_gated_delta_rule(q,k,v,g=None,gk=None,gv=None,beta=None,...)` (`fused_recurrent.py:309-327`) | Decode-step (single-token) variant, relevant for kelpie's per-step recurrence path rather than the chunked prefill path. Same `beta`/state-return caveats. | not confirmed | Triton JIT | MIT | 0.6.0 |

---

## causal_conv1d

`causal_conv1d(x, weight, state)` mutates `state` in place — short causal conv ahead of KDA/GDN layers
(`sdk/ops.py:355-373`).

| Library | Symbol | Signature | Layout vs kelpie | Dtypes | Build | License | Min version |
|---|---|---|---|---|---|---|---|---|
| fla | `fla.modules.conv.causal_conv1d.causal_conv1d_update` | `causal_conv1d_update(x, cache, residual, weight, bias, activation)` (`triton/ops.py:301-345`, kernel `causal_conv1d_update_kernel` at `triton/kernels.py:356-420`) | **Matches kelpie's in-place-state contract directly**: shifts the `[N,D,W]` ring and stores back into `cache` (used by `ShortConvolution.step()`, comment "updates the cache in-place" at `short_conv.py:220`). This is the decode/step path kelpie's op signature implies. | not confirmed | own Triton kernel, no width limit assertion (`BW=next_power_of_2(W)`) found in fla's own kernel — the `<=4` width limit only applies via the optional external `causal-conv1d` CUDA package | MIT | fla 0.6.0 |
| fla | `fla.modules.conv.causal_conv1d.causal_conv1d` | `causal_conv1d(x, weight=None, bias=None, residual=None, initial_state=None, output_final_state=False, activation=None, backend='triton', cu_seqlens=None, ...)` (`causal_conv1d.py:18-34`) | Batch/chunk (prefill) path: `x[B,T,D]`, `weight[D,W]`, state `[N,D,W]`; **returns new `final_state` rather than mutating** (`triton/ops.py:369`) — needs a copy-back wrapper for the prefill path, unlike the decode-step sibling above. | not confirmed | own Triton kernel | MIT | 0.6.0 |
| external `causal-conv1d` pip package | (not vendored, optional) | fla's `conv1d` extra (`pyproject.toml`) | Only imported via try/except (`fla/modules/conv/cuda/ops.py:22-24`); not inspected directly in this survey. Would be the source of the `<=4` width limit if kelpie needs to match vLLM-style constraints. | not confirmed | prebuilt CUDA extension | check separately | `>=1.4.0` (fla's own pin, `pyproject.toml`) |

---

## grouped_mm_mxfp4

`grouped_mm_mxfp4(x[T,K] sorted by expert, weights, scales, bias, expert_counts: list[int]) -> [T,N]` — MXFP4
grouped MoE matmul (gpt-oss, DeepSeek-V4-Flash MoE) (`sdk/ops.py:498-536`).

| Library | Symbol | Signature | Layout vs kelpie | Dtypes | Alignment | Build/cache | License | Min version |
|---|---|---|---|---|---|---|---|---|
| flashinfer | `flashinfer.grouped_mm.core.grouped_mm_fp4` | `grouped_mm_fp4(a, b, a_descale, b_descale, m_indptr, alpha=None, out=None, out_dtype=torch.bfloat16, block_size=16, *, backend="cudnn", tactic=-1) -> Tensor` (`grouped_mm/core.py:508`) | Partition is `m_indptr[E+1] int32` cumulative offsets = `[0]+cumsum(expert_counts)` (`core.py:527,551`) — **directly derivable from kelpie's `expert_counts` list**, rows pre-sorted by expert as kelpie assumes. `block_size=32` selects MXFP4 (`core.py:495-501`); `b_descale` must then be `uint8` e8m0. Shapes: `a(cum_m,k)`, `b(E,n,k)` as `float4_e2m1fn_x2`/packed `uint8` (`core.py:442-445,471,558-560`); `a_descale(cum_m,k/32)`, `b_descale(E,n,k/32)`. **Activation `x` must ALSO be fp4-quantized with per-32 scales** — kelpie's bf16 `x[T,K]` needs a quantize step first, unlike TRT-LLM's fused path below. **No `bias` param** — kelpie's `bias[E,N]` applies after the call. | `out_dtype` fp16/bf16/fp32 (`core.py:446-449`) | block_size 16 or 32 (mxfp4) | Only backend is cuDNN (`core.py:646-660`); arch gating inside cuDNN, min cuDNN version gated by `_CUDNN_MOE_MIN_VERSION` (not resolved to a number in this pass) | Apache-2.0 | flashinfer-python 0.6.18 |
| DeepGEMM | `m_grouped_fp8_fp4_gemm_nt_contiguous` | `m_grouped_fp8_fp4_gemm_nt_contiguous(a: (Tensor,Tensor), b: (Tensor,Tensor), d, grouped_layout, recipe=None, recipe_a=None, recipe_b=None, compiled_dims="nk", disable_ue8m0_cast=False, use_psum_layout=False, ensure_zero_padding=False, expected_m_for_psum_layout=None)` (`csrc/apis/gemm.hpp:176-187`, Python bindings `:830-835`) | `a` is `[M,K]` stacked rows like kelpie, but grouping is via `grouped_layout`, a **per-row group-id tensor** — not `expert_counts: list[int]`; kelpie's counts would need expanding into a per-row id tensor first. `a`/`b` are `(value, scale)` **pairs**, not kelpie's separate `weights`+`scales`. | output always bf16 (`DG_HOST_ASSERT(d.scalar_type()==torch::kBFloat16)`) | K alignment `%128==0` fp8/fp4 path, `%256==0` bf16 path (`gemm.hpp:326,433`) | JIT via nvcc, `DG_JIT_CACHE_DIR` env var (name confirmed, default path not resolved — `deep_gemm/jit/` module not present in the tree slice read) | MIT | untagged (git-derived version) |
| DeepGEMM | `m_grouped_fp8_fp4_gemm_nt_masked` | `m_grouped_fp8_fp4_gemm_nt_masked(a, b, d, masked_m, expected_m, recipe=None, recipe_a=None, recipe_b=None, compiled_dims="nk", disable_ue8m0_cast=False)` (`csrc/apis/gemm.hpp:260-269`) | `a` is `[G,M,K]` (fixed per-group capacity, padded) and `masked_m[G]` int32 — **closer in spirit to kelpie's `expert_counts`** (a per-expert count array) than the contiguous variant, but the tensor layout is padded/masked `[G,M,K]` rather than kelpie's ragged sorted `[T,K]`; converting means padding each expert's segment to a common `M`. Dispatch is by scale dtype: `torch::kFloat` scale on SM90 -> `sm90_m_grouped_fp8_gemm_masked_1d2d`; `torch::kInt` scale on SM100 -> `sm100_m_grouped_fp8_fp4_gemm_masked_1d1d` — this single symbol covers both FP8xFP8 and FP8xFP4/MXFP4 depending on operand/scale dtype. | output bf16 | same K alignment as above | JIT, `DG_JIT_CACHE_DIR` | MIT | untagged |
| TensorRT-LLM | `trtllm::mxe4m3_mxe2m1_block_scale_moe_runner` | `@torch.library.custom_op`, registered `tensorrt_llm/_torch/custom_ops/trtllm_gen_custom_ops.py:1427-1429` (body `1429-1462+`): `(routing_logits, routing_bias, hidden_states, hidden_states_scale, gemm1_weights, gemm1_weights_scale, gemm1_bias, gemm1_alpha, gemm1_beta, gemm1_clamp_limit, gemm2_weights, gemm2_weights_scale, gemm2_bias, num_experts, top_k, n_group, topk_group, intermediate_size, valid_hidden_size, valid_intermediate_size, local_expert_offset, local_num_experts, routed_scaling_factor, routing_method_type, act_type, topk_weights=None, topk_ids=None, output=None, tune_max_num_tokens=8192, use_dp=False) -> Tensor` | **Fused router + gemm1 + activation + gemm2** — takes `routing_logits` and does top-k routing internally. Does NOT match kelpie's contract, which expects pre-sorted-by-expert input and a plain count list; this op won't take a pre-grouped input directly without bypassing its internal router (e.g. feeding synthetic one-hot `routing_logits` per expert segment). Auto-tuned via an `AutoTuner`/`get_valid_tactics` machinery layer above it. Plausibly usable standalone (clean `custom_op`, tensor-only signature, fake registered) unlike TRT-LLM's attention ops — the routing-bypass adaptation is the only blocker. | — | — | AOT `.so` | Apache-2.0 | v1.3.0rc26 |
| tilelang | `examples/blockscaled_gemm_sm100/grouped_gemm_mxfp8_blockscaled_1d1d.py` | written example, not read to signature-level in this pass | Same family (MXFP8 grouped-gemm, block-scaled) as kelpie's MXFP4 need, but **FP8 scale block, not FP4** — a template to adapt from, not a direct match. Also `examples/grouped_gemm/` (fwd/fwd_ptr/bwd, 3 files) and `examples/fusedmoe/` as adjacent written examples. | — | — | JIT; cache at `$TILELANG_CACHE_DIR` (default `~/.tilelang/cache`, `tilelang/env.py:368`), also `TILELANG_DISABLE_CACHE` (`env.py:372-374`); logic in `tilelang/cache/kernel_cache.py` (namespaced staging-dir + integrity check, lines 196-841) | not confirmed in this pass | not confirmed |

---

## rms_norm / layer_norm / gelu / silu (ATEN_OPS — low priority)

Kelpie's default path calls torch/aten directly (`sdk/ops.py:1-9`); these libraries are only relevant if a
device wants a faster fused replacement registered on `aten::*`.

| Library | Symbol | Notes |
|---|---|---|
| liger-kernel | `liger_kernel.ops.rms_norm.rms_norm_forward`/`rms_norm_backward` (`ops/rms_norm.py`), `ops/layer_norm.py`, `ops/geglu.py` (GELU-mul, not plain gelu) | Plain functional API under `ops/*.py`, separate from the `transformers/` monkey-patch layer — this is the form kelpie wants. Hardware-backend variants exist under `ops/backends/_triton/`, `_cutedsl/`, `_ascend/`, selected via `LIGER_KERNEL_IMPL` env var (`ops/__init__.py:143-186`). |
| fla | `fla/modules/layernorm.py:1097 RMSNorm`; gated fused variant `rmsnorm_fn(x, weight, bias, z=None, eps, group_size, norm_before_gate)` (`layernorm_gated.py:462-469`) | The gated variant is only interesting if kelpie later wants a fused gate for KDA/GDN output normalization. |
| flashinfer | `flashinfer/norm/` (directory present) | Not examined in this pass. |

---

## Ranked default per op on CUDA

1. **rope** — flashinfer's `apply_rope_with_cos_sin_cache`. Math is bit-identical (rotate-half, confirmed at
   the CUDA-source level); the only work is a shape adapter (flatten `[T,H,D]`->the wrapper's `(nnz,H,D)`
   reshape it already does internally, and repack `cos[T,D]`/`sin[T,D]` into the half-width `cos_sin_cache`
   table). Liger's `rope_forward` is a fallback if flashinfer's JIT/build story proves too heavy for a given
   deploy target — same math, batched-shape adapter instead.
2. **paged_attention** — flashinfer's `BatchPrefillWithPagedKVCacheWrapper`. It is the only surveyed library
   whose native K/V layout (`[pages,block,Hkv,D]`, two separate members, NHD) **matches kelpie's contract
   exactly with no repacking**, and it accepts kelpie's dense `block_table`/`seq_lens`/`query_start_loc` form
   directly as an alternative to CSR. `window_left`/`sinks` map onto kelpie's `window`/`sinks` with only an
   off-by-one on window. TensorRT-LLM's sinks/window support exists but isn't exposed as a bare op — ruled out
   for a first cut.
3. **mla_attention** — flashinfer's `BatchMLAPagedAttentionWrapper`. Same reasoning as `paged_attention`: dense
   plan form accepted natively, only real adaptation is splitting kelpie's one `latent` member into flashinfer's
   two (`ckv`/`kpe`). TensorRT-LLM's MLA is real but fragmented across five ops coupled to its executor class —
   far more integration cost for the same result.
4. **grouped_mm_mxfp4** — DeepGEMM's `m_grouped_fp8_fp4_gemm_nt_masked`, because `masked_m[G]` is structurally
   the same idea as kelpie's `expert_counts` (a per-expert count), just padded instead of ragged — a lighter
   adapter than flashinfer's `grouped_mm_fp4` (which needs the *activation* fp4-quantized too, not just
   weights) or TRT-LLM's fused router path (needs a routing bypass). Accept the padding-copy cost; it is one
   memory op, not new math.
5. **chunk_gated_delta_rule / causal_conv1d** — fla is the only real source for either (DeepGEMM/flashinfer/
   liger don't touch linear attention). Use `chunk_kda` for Kimi-Linear's KDA layers and
   `chunk_gated_delta_rule` for qwen3_next's GDN, dispatched by model, not merged into one call — they already
   are two symbols upstream, matching the `ops.py` comment that "KDA generalizes GDN." Add the missing `beta`
   argument to kelpie's `chunk_gated_delta_rule` op signature (currently `q,k,v,gate,state` — no room for
   `beta`) since fla requires it. For `causal_conv1d`, use `causal_conv1d_update` for the decode/step path
   (already mutates its cache in place, matching kelpie's contract precisely) and the batch `causal_conv1d`
   entrypoint plus a copy-back wrapper for prefill.
6. **dsa_indexer_topk** — no single library covers this end-to-end. Recommendation: DeepGEMM's
   `fp8_paged_mqa_logits` (the scoring step, per vLLM/SGLang's own credit) feeding TensorRT-LLM's
   `indexer_topk_decode`/`indexer_topk_prefill` (the selection step) — or, once available, flashinfer's
   in-progress "HiSparse" kernel (`flashinfer-ai/flashinfer#3111`) as a from-scratch single-library
   alternative, not yet shipped. FlashMLA itself does not do the selection step (confirmed in the follow-up
   pass below: it only ever consumes an already-computed `indices` tensor, in both
   `flash_mla_sparse_fwd`/`flash_mla_with_kvcache` and the fused `fused_norm_rope_attn_rope_cast.prefill`), so
   it does not change this recommendation.
7. **compressed_kv_attention** — **deepseek-ai/FlashMLA**'s `flash_mla_sparse_fwd` (prefill) and
   `flash_mla_with_kvcache(..., indices=...)` (decode, the `sparse_decode_fwd` path), now surveyed directly
   (see "FlashMLA (follow-up)" below). This is DeepSeek's own reference implementation for exactly this op —
   the gather-by-`indices` contract matches kelpie's `indices`-into-`kv_member` shape closely (`indices[s_q,
   topk]` int32, `-1`/out-of-range = invalid, same convention kelpie would need). Preferred over TensorRT-LLM's
   fragmented `deepseek_v4/flash_mla.py` backend (still not read to file:line, and coupled to
   `AttentionMetadata`) for the same reason flashinfer won `mla_attention`: FlashMLA is a bare op, not a
   framework-coupled backend. Caveat: FlashMLA has no page-table-indirection decode path for sparse
   attention — `indices` already bakes in the page/offset, so kelpie's `block_table` is unused on that path,
   and the FP8-with-scale KV byte layouts (656/584/528/288 bytes per token) are FlashMLA-specific, not
   kelpie's own cache format, so the adapter must repack kelpie's `kv_member` into one of these layouts (or
   accept dense bf16 for a first cut and defer FP8 packing).
8. **sample** — keep kelpie's own Philox-keyed reference body; no surveyed library's RNG can reproduce its
   counter-based determinism (flashinfer uses cuRAND with a different key/counter scheme). If extending past
   `K=0`, adapt flashinfer's `top_k_top_p_sampling_from_logits` rejection-loop *algorithm* only, re-implemented
   on top of kelpie's own Philox draws rather than calling flashinfer's op directly.
9. **clamped_swiglu** — nothing covers it. Liger-Kernel has no gpt-oss clamp variant (confirmed absent by
   grep across the whole `src/liger_kernel/` tree); flashinfer's fused activations weren't confirmed to have
   it either. This contradicts the plan implied by `sdk/ops.py:296-298`'s comment. Needs either a fresh Triton
   kernel (adapt liger's `swiglu_forward` structure, add the clamp + `alpha` sigmoid term) or a different
   upstream source outside this survey's list.

## Ops nothing covers

- **`clamped_swiglu`** — confirmed absent from liger-kernel (grepped whole source tree) and not found in
  flashinfer's activation module in this pass. Needs a from-scratch kernel.
- **`compressed_kv_attention`** — no library in the original source list was found to implement this directly;
  FlashMLA (discovered via vLLM/SGLang, not in the original list) is the strongest lead but wasn't cloned or
  read in this survey.
- **`dsa_indexer_topk`** as one op — the scoring half (DeepGEMM) and selection half (TensorRT-LLM) are separate
  libraries with no single symbol spanning both; assembling them is a kelpie-side integration task, not a
  drop-in.
- **`sample`'s** exact Philox-counter determinism — no library reproduces it; this is expected to stay
  kelpie-owned indefinitely, not a gap to close.

## Follow-ups this survey did not close

- **DeepGEMM's `fp8_mqa_logits`/`fp8_paged_mqa_logits`** were named via TensorRT-LLM's import trace, not read
  directly in the DeepGEMM checkout — get exact signature/file:line from `deep_gemm/` itself.
- **`flashinfer/dsv3_ops/`, `flashinfer/topk_varlen/`, `flashinfer/topk.py`, `flashinfer/sparse.py`,
  `csrc/blackwell_msa`** exist in the flashinfer checkout and were not surveyed — likely relevant to
  `dsa_indexer_topk`/`compressed_kv_attention`, flagged but not opened in this pass.
- **flashinfer's `grouped_mm_fp4`'s `_CUDNN_MOE_MIN_VERSION`** and **DeepGEMM's `DG_JIT_CACHE_DIR` default
  path** were not resolved to concrete values — both need one more targeted read.
- **SGLang** was not distinguished from vLLM for the sinks-attention row; both were treated as sharing the
  same FlashInfer/FA3-fork split based on vLLM's blog only. SGLang's own gpt-oss integration should get a
  dedicated look.
- **cutlass, flash-attention (Dao-AILab), quack, tokenspeed** were checked out but not surveyed in this pass —
  out of scope for this survey's op list, but present locally under `/tmp/kernel-survey/` if a later pass
  wants them (e.g. Dao-AILab/flash-attention's own upstream sinks support, tracked as incomplete in issues
  #1797/#1895/#1810, is worth checking once it lands, as a non-vLLM-forked alternative for Hopper sinks).

---

## FlashMLA (follow-up)

Cloned `deepseek-ai/FlashMLA` full (not sparse — `git clone --filter=blob:none`; the repo has no large
binary blobs to skip, `csrc/cutlass` is a git submodule not fetched) into `/tmp/kernel-survey/flashmla`,
commit `07a1089` ("Add kernels for DeepSeek v4.1", branch `main`). Entry points all live in `flash_mla/`
(`flash_mla/__init__.py:3-9` re-exports them; `flash_mla/flash_mla_interface.py` is the only interface file,
444 lines; `flash_mla/fused_norm_rope_attn_rope_cast.py` adds one more, 203 lines).

**Public entry points** (all `flash_mla/flash_mla_interface.py` unless noted):

- `get_mla_metadata(*args, **kwargs) -> Tuple[FlashMLASchedMeta, None]` (`:37-50`) — despite the README's
  example passing `cache_seqlens, s_q*h_q//h_kv, h_kv, h_q, is_fp8, topk` (`README.md:103-110`), the actual
  function body ignores every argument and just returns an empty `FlashMLASchedMeta()` — a real
  README/code drift; scheduler metadata is now built lazily inside `flash_mla_with_kvcache`'s first call
  instead (`:124-144`).
- `flash_mla_with_kvcache(q, k_cache, block_table, cache_seqlens, head_dim_v, tile_scheduler_metadata,
  num_splits=None, softmax_scale=None, causal=False, is_fp8_kvcache=False, indices=None, attn_sink=None,
  extra_k_cache=None, extra_indices_in_kvcache=None, topk_length=None, extra_topk_length=None) ->
  Tuple[torch.Tensor, torch.Tensor]` (`:53-70`) — the decode entry point, dense **or** sparse depending on
  whether `indices` is given (`:160-179`); dispatches to `flash_mla_cuda.sparse_decode_fwd` or
  `flash_mla_cuda.dense_decode_fwd`.
- `flash_mla_sparse_fwd(q, kv, indices, sm_scale, d_v=512, attn_sink=None, topk_length=None) ->
  Tuple[torch.Tensor, torch.Tensor, torch.Tensor]` (`:185-220`) — sparse prefill, calls
  `flash_mla_cuda.sparse_prefill_fwd`.
- `flash_attn_varlen_func` / `flash_attn_varlen_qkvpacked_func` / `flash_attn_varlen_kvpacked_func`
  (`:381-444`) — dense MHA prefill/backward (SM100 FMHA, autograd-wrapped via `FlashAttnVarlenFunc`
  at `:337-378`), unrelated to MLA/compressed KV; not a candidate for any kelpie sparse op.
- `fused_norm_rope_attn_rope_cast.prefill(enable_q_norm, rms_norm_eps, token_positions, is_rope_neox_style,
  rope_dim, cos_sin_cache, n_wv_group, num_per_channels, use_tma_aligned_col_major_sf, round_sf,
  use_packed_ue8m0, q, kv, indices, sm_scale, d_v=512, attn_sink=None, topk_length=None) ->
  Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]` (`flash_mla/fused_norm_rope_attn_rope_cast.py:8-30`) —
  fuses Q-RMSNorm + Q-RoPE + sparse attention + O-RoPE + FP8 cast for DeepSeek V4/V4.1 only, SM100/103 only.

**KV cache layout.** Decode: `k_cache` is `(num_blocks, page_block_size, num_heads_k, head_dim)`
(`:74-75`), same 4D paged shape as kelpie's `kv_member`, and `block_table[batch_size,
max_num_blocks_per_seq]`/`cache_seqlens[batch_size]` int32 (`:76-78`) match kelpie's `block_table[R,P]`/
`seq_lens[R]` directly for the **dense** decode path. For **sparse** decode/prefill, `block_table` is not
used at all — the page/offset is pre-baked into `indices` (`indices_in_kvcache[i][j][k] = page_index *
page_block_size + offset_in_block`, `:85-87`, confirmed again at `README.md:69`), so kelpie's separate
`block_table` + `indices` would collapse into one FlashMLA `indices` tensor at adapter time. `indices` shape
is `(batch_size, seq_len_q, topk)` int32, invalid entries are `-1` (`:85`, `README.md:71`); prefill's
`flash_mla_sparse_fwd` takes `indices[s_q, h_kv, topk]` instead (per-head, not per-batch — one more axis
than the decode path, `:198-200`). `topk_length[batch_size]` int32 lets fewer than `topk` indices be real
per row (`:90`), directly matching kelpie's implicit need to handle a per-row topk shorter than the padded
`topk` dimension.

**FP8/FP4 variants** — four on-disk formats, chosen by the byte-width of `k_cache`'s last dim, not by a
flag: V3/V3.1/V3.2 (656 B/token: 512 B fp8_e4m3 NoPE + 16 B fp32 scale + 128 B bf16 RoPE, unquantized RoPE),
V4 (584 B/token: 448 B fp8_e4m3 NoPE + 128 B bf16 RoPE + separate 8 B fp8_e8m0 scale row), V4.1 (528 B/token:
512 B fp8_e4m3, RoPE quantized too, 16 B fp8_e8m0 scale row), V4.1-fp4 (288 B/token, e2m1 2-per-byte, only
legal as `extra_k_cache` — a second, disjoint KV member for a mixed-precision "sliding window in fp8 /
compressed attention in fp4" split) (`:92-107`, `README.md:44-49`). `is_fp8_kvcache=True` requires
`indices` (sparse) — FlashMLA's dense decode path only reads bf16/fp16 (`README.md:38`, `:163`). None of
these four layouts match kelpie's own `kv_member` cache format — an adapter must pack/repack into one of
them (or accept dense bf16 for a first cut, deferring FP8).

**SM requirements.** Dense decode: SM90 (MQA). Sparse decode: SM90 **and** SM100. Dense prefill: SM100 only.
Sparse prefill: SM90 and SM100. Fused norm/rope/attn/rope/cast: SM100 only (`README.md:59-64`). Toolchain
gate in `setup.py:28-40`: `CUDA_HOME` (from PyTorch, not the env var) must exist; NVCC >= 12.9 required for
SM100 compilation (`FLASH_MLA_DISABLE_SM100=1` env var to skip it on older toolchains,
`FLASH_MLA_DISABLE_SM90=1` for the converse); arch flags target `sm_90a`/`sm_100a`/`sm_103a` specifically
(the `a`-suffixed, not family-generic, targets — `setup.py:41-48`).

**Build/install.** AOT only, no JIT and no published wheel: `pip install -v .` after `git submodule update
--init --recursive` (`README.md:78-82`) runs `setup.py`'s `CUDAExtension("flash_mla.cuda", sources=[...])`
through `torch.utils.cpp_extension.BuildExtension` (`setup.py:8-13,65-183`). No JIT cache directory or env
var exists in this repo (grepped `setup.py`/`README.md`/`flash_mla/` for `CACHE`/`jit` — no hits), unlike
DeepGEMM's `DG_JIT_CACHE_DIR`; a compile happens once at install time and produces a normal `.so` extension
module (`flash_mla.cuda`, imported at `flash_mla_interface.py:6`). `FLASH_MLA_DISABLE_FP16` env var also
exists (`setup.py:17-19`) to drop fp16 kernel variants from the build.

**License.** MIT, `Copyright (c) 2025 DeepSeek` (`LICENSE:1-3`).

**Tests / reference implementation.** `tests/ref.py` has a genuine, from-scratch torch reference:
`ref_sparse_attn_fwd` (`tests/ref.py:19-53`, prefill) and `ref_sparse_attn_decode` (`:58-109`, decode) both
gather KV at `indices` with `index_select`, mask invalid entries to `-inf` before softmax, and support the
same `attn_sink`/`topk_length` knobs as the CUDA kernels — this is DeepSeek's own numerical ground truth,
usable directly as kelpie's reference body for `compressed_kv_attention` (and structurally close to what
`dsa_indexer_topk`'s consumer needs, since it's the same gather-by-indices shape). Test drivers
(`tests/test_flash_mla_sparse_decoding.py`, `test_flash_mla_sparse_prefill.py`,
`test_flash_mla_dense_decoding.py`, `test_fmha_sm100.py`, `test_fused_norm_rope_attn_rope_cast.py`) compare
the CUDA kernel output against `tests/ref.py` via a local `kernelkit`/`compare.py` harness (imported as `kk`
at `test_flash_mla_sparse_decoding.py:9`) — not vendored elsewhere in this survey's checkouts, self-contained
to this repo.

**Which kelpie ops FlashMLA can back.**

- **`compressed_kv_attention`** — best fit. `flash_mla_sparse_fwd` for prefill, `flash_mla_with_kvcache(...,
  indices=...)` for decode. Adapter converts kelpie's `(kv_member, indices, block_table)` into FlashMLA's
  single pre-baked `indices_in_kvcache` (fold `block_table` lookup into the index encoding at adapter time,
  `page_index * page_block_size + offset`), and kelpie's `ratio`-strided compression scheme has no direct
  FlashMLA counterpart — FlashMLA has no notion of a compression stride, only arbitrary gathered indices, so
  kelpie's stride-`ratio` selection must be computed kelpie-side (or folded into the `dsa_indexer_topk`
  step) before calling in.
- **`mla_attention`** (dense, non-sparse per-token latent) — FlashMLA's **dense** decode
  (`flash_mla_with_kvcache` with `indices=None`) and dense prefill (`flash_attn_varlen_func`, SM100-only)
  paths are candidates, but flashinfer's `BatchMLAPagedAttentionWrapper` remains the better default (see
  ranked list item 3): flashinfer accepts kelpie's dense `block_table`/`seq_lens` plan natively on both SM90
  and SM100, while FlashMLA's dense prefill is SM100-only and its `latent` cache still needs splitting into
  `ckv`/`kpe`-equivalent parts either way. Keep FlashMLA as the SM90 dense-decode fallback if flashinfer's
  SM90 dense path is ever found lacking.
- **`dsa_indexer_topk`'s selection step** — **not covered**. Every FlashMLA entry point that takes `indices`
  treats it as a pre-computed input, never computes it (`flash_mla_sparse_fwd`'s docstring: "indices: ...
  KV indices when sparse attention is enabled", `:200`; same for `flash_mla_with_kvcache`, `:85-87`, and the
  fused kernel, `fused_norm_rope_attn_rope_cast.py:26`). This confirms the existing recommendation
  (DeepGEMM scoring + TensorRT-LLM selection) rather than changing it.

**Adapter-conversion summary for `compressed_kv_attention`:** (1) fold kelpie's `block_table[R,P]` +
`indices[T,topk]` (token-relative) into FlashMLA's `indices_in_kvcache[b,s_q,topk]` (page-block-encoded,
`-1`-padded) — a per-row gather-and-encode, not free but O(topk) per row, no kernel launch; (2) either accept
kelpie's `kv_member` as dense bf16 (`is_fp8_kvcache=False`, dense-only code path loses the sparse `indices`
argument's fast path — check `:160-179`'s branch carefully, since `topk is not None` forces
`is_fp8_kvcache=True`, `:163`) or repack into one of the four FP8/FP4 byte layouts above; (3) `ratio`-strided
compression (kelpie's own knob) has no FlashMLA equivalent and must be applied kelpie-side before the
gather; (4) `n_reqs`/padding-row handling is kelpie's own convention, unaffected by FlashMLA, which takes
plain `batch_size`-shaped tensors with no separate real-vs-padded count.

The `compressed_kv_attention` and `dsa_indexer_topk` rows above and ranked-default items 6-7 have been
updated with these findings; item 3 (`mla_attention`) is unchanged — flashinfer stays the default there.
