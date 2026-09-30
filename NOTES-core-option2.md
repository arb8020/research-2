# NOTES: core option 2 (spec-agnostic core API)

Working notes for `kelpie/docs/design-core-option2.md` on branch `core/option2`. Section 8 of
the doc overrides earlier sections. Newest entries at the bottom of each list.

## Judgement calls (not covered by the doc)

- **Setup merge.** `core/kv-admission` conflicted in `scheduler.zig` (planWaiting reserve vs the
  drafts assert) and `c_api.zig` (both new tests). Kept both sides; `stallOf` and `slabsAt` now
  pass the draft arguments through. 57/57 tests.
- **Gate count.** The doc says "43 of 50 per_token traces"; after the kv-admission merge there are
  54 traces, 49 of them per_token-only. All 49 are untouched by step 1 (git diff shows only the 5
  per_seq traces changed, plus 5 new `state_*` traces). CORRECTION: "byte-identical" is relative
  to core/kv-admission (the merge base of this branch after setup), not main -- kv-admission
  itself changed two per_token traces and added four.
- **chunkFor grain = the FIRST per_token group's tokensPerBlock**, not the lcm over per_token
  groups. Section 8 item 8 says "over per_token groups only"; the lcm would re-chunk every
  multi-group per_token trace (`two_groups_*`, `per_group_block_size`, `stride_two_groups_*`),
  which the byte-identical gate forbids. What changed is only that a per_seq group 0 no longer
  disables alignment. A model of per_seq groups only gets no alignment.
- **per_seq `window` now means checkpoints kept** (ring size, `request.nCheckpoints`), K-independent.
  C config: per_seq `stride == 0` iff `window == 0`; window 1 is legal (was: >= 2 = live + ckpt).
  Trace DSL `stateS:C` = C checkpoints, default 1.
- **ZERO(g)** is allocated by `Scheduler.init` (one page of each per_seq group, held forever), not by
  the request pool; it is exposed as `plan.zero_units[g]`. `worstSlabs` counts it in the per_seq
  units so `ExceedsKvPool` stays exact for a lone request.
- **Overlap is refused with any per_seq group** (c_api `error.OverlapPerSeq`, scheduler asserts). The
  doc only says overlap stays off with extra rows; per_seq at K=0 with overlap would need the ahead
  plan to read plan N's write[0] before N commits. Not needed by anything today.
- **`ckpt_row` when no checkpoint = `request.no_row` (0xFFFFFFFF)**, with ckpt = SCRATCH. The op can
  compare rows to it unconditionally.
- **per_seq slot_mapping is 0 (the null page)** for now; the doc says per_seq gets no slot_mapping.
  The ABI export of the state indices lands in step 3.
- **keepRows runs before publishFull** so a checkpoint written this step is published this step. kept
  is computed before the partial-chunk early return (kept = 1 there).
- **freeState order**: pending, live, then the ring oldest-first, so the newest checkpoint (the most
  useful prefix) is the last to be reused off the LRU.
- **Step 1 already drives write[1..n_drafts] from the old draft path** (entry.n_drafts plays the role
  of n_extra), so `draft_k4_per_seq`/`draft_stop_mid_run` were rewritten onto the new units rather
  than left broken until step 2.
- **Step 2 carries the whole C side of the ABI** (c_api.zig, kelpie.h, abi_ids.zig): the core's commit
  shape changed, so the C boundary had to move with it to compile. Step 3 is the Python bindings.
  Between those two commits the Python bindings are stale (import smoke still passes; nothing
  calls kelpie_commit at import).
- **`next_extra` is rewritten by every commit** (0 = none) and read by the next schedule; a
  mid-prefill chunk's commit carries it too, and a runner skipped for budget keeps it. finish,
  cancel and preempt clear it (close() and request.preempt). A readmitted request's first entry
  never has extra rows (asserted in planWaiting).
- **Entry.n_work is history rows only** now (it included drafts before); `expect batch` prints
  `A:1+3` for extra rows. The trace harness defaults `next=` to Kmax for every entry (what a drafter
  does), `kept=` replaces `accepted=`, and `expect rows A [40@8,-@9]` shows no_token rows.
- **kelpie_commit validates everything before applying anything** (KELPIE_ERR_ENTRIES / COUNT /
  GRAMMAR); inside the core a bad commit is an assert. Grammar refuses n > 1 AND next_extra > 0.
  No ERR_NOT_OWNED / ERR_TOO_MANY (they belonged to `reserve`, which section 8 dropped).
