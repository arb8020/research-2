# Roadmap (wave 3 -> v0), as of 2026-09-08

The living plan. BREADCRUMBS.md has the decisions in order; PAPERCUTS.md the debt; this file the
shape of what is left. Update it when a milestone lands or a fork is taken.

## v0, defined

`kelpie serve --model <module>` serves crucible's 10-rung model ladder (crucible
`benchmarks/model_ladder/meta/FANOUT.md`) on nvidia / tpu / trainium (apple: `--dev`, eager only),
with tool calling, streaming, JSON mode, and spec decode (nvidia first); every rung passes
crucible's own L0-L5 verifier through an adapter; models, devices, kernel sets, and sharding are
plugins (one file + a corpus dir; a test asserts no name tables); parallelism is explicit comms in
the forward (shardlib, torch and JAX); knobs incl. spec depth change live; a tok/s number against
vLLM on the same B200. Bar: within 20% of vLLM on Qwen3-0.6B decode was proposed; measured 706 (script: scripts/prove_capture.py; rung: kelpie serve) vs 4204 (rung: external: vLLM) after M1 with the gap
in kernels, so the honest v0 bar is 'same order of magnitude with a per-kernel profile that says where the rest is' — for the user to set.

Spec: docs/complaints.md (4 verbatim complaints). Decisions: docs/decisions.md "Launch and
ownership" (main, a3b7f9f) and BREADCRUMBS.md 2026-09-02.

## Milestones (branches stubbed off main; each gets a worktree when started)

| M | branch | what | proof | status |
|---|---|---|---|---|
| 1 | wave3/m1-capture | `capture_model_step(cuda_graph)`: two graphs (forward, sample) on fixed leaves; `CapturedModel` + free `launch()`; captured `kelpie serve` | captured vs eager vs vLLM tok/s, 50x64x16 on B200 | **merged 93ba8b7** (+ fused ops 0df5d89, + Triton prefill 2d3df6a: the CUDA eager path is gone): **1300** (script: scripts/prove_capture.py; rung: kelpie serve) / 730 (script: scripts/prove_capture.py; rung: kelpie serve) / 4204 (rung: external: vLLM) tok/s; captured decode step 2.1 ms at R=64 (script: scripts/step_breakdown.py on events from scripts/prove_capture.py; rung: kelpie serve). Review: 97% of the step is GPU time inside the replays (9.3 ms at R=64), ops.plan 2.2 ms host, outside launch 0.6 ms (script: scripts/step_breakdown.py on events from scripts/prove_capture.py; rung: kelpie serve) — the gap is kernels (unfused reference ops in the graph), not the loop |
| 2 | wave3/m2-zig-loop | port spike/zigloop onto CapturedModel: `register_launch/start_loop/stop_loop`, `swap_launch(drain)`, shutdown order, status not exceptions | p99 flat under 16 pollers; live knob + drain-swap | **merged be3a366**: native launch, ladder captured at build, swap live (tier-1) + launch epoch (tier-2 reclaim), shutdown order asserted. Decode step 6.8 -> 5.8 ms; p99 6.0 ms flat under 16 hammering threads vs Python owner 716 ms (script: scripts/prove_zig_loop.py; rung: native Zig loop, no HTTP / Python stepper) |
| 3 | wave3/m3-overlap-grammar | one-step overlap (device token buffer, commit one late); grammar JSON mode (xgrammar Matcher, mask between the two graphs) | JSON-schema completion streamed, nvidia + tpu | **merged**: depth-two overlap in Zig (40 traces Zig == ref; poll-sentinel bug fixed; on == off bitwise; on vs off within noise at 0.6B -> default OFF); JSON mode end to end (three stacked bugs fixed; streamed, captured, {name, age} valid); grammar on the native loop takes the Python rung (counted; native matcher is the removal) --
correction (serve-native-loop, 2026-09-03): only true through the Python `Stepper`; `KelpieCore.step`
is the sole caller of `prepare_logit_mask`, so a `NativeTicker`-driven serve has no grammar rung at
all and refuses `response_format` requests with 400 instead (mimir papercut). Decode core ~5.5k tok/s (script: scripts/prove_overlap.py; rung: native Zig loop, no HTTP) > vLLM e2e 4204 (rung: external: vLLM); serve ~1200-1300 (script: scripts/prove_capture.py; rung: kelpie serve) -> the Python request path is the gap (M8) |
| 4 | wave3/m4-spec-decode | Zig K>0 (offered n_drafts on request.zig), draft model, rejection in `sample`; nvidia only | acceptance rate + tok/s gain; greedy == no-spec | **STOP: user decides first** (below) |
| 5 | wave3/m5-shardlib-jax | hybrid shardlib twin (spec -> PartitionSpec for dense, explicit collectives in shard_map for MoE/kernels; roles kept); port RPA v3 (sinks/window/self-aligning KV); gpt-oss tp x ep on v6e | gpt-oss-20b on v6e, greedy == HF | not started |
| 6 | wave3/m6-ladder | crucible L0-L5 adapter; rungs 02/03/07/08 as config-delta model files; `grouped_mm` in the JAX seam; Trainium compile-cache warmup; every rung vs HF on every device | one table: 10 rungs x 4 devices | not started |
| 7 | wave3/m7-kernels | KDA (rung 04) + Inkling (06); kernels GDN/conv, MLA + DSA top-k (nvidia), megablox GMM / MLA v2 / KDA Pallas lifted from sglang-jax (tpu) -> ladder in fixed world. Composed ops on the seam (reference = the composition): fused QKV / gate-up GEMMs first; a per-model Ops extension so a module can declare `qwen3.decode_step` (megakernel rung) | whole ladder captured on B200 | not started |
| 8 | (after 7) | shrink pass: HTTP #2 in Zig over the frozen wire contract (54 goldens are the test; own event loop like TigerBeetle io.zig; JS rejected: a second runtime + IPC per token). Open: chat templates (6 Jinja + parsers, ~2k of the 3.9k) — pre-render to token-id emitters at startup or keep rendering in Python at the boundary. Core: split the trace runner out of scheduler.zig; revisit what else can go | kelpie-http LoC and scheduler.zig LoC, before/after | not started |

