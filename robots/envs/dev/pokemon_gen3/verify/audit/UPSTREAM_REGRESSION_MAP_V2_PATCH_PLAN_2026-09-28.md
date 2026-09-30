# Upstream regression-map v2: minimal patch plan

Pinned revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This is a schema/build/validation plan only. It does not change native code,
generated data, fixtures, descriptor classification, or support claims.

## Current data flow

The reviewed source inputs flow through two generated maps:

```text
gen3ou-inherited-test-map.json        core-test-census.json
entity-manual-adjudications.json      core-manual-adjudications.json
resolved-gen3-entity-test-gaps.json
                    |
                    v
          build-gen3ou-test-map.js
                    |
                    v
             gen3ou-test-map.json
                    |
all-test-census.json + whole-suite overlays
                    |
                    v
       build-unified-regression-map.js
                    |
                    v
    gen3ou-unified-regression-map.json
                    |
                    v
           build-applicable-review.js
```

`build-gen3ou-test-map.js` currently collapses two independent facts into one
`applicability.disposition`. For a `generation_semantics_differ` row it emits a
terminal reason and cannot emit a required Gen 3 replacement case.
`build-unified-regression-map.js` preserves that collapse as
`applicable: false`. Both validators therefore accept a contradicted modern
assertion with no record of the actual Gen 3 behavior.

The evidence product currently has four arrays:

```text
native_units
differential_cases
invariants
randomized_scenarios
```

The special EV-validation record puts seven admission cases in
`differential_cases`, although they live inside `verify/admission/cases.json`
and are not battle-transition differentials.

## Migration denominator

The current unified map contains:

- 1,976 static records;
- 283 applicable modern/source-transposed assertions;
- 201 applicable assertions requiring a case;
- 52 `generation_semantics_differ` records;
- 50 of those 52 with no evidence and two with mapped evidence candidates;
- 21 already identified opposite-Gen-3 obligations in the move suites;
- seven EV admission IDs, all attached to one upstream Team Validator row.

The 21 known move rows are exactly:

| Family | Source rows |
| --- | ---: |
| Brick Break | 3 |
| Conversion 2 | 1 |
| Destiny Bond | 1 |
| Explosion | 1 |
| Fury Cutter | 1 |
| Future Sight | 6 |
| Glare | 1 |
| Hyper Voice | 1 |
| Stockpile | 1 |
| Toxic | 1 |
| Transform | 2 |
| Uproar | 1 |
| Wish | 1 |
| **Total** | **21** |

Stockpile currently carries a focused C reference plus
`stockpile-cap-spit-up`; Snatch is the other contradicted row with an evidence
candidate. These are candidates for review, not automatic v2 proof. The other
50 contradicted rows have no mapped evidence. A sound migration must adjudicate
all 52, not encode only the known 21 and leave the same omission class possible
for the remaining 31.

## Minimal new reviewed input

Add `verify/upstream-tests/gen3-replacement-obligations.json`. It is a reviewed
input, not generated evidence and not a support manifest:

```json
{
  "schema": "pokemon-gen3ou-replacement-obligations-v1",
  "pinned_revision": "6e71625b9e6cffeda268b548ae7f43a7643fc3f0",
  "records": [
    {
      "source": {
        "file": "test/sim/moves/transform.js",
        "line": 102,
        "full_test_name": "Transform > should fail against Pokemon with a Substitute"
      },
      "assertion": "Gen 3 Transform succeeds against a target behind Substitute",
      "mechanics": ["Transform target gate"],
      "boundaries": ["move hit/effect dispatch", "canonical battle state"],
      "semantic_sources": ["data/mods/gen3/moves.ts#transform"],
      "legal_scenario": "legal Gen 3 OU Transform user and a target with an intact Substitute",
      "evidence": {
        "native_units": [],
        "differential_cases": [],
        "admission_cases": [],
        "invariants": [],
        "randomized_scenarios": []
      },
      "evidence_scope": "none",
      "required_case": "transform-substitute-success"
    }
  ]
}
```

