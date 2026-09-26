# Brief: TPU/Trainium derisk — gpt2 all-reference through build -> cache -> serve

Date: 2026-09-10. Launch AFTER `chore/kernels-build` merges (needs `build(cache=)`, the manifest, and the
on-device reference `paged_attention` from part E / debt 2). One sonnet executor per device, worktrees
`xla-derisk-tpu` (v6e) and a Trainium one. "You are a subagent. Don't run memo." STOP on ambiguity.

Goal: prove the seam on XLA devices with zero new kernels. Pass = all four:
1. `kelpie build --model gpt2 --device {tpu|neuron} --cache C --check` writes a manifest with every called op
   on `reference`, verdict pass (fp32 vs fp64 truth).
2. `kelpie serve --cache C` answers `scripts/check_serve.py gpt2 echo` rows identically to CPU.
3. Zero recompile at serve: TPU `torch_xla.runtime.get_num_cached_compilation_graph()` unchanged between the
   first and last request across every bucket shape in the ladder; Trainium: the neuron compile cache dir
   gains no files during serve (record the listing before/after). A recompile is a FAIL with the shape named.
4. The manifest records the XLA persistent cache subdir (`C/xla` or `C/neuron`) and serve fails closed when
   it is missing, same as the Triton path.
Not in scope: Pallas/NKI adapters (docs/brief-adapters.md), qwen3, performance numbers beyond a tok/s line.
Known blockers to report rather than fix: torch_xla version on the host, `torchax` vs `torch_xla` choice
(research-jetstream-engine.md), any host-side tensor read in the step loop.
Report: the four results verbatim, recompile counts per shape, wall time, STOPs, papercuts.
