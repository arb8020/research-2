# Independent validation of the Gen 3 OU upstream regression map

Pinned Pokemon Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This is an independent validation of the regression-test proof boundary. It
does not change native implementation, generated data, descriptor
classification, or supported-feature claims.

## Authoritative artifacts

The row-level map already exists and should not be duplicated:

- `verify/upstream-tests/gen3ou-unified-regression-map.json` is the canonical
  machine-readable map for every pinned static test declaration.
- `verify/upstream-tests/gen3ou-applicable-regression-map.tsv` is the complete
  human-review projection of applicable Gen 3 OU assertions.
- `verify/upstream-tests/runtime-registration-census.json` records tests
  expanded dynamically by loops.
- `verify/upstream-tests/REGRESSION_MAP_COMPLETENESS_PROOF.md` documents the
  enumeration and evidence contract.

Each applicable static record identifies the pinned source file, source line,
full test name, mechanics, semantic boundaries, four separate native evidence
classes, evidence scope, authoritative Showdown sources, and either an exact
required case or assertion-specific evidence. Each excluded record has a
terminal disposition and evidence-based reason.

## Reproduced result

The pinned checkout at `/private/tmp/pokemon-showdown-audit` resolved to the
required revision. Running all checked validators reproduced:

| Boundary | Result |
| --- | ---: |
| Static `it()` / `test()` declarations | 1,976 |
| Missing or duplicated static declarations | 0 |
| Runtime-registered tests | 2,172 |
| Runtime expansions beyond static declarations | 196 |
| Explicit Gen 3 declarations independently found and mapped | 31 |
| Applicable Gen 3 OU static assertions | 268 |
| Applicable dynamic variants | 41 |
| Applicable dynamic variants with evidence | 41 |
| Applicable assertions with assertion-specific evidence | 70 |
| Applicable assertions with partial evidence | 36 |
| Applicable assertions with entity-level evidence only | 38 |
| Applicable assertions with no evidence | 124 |
| Applicable assertions requiring an exact new case | 198 |

The semantic-map validator reports 72 assertion-specific records across all
dispositions. Two are terminal/non-applicable records; the support-relevant
applicable count is therefore 70. These values are consistent rather than a
denominator disagreement.

## Omission-sensitive check

The earlier `futuremove` inventory omission did not omit the upstream Future
Sight tests from this independent test census:

- `test/sim/moves/futuresight.js:31` and `:405` have assertion-specific
  evidence;
- `test/sim/moves/futuresight.js:236` remains an explicit required case for
  screen interaction at delayed-hit resolution;
- modern Future Sight assertions with different generation semantics remain
  excluded with terminal reasons rather than being treated as Gen 3 proof;
- `test/sim/moves/wish.js:31` and `:64` remain explicit required cases.

This distinction is important: the test map can be enumeration-complete while
the native implementation and its evidence are intentionally incomplete.

## Commands run

From `verify/upstream-tests`:

```sh
node validate-unified-regression-map.js
node validate-all-test-census.js .
node validate-runtime-registration-census.js \
  /private/tmp/pokemon-showdown-audit
node test-runtime-registration-contract.js
node validate-semantic-map.js --require-complete
node audit-explicit-gen3-completeness.js \
  /private/tmp/pokemon-showdown-audit .
```

All commands passed.

## Completeness method and remaining blind spots

The proof combines a full static AST census, actual Mocha registration, an
independent explicit-Gen-3 scan, resolved-Gen-3 entity discovery, and reviewed
applicability overlays. This closes the known structural omission modes:
filename-only discovery, loop collapse, inventory-only discovery, and explicit
generation tests outside selected entity files.

It does not prove that every manual semantic adjudication is correct. The
1,708 terminal/non-applicable decisions and source mappings still depend on
human interpretation of pinned Showdown semantics. Nor does it implement the
198 open assertions. Those limitations remain visible in the canonical map
and must not be converted into support claims merely because neighboring or
entity-level tests pass.

Feature promotion remains a separate gate requiring all of:

1. an implemented native semantic boundary;
2. a focused native test;
3. differential evidence against the pinned oracle;
4. an authoritative Showdown source mapping; and
5. an explicit descriptor-classification update.
