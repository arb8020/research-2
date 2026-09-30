# Native Gen 3 OU Harbor task proposal

Status: **approved contract; runnable build/API packaging slice, not published**.

This directory is a stable, parameterized implementation-and-verification
envelope for iterative work on the native Gen 3 OU interpreter. It is not a
claim that one agent or submission should solve the full environment end to
end today, and it deliberately does not equate a finite test run with
exhaustive enumeration of Pokemon battles. The same cases and boundary
projections are usable during development and when submitting to Harbor.

The proposed task is complete when a submission conforms to the pinned Pokemon
Showdown oracle for every feature declared `required` in the frozen supported
feature manifest, across the observable contract and acceptance gates in
`GRADER_CONTRACT.md`. The claim is conformance over an explicit domain, not a
proof over every possible battle state.

## Proposed Harbor layout

```text
gen3ou-native/
├── task.toml                     Harbor metadata and resource limits
├── instruction.md                instruction visible to the implementer
├── README.md                     this review document
├── GRADER_CONTRACT.md            observables, scoring, gates, and completion
├── feature-map.schema.json       machine-checkable feature record schema
├── supported-features.json       review-time feature-family manifest
├── environment/
│   ├── Dockerfile                fixed native implementation environment
│   └── source.lock               source archive/revision and toolchain hashes
├── tests/
│   ├── Dockerfile                separate, no-network verifier with oracle
│   ├── test.sh                   writes reward and failure artifacts
│   ├── oracle.lock               Showdown revision and patch hashes
│   ├── public/                   disclosed focused and regression cases
│   └── hidden/                   withheld generated/recombined cases
└── solution/
    └── solve.sh                  reference solution used only for task QA
```

Harbor requires `task.toml`, `instruction.md`, `environment/`, and
`tests/test.sh`; Harbor 0.21.0 reads named numeric rewards from
`/logs/verifier/reward.json`. The separate verifier image prevents the submitted
runtime from depending on Showdown, Node, Python, hidden cases, or answer data.

The environment image now uses a content-addressed starting archive, and the
public verifier deterministically grades a six-point build/API packaging slice.
Generated-data reproduction, real pinned PufferLib compilation, and explicit
ABI/Ocean lifecycle checks remain required before all ten build/API points are
available. Its
separate, content-addressed verifier image builds pinned Showdown and applies a
test-only observer for ordered handlers and contextual low-level PRNG draws.
Stable operation-owned PRNG labels and complete semantic boundary IDs remain
part of the unfinished differential projector. A verifier-owned shared case now
feeds both Showdown and native drivers, and its comparator records the first
unequal field. Its two request boundaries now agree. They are intentionally
unscored until queue, handler, labeled-PRNG, terminal, and broader corpus
comparisons exist, so semantic, coverage, determinism, robustness, and
performance remain zero.
Queue/phase observers, hidden tests, and the reference solution remain to be
built; this shell does not claim task completion.

The packaging slice was exercised end-to-end with Harbor 0.21 on OrbStack
Docker (arm64) using the `nop` agent. The environment archive built, Harbor
re-materialized the artifact at its original `/app` path, the separate verifier
built pinned Showdown, the oracle smoke digest matched, the manifest was
schema-valid but completion-incomplete, and the verifier reported the expected
`build_api=6`, `reward=0.06`, with every semantic category still zero. The
latest run is `/tmp/gen3ou-harbor-jobs/gen3ou-packaging-smoke-7`; case
validation, oracle/native smokes, and the two-boundary comparison all passed.

## Freeze requirements

The current worktree is based on repository commit
`89e92352df3f9688b3bc773c70b097989f142a7e`, but the Pokemon environment is
currently untracked. That commit is therefore **not** an honest fixed starting
repository. Before publishing the task, create an immutable source archive or
commit containing the reviewed starting files and record its SHA-256 in
`environment/source.lock`.

The executable oracle is Pokemon Showdown commit
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, format `gen3ou`. The verifier
image must contain that exact tree and record hashes for any observation-only
instrumentation. Instrumentation may expose queue, handler, phase, request, and
PRNG boundaries; it may not change choices, state, protocol, ordering, or PRNG.

## Deliberate boundaries

- The input domain is two teams accepted by the pinned `gen3ou` validator and
  normalized into `Gen3BattleInit`. Team parsing and teambuilder UX are oracle
  fixture-generation concerns, not native runtime responsibilities.
- The submitted runtime is C, self-contained, fixed-capacity, and callable
  through `gen3_abi.c/.h`; `pokemon_gen3.h` remains a thin Ocean adapter.
- The task covers singles battle execution from initial placement through win
  or tie. It excludes networking, matchmaking, replay text rendering, AI policy,
  and later-generation formats.
- Species, moves, abilities, items, and clauses are the exact legal/reachable
  inventory frozen in the published manifest. Unsupported manifest entries
  fail the task; out-of-manifest inputs must be rejected before mutation.
- Exceptional named handlers are allowed when the mechanic is genuinely named.
  Dispatch on observed move pairs, teams, seeds, or trace prefixes is not.

## Review decisions requested

1. Approve the observable trace ABI as a verifier-only build surface while the
   production ABI remains dependency-free.
2. Approve the hard acceptance gates and weighted partial score.
3. Approve inventory scope as all normalized sets reachable from pinned
   `gen3ou`, rather than asking the native engine to implement team validation.
4. Approve the provisional absolute performance floor plus its relative
   reference guard; both are frozen only after reproduction on the final image.
