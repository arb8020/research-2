
2026-09-02T06:35:18.000Z - unknown - Chiraag Balu

kelpie mm: transformers 5.x Idefics3 processor hard-requires torchvision (even the PIL backend fails to import) -> torchvision added to dev groups of kelpie-models and kelpie-http just for the oracle.

2026-09-02T06:35:18.000Z - unknown - Chiraag Balu

kelpie mm: HF Idefics3 preprocessing upsizes every image to longest_edge=2048 -> 13-17 tiles = ~900-1100 prompt tokens for any image; preprocess() takes longest_edge= so tests use 512/1024, but the server uses the checkpoint default.

2026-09-02T06:35:18.000Z - unknown - Chiraag Balu

kelpie mm: mutating a shared HF model fixture .double()/.float() for the fp64 truth perturbed a later generate() in the same module (11 vs 12 tokens); use copy.deepcopy for the fp64 oracle.
2026-09-02T07:12:26.000Z - unknown - Chiraag Balu

groups: HF gpt-oss built on the meta device keeps rotary inv_freq on meta after load_state_dict(assign=True); must rebuild rotary_emb (tests/oracle/synthetic.py hf_gpt_oss_from_pytree)

2026-09-02T07:12:27.000Z - unknown - Chiraag Balu

groups: MoE reference routing does a host sync (bincount().tolist()) to slice experts; a kernel backend needs device offsets for grouped_mm (torch._grouped_mm takes offs)

2026-09-02T07:49:58.000Z - unknown - Chiraag Balu

kelpie jax: ragged_paged_attention (jax 0.11.1) rejects head_dim<128 (assert kernel.py:570), bf16 with 12 kv heads (tiling), and fp32 MHA >4 heads (4-q-head block vs Mosaic %8 rule); gpt2 runs only via zero-padded heads (2-2.7x KV bytes).

2026-09-02T07:49:58.000Z - unknown - Chiraag Balu

kelpie jax: pkill -f on the TPU box matched my own gcloud ssh command line and killed the session; use pkill -f '[p]attern'. ziglang.org tarball is now zig-x86_64-linux-0.14.1.tar.xz (old name 404s). No pip in the uv venv; uv itself was not on PATH (~/.local/bin/uv).

2026-09-02T17:24:33.000Z - unknown - Chiraag Balu

shardlib: Mesh.size/index only resolve roles (closed ROLES tuple); a physical axis name silently returns size 1 / index 0 instead of asserting. The design-rules 'bottom rung' (name a physical mesh axis directly, seqax point 3) is unreachable. Fix in mesh.py: role-if-bound -> axis-if-exists -> assert.

2026-09-02T17:39:50.000Z - unknown - Chiraag Balu

spec x grammar coupling: xgrammar Matcher.rollback is bounded by max_rollback_tokens; must be >= spec-decode draft depth K. Not in either design doc.

2026-09-02T17:39:50.000Z - unknown - Chiraag Balu

reference ops.sample: softmax+multinomial runs even for greedy rows, so an all-(-inf) logit_mask row (grammar dead end) crashes. Needs an explicit test + a defined behaviour (error the request?). grammar-design §6 silent.

2026-09-02T17:43:10.000Z - unknown - Chiraag Balu

