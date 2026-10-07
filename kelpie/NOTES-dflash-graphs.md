# NOTES: DFlash under CUDA graphs (branch spec/dflash-capture)

Working notes, not a design doc: the code is the source of truth
(`kelpie-models/kelpie_models/models/torch/dflash.py` `verify` / `DFlashStep.capture`,
`kelpie-core/src/c_api.zig` `reqsPadded`).

## What changed, as a call tree

    build (sdk/run.py)
    -   assert drafter => not capture                       # refusal removed (compile still refused)
    ~   Drafter(..., scratch_slot=_scratch_slot(...))       # read off a synthetic plan: the core writes it
    ~   stepper = DFlashStep(step, drafter)                 # built once, held by Built.stepper
        _warm -> DFlashStep.warm -> dflash.step(inert)      # same program at every key, no target-only path
    +   _wrap: DFlashStep.capture(engine, steps)            # one graph per decode_extra key, shared pool
    DFlashStep.__call__(plan)
    +   decode_extra key captured -> _Graphed(plan)
    +     to_device(into=static, pinned) ; draw_into(static Draw) ; graph.replay() ; out[:n_reqs].cpu()
    ~   else -> dflash.step (eager: prefill in the batch, every entry degraded)
    verify(target, drafter, plan, batch, draw)             # THE program, eager or captured
    +   draft: noise_batch -> draft_forward -> argmax, masked -> 0     # fixed [R, 1+K]
    +   fill_extra_rows: where() over T rows                          # was boolean-mask indexing
        target.forward_device
        decide
    ~   inject over T_padded rows                                    # was sliced to n_tokens on host
    kelpie-core publishPlan
    +   reqsPadded: decode_extra pads R to min(bucket(t_pad - 1), bucket(max_batch_reqs at create))

## How the others do it (read, not run)

