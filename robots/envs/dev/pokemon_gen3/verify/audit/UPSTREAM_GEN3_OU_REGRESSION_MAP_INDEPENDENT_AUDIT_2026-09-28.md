# Independent pinned-Showdown Gen 3 OU regression-map audit

Pinned revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Audit date: 2026-09-28.

This audit is read-only with respect to native code, generated data, fixtures,
the observer, and support classification. It distinguishes a complete upstream
test *census* from a sound Gen 3 semantic-transposition and implementation-proof
map. The former is established. The latter is not yet established by the
current v1 schema.

## Per-test map and result

The exhaustive machine-readable map is
`verify/upstream-tests/gen3ou-unified-regression-map.json`. Its review projection
is `verify/upstream-tests/gen3ou-applicable-regression-map.tsv`. The JSON, not
this narrative, is the per-test record: every applicable row carries pinned
source file, line, full test name, mechanics, observable boundaries, four
separate evidence categories, evidence scope, an exact missing case when open,
and authoritative semantic sources. Every non-applicable row carries a pinned
source identity and an explicit terminal rationale.

At the audited snapshot:

| Boundary | Count |
| --- | ---: |
| Static `it()` / `test()` declarations below `test/sim` | 1,976 |
| Active / pending static declarations | 1,933 / 43 |
| Canonical / overlay-adjudicated declarations | 1,053 / 923 |
| Mocha-registered instances | 2,172 |
| Active / pending registered instances | 2,129 / 43 |
| Runtime expansions beyond lexical declarations | 196 |
| Applicable dynamic variants | 41 |
| Explicit-Gen-3 declarations independently found and mapped | 31 |
| Applicable static Gen 3 OU assertions | 283 |
| Assertion-specific / partial / entity-level / no evidence | 82 / 36 / 38 / 127 |
| Applicable static assertions naming an exact required case | 201 |

The TSV has 284 lines: one header plus all 283 applicable records. No applicable
record is omitted from that projection.

The checked map currently records zero invariant references and zero randomized
scenario references for applicable assertions. Those evidence kinds must not be
inferred from a native unit or differential case.

## Deterministic enumeration method

Completeness is auditable without trusting the native inventory:

1. Walk every pinned `test/sim/**/*.js` file in sorted order and parse every
   lexical `it()` and `test()` call, including skipped declarations. Key each
   record by `(source file, source line)` and preserve its full enclosing test
   name.
2. Require a one-to-one join against the reviewed canonical partitions or one
   explicit whole-suite overlay. Reject missing keys, duplicate keys, stale
   source lines, and revision mismatches.
3. Run Mocha's registration phase and reconcile its 2,172 registered instances
   with the 1,976 lexical declarations. Preserve all parameter values for the
   196 expansions; in particular, retain the 41 Gen 3 OU variants rather than
   treating one loop declaration as their proof.
4. Independently scan suite names, test names, and bodies for explicit Gen 3
   selectors. Join all 31 results to the canonical map.
5. Resolve tested move, ability, and item ownership from pinned Showdown's
   `ModdedDex`; never use the native frozen inventory as the upstream-test
   denominator. This prevents a missing inventory entry, such as the historical
   `futuremove` omission, from erasing its tests.
6. For applicable assertions, require mechanics, semantic boundaries,
   authoritative Showdown sources, four explicit evidence arrays, and either
   assertion-specific evidence or a named missing case.
7. Independently enumerate condition creation and removal calls. The test census
   and condition-path census are separate proof obligations: a complete Future
   Sight test map would not by itself discover a missed literal
   `addSlotCondition(target, 'futuremove')`.

The following current validators passed against a checkout whose HEAD exactly
matches the pinned revision:

```text
validate-unified-regression-map.js
validate-all-test-census.js .
validate-runtime-registration-census.js /private/tmp/pokemon-lockon-clean
test-runtime-registration-contract.js
validate-semantic-map.js --require-complete
audit-explicit-gen3-completeness.js /private/tmp/pokemon-lockon-clean .
```

They prove source identity, cardinality, joins, record shape, and the reviewed
v1 adjudication contract. They do not prove every semantic-transposition or
terminal rationale correct.

## Evidence typing

Use a differential fixture when the assertion is observable through normalized
choices, action/event ordering, requests and phases, canonical state, labeled
PRNG, switching/fainting, or terminal resolution. Use a focused C unit when the
assertion is an internal invariant or requires a constructed state unreachable
through legal Gen 3 OU choices. A unit symbol must not appear in the
`differential_cases` column, and passing either evidence type alone must not
promote a supported feature.

Seven EV-admission evidence IDs (`ban-ev-omitted`, `ban-ev-zero`,
`legal-ev-one`, `legal-ev-510`, `ban-ev-511`, `legal-ev-stat-255`, and
`ban-ev-stat-256`) resolve inside the aggregate
`verify/admission/cases.json`, not to standalone differential JSON files. They
are validator/admission evidence, not battle-transition differentials. The v2
schema should give admission its own evidence category or store an explicit
artifact path plus case ID instead of leaving these as bare names under
`differential_cases`.

