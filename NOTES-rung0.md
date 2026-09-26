# NOTES: rung 0 of the multi-GPU design (branch core/rung0-native-commit)

Spec: `kelpie/docs/design-multigpu.md`, section 2 (rung 0), with section 8 overriding it.
World-1 only: no world.py, no launcher, no NCCL or gloo. The sync seam (`kelpie_register_sync`)
and the plan digest are in place. At world 1 the seam is never registered, so exchange is the
identity and agree does not run.

## Shape of the change

```
step_loop.run (every step, every world size)
+ boundary_fn      [no lock]  inbox.drain -> batch words; exchange (world 1: skipped)
+ apply_fn         [lock]     validate whole batch; lagged checks; apply ops in order
~ plan_fn          [lock]     plan + fillPlan + planDigest
+ agree_fn         [no lock]  agree(digest) (world 1: skipped)
~ launch(plan, &StepOut)      the step fn writes n tokens per entry (ABI 3)
+ payload_fn       [no lock]  B4: rank 0's payload overwrites the StepOut (world 1: skipped)
~ commit_fn        [lock]     validateCommit (shared with kelpie_commit) + commit + ring
overlap: boundary + plan N+1 run between launch_async(N) and launch_wait(N)   (S5)
```

```
kelpie-core/src
+ inputs.zig      Inbox (own mutex) + id ledger (free/reserved/live, gen), wire format,
                  validate-then-Reader decoding, dropOp (test mutation)
~ c_api.zig       submit/cancel/set/swap/register_grammar -> inbox; poll pure; boundary/apply;
                  planDigest; validateCommit; agreePayload; register_sync; ~15 new tests
~ step_loop.zig   the phases above; wait modes (wake / heartbeat edge / follower none)
~ scheduler.zig   - KnobQueue; + submitAt, applyKnob, validateKnob(pub), release, rejectAt;
                  poll pure; commit() promotes an ahead plan's entries (bug fix, below)
~ request.zig     + acquireAt(id)
~ trace_test.zig  harness queues `set` and applies it at the next plan; releases after poll
~ abi_ids.zig     + KelpieStepOut, KelpiePlan.digest
kelpie-engine     _ffi (ABI 3), engine (Emitted, trampoline, commit(Emitted), edge/follow/wait,
                  cancel(gen), register_sync, Grammar), plan.digest
kelpie-models     Step/Echo -> Emitted; Captured.forward/sample/capturable + passthrough;
                  dflash.DFlashStep; Built.stepper; run() takes a drafter
scripts           check_core_loop (--native --replay --seeds); prove_dflash / teacher-forced
                  (--loop native); prove_dflash --require-preemption
```

## Results

| proof | where | result |
|---|---|---|
| zig tests (all trace files byte-identical; +15 tests) | local | 69/69; 300x stress hunt clean |
| check_core_loop by hand, 16 seeds x 4000 steps | local | 16/16 PASS |
| check_core_loop --native --replay, 16 seeds x 4000 | local | 16/16 PASS, every digest matches, oracles re-run on replay |
| teacher-forced --loop native, math, 256 new | Modal A100-80GB | PASS, accept 4.19 (4.41 before the review fixes), worst 1.0 bf16 step |
| prove_dflash --loop native --batched --require-preemption, 160 slabs, budget 37 (post-fix) | Modal | no FAIL: 1 exact + 7 near-ties, preempted 30, mixed 97, degraded 102, accept 3.48 |
| teacher-forced --loop native --batched, same settings (post-fix) | Modal | WARN-class gate: worst 1.0 bf16 step (8/8 within), preempted 30, accept 3.70 |
| smoke_run_k0 (capture=None -> Captured) gpt2 / qwen3 | Modal | ok / ok |
| check_serve (world-1 HTTP) | Modal | gpt2, echo, gpt_oss_tiny (== solo), stale_cancel: OK; smolvlm SKIP (not cached) |

Reproduce (worktree root; MR = `PYTHONPATH=. uv run --no-project --with modal --with requests
python kelpie/scripts/modal_run.py --gpu A100-80GB --volume kelpie-a1 --timeout 3600`):
```
cd kelpie/kelpie-core && ../scripts/zig build test
cd kelpie/kelpie-engine && PYTHONPATH=../.. uv run python ../scripts/check_core_loop.py --native --replay --seeds 4 --steps 4000
$MR --model openai/gpt-oss-20b --model z-lab/gpt-oss-20b-DFlash -- 'HF_HUB_OFFLINE=1 python -m scripts.check_spec_teacher_forced --loop native --corpus math --max-new 256'
$MR --model openai/gpt-oss-20b --model z-lab/gpt-oss-20b-DFlash -- 'HF_HUB_OFFLINE=1 python scripts/prove_dflash.py --loop native --corpus math --max-new 256 --batched --require-preemption --num-slabs 160 --max-batch-tokens 37'
$MR --model openai-community/gpt2 --model Qwen/Qwen3-0.6B --model openai/gpt-oss-20b -- 'HF_HUB_OFFLINE=1 python -m scripts.smoke_run_k0 gpt2 && HF_HUB_OFFLINE=1 python -m scripts.smoke_run_k0 qwen3 && HF_HUB_OFFLINE=1 CHECK_SERVE_CHILD=1 python scripts/check_serve.py'
```