- **Review of step 1 (subagent): no serious bugs.** Folded into step 2: c_api's per-page token
  storage now counts a per_seq stride (a S=64 checkpoint over block-16 attention would have
  overrun it); padPlan's per_seq pad slot is 0 (block_size - 1 underflowed for block 0);
  allocState asserts it took exactly newUnits pages (the post-schedule slabsNeeded assert was
  vacuous for per_seq); ring slide-out uses kv_pool.free like freeState.
- KelpieConfig's header field-id enum stopped at VOCAB_WORDS (pre-existing drift); added 18..21.
- **Merged main (0e675fe, `-Dcpu=baseline` + observe ContextVar parenting) and spec-decode/salvage
  through 1a05bc9 (6434768 alloc_kv cross-check, smoke_run_k0.py)** after step 2, per the
  coordinator. Both clean.
- **Engine.plan() closes an idle plan itself** (doc 2.4) and returns None; `run._drain` dropped its
  manual empty commit. `Engine.commit(tokens[R] or [R,S], n=None, next_extra=None)` replaces commit
  + commit_payload; it asserts KELPIE_OK and names the error.
- **Plan.max_extra** (Kmax) travels on every plan so a forward can size [R, 1 + Kmax, V] without a
  host sync; `Sampling.n_drafts` deleted; `Requests` gains n_extra / seq_start / emits / state.
- **check_core_loop.py is a mutation-tested oracle**: it caught both a wrong read unit (ZERO for a
  prefix hit) and a wrong kept unit (write[0] always), each within 300 steps. Its fake per_token
  pool stores the TOKEN at each slot and its fake per_seq pool a rolling hash of the tokens a
  state consumed, so "the read unit holds exactly hash(history[:seq_start])" is checkable.

- **Step 4, the critic's cheap check, as built**: check_dflash_drafter.py now runs each prompt a
  second way -- `inject_context_kv` alone, then `dflash.draft_logits` on a hand-built Plan whose one
  decode entry is [bonus, NO_TOKEN x 7] over the drafter group, i.e. the exact input builder loop
  (b) uses -- and requires max|diff| == 0 against the fused `dflash.forward`. The fused function is
  kept (it is inject + draft_forward) because the z-lab reference comparison still uses it.
- **Target logits are always [R, 1 + Kmax, V]** gathered at `Tokens.tail_rows` (derived once in
  to_device: min(last_row - n_extra + j, last_row)); `Host.max_drafts` is gone. Only gpt_oss (and
  toy_hybrid) read tail_rows; the other models gather last_rows, which is right while Kmax = 0.