## Semantic-completeness failures

### Terminal disposition hides Gen 3 replacement obligations

The v1 map has 52 `generation_semantics_differ` rows. That field is terminal:
the validator requires only a terminal reason and provides no place for the
opposite Gen 3 assertion, its legal scenario, evidence, or required case. Source
review has already identified 21 replacement obligations across Brick Break,
Conversion 2, Destiny Bond, Explosion, Fury Cutter, Future Sight, Glare, Hyper
Voice, Stockpile, Toxic, Transform, Uproar, and Wish. The current validator can
pass while all those replacement obligations remain absent.

The required v2 product type is:

```text
upstream_disposition:
  applicable | contradicted_by_gen3 | unreachable | outside_contract

gen3_obligation (required for contradicted_by_gen3):
  assertion
  mechanics
  observable boundaries
  semantic sources
  legal Gen 3 OU scenario constraints
  native unit evidence
  differential evidence
  invariant evidence
  randomized evidence
  evidence scope
  required case (when not assertion-specific)
```

The validator must reject any `contradicted_by_gen3` record without a non-null
Gen 3 obligation, and reject any obligation lacking assertion-specific evidence
and a required case. Summaries must count open Gen 3 replacement obligations
separately from applicable modern assertions.

Concrete source witnesses include:

- `test/sim/moves/transform.js:49`: modern Transform copies Focus Energy; Gen 3
  Transform does not. The required Gen 3 assertion is non-copy, not irrelevance.
- `test/sim/moves/transform.js:102`: modern Transform fails behind Substitute;
  Gen 3 Transform succeeds through Substitute. This is an opposite replacement
  assertion.
- `test/sim/moves/futuresight.js:13,258,294,313,337,359`: modern delayed-hit
  staging differs, but legal Gen 3 delayed-slot ownership, state snapshots,
  immunity, PRNG, and expiry still require explicit Gen 3 assertions.
- `test/sim/moves/toxic.js:9`, `glare.js:13`, `hypervoice.js:13`, and
  `uproar.js:13`: the modern assertion is contradicted, but the resolved Gen 3
  behavior remains a test obligation.

### Current evidence projection is stale relative to the fixture tree

`test/sim/moves/smellingsalts.js:13` remains `evidence_scope: none` with
`required_case: upstream-smellingsalts-13`, although the working fixture tree
now contains `smelling-salts-paralyzed-double-cure`,
`smelling-salts-clean-baseline`, and
`smelling-salts-substitute-preserves-paralysis`. This does not prove the
upstream assertion closed: the native boundary and exact fixture denotation
must be reviewed first. It does prove that the current JSON is a stale work-list
snapshot and must be regenerated after evidence adjudication.

Transform likewise still names multiple `upstream-transform-*` required cases;
the newer Transform fixtures must be matched assertion by assertion before any
row is upgraded. Filename similarity is not proof.

### Terminal rationales remain human adjudications

The structurally complete map contains 1,693 non-applicable rows. The validators
cannot prove that each owner-level exclusion preserves the assertion's
denotation. A later-generation owner may exercise a generic operation reachable
through a Gen 3 owner. The known pattern is Imposter versus Transform: Imposter
is absent, while transformation itself is reachable. Exact trigger, ownership,
ordering, and effect semantics must match before recording a Gen 3 alias.

## `futuremove` completeness boundary

The current regression map includes Future Sight tests and delayed-slot source
mapping. The separate condition audit finds both effective Gen 3 creators
(Future Sight and Doom Desire), the shared `futuremove` slot condition, and its
residual removal. This closes the specific historical extractor omission, not
the general risk. Future extractor changes must continue to enumerate literal
and computed dynamic add/remove calls for volatile, side, slot, weather,
pseudo-weather, and status state.

## Hygiene observations

No stale `/tmp` oracle JSONL, Transform diff directory, or atomic-fixture temp
directory was present during this audit. `verify/inventory/gen3-source-applicable.tsv`
is an older untracked heuristic projection and remains a cleanup candidate once
no consumer references it. Several narrative documents retain older 268/194 or
74 assertion-specific counts; the current machine artifact and validator report
283 applicable, 201 requiring a case, and 82 applicable assertion-specific.

## Conclusion

The pinned upstream source denominator and runtime-registration denominator are
complete and reproducible. The per-test v1 artifact is useful as an exhaustive
work list, but it is not yet a sound completeness proof because opposite Gen 3
replacement assertions are not representable, evidence categories include an
admission/differential conflation, and the evidence projection lags newer
fixtures. Implement schema v2 and its validator before using this map as a
completion gate. Do not change feature support merely because an upstream-shaped
case passes.