Merge gate for every branch: call-stack tree, one runnable command with expected output,
readability check. Reviewed by a different agent than the author.

Note (2026-09-03): by default `kelpie serve` runs the Python stepper (KelpieCore.step); the Zig loop
is opt-in via `--native-loop` (F part 1, merged 5ba61d9: 3342 tok/s / 6.3 ms TTFT vs 697 / 272 ms,
script: scripts/prove_capture.py; rung: kelpie serve --native-loop). Not the default until F part 2
lands: no StepEvents and no grammar rung under the loop (response_format -> 400).

## Note (2026-09-09): every tok/s number below measured through `kelpie serve` on CUDA after F2 (2026-09-04) went through the C launch table, which produces garbage tokens (BREADCRUMBS 2026-09-09, fix/c-launch-table). Treat them as launch-rate numbers, not throughput, until the fix lands and prove_capture asserts output.

## Observability (deferred 2026-09-09)

Today: events are the truth (StepEvent per commit, RequestEvent per request, from the Zig core via
the commit ring) -> sinks (EventLog JSONL, Metrics aggregates, Fanout) -> /metrics (Prometheus text),
/v1/kelpie/stats, --events. No OTel, no request-scoped spans, no OTLP export, ~no logging, no
GPU-side timing in events (t_forward_ns is the Zig wall bracket). Debt: two Prometheus renderers
(PAPERCUTS). When wanted: an `OtelSink` implementing `EventSink` (RequestEvent -> span from its
existing timestamps, StepEvent -> metrics), one file, no core or wire change.

## Size, honestly (2026-09-02, vs the resin numbers the user pasted)

kelpie non-test: 3.7k Zig (larger than resin-core's 2.8k Rust), 17.2k Python (resin 21.2k). The
model-definition gap (~350 lines/model vs ~3,700) is real and is the Ops seam — but it exists because
kelpie's models do not carry kernels: cuda_triton.py is 461 lines (decode attention, rms_norm, rope,
silu, sampler), no MLA/DSA/KDA, so 3 of 8 models run eager-reference only. HTTP is 3x resin's, in
Python. Closing the kernel gap costs ~1.5-3k Triton per exotic attention family, per device;
expect cuda_triton at 5-8k and the repo at 26-30k. The seam amortizes the plumbing, not the math:
~2x smaller than resin at parity, not 6x.

## Autonomy (2026-09-02)

