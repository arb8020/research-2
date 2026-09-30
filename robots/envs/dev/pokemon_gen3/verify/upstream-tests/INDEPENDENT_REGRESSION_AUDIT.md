# Independent Gen 3 OU upstream regression audit

Pinned Pokemon Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This audit independently checks the upstream-test denominator and exposes the
applicable subset for review. It does not change native support classification.

## Result

Pinned Showdown contains 1,976 static `it()` / `test()` declarations below
`test/sim`. Every declaration has exactly one record in
`gen3ou-unified-regression-map.json`: 1,053 records come from the reviewed
canonical partitions and 923 from the whole-suite overlay. Of those static
declarations, 283 are applicable to legal Gen 3 OU semantics.

`gen3ou-applicable-regression-map.tsv` is the review projection for those 283
assertions. Every row records the pinned source file, line and full test name;
mechanics and observable boundaries; native unit, differential, invariant and
randomized evidence; evidence scope; the required new case, if any; and the
authoritative semantic sources. The JSON remains canonical.

The evidence result is deliberately weaker than a support claim:

| Evidence result | Assertions |
|---|---:|
| assertion-specific | 82 |
| partial | 36 |
| entity-level candidates only | 38 |
| none | 127 |
| **requires an exact case** | **201** |

Passing an upstream-shaped case cannot promote a feature by itself. Promotion
still requires the native semantic boundary, focused proof, differential
evidence, source mapping and the separate feature-classification gate.

## Runtime registration

Static declarations are not the complete Mocha denominator. The pinned suite
registers 2,172 cases: 2,129 active and 43 pending. Loops expand the 1,976
declarations into 196 additional instances. The static map contains 283
applicable declarations, 82 with assertion-specific evidence and 201 still
requiring an exact case. Separately, the runtime census finds 41
Gen-3-OU-applicable dynamic variants. Its checked contract records all 41 as
proven; it must be validated alongside the static map.

The last nine obligations were the three source-linked traps (`Block`, `Mean
Look`, and `Spider Web`) and the six partial traps (`Bind`, `Clamp`, `Fire
Spin`, `Sand Tomb`, `Whirlpool`, and `Wrap`). Their descriptor-specific
pinned-oracle Baton Pass differentials now prove that move-driven switching
escapes each restriction.

This distinction is material: a source-file census can contain the declaration
which creates a test while still omitting individual mechanics represented by
its loop values.

## Semantic-transposition audit

Owner-introduction metadata alone is insufficient: a post-Gen-3 ability test
can assert an operation reachable through a legal Gen 3 owner. All 411 such
ability rows were therefore re-audited. The enforced table records 15 legal
Gen 3 alias obligations, 15 shared-operation-but-not-equivalent assertions,
and 381 owner-specific terminal rows. Transform behind Substitute is one of
the aliases; its upstream Imposter owner remains unreachable, while the legal
Gen 3 Transform boundary now requires its own differential case.

The five manually represented dynamic Random Battle registrations are outside
the native battle-runtime contract, but their source identities should still
record exact declaration lines in `test/random-battles/all-gens.js`: 40, 168,
228, 233, and 283.

## Future Sight / `futuremove` check

The regression map contains the pinned Future Sight suite, including its
resolved `data/mods/gen4/conditions.ts#futuremove` source and Gen 3 delayed-slot
boundaries. The independent condition-path audit separately proves both
effective creators—Future Sight and Gen 3 Doom Desire—and residual removal are
present in the frozen inventory. Test coverage and condition-creation closure
remain distinct proof obligations even though both are now exact.

## Reproduction

From this directory:

```sh
node validate-unified-regression-map.js
node validate-all-test-census.js .
node validate-runtime-registration-census.js /path/to/pinned/showdown
node test-runtime-registration-contract.js
node validate-semantic-map.js --require-complete
node audit-explicit-gen3-completeness.js /path/to/pinned/showdown .
node build-applicable-review.js
```

Expected facts at this revision are 1,976 static declarations, 283 applicable
assertions, 2,172 registered cases, 196 dynamic expansions, 41 applicable
dynamic variants, and 31 independently discovered explicit-Gen-3 declarations.

## Independent reproduction, 2026-09-27

The audit was rerun read-only against the pinned checkout and current native
evidence. All validators passed with the following independently observed
facts:

- 1,976 static declarations: 1,053 canonical and 923 overlay-adjudicated,
  with no omissions or duplicate source keys;
- 2,172 registered tests: 2,129 active, 43 pending, and 196 expansions beyond
  the lexical declarations;
- 41 applicable dynamic variants, all carrying the required descriptor-level
  or assertion-specific proof;
- 31 declarations independently discovered by explicit Gen 3 syntax/name/body
  scanning, all represented in the map;
- zero unresolved rows in the selected 1,053-row semantic map, after applying
  372 reviewed manual overlays;
- 283 applicable static assertions, of which 82 have assertion-specific
  evidence and 201 still name an exact required case.

An isolated copy of the generator produced byte-identical
`all-test-census.json`, `gen3ou-unified-regression-map.json`, and
`gen3ou-applicable-regression-map.tsv`. The temporary copy was removed after
comparison.

### Conflict and merge order

This audit changes no kernel, generated data, observer, feature classification,
or fixture. It must remain logically downstream of the frozen Showdown revision
and upstream-test census, but upstream of any classification promotion based on
test evidence. The safe merge order is:

1. pin/freeze the Showdown revision and resolved Gen 3 entity closure;
2. merge the static and runtime-registration censuses plus their validators;
3. merge reviewed applicability/source overlays and this audit narrative;
4. implement and verify named missing native/differential cases;
5. only then update descriptor-map support classification through its separate
   source/native/focused/differential gate.

The map has no content conflict with delayed-slot or other mechanics patches:
new evidence should update evidence references and regenerate projections after
the underlying cases land. It intentionally does not modify
`TEAM_STATUS_CURE_FIXTURES.md`.

### Remaining proof limit

Enumeration and the reviewed post-Gen-3 ability transposition boundary are
established. The 1,693 terminal static rows remain local source adjudications,
not a proof that every low-level operation is equivalent across owners. Exact
trigger, ownership, ordering, and effect denotation are required before an
assertion becomes a Gen 3 alias. The complete declaration/runtime census and
283 applicable rows therefore remain narrower than exhaustive battle-state
coverage.
