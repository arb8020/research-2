# Independent Gen 3 OU upstream regression-map re-audit

Pinned Pokemon Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This audit answers a completeness question, not a support question. It does
not change the native feature map, descriptor classifications, generated data,
or supported-mechanics claims.

## Canonical per-test result

The requested regression-test map already exists at
`verify/upstream-tests/gen3ou-unified-regression-map.json`. Its complete
human-review projection is
`verify/upstream-tests/gen3ou-applicable-regression-map.tsv`.

Every applicable static upstream assertion has:

- pinned source file, line, full test name, and revision;
- mechanics and observable semantic boundaries;
- separate native-unit, differential, invariant, and randomized evidence;
- an evidence scope which prevents entity-level evidence from masquerading as
  assertion-specific proof;
- either a named required new case or assertion-specific evidence;
- authoritative Showdown semantic sources.

Every excluded assertion has a terminal disposition and source-based reason.
The JSON is authoritative; this document deliberately does not duplicate 268
rows into prose.

## Independent reconciliation

The frozen artifacts reconcile as follows:

| Proof boundary | Result |
| --- | ---: |
| Static `it()` / `test()` declarations below `test/sim` | 1,976 |
| Active static declarations | 1,933 |
| Pending static declarations | 43 |
| Canonical records | 1,053 |
| Explicit whole-suite overlay adjudications | 923 |
| Missing or duplicated static declarations | 0 |
| Runtime-registered Mocha tests | 2,172 |
| Runtime expansions beyond lexical declarations | 196 |
| Explicit Gen 3 declarations independently found and mapped | 31 |
| Applicable Gen 3 OU static assertions | 268 |
| Applicable loop-expanded variants | 41 |
| Loop-expanded variants with direct/equivalence evidence | 41 |
| Applicable assertions with assertion-specific evidence | 70 |
| Applicable assertions still requiring an exact case | 198 |

An isolated rebuild of the static census, unified JSON, and applicable TSV was
byte-identical to the checked artifacts. The resolved Gen 3 Dex audit found one
tested entity absent from the normal inventory: Shadow Tag, accounting for four
tests. Those four records are retained in the map with a legal-Gen-3-OU
reachability proof rather than silently omitted. The only standard Gen 3
origins are Wobbuffet and Wynaut, both Uber in the pinned format data; the Gen 3
ability-copying operations cannot create an ability absent from the initial
battle.

The runtime-registration proof matters because syntax-node counting alone
would collapse parameterized Rollout/Ice Ball and trapping tests. The companion
`runtime-registration-census.json` preserves all 41 applicable variants and
requires either exact evidence or an explicit descriptor-equivalence proof.

## Omission-sensitive delayed-action findings

The map does include the upstream Future Sight suite; the earlier
`futuremove` extractor omission did not erase these tests from the test census.
The Gen 3-applicable assertions have deliberately distinct dispositions:

- `test/sim/moves/futuresight.js:31` (duplicate target-slot rejection) and
  `:405` (empty slot at resolution) have assertion-specific evidence;
- `test/sim/moves/futuresight.js:236` (the delayed hit still observes the
  target's screens) remains open as `upstream-futuresight-236`;
- modern assertions whose damage snapshot, immunity, item/ability, or turn-wrap
  semantics differ from pinned Gen 3 are excluded as modern tests and require
  separate pinned-Gen-3 semantic scenarios rather than literal ports;
- `test/sim/moves/wish.js:31` and `:64` remain open as
  `upstream-wish-31` and `upstream-wish-64`.

These are evidence gaps, not extractor gaps. Passing related delayed-slot
fixtures must not close them unless the exact semantic assertion is exercised.

## Porting rule

For each open applicable row, port the semantic assertion and legal scenario,
not the TypeScript test body. Prefer a pinned-oracle differential fixture when
the native contract can observe the choice, queue/event order, request/phase,
state, PRNG, switching/fainting, or terminal result. Use a focused C test for
an internal invariant or a constructed state that legal Gen 3 OU cannot expose.

A passing case is insufficient to expand support. Promotion still requires the
native semantic boundary, focused proof, differential evidence, Showdown source
mapping, and pinned oracle revision.

## Reproduction

From `verify/upstream-tests`:

```sh
node validate-unified-regression-map.js
node validate-all-test-census.js .
node validate-runtime-registration-census.js /private/tmp/pokemon-lockon-clean
node test-runtime-registration-contract.js
node validate-semantic-map.js --require-complete
node audit-explicit-gen3-completeness.js /private/tmp/pokemon-lockon-clean .
node audit-resolved-gen3-entity-files.js \
  /private/tmp/pokemon-lockon-clean \
  ../inventory/descriptor-map.json \
  /private/tmp/gen3-entity-audit
```

For the deterministic rebuild, copy the `upstream-tests` directory to an
isolated temporary directory, run `build-all-test-census.js`,
`build-unified-regression-map.js`, and `build-applicable-review.js` there, and
compare the three generated artifacts byte-for-byte with the checked versions.

## Limits

This re-audit independently proves enumeration, schema completeness, runtime
loop expansion, explicit-Gen-3 capture, resolved-entity supplementation, and
deterministic regeneration. It does not claim that all 1,708 terminal semantic
adjudications are immune to human interpretation error, nor that the 198 open
applicable assertions are implemented. Those facts remain visible in the
canonical map instead of being hidden by aggregate coverage.
