# Test parameterization and progress

Harbor packages and grades the repository's native solution; it is not expected
to have an agent solve the task end-to-end during routine development. A `nop`
agent run is the packaging smoke test. Semantic progress comes from submitting
the current source archive to the same verifier repeatedly.

## Canonical case

Every verifier scenario is a versioned `case.schema.json` JSON record. The
verifier owns a separately copied schema and validates each case before either
driver runs. Team export references are leaf filenames resolved only within the
verifier-owned case directory, and their ordered bytes are bound by
`normalization_digest = SHA256(team0 || NUL || team1)`. Its identity
is the tuple of oracle revision, normalized-team digest, battle seed, explicit
choices or seeded-policy revision, requested boundaries, and limits. The
verifier writes that complete record into every retained failure artifact.

The case records facts, not expected native output. Expected choices, queues,
handlers, state, events, PRNG draws, requests, and terminal resolution are
obtained from the pinned Showdown oracle during verifier-image construction or
the offline verifier run. This prevents stale golden output from silently
becoming a second oracle.

Each case names feature and interaction IDs from `supported-features.json` and
has one of five provenance classes:

1. `showdown-focused-test` translates a relevant pinned Showdown test while
   preserving its teams, setup, seed or controlled random condition, assertion,
   and authoritative source location.
2. `showdown-random-runner` mirrors Showdown's seeded legal-choice simulation
   and invariant/crash strategy.
3. `differential-regression` is a minimized persistent counterexample.
4. `coverage-generated` is selected by seeded feature rotation.
5. `hidden-recombination` uses withheld teams/seeds and recombines mapped
   features after the submission snapshot.

Focused random forcing is allowed only in verifier-owned unit tests where both
implementations receive an equivalent controlled outcome. Boundary differential
cases always use the real pinned PRNG stream and record its initial seed.

## Progress accounting

Results are aggregated by case and semantic boundary, never by raw trace-line
count. A long easy battle cannot outweigh a short scheduler or event-ordering
failure. For every required feature, the report contains:

- authoritative Showdown tests/source locations;
- native boundary and focused tests;
- public and hidden case counts by provenance;
- requested, reached, agreed, unsupported, and divergent boundary counts;
- invariant, replay, and labeled-PRNG results;
- the first divergent boundary and minimized artifact, when present.

A feature is `mapped` when those references are nonempty, `reached` when an
oracle and native trace both cross its declared boundary, and `conformant` only
when every required public/hidden case agrees. Unsupported is a semantic
failure, not skipped coverage. Completion gates remain those in
`GRADER_CONTRACT.md`.

## Showdown baseline correspondence

The verifier must maintain an inventory of applicable tests under pinned
Showdown's Gen 3 simulator suites and classify each as translated, covered by a
more general parameter family, irrelevant to the declared Gen 3 OU domain, or
still missing. Random full-battle runners, explicit seeds/forced outcomes,
post-transition invariants, and regression retention are minimum layers. Our
independent implementation adds boundary agreement, which Showdown cannot test
against itself.

The existing `regressions/gen3ou` schema-version-1 traces are migration
evidence. They must be converted to canonical version-2 cases before the Harbor
verifier awards semantic or coverage points; their seed-42 prefixes do not
define the supported domain.