The user granted: run M1 -> M2 -> M3 unattended, merging each on its gate. Design forks are resolved
from ~/research/docs/code_style and the reference engines (docs/decisions.md "Reference points";
docs/plugin-feasibility.md; the neuron-engine and sglang-jax reads in BREADCRUMBS) and recorded as
a breadcrumb with the alternative rejected. STOP before M4. Surface the M1 number as a one-liner.

## Next, in order (2026-09-08; supersedes the 2026-09-03 list below and the M4 questions)

State: main c97549b. `spike/kernel-seam` (worktrees/kernel-seam) carries
the kernel seam + catalog + taps, gpt2 + gpt_oss green; `feat/kind-from-core` carries the kind leaf.
Read docs/brief-*.md for the decisions and reasoning.

Decided 2026-09-07/08 (user):
- Kernels are values on ModelState, chosen once at build: `k = for_device(device, choose)`;
  forward reads `k.rms_norm(...)`. Open catalog `kernels/devices/<dev>/<op>.py` (named impls or an
  import path), signature-checked (name, kind, default) at build. Three op kinds: MATH (pure
  functions), TABLES (construction), BACKEND (attention, mla_attention, dsa_attention, gdn: classes
  with kv_layout / prepare_workspace / forward; a hybrid model holds N of them, one per cache
  group, `batch.attn[g].backend`). Fusing layers = fork the model module. `--kernels` is a JSON
  dict; TOML lands with tiered config.
- kind-from-core: `kind` + `n_drafts` cross the ABI per request as StepBatch leaves; the reference
  asserts `kind == decode <=> nq == 1 + num_drafts`; backends partition on `batch.kind`, never on
  row count. `StepShape.mode` stays the per-step program key.
- Taps: one site per layer (`resid_post`), layout string asserted replicated, `StepShape.taps` in the
  program key, forward returns `(logits, kv, state, taps)`. Consumer timing is the consumer's.
- kv-groups re-owned: StateRing stays Python-owned per slot; prefix cache off for recurrent /
  hybrid models; a snapshot pool is a later rewrite.
- Testing: two laptop crashes under parallel local suites. Local = fast smoke; full tails on remote
  CUDA / Trainium / TPU hardware.

1. Land taps + kind-from-core on `spike/kernel-seam` (first CUDA run of the seam).
2. Port the other five models to the seam, in parallel worktrees: qwen3 + llama (attention),
   smolvlm (+ encoder), deepseek_v32/v4 (mla_attention + dsa_attention, reference only),
   qwen3_next (attention + gdn; proposes the groupless workspace slot), the JAX twin + 4 CUDA
   scripts. Each carries `k`, `batch.attn[g]`, `kind`, taps.
3. Full suites on CUDA / Trainium / TPU -> merge seam -> main. Then test cleanup
   -> main stable (6 F2-fallout tests, vocab_words + PROOFS,
   prove_capture mode, t_forward_ns) -> push. Merge chore/open-roles; train-step after.
4. M4 spec decode, three drafters on one engine path, in target-readiness order:
   a. **DFlash on gpt-oss-20b** (`z-lab/gpt-oss-20b-DFlash`, MIT): block_size 8 -> K = 7; taps
      `resid_post` at layers [1, 6, 11, 16, 21] fixed at build from the drafter's config; the draft
      is an 8-layer Qwen3-shaped dense module (`dflash.py`, cross-context K/V from the fc'd target
      residuals + noise rows, target embed + lm_head), its own KernelSet / ModelState / graphs, a
      second ModelRunner. Verify = the sample step over `[R, 1+K, V]` rows (greedy cumprod; rejection
      sampling at T > 0). Reserve 1+K rows at plan, refund at commit; overlap stays off with K > 0.
      Proof: greedy ids == no-spec, acceptance length vs the card (~4-5), tok/s gain on B200.
   b. **DSpark mechanics** on `deepseek-ai/dspark_qwen3_8b_block7` (Qwen3-8B, a config delta of
      qwen3.py): Markov head + confidence head + anchors as the second drafter variant.
   c. **DFlash 2** (`z-lab/Qwen3.8-27B-DFlash2`: conv + candidate selector) once Qwen3.8-27B is
      onboarded or a DFlash2 head exists for a ladder model.
   d. **DSpark on DeepSeek-V4-Flash** (`deepseek-ai/DeepSeek-V4-Flash-DSpark`, drafter fused in the
      167 GB checkpoint) after M7 MLA/DSA kernels + the deepseek port: weight extraction, then b's code.
   Drafter = a module with (draft forward, accept rule); the engine path (rows, kind/n_drafts,
   verify, commit payload, second runner, taps) lands once in a.
