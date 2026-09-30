# Pinned Showdown inherited test map

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

This directory contains both the structural censuses and the reviewed canonical
Gen 3 OU regression map. `gen3ou-test-map.json` covers all 1,053 statically
declared tests in the frozen entity, core, and resolved-entity supplemental
partitions: 553 entity tests, 496 core tests, and four supplemental Shadow Tag
tests.

The canonical map separates semantic applicability from implementation proof.
Every declaration in its reviewed partitions has a manual source adjudication
or a previously reviewed terminal disposition. The canonical map currently
identifies 10 applicable assertions that still require a focused or
differential case; 238 have assertion-specific evidence.
Entity-level native evidence is retained separately and never upgrades an
assertion to covered.

`all-test-census.json` is the larger proof boundary. It deterministically walks
every static `it()` and `test()` declaration below pinned `test/sim`, including
files outside the selected entity and core partitions. Of 1,976 declarations,
1,053 have canonical map records and 923 have explicit overlay adjudications.
The census also preserves whether a declaration is active or pending.
`validate-all-test-census.js` rejects revision drift, missing or duplicate
declarations, stale mapping status, and changes to these frozen counts.

Static declarations are not the runtime test denominator. Pinned Mocha
registers 2,172 cases (2,129 active and 43 pending), because loop-defined tests
expand 1,976 declarations by another 196 cases. The checked
`runtime-registration-census.json` records the nine expanding files and the 41
Gen 3 OU-applicable Rollout/Ice Ball and trapping variants. All eight
Rollout/Ice Ball variants and all 33 trapping variants have mapped evidence.
Each variant must retain assertion-specific evidence or a descriptor-
equivalence proof. The trapping subset cardinality-checks all nine Baton Pass
instances separately.

`gen3ou-unified-regression-map.json` is the normalized consumer projection. It
joins all 1,976 static declarations to the canonical or overlay adjudication,
materializes the four evidence categories on every row, and requires every
applicable assertion to have mechanics, boundaries, and either
assertion-specific evidence or a named required case. Five dynamically expanded
Gen 3 Random Battle data/generator tests are recorded separately as admission
evidence outside the Gen 3 OU native runtime.

`gen3ou-applicable-regression-map.tsv` is the generated review projection for
the 248 applicable static assertions. See `INDEPENDENT_REGRESSION_AUDIT.md` for
the independent denominator check, evidence totals, and why the runtime
registration census remains a separate proof obligation.

`core-test-census.json` and `gen3ou-inherited-test-map.json` remain reproducible
structural inputs. Their 372 heuristic `requires-source-adjudication` rows are
resolved by `core-manual-adjudications.json` and
`entity-manual-adjudications.json`; consumers must use the canonical projection,
not treat the raw census labels as final semantics.

## Dispositions

| Disposition | Count | Meaning |
|---|---:|---|
| `g3_explicit` | 12 | The test body executes Gen 3. |
| `candidate_requires_gen3_source_adjudication` | 144 | Entity existed in Gen 3, but the test executes default/current Showdown. Inspect pinned Gen 3 inheritance before porting. |
| `different_generation_not_direct_evidence` | 150 | The body explicitly executes another generation, or its default-generation assertion is contradicted by the resolved Gen 3 mod. The title alone cannot make it Gen 3 evidence. |
| `format_unreachable_gen3ou_singles` | 93 | Scenario or required descriptor is unreachable in legal Gen 3 OU singles. |
| `mechanic_unreachable_gen3` | 57 | The asserted mechanic did not exist in Gen 3. |
| `generation_semantics_differ` | 23 | The named entity exists, but pinned Gen 3 source explicitly lacks or contradicts the tested modern behavior. |
| `outside_native_observable_contract` | 1 | The assertion tests protocol rendering rather than the native state/event contract. |
| `g3_source_applicable` | 73 | Effective Gen 3 source proves the semantic assertion applicable after replacing modern scaffolding. |

These are complete structural dispositions, not 553 support decisions. In
particular, the 144 source-adjudication records are retained as visible audit
debt rather than silently treated as applicable or irrelevant.

The terminal `mechanic_unreachable_gen3` disposition is intentionally based on
the semantic test name, not incidental tokens in the body. Upstream tests often
use modern entities as convenient scaffolding for an older assertion. Those
body-only matches remain source-adjudication debt; they are not evidence that
the assertion is unreachable.

The post-Gen-3 ability overlay has a second, stricter boundary. Its 411 rows
are reviewed for semantic transposition rather than excluded solely from the
named ability's introduction generation. The checked
`ability-semantic-transposition-adjudications.json` identifies 10 assertions
that transpose to legal Gen 3 owners, 19 that share an operation without
preserving the full denotation, and 382 owner-specific terminal assertions.
Every transposed alias remains an open required case until exact native or
differential evidence exists; it does not claim support for the future ability.

## Independent explicit-Gen-3 completeness check

`audit-explicit-gen3-completeness.js` walks every JavaScript test below pinned
`test/sim`, independently of the two census generators. It requires every
statically declared test whose name, enclosing `describe`, or body names or
selects Gen 3 to have a record in either census. The current audit maps all 31
such declarations and writes `explicit-gen3-completeness.json`.

