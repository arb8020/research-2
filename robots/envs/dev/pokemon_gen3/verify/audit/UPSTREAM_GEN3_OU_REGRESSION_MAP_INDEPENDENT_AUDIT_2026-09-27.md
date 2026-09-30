# Independent upstream Gen 3 OU regression-map audit

Pinned Pokemon Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This is an independent completeness audit of the project-local regression-test
map. It does not change native code, generated data, fixtures, or supported
feature claims.

## Result

The exhaustive per-test map is
`verify/upstream-tests/gen3ou-unified-regression-map.json`. Its human-review
projection for every applicable static assertion is
`verify/upstream-tests/gen3ou-applicable-regression-map.tsv`.

Every one of the 1,976 static `it()` / `test()` declarations below pinned
`test/sim` has exactly one JSON record. Every record preserves the pinned source
file, line, full test name and revision. Every applicable record additionally
records:

- the mechanic and observable semantic boundaries exercised;
- native focused-unit, differential, invariant, and randomized evidence;
- whether that evidence is assertion-specific, partial, entity-level only, or
  absent;
- a named new case when exact proof is still required;
- authoritative Showdown semantic sources.

Every non-applicable record has an evidence-backed terminal reason, including
generation absence, different-generation semantics, Gen 3 OU singles
unreachability, skipped upstream tests, or exclusion from the native observable
contract. These reasons are adjudications, not native support claims.

The JSON record is the objectively checkable unit. For an applicable static
test it contains `source.file`, `source.line`, `source.full_test_name`, the
record-level `revision`, `mechanics`, `boundaries`, the four native coverage
kinds under `evidence`, `evidence_scope`, `required_case`, and
`semantic_sources`. For a non-applicable static test the same source identity
and revision are present together with `disposition`,
`applicability_evidence`, and `terminal_reason`. `terminal_reason` is either a
string or an array of source-linked statements; the validator deliberately
accepts both representations.

| Denominator | Count |
| --- | ---: |
| Static declarations | 1,976 |
| Active static declarations | 1,933 |
| Pending static declarations | 43 |
| Applicable static assertions | 268 |
| Non-applicable static assertions | 1,708 |
| Runtime-registered tests | 2,172 |
| Active runtime tests | 2,129 |
| Pending runtime tests | 43 |
| Dynamic expansions beyond lexical declarations | 196 |
| Applicable dynamic loop variants | 41 |
| Dynamic Random Battle admission records | 5 |

The applicable static assertions currently have this evidence state:

| Evidence scope | Assertions |
| --- | ---: |
| Assertion-specific | 74 |
| Partial | 36 |
| Entity-level candidates only | 38 |
| None | 120 |
| **Named exact case still required** | **194** |

The four native coverage columns are not collapsed into a single boolean:

| Non-empty native coverage kinds | Applicable assertions |
| --- | ---: |
| None | 120 |
| Native unit only | 25 |
| Differential only | 15 |
| Native unit and differential | 108 |
| Invariant (in any combination) | 0 |
| Randomized scenario (in any combination) | 0 |

Those are evidence-presence counts, not proof-scope counts. In particular,
entity-level or partial evidence remains open even when one or both evidence
arrays are non-empty.

The 1,708 non-applicable declarations have these terminal dispositions:

| Disposition | Assertions |
| --- | ---: |
| `mechanic_unreachable_gen3` | 656 |
| `not-applicable-subject-unavailable-in-gen3` | 379 |
| `different-generation` | 246 |
| `format_unreachable_gen3ou_singles` | 169 |
| `different_generation_not_direct_evidence` | 151 |
| `generation_semantics_differ` | 52 |
| `outside_native_observable_contract` | 37 |
| `post-gen3-unreachable` | 13 |
| `format-unreachable` | 4 |
| `upstream_test_skipped_not_evidence` | 1 |

The map spans 354 pinned upstream source files; the 268 applicable declarations
span 105 files. Applicable records partition as 75 core, 181 entity, and 12
whole-suite-overlay declarations.

The 41 applicable dynamic variants are separately enumerated in
`verify/upstream-tests/runtime-registration-census.json`; all 41 currently have
descriptor-level or assertion-specific evidence. Keeping this map separate is
necessary because one lexical test declaration can register many mechanics via
a loop.

## Independent enumeration method

1. Parse every JavaScript file below pinned `test/sim` and enumerate lexical
   `it()` / `test()` declarations, including pending tests.
2. Require a one-to-one join between that denominator and the reviewed
   canonical partitions plus whole-suite overlays. Reject missing, duplicate,
   stale, or revision-mismatched records.
3. Compare against Mocha's dry-run registration census so loop-expanded tests
   cannot disappear behind one declaration.
4. Independently scan suite names, test names, and bodies for explicit Gen 3
   selection. All 31 discovered declarations are present in the map.
5. Resolve Gen 3 move, ability, and item ownership through the pinned
   `ModdedDex`, rather than trusting the native inventory as the upstream-test
   denominator.
6. Rebuild the declaration census, unified JSON map, and applicable TSV in an
   isolated `/private/tmp` copy. All three outputs were byte-identical to the
   checked artifacts.

The rebuild was repeated on 2026-09-28 against a checkout whose
`git rev-parse HEAD` was exactly the pinned revision. The resolved-entity audit
was also regenerated and byte-compared: it found one inventory-omitted tested
Gen 3 entity (Shadow Tag) and four tests, matching the checked artifact. No
support classification was changed.

The following validators all passed against the pinned checkout:

```text
validate-unified-regression-map.js
validate-all-test-census.js
validate-runtime-registration-census.js
test-runtime-registration-contract.js
validate-semantic-map.js --require-complete
audit-explicit-gen3-completeness.js
```