- **`Step.forward_device(plan, tokens, requests)`** is the seam loop (b) needs: it drafts, scatters
  the drafts into the device input_ids at tail_rows[:, 1:], then runs the target. `Step` lost
  set_drafter / spec_decode_step / _drafter_inputs; `Step.last_logits` stays as a diagnostic
  (prove_dflash's tie report).
- **build(drafter=...) returns `Built(..., drafter=dflash.Drafter)`** and unpacks as
  `engine, target, drafter`; Kmax = drafter block size - 1. `run()` refuses a drafter (loop (b) is
  the caller's). `build(max_extra=K)` without a drafter is for a caller that fills extra rows itself
  (the toy lifecycle proof's oracle).
- **Accept rule = argmax of the target at every tail row** (`sdk/accept.py`): an accepted draft IS
  the target's choice at its row, so tokens = choice and n = 1 + matching prefix. No host sync until
  the single D2H of (tokens, n). Greedy only, like verify.py was.
- **Recurrent / compressor per_seq windows are K-independent** (Window(n_snapshots) and
  Window(2)); reference_kv_layout accepts per_seq groups (opaque members, block 1).

- **Build's warm pass samples with the K=0 sampler**, so `Step.sample` now samples tail row 0 only
  (`logits[:, :1]`); extra rows' logits belong to the caller's accept rule. First prove_dflash run
  died on this.
- **Review of steps 2-4 (subagent): no serious bugs.** Folded in: prove_dflash stats count what
  the core KEPT (poll), not what accept said (a stop/max_new cut inflated the last step);
  `dflash.step` raises on T > 0 (it accepts greedily); `run(drafter=...)` raises ValueError
  instead of a bare assert; `kelpie_commit` with no plan in flight returns ERR_ENTRIES instead
  of tripping the scheduler assert. Not changed: a finishing request's last accepted rows are
  never published to the prefix cache (publishFull runs before the append) -- a small reuse
  loss, not correctness.

- **Step 5 found a pre-existing aliasing bug in `kv.group_views`**: `as_strided`'s storage_offset
  is absolute in the storage, so every group's view started at the ARENA's first byte, not its own
  region. Invisible while every group of an arena has the same page size (group-local ids come from
  distinct slabs, so equal-size pages never overlap -- gpt-oss's two groups, and the drafter lives
  in its own arena), but the toy's 512 B per_seq units aliased its 1024 B attention pages: writing
  state unit 7 overwrote attention page 3 row 4. Fixed (add the slice's storage_offset); a tensor
  check confirms two groups' views are disjoint. CORRECTION: the bug was real but never bit on
  main -- the only multi-group models with unequal pages (DSV4, Kimi) raise NotImplementedError
  before allocating, and every model that runs has equal page sizes.
- **Pre-existing slot leak**: build's warm request finished but was never polled, so its request
  slot was never released (one slot lost per engine). `_warm` now polls it. prove_dflash never hit
  it (one request at a time, 8 slots); the toy proof hit `Full` with 6.
- **Toy stop tokens**: with random weights eos is never the argmax, so half the toy requests get
  a per-request stop token taken from their own greedy continuation (2..11 tokens in); that is what
  makes stops land mid-block (`stopped_mid_block=66` at K=3).

## Results (Modal A100-80GB unless noted)

| proof | result |
|---|---|
| zig tests (60 trace files, 49 per_token untouched) | 57/57 |
| check_core_loop, 4 seeds x 4000 steps (local, no model) | PASS, mutation-tested |
| check_dflash_drafter split vs fused | max\|diff\| = 0 on 6/6 (fp32 + bf16) |
| prove_state_lifecycle K=0 / K=3 (A10G, cpu) | ALL PASS, 1718 / 3271 tail logits exact |
| teacher-forced gate, math 256 | PASS, accept 4.38, worst 1.0 bf16 step |
| teacher-forced gate, raw 64 | PASS, accept 2.44, worst 2.0 bf16 steps |
| prove_dflash math 256 | no FAIL, 3 near-ties (0, 0, 1 step), accept 4.19 |
| prove_dflash raw 64 | no FAIL, 3/5 exact + 2 near-ties, accept 2.33 (earlier run 2.65) |

Raw acceptance moves 2.33-2.65 between runs of the same code: "The capital of France is"
forks at a near-tie on token 1 (top1 == top2 in bf16) and the two branches draft very
differently (accept 1.85 vs 2.56). The K = 0 baseline itself is not run-to-run reproducible
at these ties (NOTES-spec-decode.md). Math (4.19-4.38) matches salvage's 4.31.

- **Review round 2 (merge blockers + should-fix), done:**
  - Extra rows no longer cause preemption: planRunning drops them (plain decode) when they do
    not fit memory; worstSlabs counts decode without them. Before, a lone request could preempt
    itself and loop. Pinned by traces/extra_drop_before_preempt.txt (mutation-checked).
  - Engine.submit refuses T > 0 when max_extra > 0 (dflash.step's refusal sat between plan and
    commit and wedged the engine).
  - kelpie_commit rejects kept NO_TOKEN / id >= vocab_size (KELPIE_ERR_TOKEN, new appended
    KelpieConfig.vocab_size); Python refuses negative ids before the uint32 cast.
  - KELPIE_ABI_VERSION 2 + kelpie_abi_version(), checked by _ffi.load: KelpieCommit changed size
    (40 -> 32) and field order, so "same offsets" never applied to it (it did to the plan,
    config and event renames).
  - Engine.commit raises CommitError on a bad status; run._warm raises instead of asserting,
    and the echo-model path cancels its warm request.
  - Six traces: window + extra rows (rejection, slide-out); cancel in flight with extra rows,
    in-place write[0] and a pending ckpt; drafting entry beside a prefill chunk that checkpoints
    mid-chunk; prefix hit then the first decode with extra rows; stop on a checkpointing step;
    drop-before-preempt.
  - check_core_loop: + window group, idle-leak check and mid-flight cancel (reviewer's
    ccl_mut.py), poisoning of a finished/cancelled request's live unit and non-full pages, a
    read-ownership rule (ZERO at 0 / own live at its position / a checkpoint at seq_start), a
    refused NO_TOKEN commit. Judgement call: pages are poisoned only if the request was in the
    plan just committed (a request absent from it may have been preempted, and its old table
    names pages someone else now owns); full computed blocks are never poisoned (the prefix
    cache may legitimately hand them out after free).
  - Mixed batches on the real model: prove_dflash / check_spec_teacher_forced --batched (the
    reviewer's diff) plus a preemption counter and --require-preemption.

## B1: mixed batches on the real model (Modal A100-80GB, 8 prompts = math + raw at once)

Budget: 64 (as suggested) never degraded an entry -- 8 drafters x (1 + 7) = 64 exactly; 60 and
36 neither: under running_first a request is admitted only when the leftover after the drafters
covers its first chunk, so the drafters admitted so far keep fitting. Degradation needs a SHORT
prompt admitted with a small leftover; so the batched runs queue math prompts first and use 37
(4 drafters = 32, leftover 5 admits a 5-token prompt, 5 drafters then need 40). The script's
`degraded` gate caught the vacuous 64/60/36 runs.

| run (budget 37) | mix | result |
|---|---|---|
| prove_dflash --batched, 2048 slabs, 128 new | mixed 11, mid-prefill 5, degraded 23 | no FAIL, 3/8 exact + 5 near-ties, accept 3.06 |
| teacher-forced --batched, 2048 slabs, 256 new (run 1) | degraded 41 | **FAIL 7/8 "Translate": tokens 13, 17 at 11.0 bf16 steps** |
| same config, runs 2, 3, 4 | degraded 38, .. | PASS, worst 2.0 / 2.0 / 1.0 |
| teacher-forced --batched, 160 slabs (forced preemption) | preempted 26, degraded 140, mixed 71 | PASS 8/8, worst 1.0 |
| CONTROL: same batch, K = 0 (--no-spec) | -- | PASS, worst 5.0 -- at "Translate" position 14 |

Reading of the one FAIL (uncertain): position 13 of "Translate to Spanish" is a three-way bf16
near-tie in every run on this branch (single-request prove runs chose 15681, 4705, 24005, with
gaps up to 6 steps); the four identical batched spec runs emitted different tokens there (the
reference kernels are not run-to-run deterministic); K = 0 batched alone moves the neighbouring
position by 5 steps. So I read 11 steps as batch-shape numerics at a known tie, not an index bug
-- the index-level oracles (check_core_loop, the toy's exact fp64 equality) are clean under the
same mixes. But the authoritative gate did fail once in four; a bitwise answer needs
batch-invariant kernels.

## Deviations from the doc

- The doc's T1 has a checkpoint "g5 row 1 (b=8)" inside an extra row; section 8 item 5 forbids
  that, so the rewritten extra_k3_per_row trace shows the boundary skipped (followed section 8).

## Uncertainties

- **Proof audit (subagent) remaining gaps, not fixed**: freed units/pages are never poisoned, so a
  read of a freed-but-not-yet-reused unit would still pass the oracles; the toy's state is read by
  clone, so an in-place kernel updating live (read == write[0]) is not modelled; cancel-while-a-
  plan-is-in-flight and plan-ahead are never exercised by the loops (lockstep plan/commit; the Zig
  traces cover them); "resumed from a mid-chunk checkpoint" is not counted separately (mid-chunk
  checkpoints are written and prefix hits happen, but their intersection is not asserted); the
  8-bf16-step tie gate scales with the top logit. Fixed from the audit: per-plan disjointness of
  write units / checkpoint units / slots across entries (both oracles), stronger exercised-gates,
  teacher-forced gate fails on zero acceptance.

- prove_dflash (and the teacher-forced gate) run ONE request at a time on the real model; mixed
  batches (a drafting entry next to a prefill or a budget-degraded one, several drafting entries)
  are exercised only model-free (check_core_loop) and on the toy (prove_state_lifecycle).

- With spec decode, a checkpoint boundary that falls inside ACCEPTED draft rows is never
  checkpointed (section 8 item 5: only history rows). The next step's seq_start is past it. So under
  spec decode the ring skips boundaries whenever acceptance straddles one; prefix hits on generated
  text get coarser. Correct, but worth knowing.

## Papercuts

- Background `Bash` is blocked by a hook (use tmux), and foreground `sleep` is blocked too; Modal
  runs go in tmux with a Monitor on the log.
- The first Modal run after merging `-Dcpu=baseline` rebuilt libkelpie on the volume (4.4 min
  setup); later runs hit the cache.
- `check_dflash_drafter` exits 1 on the pre-existing bf16 5/7 near-tie for "def fibonacci" (its
  ad hoc bf16 gate is >= 6/7); the new split-vs-fused lines are the part this branch gates on.
- `uv run` in kelpie-engine rewrites its uv.lock every time; I `git checkout` it before commits.
  Running scripts/test while a Modal run uploads the tree fails the upload ("uv.lock was
  modified during build process"): run them one after the other.
- Final re-check after round 2 (Modal A10G cpu): prove_state_lifecycle K=0 PASS (1718 exact),
  K=3 PASS (3102 exact; preemptions 31 -> 21 now that extra rows are dropped first).

- `uv run ruff check` reports 68 pre-existing errors across the three packages (advisory only).
- Trace ids are group-local but slabs are shared, so group 1's id N and group 0's id N are the same
  slab number: predicting ids by hand means tracking one shared LRU list.
- Two traces submitting with the default `base=1000` silently share prefix blocks (they dedupe at
  publish); caught me once in `state_preempt_recompute`.

## Frustrations

- (none yet)
