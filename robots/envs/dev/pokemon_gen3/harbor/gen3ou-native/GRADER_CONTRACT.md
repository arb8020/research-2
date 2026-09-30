# Grader contract

## Observable unit and boundaries

A case is `(manifest revision, normalized battle init, seed, legal choice
sequence)`. The verifier starts native and Showdown battles from the same case
and compares them at initialization, choice commit, before and after every
executed action, after every handler group, at every request boundary, and at
terminal resolution.

The serialized form and progress aggregation are fixed by `case.schema.json`
and `TEST_PARAMETERIZATION.md`. Those files also define provenance back to
pinned Showdown tests, seeded generation, feature/interaction attribution, and
the distinction between mapped, reached, and conformant behavior.

For each boundary the canonical comparison record contains:

1. phase and request kind for both sides;
2. normalized legal choices, including forced choices and waiting sides;
3. queued actions in execution order with kind, owner, target, effect, order,
   priority, speed, sub-order, and effect-order;
4. discovered event handlers in invocation order with event, holder, effect,
   handler, ordering keys, and relay result;
5. canonical battle state: field, sides, team order, active slots, immutable set
   identity, HP, PP, status, boosts, item/ability state, volatiles, counters,
   participation/faint flags, and pending faint/switch work;
6. ordered typed semantic events;
7. each PRNG draw with stable semantic label, pre-state, arguments, result, and
   post-state;
8. terminal flag, tie/winner, and empty post-terminal legal choices.

Every trace record has a monotonically increasing sequence number and semantic
boundary ID. The closed record algebra includes request, normalized choice,
queue insertion/order, action begin/end, discovered handler list, handler
begin/end with relay values, phase transition, labeled PRNG draw, mutation,
protocol event, faint-queue mutation, and terminal resolution.

The submitted engine exposes these records through a C verifier build mode.
The trace surface must be observational: compiling it out cannot change layout
of canonical state, control flow, queue/handler order, or PRNG consumption. The
Ocean adapter is graded through the production ABI, not test setters.

Equivalent states use manifest IDs and typed values, never Showdown object
addresses, JavaScript property order, nicknames, timestamps, or spectator-only
text. If Showdown emits presentation duplicates, the oracle projector maps them
to the same typed event algebra before comparison.

## Required verification layers

The verifier runs these deterministic layers in order:

1. **Build and API:** strict C build, ABI layout/version checks, generated-data
   reproducibility, real PufferLib-header compilation, and a binary dependency
   audit rejecting Node/Python/Showdown/runtime network access.
2. **Focused mechanics:** table-driven tests corresponding to applicable pinned
   Showdown Gen 3 tests, including explicit seeds or forced random outcomes.
3. **Boundary differential:** public regressions and hidden cases compared at
   every observable boundary, not only at turn end.
4. **Full battles:** deterministic randomized legal play through terminal state
   on unseen legal teams and seeds.
5. **Coverage rotation:** deterministic generation that greedily rotates
   uncovered manifest features and interactions across species, moves,
   abilities, items, statuses, weather, side conditions, switching, and
   fainting.
6. **Replay and invariants:** replay every retained/generated case twice, check
   byte-identical records, and assert invariants after every transition.
7. **Robustness and performance:** malformed/out-of-manifest boundary rejection,
   sanitizer runs, capacity checks, long-run simulation, and vectorized Ocean
   throughput.

All randomness used to generate tests is seeded and its inputs are written to
the artifact. The verifier has no network. Test dependencies and the pinned
oracle are baked into its image.

## Invariants checked after every transition

- HP is in `[0, max_hp]`; faint, active, and replacement flags agree.
- PP and stat stages are in their declared ranges.
- exactly the legal active/bench topology exists for singles.
- every queue/handler/effect reference points to live bounded storage.
- request kind and legal choices are a pure projection of canonical state.
- a suspended forced replacement retains the untouched continuation queue.
- terminal state has a stable result, no request, no queue work, and no legal
  choices.
- capacities never truncate work or events; exhaustion is an explicit failure.
- state rejected as invalid or unsupported is unchanged.
- PRNG changes only through a labeled draw owned by the current semantic step.

## Hidden and anti-overfitting construction

Hidden cases are generated after the submission snapshot from withheld team
combinations, seeds, and legal policies. At least half of semantic cases must
exercise interactions absent as exact tuples from the public corpus. The
generator performs pairwise rotation across feature families and targeted
three-way recombination for stateful interactions such as weather + ability +
move, status + switch + cure, hazards + forced replacement + faint, and speed/
priority ties + residual ordering.

The verifier rejects code or data paths keyed by corpus filenames, hidden/public
markers, complete seed values, serialized teams, or exact choice prefixes. This
is a backstop, not the main defense: unseen recombination is the primary
anti-overfitting mechanism.

## Failure artifacts

On the first mismatch, timeout, crash, or invariant failure, `test.sh` writes a
self-contained directory below `/logs/verifier/first-divergence/` containing:

