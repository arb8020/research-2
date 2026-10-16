# Asserts in practice: TigerBeetle source + matklad on invariants

Question: what should a reader's C env assert, and when, especially in a ~12-instruction `puf_step`
where 3 asserts on the action cost ~20% (390M -> 314M steps/s)?

Sources: TigerBeetle `main` at `c95d7a53` (2026-10-06), sparse clone at `/tmp/tigerbeetle-sparse`.
Paths below are relative to `src/` unless they start with `docs/` or `build.zig`. matklad posts are
linked inline.

Labels: **[TB]** = TigerBeetle's stated or visible practice. **[mk]** = matklad's writing.
**[inf]** = my inference.

## TL;DR

1. **[TB]** Asserts are tiered. A plain `assert` stays on in shipped binaries. A second tier,
   `if (constants.verify) assert(...)`, is off in release builds and on in Debug, tests and fuzzers.
   The policy is written down in `constants.zig:773-792`, quoted below.
2. **[TB]** Their cost budget: a 5% slowdown "might be deemed critical" in production. Tests
   tolerate up to 5x. Our 20% is over the production budget and well inside the test budget.
3. **[TB]** In hot loops, the default shape is O(1) asserts on the inputs before the loop and
   accounting asserts on the outputs after it. Inside the loop, an assert either costs almost nothing
   (it sits on a rare branch or is comptime) or it is gated by `verify`.
4. **[TB]** Data from outside the program (network, disk, client requests) is **not asserted**. It
   is checked and handled, and then the good case is asserted. Asserts are only for things our own
   code guarantees.
5. **[mk]** An invariant is a statement true on every run, so it "collapses away the time
   dimension". Write it down first, derive the code from it, then make it executable as asserts so
   fuzzing and exhaustive tests can check it.
6. **[inf]** For flappy: keep the always-on checks to the episode bound plus free compile-time
   checks. Put the per-step action check either behind a `VERIFY` flag or in one pass over the
   action buffer per batch. Do not delete it.

## What the current TIGER_STYLE.md adds beyond the user's copy

The user's `~/dotfiles/docs/raw/tiger_style.md` is mostly the **Safety** section. The current
`docs/TIGER_STYLE.md` has 511 lines. The extra parts relevant to asserts:

- **Performance, `docs/TIGER_STYLE.md:248-251`:** "A clear delineation between control plane and
  data plane through the use of batching enables a high level of assertion safety without losing
  performance." This is the main idea for hot paths.
- **`:260-263`:** "extract hot loops into stand-alone functions with primitive arguments without
  `self`". `lsm/compaction.zig:2042-2045` does exactly this, and those functions are still full of
  asserts (example 2 below).
- **`:431-433`:** functions should run to completion without suspending, "so that precondition
  assertions are true throughout the lifetime of the function."