5. Then the rest of the 2026-09-03 list below (E/G items), grammar-artifact, mimir breadcrumb -> optmem scopes.

## Next, in order (2026-09-03)

Landed today: chore/compress-step (one step path: `run_step` -> `Graph` -> `ModelRunner`, `build()`
precaptures, legacy step paths and kernel shims deleted),
provenance tags on every number in this file. Found: **`kelpie serve` never calls `start_loop()`**
-- serving runs the Python stepper; the Zig loop is exercised only by prove_zig_loop.py.

- E. `ModelRunner.stats()` -> `/metrics` + `StepEvent` (which rung ran is a counter, not an inference).
- F. `kelpie serve` -> `precapture()` + `start_loop()`. Gate: a proof that asserts `native_steps > 0`
  from a served process (the proof proves the assembly, not a piece). Design pass first: grammar
  (Python matcher) and parallel (rank-0 plan broadcast) inside the loop.
- G. Test pass, framed as "would this test survive an implementation swap": one fixture over
  `build()` (7 hand-rolled constructions), rule-guard tests -> `mimir audit` (import boundaries
  built: mimir `feat/audit-boundaries`; kelpie `[tool.mimir]` not yet written), one skip helper /
  reason string (today 4 spellings of "needs CUDA"), a checked-in streamed-JSON proof, curate
  fuzzer-written `divergence-*.txt` traces, `ops.py`'s boundary exemption.
- Then M4, shaped by docs/spec-decode-survey.md + docs/spec-decode-recent.md:
  drafter = a second `ModelRunner` (unanimous across engines); reserve `1+K` rows at plan, refund at
  commit (vLLM/SGLang); grammar masks the drafts before accept (no rollback bound); DFlash/DSpark
  need target hidden states at declared layers -> an additive `forward` return leaf, mode-gated
  (open: whether `target_layer_ids` lives on the drafter's or the target's config). DSpark is a
  separate checkpoint, not part of DSV4; `deepseek_v4.py` parses no DSpark fields and emits no
  hidden states.