- source/oracle/manifest identities and build configuration;
- normalized teams, seed, and choices through the failing boundary;
- native and oracle before/after canonical records;
- queue, handler, phase/request, typed-event, and labeled-PRNG traces;
- the first unequal field and semantic boundary label;
- exit/signal/sanitizer output;
- a deterministic minimized case preserving the divergence signature, when
  minimization completes within its fixed budget.

Cleanup never deletes these artifacts. Minimization is not allowed to replace
the original evidence.

## Score and gates

The reward is the weighted sum below. `test.sh` writes
`/logs/verifier/reward.json` with numeric keys `reward`, `build_api`,
`semantic`, `coverage`, `determinism`, `robustness`, and `performance`. Each
section's raw numerator, denominator, and failures also appear in
`/logs/verifier/score.json`.

| Category | Points | Measurement |
| --- | ---: | --- |
| Build/API compliance | 10 | strict build, ABI, Ocean compile/run, dependency audit |
| Semantic conformance | 55 | focused and differential cases, weighted by boundary rather than trace length |
| Manifest coverage | 15 | required features have source/native/test/corpus mappings and are exercised |
| Determinism | 10 | duplicate replay equality and exact labeled PRNG staging |
| Robustness | 5 | invariants, invalid inputs, sanitizers, capacity and long-run tests |
| Vectorized performance | 5 | calibrated Ocean batch throughput and tail-latency floor |

Partial scores diagnose progress, but **completion** additionally requires all
of these hard gates:

- full Build/API and Determinism points;
- full 55/55 Semantic conformance points;
- zero semantic mismatch, unsupported transition, crash, sanitizer finding, or
  invariant failure in required public and hidden cases;
- every required manifest entry has nonempty authoritative source, native
  boundary, focused test, and differential-case mappings;
- every required feature is reached at least once, every required interaction
  group meets its declared coverage strength, and no `native_required` marker
  is reachable without a mapped handler;
- full battles terminate under the verifier's action and battle caps;
- overall score is at least 95/100 and performance earns at least 3/5.

A submission can therefore receive useful partial credit without being called
complete. Passing one finite corpus, or achieving 95 points while failing a
hard gate, is not completion.

## Performance protocol

Performance is measured only after semantic gates pass, using a production
optimized build with tracing disabled. The fixed Harbor CPU runs warm-up plus
five measured repetitions over 1,024 independently seeded Ocean environments.
The workload uses precomputed legal policies and reports median environment
transitions/second, p99 batch-step latency, peak resident memory per environment,
and deterministic output digest.

The original uncalibrated proposal was all of:

- median at least 100,000 decision boundaries/second;
- p99 latency at most 25 ms per 1,024-environment sweep;
- incremental resident memory at most 128 KiB per environment; and
- throughput at least 0.8x the verifier-owned frozen reference interpreter.

It must be reproduced and then frozen on the final Harbor image:

- the reference interpreter establishes the correctness baseline;
- an intentionally scalar ABI loop establishes the minimum acceptable floor;
- if 100,000 transitions/second exceeds 80% of the scalar baseline's lower 95%
  confidence bound, lower the absolute number during review rather than publish
  an impossible task;
- 3/5 is the floor, 4/5 and 5/5 are awarded at 1.5x and 2x the frozen floor;
- any output digest mismatch invalidates the performance result.

This calibration rule is part of the contract. A guessed machine-independent
steps/second number is not.

The retained candidate's OrbStack Linux/GCC 14 calibration on 2026-09-29 measured a
22,947.988 boundaries/s batch median, 57.987831 ms p99 sweep latency, and 80
incremental bytes per environment with deterministic digest
`261ecb091ca9cf07`. Therefore 100,000 boundaries/s and 25 ms are not defensible
absolute gates on that host. The candidate-only regression floor, calibrated
across quiet and contended runs of the digest-pinned container, is 15,000
boundaries/s, 150 ms p99, and 128 KiB incremental RSS. It is not frozen until
the same harness and digest are reproduced on the final Harbor worker and the
0.8x independent frozen-reference comparison is available. The candidate
calibration and still-pending reference obligation are deliberately separate;
see `verify/performance/orbstack-gcc14-calibration.json` and
`verify/performance/reference-contract.json`.

## Ocean terminal lifecycle

On the step that ends a battle, both agents receive `terminal=1`; winner and
loser receive `+1` and `-1`, and a tie gives both `0`. The adapter records the
episode log, immediately resets from its exact configured normalized init and
reset-seed sequence, and publishes the next episode's initial observation and
legal masks while retaining that terminal flag and reward for the completed
step. The following nonterminal step clears them. This matches the PufferLib
Ocean autoreset shape and makes replay/reset grading unambiguous.

## Precise definition of completion

“Complete Gen 3 OU” in this task means:

> For every `required` entry in the frozen supported-feature manifest, the
> submitted native interpreter accepts the manifest's normalized legal input
> domain and matches the pinned Pokemon Showdown revision on every observable
> boundary exercised by the deterministic public and hidden verification
> strategy, with no known counterexample, while satisfying all hard gates.

It does **not** mean every possible battle state was enumerated or formally
proved equivalent. New counterexamples remain bugs and must become minimized,
persistent regression artifacts.