spike/graphs: reference cuda attention has a host read bool((blocks>0).all()); 'no host reads in the forward' is tested for model files (test_seam) but not for ops. Extend the gate to backends/*.py + ops.py.

2026-09-02T17:43:10.000Z - unknown - Chiraag Balu

spike/graphs: reference ops.sample is not capture-safe (D2H reads, host-seeded Generator, unconditional multinomial) — the design-rules:187 judgement call. Fix: device-side RNG from the sample_key leaf; greedy rows must not touch multinomial (also fixes the all-(-inf) mask crash).

2026-09-02T17:47:28.000Z - unknown - Chiraag Balu

spike/specref: Zig commit will need the OFFERED n_drafts on the persistent request (request.zig), read before commit overwrites with next_drafts; Entry.n_work=1 is ambiguous (plain decode vs budget-degraded drafts).

2026-09-02T17:47:28.000Z - unknown - Chiraag Balu

trace DSL: 'accepted=' means len(tokens) in kelpie-core/traces/entry_kind.txt but n_accepted in spec-decode-design.md's sketch. Pick one before spec traces are shared with the Zig harness.

2026-09-02T17:47:28.000Z - unknown - Chiraag Balu

5/28 kelpie-core traces (window-group ones) fail in the Python reference scheduler on main at baseline — pre-existing, found by spike/specref.

2026-09-02T19:15:32.000Z - unknown - Chiraag Balu

prefix.zig: windowed-cacheable prefix hit is a TODO returning 0 — window groups never get prefix hits on main. The reference now mirrors that deliberately (fix/refsched-traces). Real gap, not a test gap.

2026-09-02T19:25:24.000Z - unknown - Chiraag Balu

tests/oracle/synthetic.py: 3 pre-existing ruff F821 (undefined deepseek_v4) on main — repo-wide ruff is not clean; nobody runs it repo-wide.

2026-09-02T19:27:30.000Z - unknown - Chiraag Balu

spike/paged-attn review: sliding window without sinks NaNs when seq_len - window >= BLOCK_N (m init -inf); gpt-oss safe only because sinks seed the running max; single windowed test (79,64) could not catch it. Fix in flight.

2026-09-02T19:27:48.000Z - unknown - Chiraag Balu

Box coverage: everything on main touching CUDA/Neuron was re-ported to v1 this morning on a Mac and never re-run on CUDA/Trainium (the CUDA and Trainium verify branches in flight). The v1 contract refactor itself was 'TPU green, CUDA pending' — CUDA never ran it. launch-shape's JAX bridge changes need a v6e run before merge.

2026-09-02T19:33:18.000Z - unknown - Chiraag Balu

500_stats contract golden is deterministically stale (recorded with zero counters; live server carries traffic from prior cases). Fails on main. Needs KELPIE_CONTRACT_RECORD=1 re-record — a contract decision.

2026-09-02T19:38:51.000Z - unknown - Chiraag Balu

cuda_triton paged decode: at R=1, seq 2048 the kernel (0.80ms) is slower than the reference (0.42ms) — one program per kv-head walks 128 tiles serially. Needs split-K / flash-decoding for single-stream long context. First perf item for M1.

2026-09-02T19:47:13.000Z - unknown - Chiraag Balu

trainium backend: SWA/sinks asserted off (trainium.py:59) — gpt-oss blocked on Neuron

2026-09-02T19:47:13.000Z - unknown - Chiraag Balu

trainium backend: no HBM budgeting (num_blocks hardcoded in jax_timing.py); no //16*16 block-count rounding (off-by-one -> recompile, neuron-engine lesson)

2026-09-02T19:47:14.000Z - unknown - Chiraag Balu

trainium: single NeuronCore only; jax-neuronx multi-core may force process-per-core, in tension with the single-process rule — untested

2026-09-02T19:47:15.000Z - unknown - Chiraag Balu

jax Ops has no grouped_mm; torch has it. MoE rungs on TPU/Neuron have no seam entry

2026-09-02T19:47:15.000Z - unknown - Chiraag Balu

design-rules 'SPMD runner: sampling on rank 0' is a latent PP bug — should be 'the rank that owns the logits'

2026-09-02T19:55:33.000Z - unknown - Chiraag Balu

v1 port of wave2/parallel is broken on GPU (verify/gpu): TP2 rank-0 logits (100002,) = half vocab — lm_head all_gather lost; Zig-core TP2 gen: sample gets k1=2. EP2/world1/corpus pass. fix/parallel-v1 in flight.

2026-09-02T19:55:33.000Z - unknown - Chiraag Balu

Qwen3 chat renderer rejects the cached tokenizer (missing <|endoftext|>); benchmarks needed --chat-format default. Renderer should degrade or the tokenizer fact should carry the eos.

2026-09-02T20:09:29.000Z - unknown - Chiraag Balu

shardlib: a 2-token spec ('R V/tp') was applied to a rank-3 tensor and all_gather silently gathered dim 1 — the TP2 port bug. spec.check()/collectives must assert tensor.ndim == number of spec tokens (crash, don't guess).

2026-09-02T20:25:24.000Z - unknown - Chiraag Balu

examples/main.py cannot select a JAX backend (verify/tpu): build()/ops_for are torch-shaped; the JAX bridge is reached only via cli's KELPIE_BACKEND path. The composition root should take the backend module explicitly on both paths.

2026-09-02T20:46:37.000Z - unknown - Chiraag Balu

Engine.__del__ raises AttributeError when the _lib load fails before _ptr is set (found by chore/test-everything; present on main). Guard with getattr.
2026-09-02T20:53:07.000Z - unknown - Chiraag Balu

Trainium perf: 7.5 tok/s live, 1024-tok prefill 2.2-2.7 s, cold compile 130-280 s per bucket. Plain-jnp attention; NKI attention + compile-cache warmup are the M6 items.

2026-09-02T21:20:33.000Z - unknown - Chiraag Balu

M2: tier-2 drain=true swap has no 'swap applied' acknowledgement from Zig, so Python cannot safely reclaim the old ModelState. Needs an epoch (StepEvent.launch_epoch or get_config) — in review.

2026-09-02T21:20:33.000Z - unknown - Chiraag Balu

M2 proof: Python-stepper baseline 330 ms/step contradicts M1's 16.8 ms — harness stages an eager prefill per wave; tok/s columns meaningless until prefill captures. Review re-measuring.

2026-09-02T21:28:48.000Z - unknown - Chiraag Balu

cuda_triton.sample: 'assert k1 == 1' / 'draft_probs is None' are Python-level — vanish under -O and are invisible inside a captured graph. Spec decode must enforce K where it cannot be optimized out (StepShape at capture).

2026-09-02T21:28:48.000Z - unknown - Chiraag Balu

sample_kernel's Philox body duplicates ops.philox_uniform's constants with no cross-reference comment; the two copies can drift silently. Bitwise test guards it today.

2026-09-02T22:02:00.000Z - unknown - Chiraag Balu

M2 native path skips cuda_triton.plan's seq_len <= capacity assert; no Zig equivalent — a ladder/max_seq_len mismatch corrupts silently. Home: scheduler.zig planUnlocked.
2026-09-02T21:18:52.000Z - unknown - Chiraag Balu

M2: tracked-file tar sync emits hundreds of LIBARCHIVE.xattr.com.apple.provenance warnings despite COPYFILE_DISABLE=1, obscuring remote command output.

2026-09-02T21:18:52.000Z - unknown - Chiraag Balu

M2: kelpie_swap_launch has no applied-swap acknowledgement, so Python cannot know when an old CapturedModel/ModelState is safe to reclaim after drain=true.

2026-09-02T21:18:52.000Z - unknown - Chiraag Balu

M2: production policy asks Zig-native serving while M1 CUDA graphs are decode-only; new prefill cannot be handled by a native callback without a separate ownership/state-machine design.

2026-09-02T22:11:35.000Z - unknown - Chiraag Balu

docs/complaints.md, day2-intent.md, plugin-feasibility.md sat UNTRACKED on main all day (my status checks filtered '??'). Commit them after the prefill merge lands; scripts/test could assert no untracked docs/*.md.

2026-09-02T22:11:35.000Z - unknown - Chiraag Balu

No test runs the corpus/goldens through cuda_triton — they hardcode reference_ops()/ops_for(). That is how the SWA null-block BLOCKER reached review. Next task: parametrize the oracle tests over kernel sets.

2026-09-02T22:38:24.000Z - unknown - Chiraag Balu

kelpie-py suite: 52 collection errors on Linux ('illegal environment variable name' from the uv run env) — passes on Mac.

2026-09-02T23:44:41.000Z - unknown - Chiraag Balu

PROCESS: two agents were assigned the same worktree (M3 reviewer resumed after its completion notice; closer launched into the same tree). Rule: one owner per worktree; a follow-up task on a reviewed branch must wait for the reviewer to confirm it is done, or get its own branch.

2026-09-03T00:45:36.000Z - unknown - Chiraag Balu

scripts/test on Linux needs ZIG=$(which zig): three kelpie-http tests hardcode a macOS zig path (pre-existing on main).
2026-09-03T00:47:12.000Z - unknown - Chiraag Balu

8 test modules defaulted ZIG to a hardcoded ~/.zig/zig-aarch64-macos-0.14.1 path -> 44 kelpie-py + 12 kelpie-http errors on ANY Linux host, green on Mac. Most of the '52 collection errors on Linux' papercut was this, not uv env. Fixed to scripts/zig.

2026-09-03T00:47:13.000Z - unknown - Chiraag Balu

On CUDA (B200), kelpie-http has 1 real-checkpoint failure (test_config_post_applies_to_the_next_completion) and kelpie-models fails under KELPIE_REAL_CKPT=1; both pre-existing code issues, not infra. Unverified by me.
2026-09-02T22:57:57.000Z - unknown - Chiraag Balu

M3 review: kelpie-models pytest '-m cuda' selects nothing (no cuda marker is registered; gating is via skipif), so a reviewer asking for just the GPU tests silently runs zero.

2026-09-02T22:57:57.000Z - unknown - Chiraag Balu

M3 review: kelpie-py tests hardcode ZIG=~/.zig/zig-aarch64-macos-0.14.1/zig; on Linux without ZIG= set explicitly this yields 52 collection errors rather than a clear message.

2026-09-02T23:10:29.000Z - unknown - Chiraag Balu

M3 review: the archived `prove_capture.py` fails on CUDA (B200) with 'server did not become healthy' (wait_until_ready, ~286s) — HTTP server will not boot there. Unrelated to M3 content, but leaves the serving path unproven on GPU, same gap as the JSON e2e.

2026-09-03T01:44:18.000Z - unknown - Chiraag Balu

scripts/test once reported FAIL kelpie-models with no FAILED/ERROR line in the output (passed on rerun). Exit code and printed detail can disagree — harness gap.

2026-09-03T01:56:46.000Z - unknown - Chiraag Balu

kernels/triton/{attention,norm,sample}.py are 28/5/5-line re-export shims over one 554-line _impl.py — the split is cosmetic. Real refactor for next session (per-op modules, per the overlay design).

2026-09-03T01:56:46.000Z - unknown - Chiraag Balu

tests/matrix.py:113 nested conditional re-encodes the kernel-set -> device map that KERNEL_SETS already holds.

2026-09-03T17:39:06.000Z - unknown - Chiraag Balu

compress-step: ruff format --check was not clean at the base commit (17 kelpie-models, 1 kelpie-py, 3 kelpie-http files); formatted only touched files, remaining debt listed in the report

2026-09-03T17:39:06.000Z - unknown - Chiraag Balu

compress-step: the background-bash hook forces tmux for long test runs; scripts/test takes ~9 min on the Mac, so intermediate feedback loops are slow

2026-09-03T18:22:30.000Z - unknown - Chiraag Balu

Subagents (Fable, compress-step-impl and compress-step-review) stopped twice each while 'waiting on a Monitor' for a long test run; the monitor never woke them and the parent had to poke them. The remote run had actually finished (ALL PASS, rc 0). Long-running remote commands should be run foreground with a 600s timeout + bounded poll loop, or the brief should say so.

2026-09-03T19:43:32.000Z - unknown - Chiraag Balu

A subagent (mimir audit port) built mimir/audit.py + cli wiring in the SHARED mimir main tree and never committed; a later agent branching off main found no audit and stopped. Briefs must say: work in a worktree, commit on a branch, report the sha.

2026-09-03T20:02:25.000Z - unknown - Chiraag Balu

two prometheus renderers: kelpie.metrics.render_prometheus (GAUGE_HELP, scheduler gauges) and kelpie_http.server.model_stats (hand-written TYPE lines, runner stats); unify in the test/metrics pass

2026-09-03T20:29:22.000Z - unknown - Chiraag Balu

native loop: no StepEvent production (KelpieCore.step is the only publisher) and no poll wakeup (_poll_waiters fire only from step()); metrics zero and 50 ms poll latency under NativeTicker. Needs a Zig-side step-done signal + Python event pump; design pass F part 2.

2026-09-03T20:53:23.000Z - unknown - Chiraag Balu

grammar under the Zig loop: prepare_logit_mask is only called from KelpieCore.step; NativeTicker never calls it, so response_format was silently dropped. Refused with 400 for now; F part 2 needs a mask rung the loop can call (native matcher or a GIL callback between launch_forward and launch_sample).

2026-09-06T23:17:06.000Z - unknown - Chiraag Balu

seam spike: per-package venv lives only in the main checkout; worktree tests need PYTHONPATH=<worktree>/kelpie-models:<worktree>/kelpie-py and an import-path sanity check or you silently test main

2026-09-06T23:17:06.000Z - unknown - Chiraag Balu

seam spike: background bash is blocked by a hook; long pytest runs go through tmux + log files, and sequential runs in one tmux command get invalidated by edits made mid-run (baseline had to be re-run from the main checkout)

2026-09-06T23:17:06.000Z - unknown - Chiraag Balu

seam spike: tests/oracle/synthetic.py and tests/oracle/test_synthetic.py imported every model at module level, so one unported model broke collection of test_shard.py and the whole oracle package; made those imports lazy

2026-09-06T23:17:06.000Z - unknown - Chiraag Balu

seam spike: tests/test_runner.py::test_start_loop_eager_turns_model_fn_exceptions_into_a_launch_error fails on main too (_NullLoopEngine has no timing_start); pre-existing, not the seam

2026-09-07T01:00:27.000Z - unknown - Chiraag Balu

kernel-seam pass 2: ruff format wraps any 100+ col rung in examples/main.py into a 3-line paren block, fighting the one-rung-per-line + trailing-comment style; comments moved above the rung

2026-09-07T01:00:27.000Z - unknown - Chiraag Balu

kernel-seam pass 2: build(kernels=) takes a bare (attn_cls, sample, math) 3-tuple because kernels/__init__.py must be data-only; a NamedTuple would be KernelSet reborn -- flag if the tuple reads badly at call sites

2026-09-07T01:00:27.000Z - unknown - Chiraag Balu

kernel-seam pass 2: run_step is now 10 positional params (attn, sample, kernels added); the price of rung 2 being functions over values rather than taking ModelState

2026-09-07T22:53:57.000Z - unknown - Chiraag Balu

kernel-catalog: 'kelpie serve' on a Mac refuses every non-cuda composition (check_can_serve) AFTER the kernel set resolves, so demo 1/2 of the brief cannot be shown through the CLI here; shown through build() (test_bridge metal@mps with log_cli) and examples/main.py instead

2026-09-07T22:53:57.000Z - unknown - Chiraag Balu

kernel-catalog: zsh eats 'echo ======' (= prefix) and word-splits $files in for loops; every multi-command bash call needs bash-safe separators and while-read

2026-09-07T22:53:57.000Z - unknown - Chiraag Balu

kernel-catalog: the brief's '[kernels] table in the TOML config' has no TOML config to land in (no --config, no tomllib anywhere in kelpie-http/kelpie-py); left as a fork in the report

2026-09-07T23:21:51.000Z - unknown - Chiraag Balu

catalog-pass5: the worktree has no kelpie-core/zig-out or xgrammar_shim/build (zig build lib fails without the shim); symlinked both to the main checkout's (same core at c97549b) so runtime/http suites can run in the worktree

2026-09-07T23:22:34.000Z - unknown - Chiraag Balu

catalog-pass5: correction -- no symlinks needed; KELPIE_LIB / KELPIE_XGRAMMAR_LIB env vars point at the main checkout's dylibs (pass 4's recipe, section 8.6); the symlinks were removed before commit

2026-09-08T20:39:59.000Z - unknown - Chiraag Balu

taps: kelpie serve --dev is refused by check_can_serve on a Mac before build(), so the brief's 'serve starts and the build log names the taps' can only be shown by calling the CLI's parse_taps/engine_config/build from a script (r7_build_log.log) -- same wall as passes 5-6

2026-09-08T20:40:02.000Z - unknown - Chiraag Balu

taps: timing while the tmux suites run is noise (a 30% 'speedup' from adding two taps on cpu); the delta measurement has to wait for an idle box, which serialises the pass

2026-09-08T20:40:02.000Z - unknown - Chiraag Balu

taps: oracle.synthetic tiny models are 2 (gpt2) / 3 (gpt_oss) layers deep; the brief's taps at layers 1 and 3 need 4, so test_taps re-rolls both at N_LAYERS=4 in the file instead of reusing the fixtures

2026-09-08T20:40:02.000Z - unknown - Chiraag Balu

taps: ModelRunner.shapes() asserted graph_cls IS Graph, which shut out any test double; relaxed to issubclass so a Mac can exercise the graph table (EagerGraph)

2026-09-08T20:40:02.000Z - unknown - Chiraag Balu

taps: the first breadcrumb went to the MAIN checkout's BREADCRUMBS.md (mimir writes to cwd, I ran it from the main dir); later ones are in the worktree

2026-09-08T21:04:15.000Z - unknown - Chiraag Balu

Mac crashed twice while two agents ran full suites in parallel (gpt_oss MPS HF parity + 4-proc gloo + http each). Load avg 65. Local runs need a concurrency cap or move to boxes.

2026-09-09T04:51:24.000Z - unknown - Chiraag Balu

kernel-seam: uncommitted BREADCRUMBS.md in the worktree blocks 'git merge' (main-stable touches it); parked it as a patch to dry-run the merge, reapplied after abort

2026-09-09T04:51:24.000Z - unknown - Chiraag Balu

kernel-seam: smolvlm.py imports kelpie_models.ops (absent on the seam) so test_launch_shape has 3 pre-existing failures (aliases, model_facts, adapter_fact) and test_smolvlm/test_deepseek_*/test_qwen3_next fail at collection on 'from matrix import ops_for_kernel_set'; unported skip now hides the latter three, smolvlm still red