Decisions recorded, not yet code: per-request sample seed = user-supplied (`seed`) else
engine-assigned and reported -- needs `seed` on the Zig request through submit/C ABI/plan,
additive (today's key is an FNV fold over slot ids: batch-invariant, not request-invariant);
batch invariance is a property to test for and relax knowingly, not a rule (docs/references.md,
Thinking Machines); a fused forward+sample `Graph` excludes the host grammar mask -- the model
author owns masking in that mode.

Cleanup still queued: trace harness out of scheduler.zig + `cmd_expect`/`cmdExpect` as dispatch
tables; `initPlan`/`allocPlan` dedupe; the three "core"s, two `PlanView`s, kernel-set vocabulary;
`synth/` -> tests; reference scheduler `Event` dup + overlap into its own module; trace-interpreter
unification (design call); `kelpie serve smolvlm --device cuda` silently needs `--dev`.

## Questions for the user before M4 (answered 2026-09-08; see the top list, item 4)

1. Drafter: a separate small model (Qwen3-0.6B drafting for 30B-A3B) or the target's MTP head
   (DSV3.2 has one; Qwen3 does not)? Both are "a second forward in the same step"; MTP shares weights.
2. Default K (the spec-decode design assumed 1 + k with k small; grammar's rollback bound must
   be >= K).
3. Rejection sampling inside the captured `sample` graph (one launch) or a third graph (draft ->
   verify -> sample)?
4. Draft batch shape: `StepShape.mode = draft | verify` on the same CapturedModel, or a second
   CapturedModel for the drafter?
5. K>0 x overlap (spike/overlap-ref O6): plan(N+1) runs before N's accepted count is known. Reserve
   the max (1+K rows per request, KV held for a step) or reserve 1 and re-plan drafts a step late?
   Changes how much KV overlap pins; not decided.

## Questions before M5 / M6

- M5: the hybrid (annotate for dense, explicit for MoE/kernels) relaxes "nothing hides a collective"
  on the dense JAX path to "the string spec is the source of truth; `{unreduced}` is asserted, not
  written." Accept, or insist on shard_map everywhere at the cost of XLA fusion?
- M6: "full ladder" = all 10 rungs validated vs HF on every device they run on, fixed-world where
  the attention-only kernel covers (00, 01, 05, 08; 02 once grouped_mm is in the graph); M7 lifts
  the rest. Or all 10 captured before M6 is called done?
- Which of the 4 papercuts on the Trainium kernel set (SWA/sinks asserted off; no HBM budgeting; no
  block-count rounding; single core) block "serves on trainium" for v0?

## Spikes (all on `spike/*` branches, none merged; numbers in each `docs/spike-*.md`)

graphs (c8ff9f4) capturable 10x bitwise, hoist list -> ModelStep fields | zigloop (7638319) Zig
thread + native launch 4.5 ms flat vs 34 ms Python under 16 pollers (script: scripts/spike_zigloop.py
on spike/zigloop; rung: native Zig loop, no HTTP / Python stepper) | grammar zero-copy into
logit_mask, <0.13 ms @R=64 (script: scripts/spike_grammar.py; rung: eager forward) | specref (ebc7590) commit payload + entry kind hold at K=2; Zig needs
offered n_drafts | paged-attn -> merged as backends/cuda_triton (a5f8762) | swap-drain (b0ce1b6) serving/draining + swap mailbox, 33/33 Zig==ref | overlap-ref (67a3160) one-step
overlap in the reference, 5 traces; O4: preemption disabled while a plan is outstanding (skip/rotate
instead — taken); O6 -> M4 question 5; O7: reference has no grammar machinery yet.

## Landed on main today

parallel merge onto v1 + shardlib bottom rung (23e7f87); config_hash hex, wire rev 2 (fa12c7b);
trainium merge + tie-aware FIXME (abedf3a); Zig 0.14.1 toolchain (d35ac02); reference scheduler
models window groups, 28/28 (9a2a479); merge gate (104d536); capture-safe reference ops, Philox
(a05a373); Triton paged decode backend (a5f8762); launch-shape: ModelState/ModelStep/StepShape, facts,
kelpie serve as sugar (a3b7f9f); verify/gpu + vLLM baseline (801ecde); fix/parallel-v1 (6581bbf); shardlib
rank assert (02e92e8); grouped_mm in the JAX seam + SPMD sampling rule (5a9d3ec); scripts/test + order-independent
contract suite (255f570); verify/tpu (cf0f03a), Trainium verify (a4b552e); M1 capture (93ba8b7); fused
rms_norm/rope/silu/sampler (0df5d89); M2 Zig loop + native launch + swap + epoch (be3a366); Triton prefill, CUDA
eager path removed (2d3df6a); backends -> kernels rename, --device/--kernels (5405e66). Main serves Qwen3-0.6B
at 1300 tok/s (script: scripts/prove_capture.py; rung: kelpie serve) captured on a B200 (vLLM 4204, rung: external: vLLM); decode core alone 5572 tok/s (script: scripts/prove_overlap.py; rung: native Zig loop, no HTTP).

Next on this branch set: kernel sets as Nix-style overlays composed once at the root (`compose(cfg,
device, overlays) -> Ops`, eligibility per kernel, per-shape entries allowed, no registry) replacing
--kernels; cuda_triton.py split into kernels/triton/{attention,norm,sample}.py + kernels/sets/. Waits on the
popcorn/engines read (done: lift popcorn's record key + AST fingerprint + third state; vLLM's reasons list;
never wrap). chore/overlays + the test matrix merged (452c175): compose/Overlay/sets/record, --overlay, matrix with
loud skips + coverage line; the 3 xfails triaged (one real regression fixed, two tolerance bands). Spike branches kept (`git show spike/<name>:docs/...`); their worktrees removed.

## Unverified on hardware

B200: v1 contract, corpus, TP2/EP2, gpt-oss-20b tp2 greedy==HF all pass.
v6e: all JAX suites pass post launch-shape, 130.7 tok/s (script: scripts/load.py; rung: kelpie serve).
Trainium: correctness green post-port; 7.5 tok/s (script: scripts/load.py; rung: kelpie serve), prefill 1024 = 2.2-2.7 s, compile 130-280 s/bucket.
spike/decode-profile: per-kernel table of the 9 ms; fused rms_norm/rope/silu/sampler overrides.
Every number in this file that came from a spike rather than a suite.
