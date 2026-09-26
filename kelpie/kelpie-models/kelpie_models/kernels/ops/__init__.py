"""Every kelpie op, one file each. Importing this package declares them all.

The registry is DERIVED, not hand-kept: this module imports every `ops/*.py`, and each file's
`@op` puts itself in `kernels.op.REGISTRY`. A conventions check (`scripts/test`) asserts every
file here is imported, every op has a fake, sample args and a backward, and every adapter names
a declared backend -- so a new op file is the only edit adding an op takes.

Importing this registers NO device kernel. Selection happens in `kernels.op.bind`, called by
`sdk/run.py:build`.
"""

from __future__ import annotations

from kelpie_models.kernels.ops import (
    causal_conv1d,
    chunk_gated_delta_rule,
    clamped_swiglu,
    compressed_kv_attention,
    dsa_indexer_topk,
    gelu,
    layer_norm,
    mla_attention,
    moe,
    paged_attention,
    rms_norm,
    rope,
    sample,
    silu,
    silu_mul,
)

MODULES = (
    causal_conv1d,
    chunk_gated_delta_rule,
    clamped_swiglu,
    compressed_kv_attention,
    dsa_indexer_topk,
    gelu,
    layer_norm,
    mla_attention,
    moe,
    paged_attention,
    rms_norm,
    rope,
    sample,
    silu,
    silu_mul,
)

# The op objects, re-exported so a caller writes `kernels.ops.rms_norm` and gets the OP, not
# the module: `serve(gpt2, kernels={ops.rms_norm: my_rms_norm})`.
causal_conv1d = causal_conv1d.causal_conv1d
chunk_gated_delta_rule = chunk_gated_delta_rule.chunk_gated_delta_rule
clamped_swiglu = clamped_swiglu.clamped_swiglu
compressed_kv_attention = compressed_kv_attention.compressed_kv_attention
dsa_indexer_topk = dsa_indexer_topk.dsa_indexer_topk
gelu = gelu.gelu
layer_norm = layer_norm.layer_norm
mla_attention = mla_attention.mla_attention
moe = moe.moe
no_sinks = paged_attention.no_sinks
paged_attention = paged_attention.paged_attention
rms_norm = rms_norm.rms_norm
rope = rope.rope
sample = sample.sample
silu = silu.silu
silu_mul = silu_mul.silu_mul