2026-09-09T04:51:24.000Z - unknown - Chiraag Balu

kelpie-models: bare 'uv run' rewrites uv.lock (-216 lines, xgrammar drop); use 'uv run --frozen' locally. main-stable carries the same lock refresh (28e4042)
2026-09-09T05:07:14.000Z - unknown - Chiraag Balu

port-qwen3: prove_capture.py's eager half cannot run: kelpie serve --dev is refused by check_can_serve ('serving requires a captured runner'); only the cuda_graph half produced a number. test_capture::test_captured_decode_matches_eager_through_zig still calls the deleted KelpieCore.step() (every model)

2026-09-09T05:07:14.000Z - unknown - Chiraag Balu

port-qwen3: test_cuda_triton_attention's host-read lint exempted a function named plan (renamed prepare_workspace in seam pass 3) and had never run on CUDA since; nobody saw it until this CUDA run

2026-09-09T05:07:14.000Z - unknown - Chiraag Balu

port-qwen3: uv run --frozen in the worktree built a fresh kelpie-models .venv (49 packages) since venvs live per tree now; fine, but the first smoke run pays it
2026-09-09T05:10:00.000Z - unknown - Chiraag Balu

port-smolvlm: test_launch_shape test_aliases / test_model_facts stay red on this branch because kelpie_models.qwen3 still imports kelpie_models.ops (the parallel qwen3 port owns that); the 3rd red test (adapter_fact) is green now