- Pair assertions now link to the blog post
  [It Takes Two to Contract](https://tigerbeetle.com/blog/2023-12-27-it-takes-two-to-contract/).

I did not diff the Safety text line by line. The wording I spot-checked matches.

## Tiers: what is on where

| Tier | Mechanism | Release build | Debug / tests / fuzz |
|---|---|---|---|
| Compile time | `comptime assert(...)` (225 uses) | checked at build | checked at build |
| Always-on | `assert(...)` = `std.debug.assert` (8267 uses) | **on**: they ship `ReleaseSafe`, where a failed assert panics | on |
| Verify | `if (constants.verify) assert(...)` (71 uses) | **off** | on |
| Per structure | comptime parameter or runtime field, e.g. `verify_push` | off | opt-in |

Evidence:
- **Release mode.** `build.zig:89` prefers `ReleaseSafe`. `scripts/release.zig:313-318` checks that
  every shipped binary reports `ReleaseSafe` and `process.verify=false`.
- **Verify default.** `build.zig:196-198`: `config_verify` defaults to `(options.mode == .Debug)`.
  Test and integration builds force it to `true` (`build.zig:273,282`).
- **The policy**, verbatim from `constants.zig:773-792`:
  > TigerBeetle uses asserts proactively, unless they severely degrade performance. For production,
  > 5% slow down might be deemed critical, tests tolerate slowdowns up to 5x. [...]
  > In the control plane (eg, vsr proper) assert unconditionally. Due to batching, control plane
  > overhead is negligible. It is acceptable to spend O(N) time to verify O(1) computation.
  > In the data plane (eg, lsm tree), finer grained judgement is required. Do an unconditional O(1)
  > assert before an O(N) loop (e.g, a bounds check). Inside the loop, it might or might not be
  > feasible to add an extra assert per iteration. In the latter case, guard the assert with `if
  > (constants.verify)`, but prefer an unconditional assert unless benchmarks prove it to be costly.
  > In the data plane, never use O(N) asserts for O(1) computations --- [...] the overall coverage
  > is proportional to the number of tests run. Slow thorough assertions decrease the overall test
  > coverage.
- **Language safety checks are tiered too.** In two hot spots they turn off Zig's own bounds and tag
  checks: `@setRuntimeSafety(constants.verify)` in `lsm/binary_search.zig:74` and
  `@setRuntimeSafety(builtin.mode != .ReleaseSafe)` in `lsm/groove.zig:642`. Each has a comment
  saying why it is safe.

The last sentence of the policy matters even for tests: a slow assert means fewer fuzz runs, and
fewer runs means less coverage. Being in a test build is not a license to check everything.

## Representative examples

**1. Loop invariant in the hottest loop, gated by verify.** In `lsm/binary_search.zig:46-56`, the
binary-search loop invariant is asserted on every iteration, but only under `constants.verify`. It is
the same invariant matklad's post uses: everything left of `offset` is `< key`, everything right of
`offset+length` is `>= key`. The postconditions after the loop are also gated (`:117-140`).

**2. Hot data-plane loop: preconditions before, accounting after.** `lsm/compaction.zig:2112-2147`,
`values_copy_drop_tombstones`:
```zig
assert(values_source.len > 0);
assert(values_source.len <= Table.data.value_count_max);
... // tight loop; the only assert inside is on the rare tombstone branch, and it is comptime-known
assert(copy_result.consumed <= values_source.len);
assert(copy_result.produced == copy_result.consumed - copy_result.dropped);   // conservation
```
None of these are gated. They are O(1) per call and the call does O(N) work. "Produced equals
consumed minus dropped" is an accounting invariant: it is cheap and catches whole classes of bugs.

**3. Invariants on struct state.** `message_buffer.zig:54-65`:
```zig
fn invariants(buffer: *MessageBuffer) void {
    assert(buffer.suspend_size <= buffer.process_size);
    assert(buffer.process_size <= buffer.advance_size);
    assert(buffer.advance_size <= buffer.receive_size);
    if (buffer.invalid != null) { assert(buffer.suspend_size == 0); ... }  // implication
}
```
It is called at the start of operations (`:104,112`). `Replica.invariants()` (`vsr/replica.zig:1516`)
plays the same role at system scale.

**4. Boundary: handle untrusted input, then assert the good case.** `message_buffer.zig:132-158`:
```zig
if (!header.valid_checksum()) { buffer.invalidate(.header_checksum); return; }      // handle
if (header.size < @sizeOf(Header) or header.size > constants.message_size_max) {
    buffer.invalidate(.header_size); return;
}
assert(@sizeOf(Header) <= header.size and header.size <= constants.message_size_max); // restate
```
An unknown command does not trigger an assert. It calls `vsr.fatal(.unknown_vsr_command, "...
crashing for safety", ...)` (`vsr.zig:725`), which logs a message and exits with a reason code. That
gives three outcomes for "bad thing": **handle** (operating error), **fatal** (the environment is
unusable, so crash with an explanation), **assert** (our own bug).

**5. One function, two kinds of check.** `state_machine.zig:3590-3596`, `create_account`, runs once
per event in the hot path:
```zig
assert(timestamp_event != 0);                       // our code guarantees this -> assert
if (a.reserved != 0) return .reserved_field;        // client data -> result code
if (a.id == 0) return .id_must_not_be_zero;
```

**6. Pair assertions across the disk boundary.** Blocks already in memory are trusted and asserted
valid: `assert(block_header.valid_checksum())` (`vsr/grid.zig:805`). Blocks read from disk are
checked and handled: `if (!header.valid_checksum()) return .invalid_checksum;` (`vsr/grid.zig:1401`).
After that check passes, the size bounds the writer guaranteed are asserted again (`:1404-1405`).
Variable names mark which side of the boundary a value is on: `header_prepare_untrusted`
(`vsr/journal.zig:1459-1466`).

**7. Compile-time design checks.** `constants.zig:44-...` uses a `comptime { assert(...) }` block
with a long comment proving that the checkpoint interval keeps durability. Size checks such as
`comptime assert(@sizeOf(IdSeed) == 33)` (`vsr.zig:1321`) cost nothing at runtime.

**8. Expensive structural check made opt-in.** `queue.zig:96-101`:
`if (constants.verify and self.verify_push) assert(!self.contains(link));`. The O(N) duplicate check
is gated twice, with the comment "If the number of elements is large, the constants.verify check in
push() can be too expensive."

## Helpers beyond `assert`

- **`maybe(cond)`** (`stdx/stdx.zig:382-389`): "the dual of `assert`: it signals that condition is
  sometimes true and sometimes false." Its body is `assert(ok or !ok)`, so it checks nothing. It
  documents that both cases are expected and reachable, for example
  `maybe(self.status == .normal); maybe(self.status == .view_change);` (`vsr/replica.zig:902-904`).
  302 uses. It answers a reader's "can this be false here?" without a comment.
- **`comptime assert`**: checks relationships between constants and type sizes when the program is
  built.
- **`unreachable`** (697 uses): marks switch arms that cannot happen, such as deprecated enum values
  (`vsr/replica.zig:1822-1826`). In ReleaseSafe it panics.
- **`if (a) assert(b)`**: the implication form. matklad's
  [Asserting Implications](https://tigerbeetle.com/blog/2025-05-26-asserting-implications/) prefers
  it over `assert(!a or b)`.
- **`vsr.fatal(reason, fmt, args)`**: for environmental conditions that are not our bug but where we
  cannot safely continue. It logs a message and exits with a reason code.
- Density: about 8.3k asserts in about 158k lines of Zig, roughly 1 per 19 lines, tests included.

## matklad: thinking in invariants

The main post is [What is an Invariant?](https://matklad.github.io/2023/10/06/what-is-an-invariant.html)
(2023-10-06). Supporting posts:
[It Takes Two to Contract](https://tigerbeetle.com/blog/2023-12-27-it-takes-two-to-contract/),
[Asserting Implications](https://tigerbeetle.com/blog/2025-05-26-asserting-implications/),
[Random Fuzzy Thoughts](https://tigerbeetle.com/blog/2023-03-28-random-fuzzy-thoughts/),
[Generate All the Things](https://matklad.github.io/2021/11/07/generate-all-the-things.html),
[How to Test](https://matklad.github.io/2021/05/31/how-to-test.html).

The argument, distilled:
- **The bad way to get code right** is to find a failing example and "fumble with some plus or minus
  ones here and there", which "is slow, and doesn't allow discovering the problem before running the
  code."
- **The alternative** is to state precisely what must hold, then make each line keep it true. In his
  binary-search example, `lo <= insertion_point <= hi` must hold "on every iteration". The correct
  `mid + 1` follows from that rule instead of from trial and error.
- **Why it works:** "Invariants are powerful, because they are compressed descriptions of the
  system, they collapse away the time dimension". They "capture properties shared by all execution
  paths", so you reason about one statement instead of tracing many runs.
- **Three scales of "invariant":** a precise "math" way of thinking, as opposed to fuzzy thoughts; a
  technique for small code such as loops; and, for large code, "compact, viral, descriptive
  properties of the systems". An example of the last is "no allocation after startup".
- **Making it executable:** write the postcondition as an assert next to the code, then drive the
  code with every small input or with random input. "Depending on the assertion density and depth of
  the code under test, 'it does not crash' can cover quite a bit of ground!" (Random Fuzzy
  Thoughts.)
- **Where to put asserts:** "something is a real contract only when you have at least _two_
  assertions checking the relevant condition: you do one check at the call site, and one check at
  the definition site." (It Takes Two to Contract.)

The method as I'd summarize it **[inf from mk + TB]**: (1) name the state and what each field means;
(2) write the rule that holds after every operation; (3) derive the code from that rule; (4) assert
the rule at both ends of each boundary; (5) let a fuzzer or exhaustive small-input test find where
your understanding was wrong. matklad does not cover assert performance in his posts. The tiering
policy lives in `constants.zig`, and I could not confirm who wrote that comment.

## Translation to flappy's `puf_step` [inf throughout]

The function, from `rl/01-flappy.md:263-278`: `tick += 1`; `bird_row = actions[0]` (an implicit
float-to-int conversion); `reward = bird_row != pipe_row`; `terminal = tick >= episode_length`;
`episode_return += reward`; then either spawn a pipe or log and reset.

In TB terms, `puf_step` is data plane: an O(1) body called N times in a vectorized loop. `init` and
`reset` are control plane. The tiering rule maps over directly:

| # | Job | Candidate | Where | Hot-path verdict under TB practice |
|---|---|---|---|---|
| 1 | teaching | `_Static_assert(TOP == 0 && BOTTOM == 1, "action value doubles as row index")` | file scope | **keep**: free |
| 2 | teaching | `assert(tick <= episode_length)` after the increment, and `if (terminal) assert(tick == episode_length)` | step | **keep**: one integer compare on a value already in a register. It also asserts the negative space ("never overshoots"), which shows the `>=` could be `==` |
| 3 | teaching | `assert(tick == 0)`, `assert(episode_return == 0)` | end of `puf_reset` | **keep**: control plane. Pairs with #2 |
| 4 | debugging | `assert(episode_length > 0)`, and buffer pointers non-null | init | **keep**: control plane, runs once |
| 5 | debugging | accounting: `assert(episode_return <= tick)` | step, or the terminal branch only | keep it on the terminal branch, which is rare like TB's tombstone branch; **verify-gate** it if it is per step |
| 6 | debugging | `assert(pipe_row == TOP \|\| pipe_row == BOTTOM)`, `assert(obs[TOP] + obs[BOTTOM] == 1)` | end of `spawn_pipe` | **verify-gate**: per step, and it only re-checks our own code |
| 7 | debugging | `env_invariants(env)` covering all of the above | end of step | **verify-gate**, like `Replica.invariants()` |
| 8 | boundary | action in {TOP, BOTTOM} | see below | **move it, don't drop it** |

**The action check (#8).** TB's rule is: if outside data is wrong and it is not our bug, handle it;
if our own code produced it, assert. Here the policy and the sampler are the reader's own code in
the same training system, and no recovery makes sense (rounding 0.5 would hide the bug). So a crash
is the right outcome. The question is only where the check lives. Options, in TB style:
- (a) **Batch boundary**: the "O(1) assert before an O(N) loop" idea, adapted. One tight loop over
  the contiguous action buffer before the per-env step loop, or one numpy check per batch on the
  Python side. This is control plane amortized over the batch, as TigerStyle describes. It could
  plausibly be on always. **Unmeasured.**
- (b) **Keep it in `puf_step` behind `#if VERIFY`**: the literal `constants.verify` translation.
  Release builds pay nothing, and the reader's debug builds catch the 0.5 at the exact step.
- (c) **Make it cheaper**: replace the three asserts (two range checks plus `truncf`) with one
  `assert(action == TOP || action == BOTTOM)`. That is two float compares, and it also rejects NaN.
  I suspect much of the 20% is `truncf` plus three separate branches, but I **have not measured**
  this. Worth a quick bench before choosing between (a) and (b).

**C translation of the tiers.** C's `assert` has one switch, `NDEBUG`. PufferLib does not set it, so
`assert` acts like TB's always-on tier. For the second tier, add one macro, e.g.
`#if VERIFY  #define verify(c) assert(c)  #else  #define verify(c) ((void)0)  #endif`. Also, `maybe()`
is a nice teaching device for readers. For example, `maybe(reward == 0)` in the step says "dying is a
normal outcome here", where a comment would otherwise be needed.

**Teaching vs speed tension.** A teaching assert is worth having on the page even when it is
verify-gated, because the reader sees the rule either way. TB uses the same tool for both jobs: an
assert is documentation that a fuzzer can check.
