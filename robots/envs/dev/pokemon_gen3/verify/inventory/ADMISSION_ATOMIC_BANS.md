# Gen 3 OU atomic admission bans

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This records the completed atomic, descriptor-tag, and descriptor-predicate slices of the separate
pre-battle admission interpreter. It does not claim complete team validation. A known set which
matches none of these rules returns `POKEMON_ADMISSION_RESULT_INCOMPLETE`, not
accepted.

## Boundary

Pinned Showdown resolves `[Gen 3] OU` through `Dex.forFormat('gen3ou')` and its
recursive RuleTable before `TeamValidator` checks a submitted set. The native
counterpart is a generated identity universe plus an ordered atomic-ban
program. `PokemonAdmissionBundle` carries its own generated-content
fingerprint and is also checked against the generation, plugin fingerprint,
and format ID of the one `PokemonResolvedBundle` it accompanies. Admission
does not mutate battle state or consume PRNG.

The completed rules are:

- abilities: Sand Veil and Soundproof;
- items: Bright Powder and Lax Incense;
- moves: Acupressure, Assist, Double Team, Minimize, and Swagger.

The generated rule records also retain their resolved parent provenance.
Bright Powder and Lax Incense exhaust `evasionitemsclause`; Acupressure,
Double Team, and Minimize exhaust `evasionmovesclause`. Those two aliases have
no independent callback or admission branch, so their denotation is exactly
their proven flattened children. Larger aliases such as `standard` remain
unsupported until every reachable child closes.

The same interpreter consumes compact tags generated from the effective
resolved descriptor or, for species, Showdown's validation/tier species. One
generic tag-ban rule rejects Uber species, Unobtainable identities, and
Nonexistent identities across the applicable species/move/ability/item
domains. Acupressure remains an exact ban before its later-generation tag.
`-unreleased` is intentionally separate: Showdown ties it to hidden-ability
slot and source-generation semantics rather than a descriptor tag.

OHKO Clause uses the same interpreter with a generated move-property bit.
The exact flattened closure is Fissure, Guillotine, Horn Drill, and Sheer
Cold. The rule examines literal submitted move slots; Metronome is deliberately
unflagged even though it can delegate to an OHKO move at battle runtime.

The interpreter represents both OHKO Clause and Accuracy Trap Clause as a
bounded all-of rule. Accuracy Trap requires a guaranteed accuracy-drop move
and either a trapping move or trapping ability on the same submitted set. Its
generated closure is five accuracy moves, three trapping moves, and three
trapping abilities; probabilistic accuracy drops and partial-trapping moves
are deliberately outside those predicates.

Team admission is a separate phase after every member passes set-scoped
checks. Speed Pass reuses the all-of rule over Baton Pass and generated speed
source predicates. One Boost Passer uses one anchored-cardinality rule: a
Baton Pass set may contain at most one counted boost-source occurrence, and a
team may contain at most one such qualifying set. The exact generated policy
closures are intentionally not inferred from battle boost descriptors.

EV Limit uses a generated stat-vector rule bound to the resolved format
manifest rather than an ID-specific validator branch. External input is
normalized into an explicit presence bit plus a six-component vector. The
rule accepts components in `0..255` and totals through 510 inclusive. The same
boundary also preserves Showdown's adjacent `validateStats` behavior: omitted
or all-zero EVs are rejected above level one, while an all-zero level-one set
is valid. These normalization and per-component checks do not redefine the
denotation of EV Limit, which is the total cap.

Obtainable Abilities uses a generated allowed relation rather than a
species-specific validator tree. Build-time resolution produces a compressed
sparse row for each of 393 canonical species identities and 517 legal
species/ability pairs. Runtime first normalizes names to canonical IDs, then
the generic relation interpreter tests the selected ability against the
species row. Unknown identities therefore remain distinct from a known but
disallowed pair, and earlier bans retain deterministic precedence.

Obtainable Formes adds a generated guarded-rewrite rule to the same ordered
program. Its exact Gen 3 closure is Castform-Sunny, Castform-Rainy, and
Castform-Snowy: each requires Forecast and normalizes to base Castform. The
API returns admission and the normalized set as one transactional product;
set and team output buffers remain unchanged on unknown input or rejection.
Selectable Deoxys formes are not battle-only and therefore are not rewritten.
The relevant upstream selectable-forme scenario is Gen 3 OU-unreachable
because those Deoxys identities are banned as Uber. Inputs and outputs at this
boundary are canonical IDs; alias spelling preservation is not claimed.