SGLang edff717 (the local checkout's tree is all staged deletions; read via git archive), vLLM
4bb804c (fresh sparse clone).

- SGLang target verify: `DecodeCudaGraphRunner` in TARGET_VERIFY, tokens = bs x width, bs
  padded up to a captured size (decode_cuda_graph_runner.py:318-329, 1313-1320;
  base_cuda_graph_runner.py:137-151). Pads: seq_lens = backend fill value (1), out_cache_loc 0
  (cuda_graph_buffer_registry.py:71-91, 534-601). The graph ends at logits; accept and the tap
  injection into drafter KV run eagerly after replay (dflash_worker_v2.py:1965-2152).
- SGLang DFlash drafter: its own graph (TARGET_VERIFY mode on the draft runner, bonus + K mask
  embeds, dflash_worker_v2.py:1767-1896), the greedy head folded in via capture_tail_hooks
  (92-139, 452-475). EAGLEDraftCudaGraphRunner keys by bs, pads the same way
  (eagle_draft_cuda_graph_runner.py:289-291, 519-597).
- SGLang mixed batches: mixed chunked prefill is disallowed with spec (server_args.py:9876);
  a width mismatch or bs past the largest capture falls back to eager
  (decode_cuda_graph_runner.py:653-692).
- vLLM v1: uniform decode = max query len 1+K and tokens = reqs x (1+K)
  (gpu_model_runner.py:3853-3870, cudagraph_dispatcher.py:36); num_reqs = padded tokens / (1+K)
  (cudagraph_dispatcher.py:130-151); non-uniform -> PIECEWISE -> eager (300-322). Pads: slot -1
  (write skipped), null block 0, seq_len 0. Rejection sampling and propose run outside graphs.
- vLLM V2 DFlash (worker/gpu/spec_decode/dflash/speculator.py) is the closest: the drafter is a
  FULL graph that also runs the tap -> drafter-KV precompute (cudagraph.py:117-127,
  speculator.py:270-301); pad query slots PAD_SLOT_ID (95-100, 690-712); context rows are
  num_reqs x (K+1) whatever was accepted, to avoid a host sync (303-305, 365-375).

Neither fuses draft + verify + accept + inject into ONE graph; kelpie does (agreed design).

## Results (Modal, gpt-oss-20b + z-lab/gpt-oss-20b-DFlash, K=7, greedy, volume kelpie-a1)

Correctness. The A100 run was at 7c2fd37, before the review asserts; the H100 run was at 132f3bd.

| proof | A100 | H100 |
|---|---|---|
| 1. prove_dflash --capture --base spec, math 256 | 3/3 identical, accept 4.21 | 3/3 identical, accept 4.28 |
| 1. same, raw 256 | 5/5 identical, accept 2.94 | 5/5 identical, accept 3.08 |
| 2. check_spec_teacher_forced native math 256 --capture | PASS, worst 1.0, accept 4.21 | PASS, worst 1.0, accept 4.28 |
| 3. prove_dflash --batched --require-preemption (160 slabs, budget 37) --capture | no FAIL: 1 exact + 7 ties, preempted 28 | no FAIL: 2 exact + 6 ties, preempted 29 |
| 3b. same, graded teacher-forced | - | PASS, worst 2.0 |
| prove_state_lifecycle (core padding) | - | ALL PASS (K=0, K=3) |
| check_build_step | - | 14 passed |

Eager == captured is bitwise, because both run one program on the same shapes. The batched
ties are against K=0, where they were ties on eager rung0 too.

Speed: bench_spec, B concurrent requests, 256 new tokens, both modes captured. "req" is one
request's decode rate after its first poll; "total" is all tokens over wall time.

A100-80GB:

| corpus | B | K=0 req | K=0 total | DFlash req | DFlash total | accept | speedup |
|---|---:|---:|---:|---:|---:|---:|---:|
| math | 1 | 128.5 | 124.2 | 321.8 | 286.0 | 4.27 | 2.30x |
| math | 2 | 113.1 | 194.4 | 279.4 | 456.6 | 4.48 | 2.35x |
| math | 4 | 101.7 | 336.8 | 244.7 | 686.7 | 4.34 | 2.04x |
| math | 8 | 94.8 | 630.7 | 242.0 | 1247.3 | 4.43 | 1.98x |
| math | 16 | 81.0 | 950.1 | 194.1 | 2116.6 | 4.41 | 2.23x |
| raw | 1 | 127.3 | 123.8 | 240.8 | 222.8 | 3.26 | 1.80x |
| raw | 2 | 112.0 | 217.0 | 188.5 | 351.1 | 3.02 | 1.62x |
| raw | 4 | 95.4 | 369.8 | 162.8 | 466.8 | 2.73 | 1.26x |
| raw | 8 | 84.7 | 658.3 | 162.8 | 831.9 | 2.76 | 1.26x |
| raw | 16 | 78.4 | 1211.9 | 173.3 | 1590.3 | 3.41 | 1.31x |

H100:

| corpus | B | K=0 req | K=0 total | DFlash req | DFlash total | accept | speedup |
|---|---:|---:|---:|---:|---:|---:|---:|
| math | 1 | 146.6 | 137.0 | 400.6 | 324.6 | 4.17 | 2.37x |
| math | 2 | 129.2 | 232.4 | 382.3 | 523.2 | 4.60 | 2.25x |
| math | 4 | 122.2 | 389.2 | 358.0 | 955.1 | 4.22 | 2.45x |
| math | 8 | 113.0 | 717.0 | 345.6 | 1934.1 | 4.56 | 2.70x |
| math | 16 | 107.5 | 1153.0 | 302.9 | 2966.2 | 4.44 | 2.57x |
| raw | 1 | 144.9 | 136.6 | 310.0 | 270.8 | 3.35 | 1.98x |
| raw | 2 | 134.2 | 257.4 | 284.8 | 492.0 | 3.35 | 1.91x |
| raw | 4 | 116.3 | 435.3 | 211.6 | 677.1 | 2.65 | 1.56x |
| raw | 8 | 103.7 | 788.3 | 233.2 | 1093.6 | 2.86 | 1.39x |
| raw | 16 | 102.1 | 1521.8 | 225.2 | 2000.4 | 2.94 | 1.31x |

No preemption in any cell. Every B is one run, and eager tok/s has moved about 10% run to run
before (NOTES-attn), so read the tables to roughly 10%.

One DFlash step, ms (GPU time of the phases captured as separate graphs over the same static
buffers; "outside" is step wall time minus whole-graph GPU time: host checks, H2D, D2H):

| | draft | target (fill+forward) | accept | inject | whole graph | outside | wall |
|---|---:|---:|---:|---:|---:|---:|---:|
| A100 B=1 (T=8,R=8) | 3.07 | 8.72 | 0.22 | 0.48 | 12.46 | 0.62 | 13.08 |
| A100 B=16 (T=128,R=16) | 3.72 | 16.52 | 0.35 | 0.54 | 21.11 | 0.65 | 21.76 |
| H100 B=1 | 1.92 | 6.52 | 0.15 | 0.35 | 8.92 | 0.52 | 9.43 |
| H100 B=16 | 2.06 | 10.13 | 0.22 | 0.37 | 12.77 | 0.51 | 13.27 |

The draft takes about 22-25% of a B=1 step; host plus copies about 5%. The target verify at
T=8 (8 rows) costs about what a K=0 decode step does (H100: 6.5 ms GPU vs 6.8 ms wall per K=0
token), so a step's speedup is about accept x (K=0 step / DFlash step).

## Reproduce

    cd ~/research-2/worktrees/dflash-graphs
    M='uv run --frozen --project kelpie/kelpie-http kelpie remote --volume kelpie-a1 --model openai/gpt-oss-20b --model z-lab/gpt-oss-20b-DFlash --gpu H100 --'
    $M 'HF_HUB_OFFLINE=1 python -m scripts.prove_dflash --corpus math --max-new 256 --loop native --capture --base spec'
    $M 'HF_HUB_OFFLINE=1 python -m scripts.check_spec_teacher_forced --loop native --corpus math --max-new 256 --capture'
    $M 'HF_HUB_OFFLINE=1 python -m scripts.prove_dflash --loop native --corpus math --max-new 256 --batched --require-preemption --num-slabs 160 --max-batch-tokens 37 --capture'
    $M 'HF_HUB_OFFLINE=1 python -m scripts.bench_spec --profile --out /data/dflash-graphs/bench-h100.json'

## Judgement calls

- **The core pads decode_extra's request axis (kelpie-core `reqsPadded`).** The graph is keyed by
  the token bucket (the user's choice), but R_padded varied within one token bucket (a degraded
  plan has more entries), and every [R] tensor of the target and the drafter needs one R per
  graph. Options were: Python pads further (a second pad writer; shapes.py forbids it), key the
  graph by (T, R) (several graphs per key and eager fallbacks), or the core pads R by T.
  Picked the core: R = min(bucket(T - 1), bucket(max_batch_reqs at create)). An entry with extra
  rows is >= 2 rows, so n_reqs <= T - 1. The cap is the plan buffers' size, fixed at create, so
  a live `max_batch_reqs` change cannot move it. stepShape's R bits now carry the padded count.
- **The drafter runs over EVERY padded slot (agreed design), so it pays for masked slots.** At
  B=1 the key is T=8, so R=8 and the drafter runs 64 rows where 8 would do. The target's lm_head
  also gathers R x (1+K) tail rows. Measured cost: see the step breakdown (draft 3.1 ms of 12.5
  at B=1 on A100). The alternative is a compacted drafter axis D = T // (1+K) (argsort drafting
  entries, scatter drafts back) plus the target keyed by (T, R). That is a design change, not
  made here; it is the first thing to try for B <= 4.