Key replacement records by the exact triple `(file, line, full_test_name)`.
The file must contain exactly one row for every source record whose upstream
disposition is `contradicted_by_gen3`, initially all 52 current
`generation_semantics_differ` rows. This exact-overlay rule prevents a newly
contradicted assertion from silently bypassing review.

Do not allow a nullable bag of replacement fields on arbitrary records. Use the
sum-type shape below in generated artifacts:

```text
upstream_disposition:
  { kind: "applicable" }
  { kind: "contradicted_by_gen3", gen3_obligation: Gen3Obligation }
  { kind: "unreachable", reason: string }
  { kind: "outside_contract", reason: string }
```

The existing detailed legacy disposition may remain as
`upstream_disposition.detail` during migration, but it must not decide whether
a Gen 3 obligation exists.

## Exact file changes

### Reviewed input

- Add `verify/upstream-tests/gen3-replacement-obligations.json` with 52 exact
  source-keyed records.
- Extend the 21 known move records first from pinned source. Adjudicate the
  remaining 31 before enabling the v2 completeness validator; do not create
  placeholder terminal reasons.
- In `core-manual-adjudications.json` and
  `entity-manual-adjudications.json`, keep the modern-source adjudication but
  rename new uses of `generation_semantics_differ` to
  `contradicted_by_gen3`. The replacement assertion itself belongs in the new
  overlay so there is one uniform join point for manual and inherited rows.

### Builders

- `build-gen3ou-test-map.js`
  - Add `admission_cases` to the evidence product.
  - Teach `evidenceFromIDs` the explicit `admission:` prefix.
  - Move the seven EV IDs into `admission_cases`.
  - Load and exact-join `gen3-replacement-obligations.json` after the 1,053
    canonical rows are formed.
  - Emit `upstream_disposition` and `gen3_obligation`; never derive replacement
    proof merely from the old terminal row's non-empty evidence.
  - Preserve explicit `evidence_scope`. A non-empty evidence array is a
    candidate until the reviewed input marks it `assertion_specific`.
- `build-unified-regression-map.js`
  - Preserve the sum type and the complete replacement obligation verbatim.
  - Add `admission_cases` to `emptyEvidence` and every copied evidence product.
  - Keep `applicable` temporarily as a compatibility projection meaning only
    “the upstream assertion itself applies”; do not count a replacement as an
    applicable upstream assertion.
  - Add summary fields `contradicted_by_gen3`,
    `gen3_replacement_assertion_specific`, and
    `gen3_replacements_requiring_case`.
- `build-applicable-review.js`
  - Add an `admission_cases` column.
  - Keep the existing 283-row upstream-applicable TSV stable.
  - Add a separate generated `gen3ou-replacement-obligations.tsv` containing
    all 52 replacement rows. Mixing upstream and opposite assertions in one TSV
    makes review counts ambiguous.
- `build-all-test-census.js`
  - No enumeration change is required.
  - Preserve the detailed source disposition and add a boolean or kind showing
    that a replacement obligation is attached, so census review can detect a
    stale join without duplicating the obligation body.

### Validators

- `validate-semantic-map.js`
  - Require the replacement-overlay revision and exact source-key coverage.
  - Reject duplicates, extra rows, stale names/lines, and any contradicted row
    without exactly one obligation.
  - Reject an obligation with empty assertion, mechanics, boundaries, semantic
    sources, or legal-scenario constraint.
