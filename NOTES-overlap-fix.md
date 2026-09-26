# NOTES: overlap re-plans an in-flight prefill (branch core/overlap-prefill-fix)

Bug: NOTES-rung0.md, "Pre-existing overlap bug, NOT fixed". Under overlap, plan N+1 is built
between launch_async(N) and launch_wait(N). `reserveAhead` only handled decode entries, so N+1
planned an in-flight prefill chunk again, at the same positions. The second commit then
over-advanced (`request.zig:288`, `assert(n <= nWork)`).

Invariant: a row is never planned twice while it is in flight, and positions always come from
committed + in-flight counts.

## Shape of the change

```
plan (building ahead)
  reserveAhead
~   every entry of plan N: n_computed += n_work; n_in_flight = n_work     (was: decodes only)
~   an emitting entry (decode OR prompt-completing chunk): placeholder at tokens[n]
  planRunning / planWaiting    unchanged: they plan from n_computed, which now includes in-flight rows
  emitEntry
+   assertNotInFlight: start == live seq_start + n_work of its N entry; else n_in_flight == 0
commit(N)
  commitEntry
~   n_in_flight > 0: skip request.advance (already counted); zero n_in_flight
~   cancelled: unwind if n_in_flight > 0 (was: if reserved), free blocks, strike from N+1
```

```
kelpie-core/src
~ request.zig      + Request.n_in_flight (rows of the plan in flight counted in n_computed)
~ scheduler.zig    reserveAhead, commitEntry, + assertNotInFlight (called from emitEntry)
~ trace_test.zig   + `expect ahead_rows` (expect rows, read from the ahead plan)
~ c_api.zig        overlap race test: 1-token prompt cap removed
kelpie-core/traces
+ overlap_prefill_whole_in_flight.txt    the NOTES-rung0 repro
+ overlap_prefill_chunks_pipelined.txt   steady state: plan N+1, commit N, plan N+2, ...
+ overlap_cancel_prefill_in_flight.txt   cancel with prefill chunks in both plans
+ overlap_cancel_ahead_only.txt          cancel of a request only N+1 names (review finding)
~ prefill_then_decode_overlapped.txt     pinned the old behaviour (diff explained in d2e3696)
```

## Reference engines (checkouts in ~/research-2/tmp/refs; vllm 7f1a539, sglang efff836, tokenspeed 909e6b5)

None of them skips the request. All three plan the next chunk, starting where the in-flight
chunk ends, because progress moves forward when a chunk is scheduled, not when its result lands.

- vLLM v1: `vllm/v1/core/sched/scheduler.py` `Scheduler._update_after_schedule` does
  `num_computed_tokens += num_scheduled_token`. The comment there says this is "allowing us to
  schedule the prefill request again immediately in the next scheduling step". In `schedule()`,
  `num_new_tokens = num_tokens_with_spec + num_output_placeholders - num_computed_tokens`.
  `vllm/v1/core/sched/async_scheduler.py` `AsyncScheduler._update_after_schedule` adds output
  placeholders only when the request is not `is_prefill_chunk`, so the chunk that completes the
  prompt gets one. Our placeholder rule is the same.
- SGLang: `python/sglang/srt/managers/scheduler.py` `event_loop_overlap` plans N+1 before it
  processes N's result. `get_next_batch_to_run` calls `stash_chunked_request`, then
  `RadixCache.cache_unfinished_req` moves `chunked_req.prefix_indices` past the in-flight chunk.
  After that, `schedule_policy.py` `PrefillAdder.add_chunked_req` does
  `set_extend_range(len(prefix_indices), ...)`.
- TokenSpeed: `docs/design/event-loop.md`, "Principle 4: correctness never depends on the
  in-flight depth". A request becomes PrefillDone when its last chunk is scheduled, not when it
  is committed.

## Results

| proof | result |
|---|---|
| red commit f621b55: each new trace alone, old scheduler | all 3 fail (N+1 plans A:10, or rows 0..3 again) |
| zig tests after the fix (+4 traces) | 69/69; every pre-existing trace except prefill_then_decode_overlapped is byte-identical |
| overlap race test, multi-token prompts, old scheduler | panic at request.zig:288 `advance` |
| same test, fixed, seeds 100..115 (temporary edit), binary run 300 times | 300/300 pass (4800 overlap races) |
| in-flight prefill entries hit by the test suite (temporary print) | 1189 partial multi-token chunks, 1433 multi-token chunks that complete a prompt, 200 one-token |
| check_core_loop --native, 16 seeds x 4000 | 16/16 PASS |
| check_core_loop --native --replay, 16 seeds x 4000 (rebased onto core/replay-fix) | 16/16 PASS |