- **One program for every family.** `verify` runs the same code eagerly (prefill in the batch,
  the decode family) and under a graph (decode_extra). There is no branch on batch contents: the
  drafter also runs, fully masked, on steps where nothing drafts. That keeps warm == serve and
  eager == captured (proof 1 below is bitwise). The cost is a wasted drafter pass on prefill and
  degraded steps, which are all eager and rare.
- **"Drafting" means n_extra == K.** A synthetic entry with 0 < n_extra < K (buckets below 1+K,
  which DFlashStep never reaches) is masked, and its extra rows verify drafts of token 0. That is
  still exact, and it removed `DFlashStep.warm`'s target-only special case. Real plans assert
  n_extra in {0, K}, and every drafting entry is 1 + K rows.
- **All decode_extra keys are captured, T=2 and T=4 included,** though K=7 cannot reach them
  (dead graphs, cheap). The decode family (every entry's extras dropped) and prefill stay eager.
- **The masked-slot write target is the core's scratch slot, read off a synthetic plan in
  `build`** (`_scratch_slot`), not recomputed as block_size - 1. check_dflash_drafter (no core)
  hardcodes bs - 1 and says so.
- **inject runs over all T_padded rows** (pad rows onto the scratch slot, by padPlan). Before, it
  ran over n_tokens real rows: a host slice, and non-bucket shapes on the eager path.
- **Draw is static too.** `decide.draw_into` copies sampler inputs in place and asserts the
  host switches (all_greedy, max_top_k) match the ones baked in at capture.
- **Graphs share one memory pool** (largest key first); each step reads its output before the
  next replay. `Built.stepper` is now a field: the DFlashStep that warmed is the one holding the
  graphs. `Built.step` stays the bare target, so hand loops are unchanged (and eager).
- **`build` still refuses compile with a drafter.** A drafter build on CUDA captures by default
  (`capture=None` means capture on CUDA), as a target-only build does.

## Uncertainties

- **Split-KV (3D) attention at q_len 8.** With the new padding, decode_extra T=8 and T=16 have
  T == R, which the vLLM adapter reads as "decode" and routes to the 3D kernel with 8-row
  queries. On main those plans had R=1 or 2 and took the 2D path. The adapter notes say 3D is
  correct for any query length, and B=1 math at 256 tokens (exactly the T=8, R=8 key) passes the
  teacher-forced gate (worst 1.0 bf16 steps). But bench_attention has no T == R with q_len > 1
  case. Worth adding.
- **Why is the draft 3 ms?** The drafter has 8 small layers plus a lm_head over R*(1+K) rows
  (1.16 GB of weights read once). 3.1 ms at T=8 and 3.7 ms at T=128 on A100 is flat in batch, so
  weight reads plus launches dominate, not rows. Not profiled per kernel.
- **Raw-corpus acceptance at B=4/8 (2.7) is lower than at B=1 (3.3) or B=16 (3.4).** The cells
  cycle 5 prompts, so B=4 drops the easy "1 + 1 = 2" prompt and B=8 duplicates the hard ones.
  That comes from the corpus mix, not the batch size.
- **P3 vs K=0: 7/8 near-ties (<= 8 bf16 steps).** Same as eager on rung0 (1 exact + 7 ties).
  Captured == eager exactly was shown unbatched only.

## Papercuts

- A core change means a fresh libkelpie build on Modal: `box.setup.libkelpie` took 229 s the
  first time per core sha.
- `bench_spec --out` crashed the first A100 run after printing (the /data dir did not exist).
  Fixed; the A100 table is from stdout.
- Background shells are blocked; Modal runs go through tmux plus a wait loop, as before.
- `uv run` rewrites kelpie-engine/uv.lock; restored before each commit.
- Pre-existing on main: `check_core_loop.py --native --replay` asserts wire version 1 while the
  core sends 2 (inputs.zig wire_version); `check_run_wrapped_step.py` still expects run() to
  refuse drafter=. The by-hand `check_core_loop` passes on this branch.
- The local sglang checkout used for reference had an empty working tree (every file a staged
  deletion); it was read via git archive.
