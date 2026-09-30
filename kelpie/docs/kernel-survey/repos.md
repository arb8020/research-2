# Kernel survey: TokenSpeed, sglang-jax, neuron-engine (2026-09-10)

Sources checked:

- TokenSpeed (upstream: https://github.com/lightseekorg/tokenspeed, "TokenSpeed: Tokens at the
  speed of light"). CUDA/Blackwell inference engine.
- sglang-jax (upstream: https://github.com/sgl-project/sglang-jax), surveyed from a fork of it.
  JAX/Pallas, TPU.
- neuron-engine (no public upstream). Trainium, mostly torch_xla with two real NKI kernel files.

Kelpie's contract (`kelpie-models/kelpie_models/sdk/ops.py`) is a set of `torch.library.custom_op`s
whose reference body is the spec. `paged_attention`'s signature:

```
paged_attention(q[T,H,D], k[T,Hkv,D], v[T,Hkv,D], kv_member, query_start_loc[R+1], seq_lens[R],
                 block_table[R,P], slot_mapping, n_reqs, window, sinks[H]) -> out[T, H*D]
```

`kv_member` is `[num_blocks, block_size, 2*Hkv, D]`, K on even heads / V on odd heads
(`ops.py:171-179`). `sinks` is one extra per-head logit that competes inside the softmax then gets
dropped (gpt-oss). `window > 0` means query at position p sees keys `[p-window+1, p]`.

---

## 1. TokenSpeed (lightseekorg/tokenspeed)

Three code trees matter: `tokenspeed-kernel/` (registry/dispatch kernel package),
`tokenspeed-mla/` (Blackwell CuTe DSL MLA), and the engine package
`python/tokenspeed/runtime/` (GDN, conv1d, clamped-swiglu, DSA, MoE glue).

License: every file in all three trees carries the same header, e.g.
`tokenspeed-kernel/python/tokenspeed_kernel/thirdparty/cuda/rmsnorm.py:1-19`:
`# Copyright (c) 2026 LightSeek Foundation` under an MIT-style grant (`tokenspeed-mla/LICENSE` is
MIT, "Copyright (c) 2026 LightSeek Foundation <contact@lightseek.org>"). Upstream attributions
(TensorRT-LLM Apache-2.0, triton MIT, DeepEP MIT, DeepGEMM MIT, flash-attention BSD-3, FlashMLA
MIT, fast-hadamard-transform BSD-3, sgl-kernel Apache-2.0, flashinfer Apache-2.0) exist only
centrally in `tokenspeed-kernel/python/THIRDPARTYNOTICES` — no per-file upstream copyright
survives even where a docstring cites its origin (e.g.
`python/tokenspeed/runtime/layers/attention/linear/chunk.py:188` cites `fla.ops.gated_delta_rule`).
One file has no header: `.../kv_cache/trtllm_fp8_kv_kernel.py:1-13`.

| op | file:symbol | signature | KV/plan layout vs kelpie | dtypes | block/align | tests/reference | license |
|---|---|---|---|---|---|---|---|
| rms_norm | `tokenspeed-kernel/python/tokenspeed_kernel/ops/layernorm/triton.py:8-90` `rmsnorm(x, weight, eps, residual=None, out=None)`; also CUDA `thirdparty/cuda/rmsnorm.py:43-62` `rmsnorm_fused_parallel(input1, weight1, output1, input2, weight2, output2, eps=1e-6, enable_pdl=False)` (two norms per launch); FlashInfer passthrough `ops/layernorm/flashinfer.py:23-37` | n/a (not attention) | none | Triton: `BLOCK=next_pow2(hidden)`, fp32 accumulate | `test/ops/test_layernorm.py:19-68`, `assert_close(atol=2e-2, rtol=2e-2)` vs torch fp32 | LightSeek MIT |
| layer_norm | only a gated-Mamba-scoped variant: `python/tokenspeed/runtime/layers/attention/linear/layernorm_gated.py:34-200` `_layer_norm_fwd(x, weight, bias, eps, z=None, out=None, group_size=None, norm_before_gate=True, is_rms_norm=False)` | n/a | none | `BLOCK_N=min(65536//elem_size, next_pow2(group_size))`; errors if feature dim >= 64KB (`:137`) | untested | LightSeek MIT |
| gelu | absent (only stubbed `ops/activation/flashinfer.py:23-36`, errors without flashinfer) | — | — | — | — | — | — |
| silu_mul | fused-quant only: `thirdparty/cuda/activation.py:48-83` `silu_and_mul_fuse_block_quant(input, scale_out, out=None, enable_pdl=False, num_tokens_per_expert=None, num_tokens_hint=None, num_experts=0)`; `:100-154` `silu_and_mul_fuse_nvfp4_quant(input, global_scale, enable_pdl=False)`; plain unquantized only via external `ops/activation/flashinfer.py:25,32` | input `[M,2*I]` concatenated gate\|up, not interleaved (kelpie takes two separate tensors) | bf16/fp16 | `2*I % 32 == 0` (`activation.py:130`) | `test/thirdparty/test_cuda.py:1190` | LightSeek MIT |
| rope | Triton `ops/embedding/triton.py:40-198` kernel, `:201-355` `apply_rope_triton(positions, query, key, head_size, cos_sin_cache, is_neox=True, offsets=None, rotary_dim=None, fused_set_kv_buffer_arg=None, output_q_rope=None, output_k_rope=None)`; CUDA `thirdparty/cuda/rope.py:53-127` `apply_rope_with_cos_sin_cache_inplace(...)` | takes `cos_sin_cache[max_pos, rotary_dim]` indexed by integer `positions`, vs kelpie's per-token `cos[T,D]`/`sin[T,D]`; `is_neox=True` (split-half) == kelpie's rotate-half math exactly (`triton.py:137-147`); optionally fuses K/V-cache scatter | dtype of q/k; CUDA path hard-requires `cos_sin_cache.dtype == float32` (`rope.py:70-71`) | `rotary_dim` even, `<= head_size` (`triton.py:245-248`), partial rotary supported | `tokenspeed-kernel/test/ops/test_enbedding.py:28,90,151,224,286,341,376` vs torch ref, `rtol=atol=2e-2`; `test/thirdparty/test_cuda.py:41,109-132,199-214` | LightSeek MIT |
| sample | no match: own CUDA is spec-decode only (`thirdparty/cuda/sampling_chain.py:43-60,63-88`); single-step sampling delegates to FlashInfer `top_k_top_p_sampling_from_logits` (`ops/sampling/flashinfer.py:23-47`, called from `python/tokenspeed/runtime/sampling/backends/flashinfer.py:230-283`) | no philox-4x32-10 counter scheme, no bitmask `logit_mask` param (mask applied pre-kernel, `:256`); greedy via `torch.argmax` (`:246`) | — | — | spec-decode kernels tested only, `test/thirdparty/test_cuda.py:745-904` | LightSeek MIT |
| write_kv | no interleaved-layout match anywhere; K/V always kept separate: `python/tokenspeed/runtime/layers/attention/kv_cache/mha.py:338-355` `set_kv_buffer(layer, loc, cache_k, cache_v, k_scale=None, v_scale=None,...)`; fused-with-rope scatter (`ops/embedding/triton.py:168-198`); fused fp8-quant scatter `kv_cache/trtllm_fp8_kv_kernel.py:88-201` `fused_fp8_set_kv_buffer(k, v, k_cache, v_cache, cache_loc, k_scale=None, v_scale=None, page_size=16, use_triton=True)` | caches `[total_slots, Hkv, D]` or `[num_pages, page_size, Hkv, D]`, **not** interleaved 2*Hkv like kelpie | fp8 stored as uint8 (`mha.py:99-120,`base.py:53-57`) | `page_id = loc // page_size` | none dedicated | LightSeek MIT / no header on trtllm_fp8_kv_kernel.py |
| paged_attention (window+sinks) | dispatch contract `tokenspeed-kernel/python/tokenspeed_kernel/ops/attention/__init__.py:44` `mha_prefill(...)`, `:147` `mha_prefill_with_kvcache(q,k,v,cu_seqlens_q,k_cache,v_cache,page_table,cache_seqlens,max_seqlen_q,max_seqlen_k,softmax_scale=None,is_causal=True,window_left=-1,logit_cap=0.0,sinks=None,return_lse=False,override=None)`, `:261` `mha_decode_with_kvcache(...)` (q_len forced to 1); own hand-written Triton backend `triton/mha_prefill.py:31-345` + `triton/mha_decode.py:34-169,248-419,514-579,731-794`; also FA4 (Blackwell sm_100 only), FA3 (Hopper), FlashInfer/TRT-LLM backends | separate `k_cache`,`v_cache` `[num_pages, page_size, Hkv, D]` (FlashInfer backend wants `[pages, Hkv, page_size, D]`); `page_table[batch,max_pages]`,`cache_seqlens[batch]` ~= kelpie's `block_table`/`seq_lens`; `cu_seqlens_q` ~= `query_start_loc`; no `slot_mapping`, op does not write KV itself; `n_reqs` derived from `cu_seqlens_q.shape[0]-1` | fp16/bf16 (Triton, FA3/FA4); FlashInfer path fp8 supported via TRT-LLM | no page-size power-of-2 assertion; tests use 64/128; head_dim in `[8,128]` step 8 for FA4 (`flash_attn/__init__.py:59-61`) | `tokenspeed-kernel/test/ops/test_attention.py:47,84,189` assert **shape only** (`:77,182,272`); no numerical reference, no window test, no sink test anywhere | LightSeek MIT |
| mla_attention | Blackwell CuTe DSL, split decode/prefill: `tokenspeed-mla/python/tokenspeed_mla/mla_decode.py:294-310` `tokenspeed_mla_decode(query, kv_cache, workspace_buffer, kv_lora_rank, qk_rope_head_dim, block_tables, seq_lens, max_seq_len, softmax_scale, output_scale=1.0, out=None, is_var_seq=True, causal_mask=True, enable_pdl=False)` (weight-absorbed); `mla_prefill.py:286-298` `tokenspeed_mla_prefill(query, key, value, seq_lens, cum_seq_lens, max_seq_len, batch_size, softmax_scale, is_causal=True, return_lse=False, cum_seq_lens_q=None, max_seq_len_q=None, enable_pdl=False)` (expanded K/V, unpaged) | kelpie's single op (`q, latent, kv_member, ...`) is split into decode (absorbed, paged) vs prefill (expanded, unpaged); neither writes cache inside attention (separate `mla_kv_pack_quantize_fp8.py:122-218`) | `{fp16, bf16, float8_e4m3fn}` (`mla_decode.py:361`); cache dtype must equal q dtype | `page_size = kv_cache.shape[1]`; `mma_m_tile=128`, requires `H>=128` or `H*q_len<=128` (`:398-406`) | pack-quantize bitwise-tested vs torch ref (`tokenspeed-kernel/test/ops/test_tokenspeed_mla.py:66-206`); no golden-output test of the CuTe decode/prefill kernels themselves | LightSeek MIT |
| dsa_indexer_topk | reference `python/tokenspeed/runtime/layers/attention/deepseek_v4_ops.py:2533-2564` `deepseek_v4_indexer_topk_reference(q[T,H,dim], k[KV,dim], weights, top_k, lengths=None, row_starts=None)`, `DEEPSEEK_V4_INDEXER_DIM=128`; production `python/tokenspeed/runtime/models/deepseek_v4.py:613` (bmm+relu, then `fast_topk_v2` for topk in {512,1024,2048} else `torch.topk`), fp8/mxfp4 deepgemm paths at `:939,:1022` (`fp8_fp4_mqa_logits`/`fp8_fp4_paged_mqa_logits`) | indexer cache: fp8 `[values \| fp32 scale]`, mxfp4 `[64B values \| 4 ue8m0 scales]` block 32, viewed `[num_pages, block_size, 1, row_bytes]` — not kelpie's `indexer_member` shape | fp8, mxfp4 | block 32 quant; local→global slot conversion Triton kernel `deepseek_v4_ops.py:2043-2088` | `test/runtime/test_deepseek_v4_config.py:658-724`, `test/runtime/test_deepseek_v4_attention_ops.py:573` vs reference | LightSeek MIT |
| compressed_kv_attention | cache/index machinery own, attention itself external FlashMLA: `python/tokenspeed/runtime/layers/attention/backends/deepseek_v4.py:395-455` `forward_deepseek_v4_decode(..., compress_ratio, window_size, softmax_scale, attn_sink, topk_indices)` calls `flash_mla.flash_mla_with_kvcache(..., is_fp8_kvcache=True, indices=swa_indices, attn_sink=attn_sink, extra_k_cache=compressed_cache, extra_indices_in_kvcache=extra_indices, topk_length=swa_lens, extra_topk_length=extra_lens)`, raises `DeepseekV4AttentionOpUnavailable` if flash_mla missing | CSA `compress_ratio=4` + 8-token overlap window (`deepseek_v4_ops.py:2874-2905,2589`); HCA `compress_ratio=128` dense strided (`:2699-2724`); cache head 512 = nope 448 (fp8, ue8m0 block-64) + rope 64 (bf16/fp16) (`:33-42`) | fp8 nope + bf16/fp16 rope | token stride 576B, +8 scale bytes/block | only own fused kernel here is `csrc/deepseek_v4_attention.cu:84-226` `fused_qnorm_rope_kv_insert_kernel`; no end-to-end CSA/HCA test | LightSeek MIT |
| chunk_gated_delta_rule | vendored fla port: `python/tokenspeed/runtime/layers/attention/linear/chunk.py:136` `chunk_gated_delta_rule(q, k, v, g, beta, scale=None, initial_state=None, output_final_state=False, cu_seqlens=None, head_first=False, use_qk_l2norm_in_kernel=False, output_h=False) -> (o, final_state[, h])`, Triton core `chunk_delta_h.py:48,285` | q/k `[B,T,H,K]`, v `[B,T,H,V]`, g `[B,T,H]` log-space, state `[N,H,K,V]`; **functional** (returns new state) vs kelpie's in-place; kelpie has no `beta` param | bf16/fp16 only, asserts not fp32 (`:213-216`) | — | no unit test found | LightSeek MIT (attribution to `fla.ops.gated_delta_rule` only in a docstring, `:188`) |
| causal_conv1d | vLLM/mamba continuous-batching port: `linear/causal_conv1d.py:394` `causal_conv1d_fn(x[dim, cu_seq_len], weight[dim, width], bias, conv_states[..., dim, width-1], query_start_loc, cache_indices=None, has_initial_state=None, activation="silu", pad_slot_id=PAD_SLOT_ID, metadata=None, validate_data=False, **kwargs)`, kernel `:31`; decode step `causal_conv1d_update:918`, kernel `:652` | state mutated in place via `cache_indices`, matches kelpie's spirit; extra `query_start_loc`/pad-slot semantics beyond kelpie's `(x, weight, state)` | — | — | no unit test found | LightSeek MIT |
| clamped_swiglu | exact math match: `python/tokenspeed/runtime/layers/activation.py:83-113` `compute_swiglu(gelu, linear, scale, alpha, limit)` — clamps gate above at `limit`, up to `[-limit,limit]`, `(up+1)*gate*sigmoid(alpha*gate)` via `tl.fma`; defaults alpha=1.702, limit=7.0 (`moe/backends/mxfp4/triton_kernel.py:221-222`) | fused into MoE gate_up GEMM, not standalone; `swiglu_fn` splits **interleaved** pairs via `tl.split`, matching kelpie's interleaved `gate_up[...,2I]` layout | — | — | no unit test; note a **look-alike that does not match**: `models/deepseek_v4.py:1653-1656` is `silu(clamp(gate))*clamp(up)`, missing the `alpha`/`+1` term | LightSeek MIT |
| grouped_mm_mxfp4 | via external `triton_kernels`: `python/tokenspeed/runtime/layers/moe/backends/mxfp4/triton_kernel.py` (`Mxfp4TritonKernelBackend.forward`, ~`:180-260`) — `moe_route(...)` -> ragged metadata + gather/scatter permutations, then `moe_experts(..., traits={"weight_dtype":"mxfp4"})` with swiglu fused in | batching = OpenAI `triton_kernels` `RaggedTensorMetadata` + gather/scatter, **not** kelpie's sorted-rows + `expert_counts: list[int]`; weights `w13[E,2*I_pad,H_pad//2]` uint8, `w13_scale[E,2*I_pad,H_pad//32]` uint8 e8m0 block 32 (`mxfp4/weights.py:29-75`) | mxfp4 weights, other formats via same interface (bf16/fp8/mxfp4/nvfp4, `moe/__init__.py:95-99`) | `round_up(I,64)` padding on Blackwell (`:123-127`) | none under `tokenspeed-kernel/test/`; nearest is `test/ops/test_nvfp4_gemm_swiglu_nvfp4_quant.py` | LightSeek MIT |

Cross-cutting tokenspeed findings:
1. Cache layout is always separate K/V, `[pages, page_size, Hkv, D]`; kelpie's interleaved
   `[pages, block, 2*Hkv, D]` needs an adapter everywhere.
2. Window off-by-one: TokenSpeed's `window_left = kelpie_window - 1`; and TokenSpeed's own
   Triton prefill vs decode paths disagree with each other by one key
   (`mha_prefill.py:146-151,259-262` vs `mha_decode.py:76-79,301-303,538-540`).
3. Sinks: the hand-written Triton backend's math is bit-identical to kelpie's
   (`mha_prefill.py:333-335`, `mha_decode.py:574-577`, denominator-only `exp(sink - max)` term);
   FA3/FlashInfer just forward `sinks=` upstream opaquely, FA4 silently drops it
   (`flash_attn/__init__.py:98-112,152-166`, gated out by traits at `:76-77`).
4. Verification is thin overall: paged-attention/window/sink tests check shape only; GDN,
   conv1d, clamped_swiglu, and mxfp4 MoE have zero dedicated unit tests. rope, rmsnorm, MLA
   pack-quantize, and the DSA indexer do have real reference-comparison tests.

---

## 2. sglang-jax (sgl-project/sglang-jax)

Root `LICENSE` = Apache-2.0; a mirror of `sgl-project/sglang-jax` with Kimi K3 TPU support (KDA
hybrid, MXFP4). Kernel layout: `python/sgl_jax/srt/kernels/{ragged_paged_attention,
paged_attention, update_kv_cache, mla/v1, mla/v2, dsa, kda, gdn, simple_gla,
gmm/megablox_gmm_kernel, fused_moe/v1, fused_moe/v2, quantized_matmul, grouped_topk, biased_topk,
speculative}`; norms/activations under `srt/layers/`. (`worktrees/agentic-perf` and
`worktrees/executable-cache` hold duplicate copies, not surveyed — presumed stale.)

| op | file:symbol | signature | KV/plan layout vs kelpie | dtypes | block/align | tests/reference | license |
|---|---|---|---|---|---|---|---|
| paged_attention (window+sinks) — production | `srt/kernels/ragged_paged_attention/ragged_paged_attention_v3.py:1667-1699` `ragged_paged_attention(queries, keys, values, kv_cache_fused, kv_lens, page_indices, cu_q_lens, cu_kv_lens, distribution, custom_mask, attention_sink=None, *, causal=1, sm_scale=1.0, sliding_window=None, soft_cap=None, mask_value=DEFAULT_MASK_VALUE, q_scale=None, k_scale=None, v_scale=None, xai_temperature_len=None, softmax_dtype=None, chunk_prefill_size=None, d/p/m_block_sizes=None, vmem_limit_bytes=None, out_dtype=None, skip_kv_mask=False, disable_semaphore_checks=True, debug_mode=False, mask_aligned_to_cu_kv=False)`, kernel body `:328`, three `pallas_call`s (DECODE/PREFILL/MIXED) | cache `[total_num_pages, page_size, 2*Hkv, D]`, K/V interleaved by head — **identical layout to kelpie's `kv_member`**, viewed 5D `[pages, page_size, 2*Hkv//kv_packing, kv_packing, D]`, `kv_packing=32//itemsize_bits` (`util.py:16-18`); but `block_table` differs: v3 wants **flat** `page_indices` with each seq's pages tightly packed, located via `cu_kv_lens[i]//page_size`, not kelpie's padded 2D `[R,P]`; `cu_q_lens`==`query_start_loc`, `kv_lens`==`seq_lens`, `n_reqs` carried in `distribution[2]`; no `slot_mapping` — kernel writes new K/V itself at `cu_kv_lens`-derived positions (new tokens must be seq tail, matches kelpie) | must be `jnp.floating` (`:1365`), q/k/v/cache dtype must match; fp32/bf16/fp8 — **no int8 KV** despite scale args | `head_dim % 128 == 0` (`:411`); 4-tuple block sizes per mode from a 2229-line tuned LUT (`tuned_block_sizes_v3.py`) | `test/flashattention_common.py:466-483` vs `ref_ragged_paged_attention` (naive per-seq einsum, same file), `rtol=2e-2,atol=1e-2`; sink-specific `test/test_flashattention_gqa.py:195-239`, same tolerance | `# Adapted from vllm-project/tpu-inference v0.11.1` / `# Copyright 2025 The tpu-inference Authors.` — no Apache boilerplate block |
| paged_attention — legacy v1 | `srt/kernels/ragged_paged_attention/ragged_paged_attention.py:1394-1421`, same args minus `attention_sink` | same idea, block sizes are plain ints not tuples; **no sinks anywhere** (zero grep hits); not imported by the serving backend | as v3 minus sinks | `head_dim % 128` (`:368`) | none dedicated (superseded) | same tpu-inference header |
| paged_attention — legacy decode-only kernel | `srt/kernels/paged_attention/paged_attention.py`, decode-only, `q[B,H,D]`, `k_pages/v_pages[Hkv,pages,page_size,D]` **split K/V, head-major** (differs from kelpie), `block_tables i32[B,pages_per_seq]`, `lengths i32[B]`, optional `k/v_scales_pages[Hkv,pages,page_size]` (int8 KV) | no window, no sinks; has softcap + xai temperature | int8 KV supported via scale arrays | `block_h % 16 == 0` (`:432`) | `test/test_pagedattention.py:138,162-168` vs `paged_attention_reference` (`:467-526`), `rtol=2e-2,atol=1e-2` | full Apache-2.0 header, `# Copyright 2025 Yanko (@Yanko-7)` / `# Copyright 2023 The JAX Authors` |
| write_kv | `srt/kernels/update_kv_cache/update_kv_cache.py:197-286` `kv_cache_update(new_kv[total_tok,Hkv,D], slices[3,slices], kv_cache[max_tok,Hkv,D], num_kv_update_slices[1], *, page_size=1, num_slices_per_block=8, kv_partition_axis="tensor")`, kernel `:69-83` pure DMA, no compute | layout is **slice runs** `[3, padded_slices]` of `(cache_start, new_start, len)` via `get_slot_mapping` (`:14-32`), not kelpie's per-token flat `slot_mapping[T]`; cache aliased in place | rejects float16 explicitly (`:129-154`); `new_kv.dtype == kv_cache.dtype` required | `num_combined_kv_heads % 2 == 0`, `head_dim % 128 == 0`; 64MB VMEM budget (`:35`) | none dedicated (in practice RPA v3 fuses the write itself) | same tpu-inference attribution header |
| mla_attention | `srt/kernels/mla/v2/kernel.py:1338-1408` `mla_ragged_paged_attention(ql_nope, q_pe, new_kv_c, new_k_pe, cache_kv, kv_lens, page_indices, cu_q_lens, cu_kv_lens, distribution, *, sm_scale=1.0, sliding_window=None, soft_cap=None, mask_value=DEFAULT_MASK_VALUE, q/k/v_scale=None, chunk_prefill_size=None, num_kv_pages_per_block=None, num_queries_per_block=None, vmem_limit_bytes=None, decode_batch_size=1, debug_mode=False) -> (out, updated_cache)`, kernel `:253` | kelpie's single `latent` tensor is split into `new_kv_c`+`new_k_pe`, and `q` into `ql_nope`/`q_pe`; absorbed/MQA-on-latent form, value = `kv_c` only; same ragged `page_indices`+`cu_kv_lens` convention as RPA v3; cache row width = `align_to(kv_lora_rank,128) + align_to(qk_rope_head_dim,128)` | floating dtypes only, bf16 in all tests/tunings; `lkv_dim % 128 == 0`, `r_dim % 128 == 0` | `input_output_aliases={8:0,12:1}`; DEFAULT_VMEM_LIMIT=100MiB; tuned LUT for kv_lora_rank=512, qk_rope_head_dim=64, TPU v6e/v7 only (v5 empty) | `test/test_mla_attention.py:541-566` vs `mla/v1/ref.py:108-126` (pure jnp), `rtol=2e-2,atol=1e-2`, bf16; page sizes 8/16/32/64, decode/prefill/batched-decode, window, softcap | full Apache-2.0 header, `# Adapted from vllm-project/tpu-inference` + `# Copyright 2026 Google LLC` |
| dsa_indexer_topk — Pallas (unwired) | `srt/kernels/dsa/streamindex_topk.py:522-547` `streamindex_topk(q, indexer_weights, cache_kv, seq_lens, page_indices, cu_q_lens, distribution, *, k, compression_ratio, num_kv_pages_per_block=None, num_queries_per_block=None, vmem_limit_bytes=DEFAULT_VMEM_LIMIT_BYTES) -> i32[T,k]` | operates on compressed KV, `kv_len = seq_len // compression_ratio`; `page_indices` fixed-stride (== kelpie's flattened `block_table`) | — | `k % 128 == 0`, `head_dim % 128 == 0`; top-k is an unrolled `for _ in range(k)` argmax-and-mask loop (`:180-201`) since Pallas TPU has no top_k lowering | no test exercises this kernel directly | `# Vendored from vllm-project/tpu-inference @ 35011e5 (Apache-2.0)` / `# Copyright 2026 Google LLC` + Apache boilerplate |
| dsa_indexer_topk — production | `srt/kernels/dsa/ref.py:51-63` `streamindex_topk_ref(q, weights, cache_kv, ...) -> i32[T,k]` (-1 padded), uses `jax.lax.approx_max_k(recall_target=0.70)` then exact top_k; page-level `:173` | plain jnp, not Pallas — "Phase A" per `dsa_sparse_backend.py` docstring; decode uses Pallas `sparse_mla_page_level`, extend falls back to dense | — | — | `test/srt/kernels/dsa/test_ref.py` vs numpy oracles, `rtol=1e-3,atol=1e-4`, CPU | no header |
| compressed_kv_attention (partial) | `srt/kernels/dsa/sparse_mla.py:73-192,207-297` `sparse_mla_page_level`/`sparse_mla_via_dense` build per-token pseudo-sequences from `topk_indices` and call the dense MLA v2 kernel; ref `dsa/ref.py:272-337` `sparse_mla_ref(q, cache_kv, topk_indices, ...)` | no standalone stride-`ratio` compressed-KV attention kernel; the `ratio` concept lives only inside the indexer (`compression_ratio`) | — | — | no Pallas-level test | no header |
| chunk_gated_delta_rule — KDA prefill (Pallas) | `srt/kernels/kda/kda.py:1449-1470` `chunk_kda_fwd(q, k, v, g, beta, scale, initial_state, output_final_state, cu_seqlens, use_qk_l2norm_in_kernel=False, chunk_indices=None, chunk_size=64, safe_gate=True, lower_bound=None, use_gate_in_kernel=False, A_log=None, dt_bias=None, disable_recompute=False, return_intermediate_states=False, cp_context=None, transpose_state_layout=False)` -> 12-tuple; 4 `pallas_call`s | state `[N,H,K,V]` fp32, N=`len(cu_seqlens)-1` per request; gate `gk` **per-channel** `[B,T,H,K]` log-space (kelpie's `gate` arg is untyped/unshaped in its stub — this constrains it); functional not in-place, unlike kelpie's mutated `state` | bf16 in, fp32 accumulate | `chunk_size >= 16 and % 16 == 0`; `K <= 256`; K/V padded to 128; `T % chunk_size == 0` after alignment | `test/kernels/kda_test.py:400-434` vs `naive_recurrent_kda`, `rtol=2e-2,atol=1e-2` | `# Adapted from primatrix/pallas-kernel (rev 3c691ad3)` — **upstream repo now private, provenance unverifiable**; no license text |
| chunk_gated_delta_rule — KDA decode | `srt/kernels/kda/decode.py:19` `fused_recurrent_kda_decode` is a **stub** that logs "not pushed yet" and calls `naive.py:15 naive_recurrent_kda` (plain Python loop) | kelpie's single-token decode path has **no Pallas kernel** here | — | — | — | same as above |
| chunk_gated_delta_rule — GDN (qwen3_next) | `srt/kernels/gdn/gated_delta.py:356` `ragged_gated_delta_rule_ref` (`lax.scan`, per-head **scalar** gate `g=-A*softplus(a+dt_bias)[...,H]`, state pool `[num_blocks,n_v,d_k,d_v]` + `state_indices[B]`); decode `:514` | **no Pallas, no header at all**; confirms kelpie's "KDA generalizes GDN" call — GDN's scalar-per-head gate is a special case of KDA's per-channel gate, so the KDA kernel could serve GDN by broadcasting | — | — | `test/test_gdn_attention.py`, `atol=1e-2` | none |
| simple_gla (adjacent, not a kelpie op) | `srt/kernels/simple_gla/simple_gla.py:854,940`, same primatrix header (rev 41431b1) | `K % 128 == 0 and V % 128 == 0`; `B == 1`; gate `g[B,T,H]` or `g_gamma[H]` | — | — | `test/kernels/simple_gla_fused_test.py` | primatrix, provenance unverifiable |
| causal_conv1d | plain JAX, no Pallas: `srt/kernels/gdn/gated_delta.py:116` `jax_causal_conv1d_prefill(x[D,T], weight[D,kernel_size], bias, cu_seqlens, conv_state[num_blocks,D,kernel_size-1], state_indices, has_initial_state, activation, ...)`, `:280` `jax_causal_conv1d_update`; also `srt/layers/attention/linear/short_convolution.py:56` `short_convolution(x, weight, cache, cu_seqlens, forward_mode, bias=None, activation="silu")` | ring state width `kernel_size-1`, matches kelpie's `state` ring in spirit | — | — | only model-level tests (`test_short_conv.py`, `test_kimi_k3.py`, `test_qwen3_5.py`) | none |
| grouped_mm_mxfp4 | `srt/kernels/gmm/megablox_gmm_kernel/gmm_v2.py:1224-1240` `gmm_v2(lhs[M,K], rhs[E,K,N], group_sizes, rhs_scale=None, rhs_bias=None, group_offset=None, *, tile_info=calculate_tiling, vmem_limit_bytes=None, precision=DEFAULT, preferred_element_type=None, acc_dtype=None, maybe_quantize_lhs=True, zero_initialize=True, rhs_packed_fp4=False)`; MXFP4 path `rhs_packed_fp4=True` | `group_sizes` (counts per expert, rows sorted by expert) is **exactly** kelpie's `expert_counts`; but `rhs` is uint8 `[E,K//2,N]` (2 e2m1 nibbles/byte, compressed-tensors convention) not kelpie's `[E,K/32,...]` layout; scale uint8 e8m0 `[E,K//32,N]` block 32; decoded via integer bit tricks since Mosaic can't unpack `float4_e2m1fn` | bf16/f32/fp8_e4m3fn/fp8_e5m2/int8 base dtypes; mxfp4 W4A16 only (`maybe_quantize_lhs` must be False) | `size_k % 256 == 0` (`_PACKED_FP4_GRANULE=256`); lhs columns pre-deinterleaved | `test/kernels/gmm_test.py:273-315` `test_gmm_v2_packed_fp4` vs bf16 `reference_gmm` on dequantized weights, `atol=rtol=3e-2`; `test/models/test_kimi_k3_mxfp4.py` (nibble/e8m0 round-trip, EPMoE parity, CPU-runnable) | header line only, `# Adapted from vllm-project/tpu-inference gmm_v2.py`, no license text; `common.py` cites `# Copyright 2025 The JAX Authors` |
| clamped_swiglu | inlined only, both fused-MoE kernel versions: `fused_moe/v1/kernel.py:223-229`, `v2/kernel.py:132-138` `swigluoai(gate, up, *, alpha=1.702, limit=7.0)`: `gate=clip(gate,max=limit); up=clip(up,-limit,limit); glu=gate*sigmoid(alpha*gate); return (up+1)*glu` | same math as kelpie exactly, but takes **separate** gate/up args, not kelpie's interleaved `gate_up[...,2I]`; lives inside the MoE Pallas epilogue, no standalone op | — | — | `fused_moe_v{1,2}_test.py::test_activation` over `["silu","gelu","swigluoai"]`, `atol=rtol=5e-2` | no header |
| rms_norm / layer_norm / gelu / silu_mul / rope / sample | all plain flax/jnp, zero `pallas_call`: `srt/layers/layernorm.py:30,187,224,239` (no LayerNorm class exists at all); `srt/layers/activation.py:32` `GeluAndMul`, `:8` `situ_glu`; `srt/layers/moe.py:915,963,1190` inline `silu(gate)*up`; `srt/layers/embeddings.py:571-596` `apply_rotary_emb(x,cos,sin,is_neox_style)`; `srt/layers/sampler.py:342` `top_k_top_p_min_p_sampling_from_probs_jax`, Gumbel via `jax.random` (not Philox-counter-reproducible like kelpie's) | n/a | — | — | `test/layers/test_group_rmsnorm.py` only (fp64 numpy oracle, `atol=8.6e-6,rtol=1.4e-6`); no LayerNorm/gelu/rope/sample tests | none |

License summary for sglang-jax: root LICENSE Apache-2.0, but per-file headers are uneven — full
Apache boilerplate on `mla/v1,v2`, `dsa/streamindex_topk.py`, `paged_attention.py`,
`gmm/tuned_block_sizes.py`; attribution-comment-only (no license text) on RPA v1/v3,
`update_kv_cache.py`, `gmm.py`, `gmm_v2.py`, `fused_moe/v1`; primatrix "vendored from now-private
repo" with no copyright on `kda.py`/`simple_gla.py`; **no header at all** on `gated_delta.py`,
`fused_moe/v2/kernel.py`, `dsa/ref.py`, `dsa/sparse_mla.py`, `layernorm.py`, `activation.py`,
attention backends.

---

## 3. neuron-engine

This is a nano-vLLM-derived inference engine for Trainium (torch_xla + a small amount of real
NKI), not a kernel library. **Real NKI usage is exactly two files**, `neuronengine/kernel/
activation.py` and `neuronengine/kernel/sampler.py`. Everything else — attention, MLA, MoE,
indexer, rope, norms — is plain eager PyTorch/torch_xla (einsum, softmax, index_copy_) compiled
through XLA/HLO, not NKI. A third source, `extra/dsv4_ref.py` and `extra/dsa_ref.py`, is
explicitly disconnected reference code (never imported by `neuronengine/`) written in
**TileLang** (`@tilelang.jit`), a CUDA-target DSL — not NKI, not Trainium; it would not compile
for this hardware as-is. **No file in the repo carries a license or copyright header, and there
is no top-level LICENSE file.**

| op | file:symbol | signature | KV/plan layout vs kelpie | dtypes | block/align | tests/reference | license |
|---|---|---|---|---|---|---|---|
| silu_mul | real NKI: `neuronengine/kernel/activation.py:9` `nki_silu_and_mul_v0(x)`, `:32` `nki_silu_and_mul_v1(x)`, `:65` `nki_silu_and_mul_v2(x)` (the wired version, uses `nl.load`/`nl.store`); class `:94` `SiluAndMul.forward(self, x, nki=False)` | takes **one** concatenated tensor `x` and splits it, not kelpie's two separate `(gate, up)` tensors — signature mismatch, adapter needed | `x.dtype` untouched through the tiles (test uses fp32) | partition dim `d0`/`df` (after flattening) must be `<= nl.tile_size.pmax` (Trainium SBUF 128 partitions); last dim must be even | `test/test_activation.py:16` `test_numerical_correctness`, eager vs `nki=True`, `torch.testing.assert_close(rtol=1e-3,atol=1e-3)` | none |
| sample | real NKI, greedy-only: `neuronengine/kernel/sampler.py:14` `nki_sampler_v0(logits, temperatures)` (comment: "tensors too large to fit on sbuf" — known-broken/superseded), `:33` `nki_sampler_v1(logits, temperatures)` (tiles vocab in `F_TILE=16384` chunks, the wired version); both call `nkilib.core.max.cascaded_max` (vendored, not authored here) for **pure temperature-scaled argmax**; class `:61` `Sampler.forward(logits, temperatures, nki=False)` | **materially weaker than kelpie**: no Gumbel noise, no `logit_mask` bitset, no `key`, no k>0 — the NKI path is greedy-only even though the eager reference path (`:62`) does real Gumbel-max stochastic sampling | logits cast to `nl.float32` explicitly | `F_TILE=16384` vocab chunking (only explicit SBUF-capacity tile size in the repo) | `test/test_sampler.py`: `test_shape:15`, `test_valid_index:22`, `test_peaked_argmax:29` (exact index match), `test_greedy:39` (vs eager reference at temp=1e-6, exact match); `VOCAB=151936` | none |
| rms_norm | no NKI, plain `F.rms_norm` wrapper: `neuronengine/models/deepseekv3/layers/norm.py:6-14`; also inline `neuronengine/models/qwen3/inf_model.py:90` | n/a | — | — | none beyond end-to-end smoke | none |
| layer_norm | no NKI, plain `F.layer_norm` wrapper: `neuronengine/models/deepseekv3/layers/norm.py:17-26` | n/a | — | — | none | none |
| gelu | **absent entirely** — no `gelu` reference anywhere; all models use SiLU-based MLPs | — | — | — | — | — |
| rope | no NKI, plain torch/XLA math, **three independent implementations**: `neuronengine/models/deepseekv3/layers/embed.py:34-62` `RotaryEmbedding.forward(self, x, position_ids, interleaved=True)` (supports both HF-interleaved and non-interleaved conventions, superset of kelpie); `neuronengine/models/qwen3/inf_model.py:139-156` `get_rope` (separate, not shared); `extra/dsa_ref.py:28-38` `apply_rotary_emb` (`torch.polar`/`view_as_complex` style, disconnected reference) | `cos_cached[position_ids]` gathered `[T,D/2]`, standard complex-rotation RoPE, mathematically the rotate-half form kelpie uses but via separate cos/sin not `cat([-x2,x1])` | — | — | none dedicated (only indirect via `test_mla.py`/`test_dsa.py` smoke runs) | none |
| write_kv | no factored op, inlined `index_copy_` per module: `mla.py:73-74` `self.kv_cache.index_copy_(0, slot_mapping, ...)`; `index.py:78` `self.k_cache.index_copy_(0, slot_mapping, k)`; `qwen3/inf_model.py:214-215` | same idea as kelpie but no combined k/v interleave; cache is per-sequence-slab, not paged | — | — | none | none |
| paged_attention | **no block-table match at all** — GQA at `neuronengine/models/qwen3/inf_model.py:199-248`, MLA-flavored at `mla.py:55-120` | cache is a **flat single-slab-per-sequence** buffer `[max_batch_size*max_seq_len, ...]` (`mla.py:45-46`), addressed by `slot_mapping` (prefill, `index_copy_`) or by `context.block_tables[:, 0]` **only the first column of the block table is ever used** (`mla.py:92`, `index.py:96`, `qwen3/inf_model.py:222`) — i.e. one contiguous block per sequence, not real pagination; `block_table[R,P]` with P>1 is never consulted beyond column 0; decode gathers a `bucket`-sized window via fancy-indexing then dense einsum+mask, not a paged/flash kernel; no window support anywhere; no sinks in live code | — | `bucket = max(32, min(2**bits, max_seq_len))` | smoke only, no numerical assertions | — |
| mla_attention | full-layer, not a factored op: `neuronengine/models/deepseekv3/layers/mla.py:55-120` `MLA.forward` — q_lora/kv_lora projections, decoupled RoPE-vs-nope split, compressed latent cache + separate `pe_cache`, plus inline call to the DSA indexer (`:109`) all in one `forward`; disconnected 2nd reference `extra/dsa_ref.py:93-176` (`torch.polar` rope, `start_pos` not block tables) | kelpie's op boundary (`q`, pre-formed `latent`, `kv_member`, block-table plan) doesn't exist as a separable unit here; same single-slab cache as paged_attention above | — | — | `test/test_mla.py:15` `test_mla` — scheduler+model smoke run, `print()` only, **no assertions comparing to any reference** | none |
| dsa_indexer_topk | full-layer: `neuronengine/models/deepseekv3/layers/index.py` `Index.forward(self, x, qr, positions, mask) -> topk_indices` at `:57`; relu-scored logits (`:101`), weighted sum across heads (`:102`), `scores.topk(...)[1]` (`:107`) — matches kelpie's score-then-topk in spirit but bundled with q/k rope, a Hadamard rotate-activation step (`:27-30,73-74`), LayerNorm on k; same single-slab cache as above (`block_tables[:,0]`, `:96`); two disconnected reference variants `extra/dsa_ref.py:41-91` (imports external `fast_hadamard_transform`, CUDA-oriented — this file was clearly never meant for Trainium) and `extra/dsv4_ref.py:925-980` | — | — | — | `test/test_dsa.py:15` — same shape as `test_mla`, smoke only, no assertions | none |
| compressed_kv_attention | **no live coverage**; only in disconnected TileLang reference: `extra/dsv4_ref.py:280-372` `sparse_attn_kernel`/`sparse_attn(q, kv, attn_sink, topk_idxs, softmax_scale)` — has both attention-sinks (`attn_sink[h]` folded into softmax denominator) and topk gathering, conceptually close to kelpie, but `kv` is single flat `[b,n,d]` (no separate K/V, no block table, no `ratio`-strided compression matching kelpie's `ratio`/`indices` args) | TileLang targets CUDA thread/warp primitives (`T.Kernel(threads=256)`, `T.gemm`); **would not compile for Trainium as-is** | BF16 | — | never imported by `neuronengine/`, no test | none |
| grouped_mm_mxfp4 | **no true MXFP4 grouped matmul**; closest is `extra/dsv4_ref.py:444-543` `fp4_gemm(a, a_s, b, b_s, scale_dtype=torch.float32)`, `A[M,K]` fp8 per-128 act scale, `B[N,K//2]` fp4 (`float4_e2m1fn_x2`) with per-32 E8M0 weight scale — genuinely MXFP4-style, but a **single dense GEMM**, no `expert_counts` partitioning, no per-expert weight table matching kelpie's contract; the actually-running MoE path (`neuronengine/models/deepseekv3/layers/moe.py:63-68` `BatchedExperts.forward`) uses plain unquantized bf16 `torch.einsum` — **the live MoE path has no quantization story whatsoever** | fp8/fp4 (reference only) | — | never imported, no test | none |

---

## What kelpie can lift, ranked by effort

1. **paged_attention sinks math from tokenspeed's Triton backend** (`mha_prefill.py:333-335`,
   `mha_decode.py:574-577`) — denominator-only `exp(sink - max)` term, bit-identical semantics to
   kelpie's own (`ops.py:213-216`). Lowest effort: same math, same framework family (Triton),
   just needs the kelpie block-table/`kv_member` layout wired in instead of tokenspeed's separate
   K/V caches.
2. **sglang-jax's `ragged_paged_attention_v3` cache layout is already kelpie's layout** —
   `[pages, page_size, 2*Hkv, D]` interleaved by head, byte-identical structure to kelpie's
   `kv_member`. For a TPU backend this is the natural target: the adapter work is entirely on the
   *plan* side (kelpie's 2D `block_table[R,P]` → v3's flat tightly-packed `page_indices` +
   `cu_kv_lens`), not the cache. Sinks (`attention_sink[H]`, folded via a seeded online-softmax
   state) and window (`sliding_window`) both already match kelpie's semantics exactly. Medium
   effort: write the block_table→page_indices/cu_kv_lens conversion, verify the
   `distribution`/kind-sorting requirement against kelpie's `kinds`/`row_request`.
3. **tokenspeed's `chunk_gated_delta_rule` (fla port, `linear/chunk.py:136`) and `causal_conv1d`
   (vLLM/mamba port, `linear/causal_conv1d.py:394`)** for the two ops kelpie has declared but not
   implemented. Medium effort: both are functional (return new state) vs kelpie's in-place
   `state` mutation, so the call site needs adapting, and neither the fla port nor the sglang-jax
   KDA kernel (`kda/kda.py:1449`) has license clarity — the fla one is attributed only in a
   docstring, the KDA one cites a now-private upstream repo. sglang-jax's KDA kernel is Pallas
   (TPU-only) and has real tests (`kda_test.py:400-434`, tol 2e-2) but its decode path is a
   stub (`kda/decode.py:19`) falling back to a naive Python loop — not production-ready for
   decode.
4. **tokenspeed's `clamped_swiglu` (`layers/activation.py:83-113`)** is an exact math match to
   kelpie's spec (clamp-then-`(up+1)*gate*sigmoid(alpha*gate)`) and even matches kelpie's
   interleaved `gate_up[...,2I]` calling convention already — lowest effort of the "not yet
   implemented" ops, but has zero unit test in tokenspeed, so kelpie would need to write its own
   verification rather than borrow one. sglang-jax's `swigluoai` has the same math but takes
   separate gate/up args (adapter needed) and does have a test
   (`fused_moe_v{1,2}_test.py::test_activation`, tol 5e-2).
5. **grouped_mm_mxfp4**: sglang-jax's `gmm_v2` (`rhs_packed_fp4=True`) has `group_sizes` that is
   exactly kelpie's `expert_counts` (same sorted-by-expert convention), with a real test
   (`gmm_test.py:273-315`, tol 3e-2) — best-tested MXFP4 grouped-matmul option, but weight
   packing (`[E,K/2,N]` uint8 nibbles, `[E,K/32,N]` e8m0) differs from kelpie's docstring shape
   and needs unpacking work since Mosaic can't lower `float4_e2m1fn` directly. tokenspeed's
   `triton_kernels`-based MXFP4 MoE path uses a different ragged-gather/scatter batching
   convention entirely (not sorted-rows), higher effort to adapt. neuron-engine's `fp4_gemm` is a
   single dense GEMM with no expert batching at all — not usable as-is.
6. **mla_attention**: both tokenspeed (CuTe DSL, Blackwell, split decode/prefill, no combined
   cache-write) and sglang-jax (Pallas, TPU, `mla/v2/kernel.py`, real ref-comparison test) have
   real, tested kernels, but both split kelpie's single `(q, latent)` op into absorbed-nope +
   rope-tail pieces — nontrivial adapter work either way, and picking one commits kelpie to a
   hardware family (tokenspeed = Blackwell CUDA, sglang-jax = TPU). neuron-engine's MLA is
   untested (smoke-only) eager torch with an incompatible single-slab cache — not liftable
   without a rewrite.

## What is missing entirely (no source has usable coverage)

- **`sample`'s exact contract** (Philox-4x32-10 counter-based Gumbel noise + `logit_mask` bitset)
  — nobody implements this. tokenspeed delegates to FlashInfer's `top_k_top_p_sampling_from_logits`
  (no counter-reproducible noise, no bitmask arg); sglang-jax uses `jax.random` (not
  counter-based); neuron-engine's only NKI sampler is greedy-argmax-only, with real stochastic
  sampling existing only in its *un-accelerated* eager reference path. Kelpie's counter-based
  Philox scheme (for cross-device bit-reproducibility) is essentially unique — this is a
  from-scratch port for whichever device kelpie targets, not a lift.
- **`gelu`** — absent from all three repos entirely; nobody has a gpt-oss-style or general GELU
  kernel (all attention-heavy modern models in these codebases use SiLU/SwiGLU MLPs).
- **`write_kv`'s exact interleaved layout** (`[pages, block, 2*Hkv, D]`, k on even heads / v on
  odd) — tokenspeed and neuron-engine both keep separate K/V cache tensors; only sglang-jax's
  `ragged_paged_attention` cache (interleaved by head) matches, but it has no standalone
  `write_kv`-shaped op — the write is fused into attention.
- **`compressed_kv_attention`'s stride-`ratio` gather semantics matching kelpie's `(indices,
  ratio, block_table, slot_mapping)` signature** — tokenspeed's CSA/HCA path calls out to external
  FlashMLA with a different argument shape; sglang-jax has no standalone compressed-KV attention
  kernel (only MLA-over-gathered-pseudo-sequence); neuron-engine's only related code is a
  disconnected, untested, CUDA-targeted TileLang kernel.
- **A NKI (Trainium) kernel for any op** beyond `silu_mul` and greedy `sample` — neuron-engine
  has no NKI paged attention, MLA, MXFP4 grouped matmul, GDN, or conv1d; anything Trainium-shaped
  in that repo (`extra/dsv4_ref.py`, `extra/dsa_ref.py`) is TileLang/CUDA-targeted reference code
  that would need a full NKI rewrite, not adaptation, and is neither imported nor tested.
</content>