## Left for later
- Grammar with extra rows (2.5 stage 0b, `kelpie_fill_extra_masks`): not built; still refused.
- The overlap multi-token-prefill re-plan bug (below).
- Rung 1: world.py, the launcher, gloo exchange behind the seam, draft broadcast.

## Judgement calls

- **Prompt staging.** A queued submit's prompt sits in an inbox-owned staging arena,
  `[max_requests * max_seq_len]`, indexed by id. The batch buffer is worst-case sized, so
  `apply_step` stays exact: a drain always takes every queued op and never caps. This costs
  about 2x tokens_storage more host memory. The alternative was staging the prompt in the
  core's slot memory, which was rejected: the step thread owns that memory.
- **Order of synchronous rejections kept exactly.** Draining, then ExceedsKvPool (only if
  the request fits max_seq_len), then Full, then TooLong. That is today's order.
  `n_rejected_full` is counted in the inbox and carried in the batch header, so every rank
  folds it into the same StepEvent.
- **A cancel is visible to poll at once.** The ledger's `cancel_queued` flag makes poll
  report cancelled before the boundary, as the old cancel-on-the-spot did.
- **No release lag, with one exception.** Without overlap, a cancel frees the ledger id when
  it is pushed (it releases immediately at apply). Under overlap, the in-flight plan may still
  hold the slot, so the ledger frees the id on `reconcile` after the core actually releases it.
- **S5's "defer to the next boundary" needed no new code.** A boundary runs before plan N+1,
  so the only plan in flight is N. `scheduler.cancel` already holds a planned slot until its
  commit.
- **S2 reject state is `cancelled`,** from new `scheduler.rejectAt`. The slot is kept until
  the edge's release, like any finished request. I did not add a new State.
- **Stale cancels need the caller's generation.** Ops carry (id, gen). The public id is
  still the slot id: HTTP's waiters match `record.advanced` slot ids, so the id cannot encode
  the gen. `kelpie_generation` and `kelpie_cancel_gen` give an exact cancel. A plain
  `kelpie_cancel` means "the current occupant". The HTTP handlers record `generation` right
  after submit and cancel with it (`app.cancel_on_disconnect`); check_serve row `stale_cancel`.
- **Header is 48 bytes, not 32.** It adds a `boundary` sequence number (S3's exactness; apply
  asserts plan step == boundary) and `n_rejected_full`.
- **Grammar.** `kelpie_register_grammar(key, handle, source)` goes into a registry with its
  own lock and condvar (capacity 256, no eviction). On the edge it also queues a
  `grammar_prepare` op. At world 1, applying that op does nothing. A submit that names an
  unregistered key waits up to 30 s at apply, then panics (B3). `kelpie_attach_grammar` is
  gone.
- **Grammar with extra rows is still refused (2.5 stage 0b not built).** It is refused at
  submit: -3, and `Engine.submit` raises. It used to be refused at commit, but a refused commit
  inside the native loop panics, so the refusal had to move earlier.
- **`Built.step` stays the target Step; `Built.stepper` is what `run()` runs.** For a drafter
  that is `DFlashStep`. The design said `Built(step = DFlashStep)`, but that would break every
  `engine, target, drafter = build(...)` hand loop.
- **Payload hash is stride-independent.** It covers per-entry count, next_extra and kept
  tokens only, so a hand loop committing [R, 1] and the loop's [R, 1 + K] StepOut hash the
  same.
- **Idle plans get a digest,** and agree runs once per plan, idle included. Payload agreement
  skips idle plans on every rank.
- **The edge sends its stop batch on close only in heartbeat mode** (a sync is registered).
  Under overlap with a plan ahead, the edge finishes that plan before stopping. This is only
  reachable once there are followers.
- **Captured.** Added `forward` (a replay when the shape was captured, else eager), `sample`,
  `capturable`, and `__getattr__` passthrough to the wrapped Step. `__call__` returns Emitted.

## Found along the way

