# Gen 3 OU regression-map completeness proof

Pinned Pokemon Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This document records an independent reconciliation of the checked-in
regression map. It does not change feature classifications or claim that the
native engine implements every mapped assertion.

## Result

The regression-test map is structurally complete for the pinned
`test/sim/**/*.js` suite:

| Denominator | Count | Reconciliation |
| --- | ---: | --- |
| Static `it()` / `test()` declarations | 1,976 | 1,053 canonical records + 923 overlay-adjudicated records; zero missing or duplicated |
| Active static declarations | 1,933 | AST census agrees with checked artifact |
| Pending static declarations | 43 | AST census agrees with checked artifact |
| Mocha-registered test instances | 2,172 | 2,129 active + 43 pending |
| Dynamic instances beyond static declarations | 196 | `2,172 - 1,976` |
| Applicable static Gen 3 OU assertions | 251 | Checked unified-map total, including 10 reviewed ability aliases |
| Applicable dynamic loop variants | 41 | All 41 evidenced |
| Dynamic Random Battle admission records | 5 | Kept separate from native battle-runtime assertions |

`gen3ou-unified-regression-map.json` is the canonical machine-readable result.
Every one of its 1,976 records contains revision, source file, source line,
full test name, execution status, disposition, four explicit native-evidence
categories, and either a terminal reason or a proof/required-case decision.
Every applicable record additionally has nonempty mechanics, semantic
boundaries, and authoritative Showdown sources.

`gen3ou-applicable-regression-map.tsv` is the complete human-review projection
of the 248 applicable static assertions. It contains, per assertion:

- pinned source identity and test name;
- mechanics and observable semantic boundaries;
- native focused units, differential cases, invariants, and randomized cases;
- evidence scope and the required new case, if any;
- authoritative Showdown semantic sources.

`runtime-registration-census.json` is the companion map for dynamically
registered tests. It prevents a loop declaration from standing in for proof
of every parameter value.

## Enumeration method

The proof deliberately uses independent boundaries:

1. Walk every JavaScript file below pinned `test/sim` and parse it with the
   pinned TypeScript parser. Record each lexical `it()` or `test()` declaration
   by source file and start line, including skipped declarations.
2. Join that complete set against the reviewed canonical partitions and four
   whole-suite adjudication overlays. Reject missing, duplicated, or stale
   source keys and revision mismatches.
3. Execute pinned Mocha with `--dry-run --reporter json` over
   `test/sim/**/*.js`. This discovers the actual registered names rather than
   inferring loop cardinalities only from source syntax.
4. Reconcile the static and runtime counts. Inspect all files where registered
   instances exceed lexical declarations and preserve each Gen 3-relevant
   parameter value as its own variant record.
5. Independently scan the entire suite for tests whose suite, name, or body
   explicitly selects or names Gen 3. All 31 such declarations map to the
   canonical/overlay universe.
6. Resolve standard Gen 3 move, ability, and item test filenames from the
   pinned `ModdedDex`, independently of the native descriptor inventory. This
   retains Shadow Tag as source-proven Gen 3 OU-unreachable rather than losing
   its tests because the runtime inventory omitted the ability.
7. Rebuild the all-test census, unified JSON, and applicable TSV in an isolated
   temporary directory and require byte-for-byte equality with the checked
   artifacts.

The mapping ports semantic assertions and legal scenarios, not upstream
JavaScript implementations. Observable choice, queue, event, phase/request,
state, PRNG, switch/faint, and terminal behavior belongs in differential
fixtures. Internal invariants and otherwise unreachable constructed states
belong in focused C tests.

## Applicability and evidence state

The 248 applicable static assertions currently divide as follows:

| Evidence scope | Assertions |
| --- | ---: |
| Assertion-specific | 246 |
| Partial | 0 |
| None | 0 |
| **Named exact case still required** | **0** |

Native-unit references appear on 182 applicable assertions and differential
references on 210. No applicable assertion currently claims invariant-only or
randomized-only coverage. Empty arrays are intentional evidence facts, not
missing schema fields.

Recent reconciliations close exact Imprison, PRNG, atomic-formula, item,
Substitute, Ingrain, Taunt, Yawn, and trapping-lifecycle assertions. The
Pomeg Glitch Clause row is closed by its exact stock/custom-format admission
pair. Assertions about intentionally partial client requests
(`maybeDisabled`) and `cantUndo` submission behavior remain outside the Ocean
contract because it exposes omniscient legal actions and atomic joint steps.

The 1,730 non-applicable static records all retain an explicit terminal reason.
Their dispositions cover mechanics absent from Gen 3, different-generation
semantics, Gen 3 OU singles reachability, skipped upstream tests, and behavior
outside the native observable contract. These terminal reasons are source
adjudications, not native support claims.

Of the 41 applicable dynamic variants, all eight Rollout/Ice Ball variants and
all 33 trapping variants have direct or descriptor-equivalence evidence. The
nine Baton Pass variants exercise move-driven switching through each trap and
now have per-descriptor differentials in addition to the shared generic
continuation/state-transfer unit.

## Exact verification commands

Run from `robots/envs/dev/pokemon_gen3/verify/upstream-tests`:

```sh
node validate-unified-regression-map.js
node validate-all-test-census.js .
node validate-runtime-registration-census.js \
  /private/tmp/pokemon-lockon-clean
node test-runtime-registration-contract.js
node validate-semantic-map.js --require-complete
node audit-explicit-gen3-completeness.js \
  /private/tmp/pokemon-lockon-clean .
```

The isolated deterministic rebuild used:

```sh
node TMP/build-all-test-census.js \
  /private/tmp/pokemon-lockon-clean \
  TMP/gen3ou-test-map.json TMP/all-test-census.json
node TMP/build-unified-regression-map.js \
  /private/tmp/pokemon-lockon-clean
node TMP/build-applicable-review.js
cmp verify/upstream-tests/all-test-census.json \
  TMP/all-test-census.json
cmp verify/upstream-tests/gen3ou-unified-regression-map.json \
  TMP/gen3ou-unified-regression-map.json
cmp verify/upstream-tests/gen3ou-applicable-regression-map.tsv \
  TMP/gen3ou-applicable-regression-map.tsv
```

Here `TMP` is a private copy of the `upstream-tests` directory. This avoids
mutating checked artifacts while proving regeneration determinism.

## Confidence and limits

Confidence is high that every pinned static declaration and runtime-registered
test instance is counted, and that every currently adjudicated applicable
assertion has a structurally complete record. The AST denominator, Mocha
runtime denominator, explicit-Gen-3 scan, resolved-entity audit, mutation-tested
runtime contract, and byte-identical regeneration agree.

This does not prove that all 18 open static assertions are implemented or that
every applicability adjudication is
immune to human semantic error. It also does not make passing a mapped test a
support claim. Feature promotion still requires the corresponding native
boundary, focused proof, differential evidence, source mapping, pinned
revision, and classification gate.
