# Brief: kernel adapters, from the survey

Date: 2026-09-10. Launch AFTER `chore/kernels-build` merges (adapters live inside `kernels/ops/<op>.py`,
which that branch creates). Source of every claim: `docs/kernel-survey/{cuda,xla,repos}.md`. One
executor per device (sonnet), worktrees `adapters-cuda`, `adapters-tpu` and a Trainium one. "You are a
subagent. Don't run memo." STOP on any survey/contract mismatch; do not bend the op contract to a library.

Rules from `docs/brief-kernels-build-tiers.md`: adapter = `@<op>.register("<backend>", source=..., predicate=...)`
in the op's file; `declare_backend` pins the package + version; plan conversion happens inside the adapter
(canonical plan from Zig, CSR etc derived there); K,V members `[pages, block, Hkv, D]`; every adapter gets
a `build(check=True, bench=True)` verdict on the ladder shapes before it becomes a `DEFAULTS` entry.
Verification = `kelpie build --check --bench` manifest + `scripts/check_serve.py` rows on the device.

## CUDA (B200), in this order
1. `paged_attention` -> flashinfer `BatchPrefillWithPagedKVCacheWrapper` (native NHD two-member layout = ours,
   dense plan accepted; `window_left = window - 1`; sinks 1:1). First adapter: proves the seam.
2. `rope` -> flashinfer `apply_rope_with_cos_sin_cache` (repack cos/sin to half-width table). Liger fallback.
3. `mla_attention` -> flashinfer `BatchMLAPagedAttentionWrapper` (split `latent` -> ckv/kpe).
4. `chunk_gated_delta_rule`/`causal_conv1d` -> fla (`chunk_gated_delta_rule` for GDN, `chunk_kda` for Kimi;
   `causal_conv1d_update` decode, `causal_conv1d` prefill). STOP: fla needs a `beta` arg our op lacks — report
   before changing the signature.
5. `grouped_mm_mxfp4` -> DeepGEMM `m_grouped_fp8_fp4_gemm_nt_masked` (`expert_counts` -> `masked_m`, padded).
6. `compressed_kv_attention` -> FlashMLA `flash_mla_sparse_fwd` / `flash_mla_with_kvcache(indices=)`; AOT build,
   SM90/SM100; `indices` bakes in page*block+offset; FP8 KV byte layouts are theirs — first cut dense bf16,
   report the repack cost. Its `tests/ref.py` is a usable torch reference body.
7. `dsa_indexer_topk` -> DeepGEMM `fp8_paged_mqa_logits` + TensorRT-LLM `indexer_topk_{decode,prefill}` (two libs;
   watch flashinfer#3111 HiSparse). Last; may STOP if TRT-LLM's op is not importable standalone.
Keep ours: `sample` (Philox determinism has no match), `write_kv`. Write from scratch (Triton, in the op
file): `clamped_swiglu` (nothing covers it; the `ops.py` comment about liger is wrong — delete it).
Also: tkspeed's Triton sinks math is bit-identical to ours (`mha_prefill.py:333`, `mha_decode.py:574`) —
a second CUDA impl for `paged_attention` to compare against, but its prefill/decode window conventions
disagree by one key; do not trust its window tests (shape-only).

## TPU (v6e)
1. Fix `_pallas.py` stub: pass `sliding_window` through (kernel supports it); keep sinks asserted off.
2. `paged_attention` -> jax `ragged_paged_attention` / torch_xla `ragged_paged_attention_v2` via
   `torch_xla.experimental.custom_kernel`; cache layout `[pages, page, 2*Hkv, D]` interleaved — matches our
   `kv_member`; adapter = `block_table[R,P]` -> flat `page_indices` + page-aligned `cu_kv_lens`. sglang-jax
   `ragged_paged_attention_v3` is the same kernel, newer; prefer it if importable.
3. Everything else stays reference under XLA. Zero-recompile assert: `torch_xla.runtime.get_num_cached_compilation_graph()`
   constant across serve; persistent cache dir under `--cache`.
Gap: sinks (gpt_oss) — no TPU kernel. Reference fallback only.

## Trainium
1. `paged_attention` -> NxDI `attention_block_tkg` (closed `nkilib`, callable not readable; sinks+window trn2+ only).
2. `rms_norm` -> our `_nki.py`. Everything else reference. neuron-engine has nothing liftable (two NKI kernels,
   single-slab cache); ignore it.
3. Zero-recompile: no Python counter; watch the neuron cache dir for new entries during serve.

Report per device: adapters landed with manifest rows (verdict, err, budget, time_us) per ladder shape,
check_serve lines, STOPs, judgement calls, papercuts. Commit per adapter, brief trailer.
