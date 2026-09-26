# References

The engines and writing kelpie's decisions are checked against. Roadmap and decisions cite
"reference engines" / "Reference points"; this file is that list. Add the alternative rejected
when a reference decides something (docs/decisions.md).

## Engines

- vLLM v1 — scheduler shape, async scheduling + spec decode (reserve `1+K` placeholders), rejection
  sampler as a separate stage. `docs/spec-decode-survey.md`.
- SGLang — radix prefix cache (deferred), EAGLE tree drafts, `FutureMap` across the async boundary,
  grammar mask applied before accept/reject. `sglang-upstream` checkout.
- nano-vllm, mini-sglang — the "small engine" bar kelpie is measured against (complaints.md #2).
  Neither has spec decode.
- TokenSpeed — explicit-batch attention, chain-only spec decode (tree rejected at config time).
- llama.cpp — the local / single-GPU reference: separate draft context, chain-only, CPU-side
  rejection loop, no grammar awareness in the speculative path. The simplicity baseline; what
  "no overlap scheduling" costs.
- resin — LoC comparison (roadmap "Size, honestly").
- neuron-engine, sglang-jax — symmetric SPMD lesson; Pallas kernels to lift (M7).
- TigerBeetle — Zig pin, TigerStyle, trace DSL in `testing/table.zig`, VOPR (single implementation
  + deterministic simulation; kelpie's two-implementation differential is the adaptation).
- popcorn — validation record key, AST fingerprint, third state (kernels/record.py).
- seqax shardlib — sharding notation (complaints.md #4).

## Writing

- Thinking Machines, "Defeating Nondeterminism in LLM Inference"
  https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/ — kernels are
  batch-variant (reduction order changes with batch size); the fix is batch-invariant kernels.
  Kelpie's sampler-side twin: the sample key must be per-request `(seed, n_generated)`, not a
  step counter, or the noise is batch-variant even when the logits are not.
- ~/research/docs/code_style — CODING_STANDARDS.md (rulings), tiger_style, casey_{semantic_compression,
  granularity,worst_api}, sean_goedecke_system_design. docs/CODING_STANDARDS.md is kelpie's distillation.