- **Pre-existing overlap bug, fixed.** Under overlap, a request admitted by the AHEAD plan
  kept `planned=false` after that plan was promoted, and its commit asserted. So any submit
  landing mid-run under overlap crashed the loop. `scheduler.commit` now marks every entry of
  the promoted plan as planned. All traces still pass.
- **Pre-existing overlap bug, NOT fixed.** The ahead plan re-plans an in-flight multi-token
  PREFILL chunk against the not-yet-committed `n_computed`, so positions are stale; the second
  commit then over-advances and hits `assert(n <= nWork)` in `request.advance`.
  `traces/prefill_then_decode_overlapped.txt` pins this behaviour ("N+1 ... plans against
  n_computed 0 too"), and traces must stay byte-identical, so it is left as is. The overlap
  race test uses 1-token prompts, the only prefill that is sound today. Overlap is off by
  default and refused with extra rows. The user decides the fix, because it changes a
  byte-identical trace.
  Repro: save this as `kelpie-core/traces/zz_repro.txt` and run `../scripts/zig build test`.
  Both plans hold A's whole 10-token prompt at positions 0..9. The second commit panics at
  `request.zig:288 advance` (`assert(n <= nWork)`: n_work 10, nWork 1).
  ```
  config max_batch_tokens=16 max_batch_reqs=4 block_size=4 num_blocks=16 reserve_ratio=0 order=running_first eos=99 overlap=1
  submit A prompt=10 max_new=4
  plan
    expect batch A:10
  plan
    expect batch A:10
  commit
  commit
  ```
  The mechanism: `reserveAhead` reserves only decode entries. `planRunning`, building ahead,
  calls `chunkFor(n_computed)`, and plan N has not committed n_computed yet. So an in-flight
  prefill chunk is scheduled a second time, at the same positions.
- **A test-driver race, not an engine race.** One run in about 170 of the stress hunt hung.
  The poller read the "all submitted" counter after its pass, so the last submit could land in
  an id the pass had just seen free. It now reads the counter before the pass. After the fix:
  300/300 clean runs.

## Review (independent subagent, on b42a74d..69aca03)

Verdict: "not mergeable as rung 0 until 1 and 2 are fixed". Fixed in 54d28a7:
1. BLOCKER: without overlap, a cancel freed the id as soon as it was pushed. So submit+cancel
   pairs between two boundaries kept adding ops until the inbox overflowed, and each pair
   overwrote a queued prompt's staging. Now a cancel of a submit still in the inbox drops the
   submit op itself (B2). A submit that was drained but not yet applied still gets a FIFO
   cancel op.
2. An S2-rejected request that was then cancelled was never released. Now the cancel is its
   release.
3. check_core_loop's oracle poisoned pages from the previous occupant of a reused slot
   (flaky; seed 8 failed every time). Now a new occupant forgets the old one's entries.
   16/16 seeds pass in both modes.
4. The trampoline could commit stale StepOut tokens when n was larger than the number of
   columns the step returned. Now refused, and float tokens are refused too.

Also fixed: the `register_sync` partial-failure leak, and `Engine.cancel`'s return value.

Accepted, not changed:
- A bad payload from the native loop is now a panic, not a silent commit. This matches the
  design: validateCommit is shared.
- `n_rejected_full` shows up in the next boundary's StepEvent, not the current one's.
- Under overlap, cancelling a submit that was drained but not yet applied frees its id only
  after apply + reconcile. That is a small lag, overlap only.
- Grammar registry limits (see the Uncertainties section).

## Uncertainties

- The heartbeat, follower and stop-batch paths are compiled and exercised only through
  in-process tests (Recording / Replay, and the follower loop in the overlap test). There is no
  real multi-process exchange yet (rung 1).
- `applySwap` waits up to 30 s for a follower's swap registration (S6). No Python caller
  swaps today.
- Registry capacity (256) and grammar-source size (64 KiB) are guesses. Past either limit,
  `Engine.submit` fails with an AssertionError. Two grammars registered under one key keep the
  first.
- The batched teacher-forced gate's 8-step threshold is a guess, so its result counts as a
  WARN, not a PASS/FAIL. After the review fixes, its worst gap was 1.0 bf16 step, with
  preempted 30.

## Papercuts

- `uv run` in a fresh worktree rewrites `kelpie-engine/uv.lock` (+192 lines). A `git stash`
  around it then failed to pop. Reverted each time; not committed.
- `kelpie_submit` and friends now call `loop.wake()` themselves, so `Engine.submit`'s own wake
  was dropped. A caller of the C ABI no longer needs to wake after an input.
- The background-bash hook blocks `run_in_background`, so long jobs go through tmux.