`validate-all-test-census.js` takes the artifact directory, not the Showdown
checkout. The source-to-artifact check is performed by rebuilding from the
pinned checkout and byte-comparing. A minimal reproduction from
`verify/upstream-tests` is:

```sh
node validate-unified-regression-map.js
node validate-all-test-census.js .
node validate-runtime-registration-census.js /private/tmp/pokemon-lockon-clean
node test-runtime-registration-contract.js
node validate-semantic-map.js --require-complete
node audit-explicit-gen3-completeness.js /private/tmp/pokemon-lockon-clean .
```

The aggregate claims above can be recomputed without trusting this prose:

```sh
jq '.summary' gen3ou-unified-regression-map.json
jq -r '.records[] | select(.applicable) | .evidence_scope' \
  gen3ou-unified-regression-map.json | sort | uniq -c
jq -r '.records[] | select(.applicable == false) | .disposition' \
  gen3ou-unified-regression-map.json | sort | uniq -c
```

The neighboring re-audit's earlier 70 assertion-specific / 198 required-case
figures are stale relative to the current deterministic artifact. The current
checked JSON summary and isolated rebuild both yield 74 / 194.

## How to port an upstream regression

Port the semantic assertion and legal scenario, not the TypeScript test body.
Use a pinned-oracle differential when choices, queue/event ordering,
phase/request transitions, state, labeled PRNG, switching/fainting, or terminal
resolution are observable through the native contract. Use a focused C test for
an internal invariant or for a constructed state that legal Gen 3 OU cannot
reach.

A passing port does not expand support. Reclassification still requires all of:
the native semantic boundary, a focused test, differential evidence,
authoritative source mapping, and the pinned oracle revision.

## Blind spots and independent proof obligations

The census proves declaration and runtime-registration completeness, not
semantic-transposition completeness. A test owned by an unavailable later-gen
entity can still assert an operation reachable through a legal Gen 3 owner. The
known witness is `test/sim/abilities/imposter.js:22`: Imposter is unavailable,
but its Substitute-blocks-transformation assertion is reachable through Gen 3
Transform and is represented by `test/sim/moves/transform.js:102`. Therefore an
owner-level terminal reason must not be treated as proof that its underlying
operation is irrelevant.

The map also does not prove dynamic condition-creation completeness. The prior
`addSlotCondition(..., 'futuremove')` omission demonstrates why condition
creation/removal needs its own source audit even though Future Sight tests are
present here.

Finally, assertions excluded as client-protocol-only require care: the Ocean
contract deliberately exposes omniscient legal actions and atomic joint steps,
so protocol details such as partial `maybeDisabled` requests may be outside the
contract while the underlying admission or rollback semantics remain in scope.

The validators prove identity/completeness and required field shape, but they
cannot mechanically prove that every human-written `mechanics`, `boundaries`,
or irrelevance explanation is the uniquely correct semantic interpretation.
The terminal disposition table therefore remains an auditable classification,
not an executable proof of all 1,708 irrelevance judgments. Likewise, empty
invariant and randomized columns mean those native coverage kinds have not yet
been recorded here; they must not be inferred from unit or differential links.

## Conclusion

The project has an exhaustive, pinned per-declaration map and a separate
runtime-expansion map. The immediate verification debt is the 194 applicable
static assertions that still name an exact missing case. That backlog should be
closed by semantic family and recombination value, not by mechanically porting
test files or promoting features merely because an upstream-shaped scenario
passes.

## 2026-09-28 semantic-completeness correction

An independent source review found that the declaration census is structurally
complete but the v1 disposition schema is not semantically complete. In v1,
`generation_semantics_differ` is terminal and therefore cannot also carry a
required Gen 3 replacement case. This hides 21 known replacement obligations
across Brick Break, Conversion 2, Destiny Bond, Explosion, Fury Cutter, Future
Sight, Glare, Hyper Voice, Stockpile, Toxic, Transform, Uproar, and Wish.

The replacement obligation is a separate fact from the disposition of the
modern upstream assertion. The next map schema must represent both:

```text
upstream_disposition:
  applicable | contradicted_by_gen3 | unreachable | outside_contract

gen3_obligation:
  assertion, mechanics, boundaries, semantic_sources,
  legal Gen 3 OU scenario constraints, four evidence kinds,
  evidence scope, and an optional required case
```

Every `contradicted_by_gen3` record must have a non-null Gen 3 obligation, and
that obligation must have either assertion-specific evidence or a required
case. The summary must count open Gen 3 replacements separately from open
applicable upstream assertions. `terminal_reason` must not encode both facts.

Source review also found concrete v1 adjudication errors that must be corrected
before treating the map as semantic proof:

- Gen 3 Transform succeeds through Substitute, does not copy Focus Energy, and
  copies an ability without dispatching its Start event. The modern Imposter
  Substitute assertion is opposite, not an alias.
- Knock Off removing an item before Rough Skin faints its user is reachable in
  legal Gen 3 and has different semantics from the modern assertion.
- The Pursuit declaration contains a legal Baton Pass subscenario even though
  its U-turn and Volt Switch scaffolding is unreachable.
- Dry Skin's 1/8 rain healing is not equivalent to Gen 3 Rain Dish's 1/16.
- Pastel Veil ally curing and the cited Storm Drain doubles/triples assertions
  are outside Gen 3 OU singles. Persistent dual-holder Magic Bounce behavior
  is not proven equivalent to turn-bounded Magic Coat.

These findings do not change any native support classification. Until the v2
records and validator exist, the v1 map remains an exhaustive source census
and a work list, not a sound proof that every semantic transposition or terminal
disposition is correct.
