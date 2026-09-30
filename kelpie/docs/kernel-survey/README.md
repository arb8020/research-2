# Kernel survey (2026-09-10)

Which existing kernels cover kelpie's ops, per source. One file per source cluster; each is a table
op x (library, symbol, signature, KV/plan layout it expects, dtypes, constraints, license, how it was
verified). Feeds docs/brief-adapters.md once chore/kernels-build merges.

Ops: rms_norm layer_norm gelu rope silu_mul clamped_swiglu sample write_kv paged_attention(window,sinks)
chunk_gated_delta_rule causal_conv1d mla_attention dsa_indexer_topk compressed_kv_attention grouped_mm_mxfp4

Contract for paged_attention: K,V members [pages, block, Hkv, D]; plan = block_table[R,P], seq_lens,
query_start_loc, slot_mapping, kinds, row_request (kelpie_models/sdk/ops.py, docs/brief-kernels-build-tiers.md E).