2026-09-09T05:11:12.000Z - unknown - Chiraag Balu

test_seam.py hand-lists ported models in 4 places (import, 3 loops); both ports conflicted there. One PORTED tuple, or derive from kelpie_models/*.py glob
2026-09-08T22:15:44.000Z - unknown - Chiraag Balu

fresh worktree: zig build test fails until kelpie-core/xgrammar_shim/build/{libxgrammar,libxgrammar_shim}.dylib exist; copied them from the main tree's build dir. scripts/build_xgrammar.sh per worktree is a CMake build; a shared build location (or scripts/zig auto-copy) would save the trip.

2026-09-08T22:15:44.000Z - unknown - Chiraag Balu

kelpie-py 'uv run pytest -q' hung silently at 0% CPU for 5+ min on the first run in a fresh worktree (before any test output); killed and re-ran and it finished in <1 s. Not reproduced; suspect uv lock/venv creation contention with a parallel uv invocation.
2026-09-04T11:17:55.000Z - Claude Opus 5 - Chiraag Balu

Per-package venvs (kelpie-models/.venv etc) live only in the main checkout, never in worktrees, so every command in a fresh worktree needs an absolute path back to the main tree's venv plus PYTHONPATH. ruff/pytest are not on PATH. A worktree bootstrap step (or uv sync on create) would pay for itself given 'always worktrees'.

2026-09-04T11:17:55.000Z - Claude Opus 5 - Chiraag Balu

~12 stale worktrees under .claude/worktrees/ and worktrees/ poison every naive 'grep -r' in kelpie: searching parse_knobs returns 30+ hits of which 2 are real. Any dead-code tooling needs them excluded by default. Related: __pycache__ outlives deleted sources -- that is how the empty kelpie_models/backends/ stayed on disk.

2026-09-06T22:49:24.000Z - unknown - Chiraag Balu

kelpie serve: EngineConfig.vocab_words defaults 0 and cli.py never sets it, so every response_format request 500s (attach_grammar rc=-1). prove_json_schema catches it on CUDA but is absent from scripts/test's PROOFS registry, so a green scripts/test hides it.

2026-09-08T19:58:43.000Z - unknown - Chiraag Balu

Disk at 100% (405 MiB free on /System/Volumes/Data): subagent greps hit 'no space left on device'. Needs freeing before more test runs / obol renders.

2026-09-09T04:53:22.000Z - unknown - Chiraag Balu

scripts/test: a failing pytest section shows only the tail of the output (last traceback + -rs skip summary), so the NAMES of the failed tests are not in the log when >1 fails; had to read the remote tree's .pytest_cache/v/cache/lastfailed. Adding -rf (or -ra) to the pytest args would put 'FAILED <nodeid>' lines in the summary.

2026-09-09T04:53:22.000Z - unknown - Chiraag Balu

prove_json_schema: server-side log lives in a TemporaryDirectory and is discarded on failure, so a bad response (1 SSE chunk, no content) gave no server-side clue; the proof now prints finish_reason, but tailing the server log into the failure like wait_until_ready does would be better.

2026-09-09T05:32:22.000Z - unknown - Chiraag Balu

fix-c-launch: remote run logs bury a run's failing test names; the Monitor tool + tmux pipe-pane works, but background bash is hook-blocked and foreground sleep chains are blocked, so every remote wait is a tmux+until dance.

2026-09-09T05:32:22.000Z - unknown - Chiraag Balu

fix-c-launch: the C launch table had no test asserting its output until 1644aa7 (test_capture drove KelpieCore.step, the Python rung); a captured-rung correctness check should be part of every proof that claims native launches.
2026-09-09T05:26:15.000Z - unknown - Chiraag Balu

fresh worktree on the Mac: zig build lib fails (no libxgrammar_shim in the tree) -- kelpie-core/scripts/build_xgrammar.sh is per-tree; scripts/test --fast reports kelpie-core FAIL locally until it is built

2026-09-09T05:26:15.000Z - unknown - Chiraag Balu

scripts/test SUMMARY undercounted skips (counted pytest's folded SKIPPED [n] lines as 1): 54 -> 22, 78 -> 13 in the 2026-09-09 CUDA sweep log; fixed in chore/tests

2026-09-09T17:29:33.000Z - unknown - Chiraag Balu

the tree at dd42b55 still imports deleted modules: kelpie_models.kernels.overlay (jax/bridge.py, jax/kernels/{tpu,trainium}.py -> tests/test_jax_{corpus,engine}.py fail to COLLECT, which fails every kelpie-models real-ckpt/rest section even with -k) and kelpie_models.ops (kelpie-py tests/test_grammar.py, scripts/prove_{paged_attn,sample,triton_ops}.py). Invisible on a remote copy of main whose sync never deleted the old files.

2026-09-09T17:29:33.000Z - unknown - Chiraag Balu

scripts/test -k cannot select past a collection error: one broken test module fails the whole section (0 failed, 1 error, everything deselected). --continue-on-collection-errors or per-file selection would let a -k run mean something.
2026-09-09T17:19:10.000Z - unknown - Chiraag Balu

scripts/test SUMMARY prints '2 need needs hf:...' -- the formatter prefixes 'need' to reason strings that already start with 'needs' (every needs_* mark)

2026-09-09T17:19:10.000Z - unknown - Chiraag Balu

a fresh worktree has no kelpie-core/xgrammar_shim/build and no libkelpie; kelpie-http tests fail with FileNotFoundError until you symlink main's build and run scripts/zig build lib. The symlink then shows as untracked: .gitignore's 'xgrammar_shim/build/' (trailing slash) does not match a symlink

2026-09-09T17:19:10.000Z - unknown - Chiraag Balu

'uv run scripts/foo.py' from the repo root creates a root .venv and uv.lock (root pyproject.toml has [tool.mimir] but no [project]); hf_warm.py re-execs under --project kelpie-models to dodge this, but the stray .venv is still created first

2026-09-09T17:19:11.000Z - unknown - Chiraag Balu

huggingface_hub caches by repo id as written: 'gpt2' and 'openai-community/gpt2' are two 529MB cache entries; the tests spell both, so hf-models.txt lists both

2026-09-09T17:42:30.000Z - unknown - Chiraag Balu

scripts/test MAPPING kernels/* row named tests/test_overlay.py + test_record.py (deleted with the seam) -- any kernels/ change would have selected clauses that match nothing; replaced with test_catalog/test_seam/test_imports

2026-09-09T17:42:30.000Z - unknown - Chiraag Balu

kelpie-models section cannot collect at main: tests/test_jax_{corpus,engine}.py import the deleted kernels.overlay, and scripts/test only --ignore's shard files, so --only kelpie-models fails before -k applies (Mac and CUDA). Ran the proofs by hand with --ignore for the two jax files until the JAX port lands

2026-09-09T17:42:30.000Z - unknown - Chiraag Balu

test_grammar.py imports conftest.step_sync unused; scripts/rung_compare.py and scripts/diff_native_fill.py run at module level (no __main__ guard) so an import guard cannot import them, only resolve their imports
2026-09-09T17:30:45.000Z - unknown - Chiraag Balu

jax-seam: a fresh worktree cannot run scripts/test's kelpie-core / kelpie-py sections: the xgrammar shim build (kelpie-core/xgrammar_shim/build) is per-checkout and untracked; symlinked the main checkout's build in by hand. A local setup step (or the shared ~/kelpie-cache/xgrammar layout locally) would remove this.

2026-09-09T17:59:33.000Z - unknown - Chiraag Balu

jax-seam: jax is an optional dependency group but kernels/__init__ imports every device package eagerly, so every JAX kernel file (jax/{functional,sample,attention}.py, devices/tpu/_pallas.py, devices/neuron/{_dense,_nki}.py) imports jax inside each function. Correct but noisy; the alternative (DEVICES imported lazily in for_device) is a seam change I did not make.

2026-09-09T17:59:33.000Z - unknown - Chiraag Balu

jax-seam: nki.framework.jax is written against jax 0.9 internals (aval_to_ir_type); with the uv venv's jax 0.11 first on PYTHONPATH the NKI rms_norm lowering fails. The neuron rows need the /opt jax venv's jax first and uv's site-packages appended via sys.path, not PYTHONPATH.

2026-09-09T17:59:33.000Z - unknown - Chiraag Balu

jax-seam: scripts/test path mapping still names deleted tests (test_overlay.py, test_record.py under kernels/*) and 3 pre-existing tests import the deleted kelpie_models.ops (kelpie-py test_grammar::test_ops_sample..., test_launch_shape::test_aliases (via unported/), prove_sample) -- red on main 8ee201c as well.

2026-09-09T17:59:33.000Z - unknown - Chiraag Balu

jax-seam: the brief's tests/test_gpt2.py / test_qwen3.py do not exist; the gpt2/qwen3 torch tests are test_golden.py + tests/oracle.

2026-09-09T20:24:21.000Z - unknown - Chiraag Balu

editor: three uv venvs (kelpie-py/models/http), no pyright config at root -> gd fails on cross-package symbols. Added root pyrightconfig.json pointing at kelpie-http/.venv (the only venv with all three editable).

2026-09-09T20:48:40.000Z - unknown - Chiraag Balu

fresh worktrees fail scripts/test kelpie-core/kelpie-py on 'zig build lib' (xgrammar shim not built per-worktree); agents misreport it as a toolchain issue. Needs either a shared build dir or a first-run build step in scripts/test.
2026-09-09T19:14:00.000Z - unknown - Chiraag Balu

padded-plan: KelpiePlan padding blocked on buffer sizing. scheduler.zig allocPlan sizes input_ids/positions at max_batch_tokens and seq_lens/entries/block_tables at max_batch_reqs; the bucket ladder rounds up past both (max_batch_reqs=3 -> pr=4). Emitting a padded plan needs those buffers grown to bucket(max_batch_*), or max_batch_* constrained to bucket values at kelpie_create. Neither was in the spec.

2026-09-09T21:23:21.000Z - unknown - Chiraag Balu

laptop test tier (archived): qwen3 real fp32 weights loaded on every fast run (exempt from real_ckpt gate); conftest promotes to MPS (wired memory); torch+JAX in one interpreter (--group xla); no run lock. Caused the 09-09 watchdog panic under 3 concurrent runs. When tests return: KELPIE_DEVICE=cpu on laptop, no real weights, one framework per process, keep the flock.

2026-09-09T21:49:30.000Z - unknown - Chiraag Balu

zig worktrees don't inherit xgrammar_shim/build (gitignored C++ artifact) -- every fresh worktree needs either scripts/build_xgrammar.sh (slow, needs submodules initialized) or a manual cp from an already-built tree before zig build/test can run at all. Would be nice if there were a documented fast-path (symlink XGRAMMAR_BUILD_DIR to a shared cache) for worktree-based Zig work specifically.
2026-09-09T21:53:17.000Z - unknown - Chiraag Balu

scripts/zig and scripts/build_xgrammar.sh live only on the unmerged branch docs/coding-standards (4f25dd5), so a fresh worktree off main has neither: 'zig build' picks up whatever zig is on PATH (0.16.0 here, which cannot compile this repo at all -- std.time.Instant, std.Thread.Mutex, Build.ExecutableOptions all moved). Merging that branch, or committing scripts/zig to main, would save the next agent the detour.

2026-09-09T21:53:17.000Z - unknown - Chiraag Balu

kelpie-core 'zig build test' links libxgrammar_shim + libxgrammar, so the Zig test suite cannot run until the CMake shim is built -- and third_party/xgrammar is an uninitialised submodule in a fresh worktree. I worked around it by symlinking the main checkout's prebuilt kelpie-core/xgrammar_shim/build into the worktree. A worktree-local build or a checked-in prebuilt would make 'zig build test' work out of the box.
2026-09-09T21:47:39.000Z - unknown - Chiraag Balu

kernels: bridge.kernels_for and parallel.build_shard force a kernel set via string maps (REFERENCE / FUNCTIONAL). Values-only overrides means both become value dicts; REFERENCE moves from _xla/__init__ to a jax-side module.

2026-09-09T21:51:48.000Z - unknown - Chiraag Balu

scripts/test's import smoke only does 'import kelpie_models' -- it did NOT catch a dead 'from kelpie_models.kernels.devices._xla import JAX_DEVICES' in launch.py. Anything not reached from the package __init__ is unchecked by the gate.

2026-09-09T21:55:16.000Z - unknown - Chiraag Balu

kernels: three docs named the deleted catalog-name syntax (--kernels '{"layer_norm":"metal"}') as current -- README.md:36, docs/decisions.md:410, docs/model-contract.md:22. Fixed. Other stale hits (trainium-forward, spike-kernel-seam, brief-kernel-catalog*, confusion-map) left as dated history.
2026-09-09T22:02:46.000Z - unknown - Chiraag Balu

sdk/ladder: qwen3 (step 3 of the greenfield brief) is WRITTEN BUT NOT RUN -- Qwen3-0.6B fp32 is ~2.4GB and the laptop rule forbids loading anything bigger than gpt2. Its forward, backends() and the max_seq_len field are code-reviewed only; the first real evidence is the GPU box at step 5.

2026-09-09T22:05:34.000Z - unknown - Chiraag Balu

sdk/ladder step 6 (wholesale deletion) NOT DONE and should not be, yet. The new path serves gpt2/echo text completions + chat + config. Still riding the OLD contract and would break: llama, gpt_oss, smolvlm, the 3 unported models, the whole JAX arm (jax/{batch,bridge,attention}), the mla/dsa/gdn backend ops, the triton/pallas/nki device kernels, kelpie/parallel.py, and grammar.py. Deleting plan.py/step.py/runner.py/batch.py now takes all of those with it. Each needs its own re-signature pass first -- that is a real amount of work the brief's one-line 'delete the old glue wholesale' understates.

2026-09-09T22:20:58.000Z - unknown - Chiraag Balu

kelpie-engine rename: ruff check has 82 pre-existing advisory errors in kelpie-http (TRY004/C901/PLR0912/ANN401 etc, wire.py mostly) unrelated to this rename -- scripts/test treats them as advisory so they don't block, but worth a cleanup pass someday.
2026-09-09T22:27:47.000Z - unknown - Chiraag Balu

http/trio: hypercorn.trio.serve takes shutdown_trigger as keyword-only, so nursery.start_soon(serve, app, config, trio.sleep_forever) fails with a confusing 'serve() takes 2 positional arguments but 3 were given'; needs functools.partial.

2026-09-09T22:27:47.000Z - unknown - Chiraag Balu

http/trio: kelpie-http/kelpie_http/{cli,server,contract}.py still import fastapi+uvicorn, which this branch removed from the deps. They are not on any import path scripts/test walks, so the gate stays green, but they are now dead-and-broken until the brief's step 6 deletes them.

2026-09-10T03:59:40.000Z - unknown - Chiraag Balu

trace harness config has no bytes-per-page knob, so step 1's real slab carving (pages_per_slab>1) is covered by kv_pool.zig unit tests, not a traces/*.txt trace. Adding the knob waits for step 3's group_bytes_per_page ABI.

2026-09-10T04:02:16.000Z - unknown - Chiraag Balu

LCM slab sizing (brief ruling, reopening the 09-06 'LCM slabs not earned' call) does not survive the ladder: a per_seq recurrent group's page is 77 MB (Qwen3-Next) to 449 MB (Kimi-K3) because it sums a state blob over 36-69 layers, while the full-attention page is ~400 KB. lcm of those two is the product over their gcd and lands at 147 MB / 2.5 GB. DSV4 is worse: four 4KB-padded pages that are near-coprime give 22.5 GB. Pad-to-max (vLLM) or per-group slab sizes are the two ways out.

2026-09-10T04:18:13.000Z - unknown - Chiraag Balu

step 5's 'CSA/HCA compressor blobs become reads of the existing window ring' does not hold: the compressor rings a (kv|gate) projection of the hidden states (deepseek_v4.py:469), not raw K/V rows, so there is no existing group to read it from. Options: keep a per_seq compressor group whose unit is the projection (2*ratio x 2*width for CSA, ratio x 2*width for HCA), or recompute the projection from the hidden states at resume, which needs the hidden states retained.

2026-09-10T04:22:53.000Z - unknown - Chiraag Balu

The exact-tiling rule (pages_per_slab*bytes_per_page==slab_bytes) breaks once a model has two per_seq groups: their pages are fixed (one unit per page) so there is no block_size to tune, and two fixed near-coprime pages have no common slab. DSV4's S128/S4 are 3,289,088 and 507,904. Allowing slack bytes at the end of a slab (pps=floor(slab/page)) costs 7.35% worst-case on DSV4 and keeps block 8 everywhere.

2026-09-10T04:35:09.000Z - unknown - Chiraag Balu

step 7 assumed K could ride existing per-group fields (group_windows[g] = W + K). It cannot: the core receives only the sum, so K is unrecoverable, and three ladder models have no window or checkpointing group to carry it at all. K is one per-engine number and needs one appended u32 (KelpieConfig.n_draft), which is the same additive-ABI shape group_strides/vocab_words/group_bytes_per_page already use.

2026-09-10T04:36:31.000Z - unknown - Chiraag Balu

EDITING RULE for large files: never use python s.replace(old,new) with a multi-line 'old' block on a big source file -- if the block recurs (or a prefix of it does) the replace fires many times. On 2026-09-10 this duplicated choose_block_sizes ~700x in kelpie_models/groups.py (463 -> 39k lines); git checkout recovered it. Use line-range surgery instead: head -N > tmp; cat >> tmp <<EOF ...; mv tmp file. Or edit with a unique anchor and assert the replacement count.
2026-09-10T00:22:09.000Z - unknown - Chiraag Balu

grammar-rung: 'echo has no vocabulary for grammar' 400 (brief item 4) could not be wired -- kelpie_http/sdk/{app,chat}.py only ever holds an Engine (kelpie_engine.sdk.engine.Engine), which has no model/Step awareness (no CHECKPOINT, no is-this-echo flag). The engine's supports_grammar is purely a vocab_words>0 scheduling property, true for echo too, since EngineConfig.from_model computes vocab_words from any model's cfg.vocab including EchoConfig's. Detecting echo specifically would need a new field threaded from kelpie_models.sdk.run.build / kelpie_http.sdk.serve.serve down to create_app -- both out of scope (serve.py, sdk/run.py are sibling-owned). Left unimplemented; flagged as a STOP in the final report rather than guessed.

2026-09-10T00:22:09.000Z - unknown - Chiraag Balu

grammar-rung: kelpie_engine/sdk/grammar.py's compile_json_schema needs the model's exact vocab (cfg.vocab), but the new-path Engine only exposes vocab_words (ceil(vocab/32), lossy). Used engine.config.vocab_words * MASK_BITS as vocab_size in kelpie_http/sdk/chat.py -- safe upper bound (xgrammar pads extra ids as usable but apply_logit_mask only ever indexes the real logits width, so they're never read), verified by direct grammar_smoke run producing valid JSON with gpt2. Not exact-perfect, but correct in effect.

2026-09-10T04:04:25.000Z - unknown - Chiraag Balu

check_serve gpt2 row: the brief's expected string ' its capital city, Burgundy' for gpt2 CPU 'The capital of France is' is WRONG on the current tree. HF GPT2LMHeadModel greedy for that prompt and 6 new tokens is ' the capital of the French Republic', and our stack produces exactly that through the endpoint. The Burgundy string comes from BREADCRUMBS 21:56 (sdk-ladder), before the kv[member] fix in 8b18da7 -- the same breadcrumb chain at 23:07/23:17 records that the pre-fix stack diverged from HF and that the FIXED forward matches HF greedy ('the capital of the French Republic'). I used the HF-verified string and noted it in the row.

2026-09-10T07:57:30.000Z - unknown - Chiraag Balu

check-endpoint: brief's Row shape (reference: float | NO_REFERENCE, spec: HypothesisSpec(alpha, beta, sigma, n)) doesn't match copy-verbatim check.py, whose HypothesisSpec bundles reference_mean+sample_count+sigma+alpha+beta+higher_is_better as ONE dataclass with no separate check(spec, scores, reference) signature -- check(spec, scores) reads spec.reference_mean itself. Either the brief pre-dates a check.py field rename, or check_endpoint.py's Row.spec is meant to be a partial/builder that gets reference_mean filled in at run time (NO_REFERENCE bootstrapping conflicts with a frozen dataclass needing reference_mean up front). Need to ask before picking one.

2026-09-10T07:59:14.000Z - unknown - Chiraag Balu

check-endpoint: copied probe/ files fail this repo's mimir audit (ruff format on 2 files, UP035 typing.Iterable->collections.abc, cyclomatic complexity in metrics._decode_series, too-many-args in proxy.ProbeProxy._handle_upstream_error) -- all in crucible's own code, none touched since the brief says copy verbatim + fix imports only. scripts/check_serve.py currently passes full mimir audit; check_endpoint.py's tree will not, unless bench/probe is exempted from the gate or crucible's style is reconciled with kelpie's (a decision, not mine to make silently).

2026-09-10T08:45:36.000Z - unknown - Chiraag Balu

check-endpoint: kelpie_models/sdk/run.py's build() unconditionally imports kelpie_models.sdk.captured.Captured when capture resolves True (the default on any cuda device, since serve.py's --capture defaults to None -> device.startswith('cuda')), but that module does not exist anywhere in the tree at 4c776f0 (or in worktrees/check-endpoint's sync of it). check_serve.py never hits this because all of its rows are device=cpu. Any first real CUDA row through kelpie serve --device cuda will hit this immediately unless --no-capture is passed explicitly. Worked around in check_endpoint.py; the missing module itself is someone else's landing, not filed as a bug fix here.

2026-09-10T08:48:00.000Z - unknown - Chiraag Balu

check-endpoint: kelpie-core/src/step_loop.zig:191 panics ('launch failed: status=1 step=N shape=S n_reqs=1') instead of returning a clean error/400 when a request's token count exceeds max_batch_tokens (as opposed to max_seq_len, which request.zig:379 already checks cleanly and serve.py surfaces as 400 TooLong). This crashed the whole kelpie serve process mid-run under check_endpoint.py's qwen3_gsm8k row (5-shot gsm8k prompts + num_concurrent=8 pushed one request's tokens past max_batch_tokens=4096). A downstream-task row against a real GPU model is the first thing to hit this since check_serve.py's CPU rows keep every Ask tiny. Not fixed here; worked around with generous max_batch_tokens headroom instead.

2026-09-10T08:56:07.000Z - unknown - Chiraag Balu

check-endpoint BLOCKING: kelpie_engine/sdk/engine.py's _trampoline swallows the step-thread's Python exception into a status=1 int with the message stashed in self._error, meant to be re-raised by engine.raise_error() on the poll path (called from kelpie_http/sdk/app.py:245). But kelpie-core/src/step_loop.zig:191 does 'if (status != 0) std.debug.panic(...)' on that same status BEFORE the Python poll loop ever runs again -- so a real forward-pass exception (something genuinely broken in qwen3's cuda forward, --no-capture path, or a downstream kernel) kills the whole server process with a generic Zig panic ('launch failed: status=1 step=2 shape=4107 n_reqs=1') instead of ever reaching raise_error() and surfacing the actual Python traceback. Blocks check_endpoint.py's qwen3_gsm8k row from producing a first green line on real GPU hardware: every reproduction (max_batch_tokens=4096 AND the corrected 8192) panics identically at the same shape=4107, so it is not a sizing bug -- it's a real crash somewhere in qwen3's cuda forward under load, whose message is unrecoverable without a core-engine patch. Needs someone with kelpie-core context to either (a) make step_loop.zig surface status!=0 as a clean poll-time error instead of panicking, or (b) reproduce+fix the qwen3 cuda forward crash directly with print(self._error) added ad hoc.

2026-09-10T08:59:07.000Z - unknown - Chiraag Balu

check-endpoint BLOCKING (root cause, supersedes the earlier 'launch failed' entries): kelpie_models/models/torch/qwen3.py:84 (and the two other rms_norm call sites in the same forward) calls torch_f.rms_norm(x, (config.hidden,), layer.ln_1, config.eps) with eps as a 4th positional arg. torch==2.13.0+cu130 (what uv resolves today from kelpie-models' torch>=2.4 pin) raises TypeError: rms_norm() takes 3 positional arguments but 4 were given for this call -- eps is presumably keyword-only or removed as a positional in this torch release. Crashes any CUDA qwen3 forward outright (layer_norm kernel = plain torch on cuda per kernels[cuda] in the startup log). check_serve.py never exercises this because its gpt2/echo/gpt_oss_tiny/smolvlm rows are all device=cpu. Separately: the Zig step loop (kelpie-core/src/step_loop.zig:191) std.debug.panics the WHOLE SERVER PROCESS on any non-zero launch status instead of letting kelpie_http/sdk/app.py:245's engine.raise_error() surface it as a clean 500 -- so this (and any other in-forward Python exception) currently kills the process rather than failing one request. Both are real bugs on main; neither is fixed here since both are outside scripts/check_endpoint.py's scope. Root-caused by a throwaway traceback.print_exc() patch on CUDA (B200), reverted before finishing (confirmed via grep).
2026-09-10T08:25:56.000Z - unknown - Chiraag Balu

kelpie: serve --cache makes the cache dir read-only (sdk/cache.py freeze), which is the point, but it also means 'rm -rf' on that cache fails with Permission denied until you chmod -R u+w. kelpie build should chmod the tree writable before rewriting it, and 'kelpie cache --clean' would be kinder than telling people to chmod.

2026-09-10T08:35:11.000Z - unknown - Chiraag Balu

torch refuses register_autograd on a non-functional custom op (one that mutates an arg): 'Cannot register autograd formula for non-functional operator'. Every attention op writes kv_member and every recurrent op writes state, so those 6 ops cannot have a torch-registered backward. kernels/op.py keeps the backward on the Op object instead (has_backward, .backward) and the conventions check reads that. Functionalizing a paged KV write to satisfy torch would mean copying the cache, which is what paging exists to avoid.

2026-09-10T08:35:11.000Z - unknown - Chiraag Balu

Neither TorchDispatchMode nor TorchFunctionMode intercepts a torch.library.custom_op's registered kernel, so counting which kelpie ops a model calls could not be done with a torch mode. kernels/op.py wraps every impl bind installs in a counting shim instead (op.counted). Works, and costs one Python frame per op call -- fine while the reference is the impl, worth revisiting when a real Triton kernel is on the hot path.

2026-09-10T08:35:11.000Z - unknown - Chiraag Balu

An IDLE plan is still an OPEN plan: engine.plan() returning None still needs a matching engine.commit(empty) to close it, or the NEXT plan() (the loop's first) trips scheduler.zig's build-ahead assert with 'reached unreachable code'. Cost ~30 min to find from a Zig panic trace. Either kelpie_plan should not open a plan when it returns 0, or Engine.plan should close it itself -- the by-hand rung 1 path (plan/forward/commit) should not have a footgun the loop hides.

2026-09-10T04:13:03.000Z - unknown - Chiraag Balu

stubs/decisions-in-code: item 5 (sdk/cache_spec.py) was dropped by the coordinator mid-brief -- groups.py already had CacheSpec/derive_groups live; the brief's premise (create fresh) didn't match the repo. Worth checking future briefs against the live tree before scoping, not just docs/decisions.md, which can itself be stale.

2026-09-10T04:13:04.000Z - unknown - Chiraag Balu

stubs/decisions-in-code: docs/decisions.md's own file-path convention was inconsistent (bare kelpie_models/... vs real kelpie-models/kelpie_models/...) across nearly every ruling -- systemic, not a one-off typo. Any future doc that names code paths should be spot-checked against the actual package layout, since the repo has hyphenated top-level dirs but underscored import names.

2026-09-10T04:13:04.000Z - unknown - Chiraag Balu

stubs/decisions-in-code: two live, parallel kernel-selection systems coexist today (old for_device/Kernels/AttentionBackend catalog used by qwen3.py/gpt_oss.py/smolvlm.py/llama.py/cli.py/launch.py, and the new ops.bind/torch.library.custom_op seam used by gpt2.py/sdk/run.py/sdk/step.py/serve.py). decisions.md's 09-07 catalog ruling and the 09-09 ops.bind ruling are both correctly in the index now, but nothing in the repo says which one a new model should target -- worth a decision.