- `validate-unified-regression-map.js`
  - Require schema `pokemon-gen3ou-unified-upstream-regression-map-v2`.
  - Require all five evidence arrays on both ordinary assertions and Gen 3
    obligations.
  - Forbid C test symbols in `differential_cases` and
    `admission_cases`; require admission references to resolve to an explicit
    admission artifact and case ID.
  - Require every `contradicted_by_gen3` row to carry exactly one obligation.
  - Require each obligation to satisfy exactly one proof branch:
    `evidence_scope === assertion_specific` with at least one reviewed evidence
    reference, or a non-empty `required_case`.
  - Reject `required_case` together with assertion-specific proof.
  - Reject evidence on a `none` scope and reject assertion-specific scope with
    empty evidence. This prevents filename presence from auto-promoting proof.
  - Assert migration cardinalities: 1,976 source rows, 52 contradicted rows,
    and 52 replacement obligations. The initial open/proven split must equal
    the reviewed overlay, not a hard-coded optimistic count.
- `validate-all-test-census.js`
  - Continue proving the 1,976-row denominator.
  - Additionally compare the census replacement marker against the 52-row
    overlay join.
- Add mutation tests beside `test-runtime-registration-contract.js` for:
  missing obligation, duplicate obligation, wrong source line/name, empty
  semantic source, evidence under `none`, assertion-specific with no evidence,
  both proof and required case, admission ID placed under differential, and an
  unresolved admission artifact/case pair.

## Evidence reference shape

Bare strings cannot reliably distinguish a standalone differential JSON from a
case inside an aggregate artifact. The smallest backward-compatible correction
is to retain strings for current categories and make admission references
explicit objects:

```json
"admission_cases": [
  {"artifact": "verify/admission/cases.json", "case_id": "legal-ev-510"}
]
```

The validator must parse the artifact, prove the case ID exists exactly once,
and reject battle fixtures in this category. A later all-category typed-reference
migration may be useful, but it is not required to close this defect.

## No-auto-promotion rule

The upstream map records verification evidence; it does not own supported
feature classification. Builders and validators must not import or mutate
`descriptor-map.json`, and `classify.js` must not consume v2 proof as an
automatic support decision. Feature promotion remains a separate gate requiring
the native boundary, focused test, differential evidence where observable,
source mapping, and pinned revision.

Within the map, adding a fixture file must not change `evidence_scope`.
Evidence enters only through reviewed adjudication input. Generation may verify
that a reference exists; it may not infer that the referenced scenario proves
the assertion.

## Prerequisite and merge order

1. Freeze the current 1,976/2,172 static/runtime censuses and pin tests for
   their counts.
2. Add the fifth `admission_cases` evidence category and migrate the seven EV
   IDs. Regenerate v1-compatible artifacts and verify no battle evidence count
   changes.
3. Add and validate the 52-row replacement overlay. Complete source review of
   all 31 rows beyond the known 21 before calling the overlay complete.
4. Change `build-gen3ou-test-map.js` to emit the sum type and obligation, then
   update `validate-semantic-map.js` and its mutation tests.
5. Change the unified builder/schema and unified validator. Expected source
   counts remain 1,976 total and 283 applicable modern assertions; a new
   independent denominator is 52 replacement obligations.
6. Generate the separate 52-row replacement TSV and update documentation
   counts from machine output.
7. Review newly landed fixtures (including Smelling Salts and Transform) against
   exact assertions. Update evidence scope only after semantic review.
8. Run every static census, runtime-registration, explicit-Gen-3, semantic-map,
   unified-map, and mutation validator.
9. Only after this verification layer is stable may the separate feature-map
   gate consider classification changes.

## Completion condition for the patch

The schema patch is complete when a deterministic rebuild produces:

- exactly 1,976 source-test records and 2,172 runtime registrations;
- exactly 283 upstream-applicable static assertions in the existing projection;
- exactly 52 contradicted rows and 52 joined Gen 3 obligations;
- exactly seven EV admission references in `admission_cases` and none of those
  seven in `differential_cases`;
- zero contradicted rows without a replacement assertion;
- zero replacement obligations lacking either reviewed assertion-specific
  evidence or a named required case;
- passing positive validators and all negative mutation tests;
- no change to native code, generated battle data, or descriptor support
  classification caused by the migration itself.

This closes the schema omission. It does not close the semantic cases named by
the obligations and is not a Checkpoint 6 support-completion claim.
