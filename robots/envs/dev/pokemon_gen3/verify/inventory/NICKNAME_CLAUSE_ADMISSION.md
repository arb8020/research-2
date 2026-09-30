# Nickname Clause admission

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Semantic boundary

Nickname validation is cold team admission, not mutable battle state. The
resolved format contributes one generated Nickname Clause rule. Generated
species metadata supplies each display name and base-species relation; the
generic admission interpreter owns normalization and rejection.

Pinned Showdown sources are `sim/team-validator.ts` (`validateSet`, including
length, normalization, form canonicalization, and species impersonation),
`sim/dex.ts` (`Dex.getName`), and `data/rulesets.ts` (`nicknameclause` team
uniqueness). Duplicate comparison is exact and case-sensitive after
normalization. Default and base-species names are exempt. Names of forms in
the actual species family canonicalize to its base species; an exact official
name from another family is rejected.

## Native representation

- `PokemonAdmissionSetInput.nickname` is optional UTF-8.
- `PokemonAdmissionNormalizedSet.nickname` is caller-owned fixed storage.
- The bound is 18 JavaScript UTF-16 code units, represented by at most 72
  UTF-8 bytes; malformed UTF-8 fails at the boundary.
- `PokemonAdmissionSpeciesMetadata` is immutable generated data.
- `POKEMON_ADMISSION_NICKNAME_CLAUSE_RULE` is generated only after the pinned
  resolved RuleTable and callback are verified.
- Set and team normalization remain transactional: rejected input never
  publishes a partial normalized product.

The battle kernel, `PokemonBattle`, PRNG stream, queues, and Ocean ABI are
unchanged.

## Evidence

`native/test_admission.c#test_nickname_clause_transaction` proves normalized
commit, duplicate ordering, case sensitivity, impersonation, length rejection,
malformed-bundle rejection, and output rollback. `verify/admission/cases.json`
contains eleven pinned-TeamValidator differential scenarios covering distinct
and duplicate names, defaults, forms, sanitation, ASCII and astral UTF-16
length, Unicode whitespace, and cross-species impersonation. The verifier
compares both normalized species and normalized names and replays the native
output exactly.
