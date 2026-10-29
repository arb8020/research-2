# Native boundary driver

`native_boundary_driver.c` is the verifier-owned native half of the first
boundary differential slice. It compiles the submitted `gen3_abi.c` directly
with `GEN3_VERIFY_TRACE`; it does not import or execute submission Python,
harness code, fixtures, or expected output.

The canonical input is the shared verifier-owned JSON Schema v2 case. The
verifier validates it, verifies its team digest, and writes a closed
`gen3ou-native-projection-v1` containing only the case ID, seed, and normalized
native actions for this C driver. This keeps JSON and Showdown team parsing out
of the submitted runtime while ensuring both drivers derive from one record.
The current case is
`seed42-battle04-forced-replacement`. It freezes the exact team exports, battle
seed, Showdown choices, and encoded ABI decisions (`-1` wait, `0..3` move,
`4..8` switch). The pinned Showdown revision imports the exports and serializes
the exact 608-byte `Gen3BattleInit`; the native driver reads those bytes. No
submitted Python, JavaScript, fixture, parser, or normalization is trusted.

Each JSONL record is emitted synchronously at a post-choice request trace
boundary. It contains the boundary ordinal, phase/request value, legal masks,
a canonical mutable-state projection, and typed protocol events accumulated
since the prior emitted boundary. Immutable set data are represented by
species ID and max HP in this first projection; the pinned oracle constructed
the complete immutable sets.

`oracle_boundary_driver.js` produces the same field names from Showdown and
`compare_boundaries.py` persists the first unequal field. Both frozen boundaries
must agree before this slice can award semantic points; agreement here still
does not establish broader feature-map conformance. Queue items, handler
records, and complete labeled PRNG records remain outside this first slice.

The driver emits the phase delivered by the trace stream. At every emitted
boundary it independently checks that phase against the canonical snapshot
request fields and fails closed on disagreement. Phase normalization is an
engine invariant; the verifier does not repair or project a lagging value.

`native_boundary_smoke.sh` compiles against the submitted C sources, runs the
case twice, requires byte-identical JSONL, and checks the verifier-owned digest.