## Judgement calls

- **Advance, not skip.** The brief allowed either one. All three reference engines advance, so
  the ahead plan does real work on a chunked prefill and does not stall it for a step.
- **Chunks that complete the prompt are reserved.** They emit a token, so N+1 plans the decode
  behind them with the placeholder, as it already did for decodes (vLLM does the same). This
  changes `expect reserved A false` to `true` in prefill_then_decode_overlapped.
- **`n_in_flight` is a new field. I did not reuse `pending_token`.** A partial chunk has no
  placeholder, but commit still has to know not to advance it again.
- **The invariant is checked in `emitEntry`,** where positions are written. The brief said
  "in the scheduler", and this is the one place every planned row passes through.
- **`reserveAhead` now asserts `!planned_ahead`, where it used to skip.** Nothing sets it
  between commit and the next ahead build: the promote loop and commitEntry both clear it.
- **check_core_loop has no overlap mode.** Its `Engine` registers only a plain launch, and there
  is no Python split-launch path. The 16-seed overlap run is the Zig race test instead
  (Recording + follower loop replay, with every digest matching). I did not commit the 16-seed
  version. The committed test keeps seeds 3 and 4, as before.
- **The red commit had one wrong expectation.** `expect free 8` in the cancel trace should be
  7, because block 0 is the null block. It is corrected in the fix commit, and that commit says
  so.

## Uncertainties

- ~~`check_core_loop --native --replay` fails for every seed~~ Resolved on core/replay-fix
  (this branch is rebased onto it). The oracle was wrong, not the core: since 54d28a7, a submit
  cancelled before its boundary is dropped and never reaches any rank, and the oracle counted
  occupants per id. It now matches them by (id, generation), and the script refuses a stale
  libkelpie. After the rebase: 70/70 Zig tests; --native --replay 16/16 PASS.
- No real device path consumes overlap yet. A GPU launch_async implementation will have to
  scatter N's sampled token into N+1's placeholder row for every emitting entry, including a
  prompt-completing prefill, not only for decodes. `refreshOpaque` already mirrors every
  `.decode` entry, and the entry behind a completed prompt is `.decode`.
- While an ahead plan exists, `seq.n_computed` includes rows that are not computed yet. Readers
  in that window (`slideOut`, `slabsNeeded`, `stallOf`) see the advanced value, which is what
  planning needs. Anything that later reads it as "KV written" during that window would be wrong.
  See the review below.

## Review (independent subagent, on f621b55..240b45a)

The review found no blockers in the fix. It confirmed these by running probe traces, then
deleted them:
- a cancel with the prompt-completing chunk in N and a reserved decode in N+1
- an eos on the prompt-completing chunk
- a runner that N+1 skips for budget after its chunk was counted
- a prefix cache hit that sees only committed rows
- the trace diff being legitimate: the old `expect batch` lines read the live plan (N), so
  they never checked N+1

Its findings:
1. **Should fix, also on main (now fixed, c6a9c99).** Cancelling a request that only the ahead
   plan named leaked its blocks, and `request.release` then asserted (`request.zig:543`).
   Red trace: `overlap_cancel_ahead_only.txt`. The cancelled branch now
   always frees blocks and strikes the ahead plan. Both are no-ops when cancel() already freed
   them. This is outside the bug I was asked to fix. I fixed it anyway because it is the branch
   I had just rewritten, and the multi-token overlap race now exercises it.
2. **Nit, not changed.** For window groups, `slideOut` in N+1 runs against the advanced
   `n_computed`. So it can free a window block that N's rows still read (with window 8, block 4
   and chunks of 4, it freed block 0 while row 8 of N reads positions 1..8). This is safe only
   because N and N+1 run in order on one stream, and a freed block is not reused until N+1
   writes. Before this fix the lag was 1 row; now it is a whole chunk. The same kind of
   assumption was already there for decodes. It needs a comment or an assert once a real
   overlapped device path exists.
3. **Nit, not changed.** `close()` from `cancel()` records `event.n_gen` with the placeholder
   still in the history, so it is one too high. This was already true for decodes, and now also
   happens for chunks that complete the prompt.

The reviewer suggested making the probe traces permanent (eos, budget skip, window). I did not
add them.

## Papercuts

- `uv run` in a fresh worktree creates `.venv` and rewrites `kelpie-engine/uv.lock`. I reverted
  it each time.
- check_core_loop needs `../scripts/zig build lib` first. `build test` does not produce
  `libkelpie.dylib`.
- The Zig test runner takes no `--test-filter` at runtime, and the trace test stops at the first
  failing file. To show each new trace failing on its own, I had to move the other files aside.