This remains distinct from an implementation-completeness claim. The reviewed
map resolves applicability for the 144 inherited and 225 core candidates, and
246 applicable declarations currently have complete assertion-specific evidence
(257 across applicable and terminal rows). No applicable declaration remains
without an exact disposition. Passing a fixture never expands
the supported feature map without the separate native
boundary, source, and classification gate.

`audit-resolved-gen3-entity-files.js` separately resolves the pinned Gen 3 Dex
instead of trusting the frozen inventory. Runtime move closure moved Assist,
Sheer Cold, and Struggle into the main census; the supplemental map now records
only Shadow Tag's four declarations. This is an entity-census check, not a
support claim; see
`COMPLETENESS_AUDIT.md` for the Gen 3 OU rule and reachability adjudication.
Its v2 JSON is a full supplemental regression map: each declaration records
mechanics, semantic boundaries, OU reachability, native unit/differential/
invariant/random evidence, case necessity, and pinned semantic sources.

## Direct Gen 3 priorities

The thirteen direct tests resolve as follows:

- Exact differential evidence now exists for all four Weather Ball physical /
  special retaliation combinations.
- Exact differential and focused-kernel evidence now exists for Gen 3 Pursuit
  interception and continued switching, including lethal interception.
- Missing semantic families: Conversion 2 and Fury Cutter progression. Frozen
  Flash Fire suppression now has exact focused and differential evidence,
  separate from unfrozen activation/immunity/boost cases.
- Existing-family evidence gaps: Thick Fat composed with a type item, Quick
  Claw's induced speed tie, Sitrus deferral after status residual, Glare's Gen 3
  natural immunity, and Haze preserving Focus Energy.

Direct Doubles-only tests are classified as format-unreachable rather than
`g3_explicit`: Magnet Pull ally trapping, Brick Break ally targeting, Follow Me
replacement persistence, and two Pursuit target-identity scenarios.

The four inherited Charge assertions have now been adjudicated against the
resolved Gen 3 `ModdedDex`, not only the nearest source override. Gen 3 removes
the modern Special Defense boost and keeps the Electric-only base-power
handler, but recursively inherits Gen 8's cleanup override: every non-Charge
move consumes the volatile. The modern persistence assertion is therefore not
Gen 3 evidence. The explicit Gen 8 any-move assertion is nevertheless relevant
because Gen 3 inherits that exact override. The applicable assertions remain
verification gaps until their named focused and differential cases exist.

## Record contract

`gen3ou-inherited-test-map.json` and its TSV projection contain one record per
upstream test with:

- pinned file, line, describe path, test name, and revision;
- descriptor identity and declared/actually selected generations;
- applicability disposition and evidence;
- mechanics and observable semantic boundaries;
- native focused-test and differential-case IDs, or explicit empty arrays;
- invariant and randomized-scenario IDs (currently explicit empty arrays);
- assertion-specific versus entity-level evidence scope;
- a required new case/adjudication, or a terminal complete/not-applicable state;
- authoritative Showdown descriptor sources from the feature map.

The generator rejects duplicate records, missing dispositions or evidence,
missing mechanics/boundaries, and nonterminal records without a required next
case. It also refuses an oracle or descriptor map at a different revision.

## Reproduce

```sh
node verify/upstream-tests/generate-inherited-map.js \
  --showdown /path/to/pinned/pokemon-showdown \
  --descriptor-map verify/inventory/descriptor-map.json \
  --output verify/upstream-tests

node verify/upstream-tests/audit-explicit-gen3-completeness.js \
  /path/to/pinned/pokemon-showdown \
  verify/upstream-tests

node verify/upstream-tests/audit-resolved-gen3-entity-files.js \
  /path/to/pinned/pokemon-showdown \
  verify/inventory/descriptor-map.json \
  verify/upstream-tests

node verify/upstream-tests/build-all-test-census.js \
  /path/to/pinned/pokemon-showdown \
  verify/upstream-tests/gen3ou-test-map.json \
  verify/upstream-tests/all-test-census.json

node verify/upstream-tests/build-unified-regression-map.js \
  /path/to/pinned/pokemon-showdown
node verify/upstream-tests/validate-unified-regression-map.js

node verify/upstream-tests/build-runtime-registration-census.js \
  /path/to/pinned/pokemon-showdown
node verify/upstream-tests/validate-runtime-registration-census.js \
  /path/to/pinned/pokemon-showdown
node verify/upstream-tests/test-runtime-registration-contract.js
node verify/upstream-tests/build-applicable-review.js

node verify/upstream-tests/build-gen3ou-test-map.js
node verify/upstream-tests/validate-semantic-map.js --require-complete
node verify/upstream-tests/validate-all-test-census.js verify/upstream-tests
```

Regeneration must report exactly `553 tests in 103 files` for this frozen
partition. Review the generated diff: changed upstream tests or a changed
descriptor inventory intentionally change the census and require audit review.