The generator proves that `-unreleased` has no Gen 3 OU submitted-set match
because the normalized species universe contains zero hidden-ability slots.
It also resolves the inherited `Huntail + Shell Smash + Sucker Punch` and
`Hypnosis + Gengarite` complex bans and requires at least one operand of each
to remain absent from the Gen 3 universe. These three rules are classified
unreachable, not implemented, and have no runtime branch.

Authoritative source paths are `config/formats.ts`, `data/rulesets.ts`,
`data/mods/gen3/rulesets.ts`, `sim/dex-formats.ts`, and
`sim/team-validator.ts`. Generated provenance and the exact pinned revision
are embedded by `tools/generate_gen3_admission.js`.

## Evidence

- Native boundary: `native/pokemon_admission.c` and generated
  `native/gen3_admission_data.c`.
- Focused proof: `native/test_admission.c#test_atomic_bans`, including exact
  rule index, identity kind, move-slot diagnostics, program precedence,
  malformed packed input, and cross-plugin/cross-format rejection.
- Aggregate proof: `native/test_admission.c#test_rule_source_provenance`
  asserts the exact parent of all nine flattened rules; the generator rejects
  any pinned RuleTable parent change.
- Differential proof: `verify/admission/cases.json`, with one legal control,
  each of the nine atomic bans, Uber form coverage, two Unobtainable items,
  every Nonexistent identity kind, and a recombined multi-ban set. Both native
  and pinned `TeamValidator` consume that one scenario source and agree on
  rejection and normalized species identity across 68 set- and team-scoped
  cases.
- Tag proof: `native/test_admission.c#test_generated_tag_bans` asserts the
  complete generated tag cardinalities, exact rule identity, input-kind and
  move-slot diagnostics, and legal false-positive controls.
- Predicate proof: `native/test_admission.c#test_generated_ohko_predicate`
  asserts the exact four-move closure, move-only ownership, rule identity and
  move-slot diagnostics, malformed-program rejection, and Metronome and
  ordinary-move negative controls.
- Conjunction proof:
  `native/test_admission.c#test_generated_accuracy_trap_conjunction` asserts
  exact cross-kind predicate closure, deterministic move-slot diagnostics,
  malformed all-of programs, positive ability/move routes, and negative
  probabilistic and partial-trapping controls.
- Team proof: `native/test_admission.c#test_team_admission` covers exact
  move/item/ability source cardinalities, set-versus-team staging, same-set
  overflow, second-passer rejection, Speed Pass routes, earlier set-rule
  precedence, malformed capacity, and later-member diagnostics.
- Stat-vector proof: `native/test_admission.c#test_ev_stat_vector_policy`
  covers the inclusive 510 limit, `0..255` components, omission, the
  level-one zero-vector exception, malformed normalized inputs, manifest/rule
  consistency, and a violation on a later team member. The shared differential
  source contains ten corresponding EV fixtures.
- Relation proof: `native/test_admission.c#test_species_ability_relation`
  asserts the exact 393-row/517-pair CSR shape, canonical relation and source
  IDs, primary and secondary legal slots, known disallowed pairs, atomic-ban
  precedence, and malformed-bundle rejection. Seven shared differential
  fixtures cover the same semantic boundary against pinned `TeamValidator`.
- Rewrite proof: `native/test_admission.c#test_species_rewrite_normalization`
  asserts the exact three-row generated closure, Forecast guards, canonical
  Castform result, transactional set/team commit, rejection preservation, and
  malformed-bundle rejection. Six shared differential fixtures prove base and
  battle-only Castform input, the required-ability rejection, and a later team
  member against pinned `TeamValidator`.
- Determinism: the native JSONL projection is replayed and compared byte for
  byte.
- Generated-data proof: regeneration from the clean pinned checkout is byte
  identical.

Showdown's human-facing validation-message order is not part of the native
runtime contract. The native program's deterministic first-rule diagnostic is
proved by focused tests, while the differential compares the semantic fact
that the submitted set is rejected.

## Still unsupported

Released and remaining obtainable constraints other than formes and
abilities, learnsets and sources, remaining level/set fields, complex combination
bans, aggregate team rules, and remaining aliases are outside this slice.
They remain unsupported inventory records and must continue to fail closed.
