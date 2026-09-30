# Deterministic legal full-battle differential gate

`manifest.json` records legal six-member teams, independent battle and choice-
policy seeds, expected natural termination lengths, explicit coverage
dimensions, and typed semantic witnesses. `generate.js` asks the
pinned Showdown oracle for legal choices at every request and emits the ordinary
native differential case schema. `run.js` batches those cases into a temporary
native runner, compares every stable boundary, repeats both executions, and
deletes the temporary build.

Run:

```sh
node verify/random-battles/run.js /path/to/pinned-observer-patched-showdown
```

Or run the verifier contract suite (minimizer, bounded subprocesses, retained
artifacts, coverage, team-pool recombination, promotion probing) and campaign
together. This is the checkpoint-7 gate:

```sh
make -C verify/random-battles test \
  SHOWDOWN_DIR=/path/to/pinned-observer-patched-showdown \
  SUMMARY=/tmp/gen3-random-summary.json
```

`POKEMON_VERIFY_TIMEOUT_MS` bounds every verifier subprocess (120 seconds by
default). A timeout is an explicit failure with the command, deadline, exit
status, and signal recorded in the error. `SUMMARY`, or equivalently
`POKEMON_RANDOM_SUMMARY`, requests a deterministic JSON success summary with
the pinned revision, manifest digest, case/decision/boundary counts, output
digests, replay status, ingredients present, actual semantic observations, and
the disposition of every declared witness. Merely carrying a move, ability, or
item on a team does not count as exercising it. Witnesses must match agreed
boundary records and can require evidence across multiple cases and team
pairings. Raw decisions and trace-line counts never substitute for witnesses.

The selector vocabulary is deliberately small: request, choice, queue, event,
PRNG, handler, condition, effect, and terminal records. Negative claims and
observer surfaces outside this vocabulary belong in focused fixtures rather
than being inferred from aggregate absence.

On a semantic divergence, the runner first retains the complete original case,
both source teams, and the original oracle/native JSONL. It then adds the
causal-prefix case and its independently replayed JSONL. If minimization itself
fails or times out, the original evidence remains and the failure metadata
records that minimizer error.

Failures before comparison are retained too. Generation, timeout/nonzero/spawn,
malformed-output, replay, and coverage failures produce a structured directory
under `FAILURE_DIR` containing the manifest, source teams, the current generated case when
available, captured oracle/native output, and lossless subprocess status,
signal, deadline, timeout flag, stdout, and stderr. Existing directories are
never overwritten. Validate the metadata and every retained payload digest with:

```sh
node verify/random-battles/replay-artifact.js FAILURE_DIR/ARTIFACT
```

The command reports whether an artifact is validation-only or contains a
differential case suitable for semantic replay. Semantic mismatches continue to
use the richer causal-prefix artifact and minimizer described above.

The submitted C/Ocean runtime has no Node or Showdown dependency. Both are
verifier-only. Reaching the decision cap is an error; only natural terminal
results enter this manifest. The choice-policy LCG is independent of battle
randomness and is identified in each generated case rather than represented as
Showdown's `RandomPlayerAI`.

## Legal-team recombination

`team-pool.json` is a checked-in pool of 17 canonically packed sets taken from
the three already-supported source teams named in the file. `team-pool.js`
selects six entries without replacement for each side, so duplicate species are
unrepresentable inside a generated team. It then asks the pinned Showdown
`gen3ou` validator to accept the complete team; rejection is a hard error rather
than a retry or fallback.

`recombination-manifest.json` records a campaign-order seed, two team-selection
seeds, the four-word battle seed, and the choice-policy seed separately. The
campaign seed only orders cases, and the team-selection streams cannot consume
battle or policy randomness. Generate and
inspect the legal teams with:

```sh
node verify/random-battles/recombine.js \
  /path/to/pinned-showdown \
  verify/random-battles/recombination-manifest.json
```

`test-team-pool.js` generates the complete campaign twice and requires byte-for-
byte identity, independently validates every emitted team with pinned Showdown,
proves every pool entry came from a declared source team, and exercises honest
rejection of undersized, inconsistent, and illegal pools. These are verifier
inputs only; they do not change or replace the existing four-battle,
405-boundary differential campaign until recombined battles have separately
passed the full native boundary gate.

Materialize a promotion candidate in a new directory with:

```sh
node verify/random-battles/probe-recombined.js \
  /path/to/pinned-observer-patched-showdown \
  verify/random-battles/recombination-manifest.json \
  /tmp/gen3ou-recombined-campaign
```

The probe writes each selected team and a standard random-battle manifest v2.
Expected decisions and boundaries come from natural Showdown termination through
the same `generate()` function used by the differential campaign. Hitting the
1,023-decision cap fails without publishing the output. The complete directory
is built beside the destination and renamed into place only after every battle
terminates; an existing destination is never replaced. Run the candidate
without modifying the checked-in campaign:

```sh
node verify/random-battles/run.js \
  /path/to/pinned-observer-patched-showdown \
  /tmp/gen3ou-recombined-campaign/manifest.json \
  /tmp/gen3ou-recombined-failures \
  /tmp/gen3ou-recombined-summary.json
```

`checkpoint7-report.json` retains the compact success evidence for the gated
four-battle campaign: manifest and output digests, exact totals, replay status,
coverage dimensions, and the invariant/minimizer contracts. The detailed
63-KiB observation summary remains reproducible output rather than checked-in
bulk data.
