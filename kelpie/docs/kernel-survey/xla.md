# XLA-family kernel survey (TPU Pallas, Trainium NKI)

Sources cloned sparse at `/tmp/kernel-survey/<name>` (not checked into this repo):

- `jax` — github.com/jax-ml/jax @ `d4d4a75` (2026-09), path `jax/experimental/pallas/ops/tpu/`
- `torch_xla` — github.com/pytorch/xla @ `41398bf`, paths `torch_xla/experimental/{custom_kernel.py,splash_attention.py,pallas_kernels/}`
- `nxdi` — github.com/aws-neuron/neuronx-distributed-inference @ `4bcdc54`, paths `src/neuronx_distributed_inference/{modules/attention,modules/kvcache,modules/flashdecode,models/deepseek,models/gpt_oss}`
- `nki-samples` — github.com/aws-neuron/nki-samples @ `ea7dfed`, path `src/nki_samples/tutorials/`

Kelpie's contract (read before this table): `kelpie-models/kelpie_models/sdk/ops.py` — K,V members
`[pages, block, Hkv, D]` per cache group; `paged_attention(q, k, v, kv_member, query_start_loc,
seq_lens, block_table, slot_mapping, n_reqs, window, sinks) -> out[T, H*D]`; `sinks` f32[H] is
folded *inside* the softmax denominator, then dropped. `kv_member`'s layout is `[num_blocks,
block_size, 2*Hkv, D]`, k on even head-slots / v on odd (`ops.py` `write_kv`,
`kelpie-models/kelpie_models/sdk/ops.py:184-192`). TPU's existing stub
(`kelpie-models/kelpie_models/kernels/devices/tpu/_pallas.py`) already targets the exact JAX
kernel surveyed below and documents `window == 0 and sinks is None` as unwired
(`_pallas.py:93`). Neuron's stub (`kelpie_models/kernels/devices/neuron/_nki.py`) only has
`rms_norm`; no attention kernel is wired yet.

## TPU (JAX Pallas)

| op | symbol | signature (verbatim) | KV/plan layout vs kelpie's contract | dtypes | block/alignment constraints | invoked from torch via | license |
|---|---|---|---|---|---|---|---|
| paged_attention | `ragged_paged_attention` | `jax/experimental/pallas/ops/tpu/ragged_paged_attention/kernel.py:732` — `ragged_paged_attention(q, kv_pages, kv_lens, page_indices, cu_q_lens, num_seqs, *, sm_scale=1.0, sliding_window=None, soft_cap=None, mask_value=DEFAULT_MASK_VALUE, k_scale=None, v_scale=None, num_kv_pages_per_block=None, num_queries_per_block=None, vmem_limit_bytes=None)` | `kv_pages` is `[total_num_pages, page_size, 2*Hkv, D]`, k/v interleaved on the combined-head axis — matches kelpie's `[pages, block, 2*Hkv, D]` head-interleave exactly (`kernel.py:735`, `kernel.py:96-100`). Differs: (1) plan is `kv_lens`/`page_indices`/`cu_q_lens`/`num_seqs` — kelpie's `seq_lens`/`block_table`/`query_start_loc`/`n_reqs` map 1:1 by content but `n_reqs` is a Python int in kelpie's op vs a device array `num_seqs: i32[1]` here (kelpie's torch reference reads it as a host int inside `paged_attention`, `ops.py:238`, which is fine for the torch eager/compile path but is exactly the shape-vs-data problem `docs/research-jetstream-engine.md` calls out); (2) the kernel has **no `sinks` argument at all** — only `sliding_window: int` and `soft_cap: float`, no per-head additive logit. Kelpie's `sinks` (extra logit inside the softmax, dropped after) has no equivalent here; TPU's `_pallas.py:93` stub already asserts `sinks is None` for this reason. `sliding_window` semantics match kelpie's window (`q_span - sliding_window >= kv_span` masked, `kernel.py:139-140` in `ref_ragged_paged_attention`, and `kernel.py:2003-2004` in the v2 torch_xla copy) i.e. keys `[p-window+1, p]`, same as kelpie's `_one()` (`ops.py:206-208`). | any float dtype XLA/Mosaic accepts (bf16/fp32 exercised in kelpie's XLA forward); `q.dtype == kv_pages.dtype` implicitly via one `pallas_call` | `head_dim` padded to >=128 (kelpie's `_pallas.py:MIN_HEAD_DIM`, sourced from `kernel.py:570`'s l/m scratch being 128 lanes); combined kv-head count `2*Hkv` must be XLA-fully-tiled — in `{1,2,4,8}` or a multiple of 8 (`get_min_heads_per_blk`, `kernel.py` via `tuned_block_sizes.py`); q-head block must be a multiple of 8 or the whole array (Mosaic rule) — this is exactly what kelpie's `head_plan()` in `_pallas.py:130-150` searches for; `num_kv_pages_per_block <= pages_per_seq`, `num_queries_per_block <= num_q_tokens` (`kernel.py:271-283` `static_validate_inputs`) | `torch_xla/experimental/custom_kernel.py:969` `ragged_paged_attention` (torch-facing wrapper) → `trace_pallas(...)` → `torch_xla._XLAC._xla_tpu_custom_call(...)` (`custom_kernel.py:1041-1058`); torch_xla vendors its **own copy** of the kernel body at `torch_xla/experimental/pallas_kernels/ragged_paged_attention_v2.py:2188` (not jax's copy) behind `torch.library.define("xla::ragged_paged_attention", ...)` (`custom_kernel.py:1641` `ragged_paged_attention_xla` impl) — same signature, same "no sinks" gap (`ragged_paged_attention_v2.py` greps for `sliding_window` 12x, `sinks`/`attention_sink` 0x). | Apache-2.0 (both jax and torch_xla repos) |
| paged_attention (non-ragged, older) | `paged_attention` | `jax/experimental/pallas/ops/tpu/paged_attention/paged_attention_kernel.py:378` — `paged_attention(q, k_pages, v_pages, lengths, page_indices, *, mask_value=DEFAULT_MASK_VALUE, attn_logits_soft_cap=None, pages_per_compute_block, megacore_mode=None, inline_seq_dim=True)` | `k_pages`/`v_pages` are **separate** `[num_kv_heads, total_num_pages, page_size, head_dim]` arrays, not one interleaved KV member — does not match kelpie's `[pages, block, 2*Hkv, D]` layout at all; would need a KV-member split/transpose to feed it. Single query per request only (`q: [batch_size, num_q_heads, head_dim]`, no ragged/T dimension) — cannot serve chunked prefill, decode-only. | any float | `pages_per_compute_block` required (no auto-tune); `megacore_mode` in `{None, "kv_head", "batch"}` with divisibility requirements (`paged_attention_kernel.py:406-414`) | `torch_xla/experimental/custom_kernel.py:1174` `multi_queries_paged_attention` (adds a query-length dimension back in) → `pallas_kernels/multi_queries_paged_attention_kernel.py` | Apache-2.0 |
| flash / dense causal attention (prefill, no cache) | `flash_attention` | `jax/experimental/pallas/ops/tpu/flash_attention.py:140` — `flash_attention(q, k, v, ab=None, segment_ids=None, *, causal=False, sm_scale=1.0, block_sizes=None, debug=False)` | `q/k/v` are dense `[batch, heads, seq, dim]`, no block table, no paging at all — a prefill-only kernel; kelpie would use it only pre-cache (chunked prefill still needs paged output). No sinks; `segment_ids` gives ragged-batch masking, not a window. | any float | `causal` bool, `block_sizes: BlockSizes` (q/kv/kv-compute block sizes, tunable) | `torch_xla/experimental/custom_kernel.py:854` `flash_attention` wrapper (`flash_attention_xla`/`flash_attention_non_xla` impls at `custom_kernel.py:1533,1541`) | Apache-2.0 |
| flash / prefill attention, long context | `splash_attention` (`make_splash_mha`) | `jax/experimental/pallas/ops/tpu/splash_attention/splash_attention_kernel.py` (mask-sparse flash attention; block-sparse mask via `splash_attention_mask.py`) | Dense-batch layout like flash_attention, not paged; masks are precomputed sparsity patterns (`SplashAttentionMaskInfo`), not kelpie's per-request window/sinks scalars. | bf16/fp32 | mask must be expressible as `splash_attention_mask.Mask` (causal, local, or custom); block sizes configurable via `SplashAttentionConfig` | `torch_xla/experimental/splash_attention.py` — `SplashAttentionConfig` dataclass + `torch.library.custom_op` wrapper using `torch_xla.core.xla_builder.call_jax` (not `_xla_tpu_custom_call`; goes through `call_jax` bridge instead) | Apache-2.0 |
| grouped_mm_mxfp4 (MoE) | `gmm` | `jax/experimental/pallas/ops/tpu/megablox/gmm.py:314` — `gmm(lhs, rhs, group_sizes, preferred_element_type=jnp.float32, tiling=(128,128,128), group_offset=None, existing_out=None, transpose_rhs=False, interpret=False)` | `lhs [m,k] @ rhs [num_groups,k,n]` grouped by `group_sizes[num_groups] i32` — no block-table/paging concept, this is pure MoE-token-routing matmul; the "layout" mismatch with kelpie's `sdk/ops.py` `grouped_mm_mxfp4` is dtype, not shape: **gmm has no mxfp4 path** — `preferred_element_type` is an output cast, inputs are ordinary jnp dtypes (bf16/fp32/int8 quantized variants exist elsewhere in jax, but no fp4/mxfp4 block-scaled format in this kernel). | fp32/bf16 (+ separately, jax has an int8 quantized gmm variant not surveyed here) | `tiling` (m,k,n) tile triple, default 128/128/128 | `torch_xla/experimental/custom_kernel.py` defines `xla::gmm` (`gmm_xla` impl) calling this `gmm` directly | Apache-2.0 |
| rope, rms_norm, layer_norm, gelu, silu, silu_mul, clamped_swiglu, sample, chunk_gated_delta_rule, causal_conv1d, mla_attention, dsa_indexer_topk | — | not present | n/a | n/a | n/a | n/a | n/a |

Nothing in `jax/experimental/pallas/ops/tpu/` or torch_xla's `pallas_kernels/` covers rope,
rms_norm/layer_norm/gelu/silu (torch/XLA lower these directly, no Pallas kernel needed — matches
kelpie's own "aten-owned" design in `sdk/ops.py:44-47`), the sampler, gated-delta-rule /
causal-conv1d (linear attention), MLA, DSA indexer top-k, or an mxfp4 grouped matmul. MaxText and
JetStream (`docs/research-jetstream-engine.md` section 1-2) use `ragged_mha` (a `shard_map`
wrapper over the same class of kernel, not a new op) for decode and Splash for prefill — no MLA
or GDN kernel found in either; DeepSeek/Kimi-class models on TPU would need to be hand-written or
wait on jax upstream.

## Trainium (NKI)

NxDI's attention module (`neuronx_distributed_inference/modules/attention/attention_base.py:64-69`)
imports `nki` and, critically, `from nkilib.experimental.transformer.attention_block_tkg import
attention_block_tkg` — `nkilib` is a **separate, closed-source package** (ships inside the AWS
Neuron SDK, not on GitHub, not in `nki-samples`) that holds the actual flash/paged-attention
kernel bodies. `nki-samples` (the open repo) contains only tutorial kernels — `rms_norm` isn't
even among them (kelpie's own `_nki.py` rms_norm is hand-written from the nki 0.5 API directly,
not adapted from `nki-samples`); `fused_mamba/mamba_nki_kernels.py` is the closest thing to a
recurrent-SSM kernel (relevant precedent for `chunk_gated_delta_rule`/`causal_conv1d`, not a
drop-in) and `attention_fwd_performance/attention_kernels.py` is a dense (non-paged) flash
attention teaching example, not production. This means: **NxDI itself is the only public source of
"how a real Neuron paged/flash attention call looks," but the kernel it calls is not
inspectable.**

| op | symbol | signature (verbatim, from the NxDI call site, since the kernel body is closed) | KV/plan layout vs kelpie's contract | dtypes | block/alignment constraints | invoked from torch via | license |
|---|---|---|---|---|---|---|---|
| paged_attention(window, sinks) | `attention_block_tkg` (token-gen / decode path) | imported at `attention_base.py:68`; called with `active_blocks_table=active_block_table.to(torch.uint32)`, `sink=sink` (`attention_base.py:1326,1330`) where `sink = self.get_learned_sinks().data.unsqueeze(-1)` (`attention_base.py:1270`); `attn_block_tkg_nki_kernel_cascaded_attention` flag required to combine with sliding window during speculative decoding (`attention_base.py:244`) | Block-table based ("active_blocks_table"), so the *shape of the interface* matches kelpie's `block_table` — but the actual per-page/per-head layout is undocumented (closed kernel). NxDI's KV cache manager (`modules/kvcache/block_kv_cache_manager.py`) owns page allocation the way kelpie's `kv.py`/Zig scheduler does, so the two designs are structurally close, but nothing here confirms k/v interleaving or head-major/dim-major layout the way jax's kernel docstring does. | bf16/fp32 (mxfp4 compute is a separate flag, see below) | `sink` argument **unsupported on trn1**: `assert get_platform_target() != "trn1"` (`attention_base.py:714`); same guard for `sliding_window` (`attention_base.py:717`) — i.e. sinks + window are trn2/trn3-only, not universal | `nki.jit(attention_cte)` for context-encoding (prefill) built at `attention_base.py:82`; token-gen path calls `attention_block_tkg` directly (already nki-jitted inside `nkilib`) | nxdi repo itself Apache-2.0 (`LICENSE`); `nkilib` license unknown — not distributed in either surveyed repo |
| paged_attention (sinks, kelpie contract) | — | kelpie's `sinks` (extra per-head logit *inside* softmax, dropped after — `ops.py:214-219`) matches NxDI's `LearnedSink` model **semantically**: `sink.py:10-38` is a per-head learned scalar parameter (`learned_sinks_size == 1` only), concatenated onto attention scores before softmax in the non-kernel path (`attention_base.py:761-767`: `active_scores = torch.cat((active_scores, learned_sinks), dim=-1)`) — this is the closest public reference implementation of gpt-oss-style sinks anywhere in this survey (TPU has none at all). | same as above | bf16/fp32 | `learned_sinks_size` must be exactly 1 (`sink.py:22-24`) | plain torch path (no kernel) is `attention_base.py:761-767`; kernel path folds `sink` into `attention_block_tkg`'s kwargs | Apache-2.0 |
| mla_attention | — (no dedicated kernel; plain torch einsum) | `models/deepseek/modeling_deepseek.py:79` `DeepseekV3Attention` — NOT `NeuronAttentionBase`, a separate `nn.Module` (`modeling_deepseek.py:84`). Weight-absorbed MLA: `q_absorb`/`out_absorb` split from `wkv_b` (`:253`), `compressed_kv = kv_a_layernorm(kv_a_proj_with_mqa(hidden_states))` (`:260-268`), scores = `q_pe @ k_pe.T + einsum('bhqc,blc->bhql', q_nope, compressed_kv)` (`:281`), output re-absorbed via `out_absorb` (`:292`). This is dense matmul over the **latent cache directly** (`compressed_kv` cached, not expanded K/V) — closer to kelpie's `mla_attention(q, latent, kv_member, ...)` contract in spirit (latent-cache attention) than any paged kernel, but it is NOT block-table paged and NOT a Pallas/NKI kernel at all — just torch ops NxDI compiles through neuron_cc like any other model math. | bf16/fp32 | none beyond ordinary matmul tiling (compiler-scheduled) | plain `torch.einsum`/`torch.matmul`, compiled whole-graph by neuronx-cc | Apache-2.0 |
| clamped_swiglu | — (no dedicated kernel) | `models/gpt_oss/modeling_gpt_oss.py` MLP forward (`:694`) sets `gate_clamp_upper_limit=7.0`, `up_clamp_lower/upper_limit=(-7.0,7.0)` (`:682-685`), `hidden_act="sigmoid"` (`:545`) — same math as kelpie's `clamped_swiglu` doc (`ops.py:280-293`: `(up+1)*gate*sigmoid(alpha*gate)`), but expressed as plain torch clamp/sigmoid ops in the model file, not a custom op or kernel. Constants differ from kelpie's default `limit`/`alpha`(1.702) — NxDI's `gate_clamp_upper_limit`/`up_clamp_*` are configurable per-model, not hardcoded 1.702, so this is evidence for the *shape* of the op, not a reusable kernel or a canonical constant. | bf16/fp32; separately `is_mxfp4_compute` flag (`modeling_gpt_oss.py:180,757,826-835`) routes through `mx_layout_transform.py`'s `convert_hf_format_state_dict_mxfp4_compute`/`shuffle_hidden_dim` for weight-only mxfp4, applied to the whole expert MLP, not specifically the swiglu op | none (compiler-scheduled) | plain torch, compiled by neuron_cc | Apache-2.0 |
| grouped_mm_mxfp4 (MoE) | `convert_hf_format_state_dict_mxfp4_compute`, `shuffle_hidden_dim`/`unshuffle_hidden_dim` | `models/gpt_oss/mx_layout_transform.py` | This is weight preprocessing (HF's mxfp4-packed expert weights reshuffled into Neuron's preferred hidden-dim layout) around the expert MLP's ordinary grouped matmul, not a standalone `grouped_mm_mxfp4(lhs, rhs, group_sizes)` kernel like kelpie's op signature implies — no equivalent to jax's `gmm` (group-sizes-driven ragged matmul) surfaced anywhere in NxDI's public source. | mxfp4 (weight-only block-scaled), bf16 compute unless `is_mxfp4_compute` | hidden-dim shuffle required unless `is_full_model_shuffled` (`modeling_gpt_oss.py:826-835`) | compiler-scheduled scatter/gather + matmul, no explicit kernel call found | Apache-2.0 |
| rope, rms_norm, layer_norm, gelu, silu, silu_mul, sample, chunk_gated_delta_rule, causal_conv1d, dsa_indexer_topk | — | not found as dedicated kernels in the surveyed paths | n/a | n/a | n/a | n/a | n/a |

`nki-samples/src/nki_samples/tutorials/fused_mamba/mamba_nki_kernels.py` is the one open,
inspectable recurrent-SSM-shaped NKI kernel in this survey; it targets Mamba's SSM scan, not
gated-delta-rule/KDA, but is the right template to adapt for `chunk_gated_delta_rule` and
`causal_conv1d` if/when kelpie vendors a Trainium kernel for those ops (Apache-2.0,
`nki-samples` repo license header confirmed at `LICENSE.txt:1-4`, Apache License 2.0, Copyright
Amazon.com; verified by `head`).

## Compile cache: how each device asserts zero recompile at serve

**TPU / JAX persistent cache.** Kelpie's earlier XLA forward notes already measured
this directly on kelpie's own JAX arm: `jax_compilation_cache_dir=~/.cache/jax_cache`,
`min_compile_time_secs=0` — a second process loads a previously-compiled program in 0.5-1.0s
instead of 5-11s. The cache key is the HLO, which means every static field in kelpie's
`StepBatch` (bucket ladder value, dtype, weight pytree structure, kernel-set choice) is cache-key
material — a changed bucket ladder is a cold compile (`xla-forward.md` "Persistent cache"
paragraph). To assert zero recompile at serve: warm every `StepShape` in the bucket ladder once
(kelpie's own `scripts/jax_timing.py`/`jax_run50.py` already do this — 6 distinct programs cover
a real 50-request run per `xla-forward.md`'s "50 requests through the real Zig core" table), then
watch that no 7th program appears; JAX exposes this as `jax.monitoring` compile-time events, but
kelpie's own approach so far (count distinct `(T,R)` programs actually compiled) is simpler and is
already implemented in `jax_run50.py`'s per-step log (`xla-forward.md`, "compile steps (index: s)"
column).

**TPU / torch_xla persistent cache.** `torch_xla/runtime.py:250` `initialize_cache(path,
readonly=False)` must be called before any computation; it sets `XLA_PERSISTENT_CACHE_PATH` /
`XLA_PERSISTENT_CACHE_READ_ONLY` env vars (`runtime.py:263-264`) which the C++ runtime reads at
graph-compile time (`torch_xla._XLAC._xla_computation_cache_is_initialized()` guards
double-init). To assert no recompile at serve: `torch_xla.runtime.get_num_cached_compilation_graph()`
(`runtime.py:266-274`) returns the in-memory cached-graph count — call it once after warmup and
again after N serve steps; if the count is unchanged, nothing recompiled. This is the torch-path
equivalent of "CompileTime metric" the task asked for; torch_xla does not expose a separate named
`CompileTime` metric in the surveyed files — `get_num_cached_compilation_graph` is the mechanism
actually available.

**Trainium / neuron_cc cache.** Not found as an explicit API call anywhere in NxDI's surveyed
source — no `NEURON_COMPILE_CACHE_URL` reference in any of the modules/attention, modules/kvcache,
modules/flashdecode, models/deepseek, or models/gpt_oss files (grepped, zero hits). The one env
var actually set in this survey is `NEURON_CC_FLAGS` (`experimental/models/llama3/examples/run_jit.py:22`,
`os.environ["NEURON_CC_FLAGS"] = "--auto-cast=none"`), which controls compiler numerics, not
caching. `NEURON_COMPILE_CACHE_URL` is documented Neuron-SDK-wide (outside these repos) as the
neuronx-cc persistent cache location; kelpie's own XLA/Trainium forward
lineage (per `research-jetstream-engine.md` table 1: "Trainium … every decode step compiles
because seq_lens grows by 1 (… 111-141s on Trainium)") is the actual evidence that Trainium
recompiles catastrophically without a fixed-shape (paged, data-driven seq_lens) program — the
persistent cache alone does not fix that; it only avoids re-paying the *same* compile twice. To
assert zero recompile at serve on Trainium: same approach as TPU — warm every StepShape bucket
once with the cache enabled, then track that neuronx-cc is not invoked again (no direct counter
API found in NxDI; would need to shell out to check `NEURON_COMPILE_CACHE_URL`'s directory
mtimes, or watch subprocess calls to `neuron-cc`/`neuronx-cc`, since NxDI's own source exposes no
Python-level cache-hit counter analogous to `get_num_cached_compilation_graph`).

## Ranked default per op, per device

**TPU:**
1. `paged_attention` (window, sinks) → `ragged_paged_attention` (jax `kernel.py:732` /
   torch_xla `ragged_paged_attention_v2.py:2188`) for window; **no TPU kernel supports sinks** —
   kelpie's TPU stub already reflects this (`_pallas.py:93`, `assert window == 0 and sinks is
   None`, which is backwards from what's actually unwired: window IS supported by the kernel,
   only sinks is the real gap). Recommend: fix the TPU stub to pass `sliding_window` through
   (currently asserted away even though the kernel accepts it) and leave `sinks` as the one
   genuinely unsupported dimension until upstream jax adds it.
2. `rope`, `rms_norm`, `layer_norm`, `gelu`, `silu`, `silu_mul`, `sample` → no Pallas kernel
   needed or found; stay on kelpie's existing `jnp`/aten reference path
   (`jax/functional.py`, `jax/sample.py`).
3. `grouped_mm_mxfp4` → `gmm` (`megablox/gmm.py:314`) covers grouped matmul shape but not mxfp4
   dtype; no default exists for the mxfp4 dtype itself on TPU in the surveyed source.
4. `chunk_gated_delta_rule`, `causal_conv1d`, `mla_attention`, `dsa_indexer_topk` → nothing;
   would need hand-written Pallas kernels (MaxText/JetStream also have none per
   `research-jetstream-engine.md`).

**Trainium:**
1. `paged_attention` (window, sinks) → `attention_block_tkg` via NxDI's `NeuronAttentionBase`
   (`attention_base.py:64-69,1326-1330`), the only surveyed kernel that supports BOTH window and
   sinks — but body is closed-source (`nkilib`), and both are gated off on trn1
   (`attention_base.py:714,717`).
2. `rms_norm` → kelpie's existing hand-written `_nki.py` kernel (already matches this survey's
   finding that `nki-samples` has no rms_norm to adapt from).
3. `mla_attention` → no kernel; NxDI's `DeepseekV3Attention` plain-torch weight-absorbed pattern
   (`modeling_deepseek.py:79-313`) is the reference shape to copy into kelpie's torch reference
   body, not a kernel to bind.
4. `clamped_swiglu` → no kernel; NxDI's gpt_oss MLP clamp/sigmoid (`modeling_gpt_oss.py:682-685,545`)
   confirms kelpie's documented math but supplies no fused kernel.
5. `grouped_mm_mxfp4` → no kernel; only weight-layout shuffling (`mx_layout_transform.py`) found.
6. `rope`, `layer_norm`, `gelu`, `silu`, `silu_mul`, `sample`, `chunk_gated_delta_rule`,
   `causal_conv1d`, `dsa_indexer_topk` → nothing found; `fused_mamba/mamba_nki_kernels.py` is the
   nearest open template for the recurrent ops.

## Ops nothing covers (either device)

`chunk_gated_delta_rule`, `causal_conv1d`, `dsa_indexer_topk`, and `compressed_kv_attention` have
no public kernel on TPU or Trainium anywhere in this survey. `grouped_mm_mxfp4` has a shape match
on TPU (`gmm`, no mxfp4 dtype) and a weight-layout-only match on Trainium (no matmul kernel
itself). `sample` has no kernel on either device (both kelpie's own `jax/sample.py` reference and
plain-torch on Trainium are what's actually used today, per `xla-forward.md`'s package table).
