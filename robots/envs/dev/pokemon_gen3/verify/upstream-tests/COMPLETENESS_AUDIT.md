# Independent upstream-test completeness audit

Pinned oracle: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

This audit checks the two generated censuses without treating the frozen native
descriptor inventory as an independent source of truth. It does not change any
support classification.

## Proven structural coverage

- The full pinned `test/sim` universe contains 1,976 static declarations.
  The reviewed partitions map 1,053; the remaining 923 are preserved as
  explicit unadjudicated audit debt in `all-test-census.json`. This prevents
  selected-file coverage from being mistaken for a whole-suite adjudication.

- The inherited census contains 553 declarations from 103 move, ability, and
  item files selected by the frozen descriptor inventory.
- The core census contains 496 declarations from its explicitly listed core,
  misc, ruleset, and team-validator partitions.
- An independent AST walk finds 31 statically declared tests under `test/sim`
  whose name, enclosing suite, or body names or selects Gen 3. All 31 occur in
  one of the two maps. See `explicit-gen3-completeness.json`.

The raw censuses deliberately retain 147 inherited and 225 core heuristic
rows. Both sets have now been manually adjudicated into the canonical
`gen3ou-test-map.json`. The unified map extends that review to all 1,976 static
declarations. That resolves test applicability, not implementation: 82 of 283
applicable declarations currently have complete assertion-specific evidence;
201 still require an exact focused or differential case. Of those open rows,
36 have partial evidence and 38 only have entity-level candidate evidence.

## Frozen-inventory omissions

Resolving the pinned `Dex.forGen(3)` and comparing its standard entities with
upstream move/ability/item test filenames now finds one tested Gen 3 entity
which the runtime-closed descriptor inventory does not contain: Shadow Tag.
Assist and Sheer Cold enter through legal Metronome, while Struggle is created
by request normalization; their five declarations are now in the main census.

| Upstream test | Boundary | Audit disposition | Required evidence |
|---|---|---|---|
| `test/sim/abilities/shadowtag.js:13` “prevent most Pokémon from switching normally” | trapping, legal choices/request | Format-unreachable. Wobbuffet and Wynaut are the only standard Gen 3 origins and both are Uber. Every Gen 3 ability-changing operation is source-preserving, so closure from legal initial abilities cannot create Shadow Tag. | Retain admission plus ability-origin closure evidence; do not add an illegal battle fixture. |
| `test/sim/abilities/shadowtag.js:23` “not prevent switching by moves” | trapping, move-driven switching | Same format-unreachability; the scenario also uses post-Gen-3 U-turn. | No Gen 3 OU runtime case. |
| `test/sim/abilities/shadowtag.js:34` “other Shadow Tag can switch” | trap immunity, legal choices/request | Same format-unreachability. Gen 3's `onFoeTrapPokemon` is unconditional, so this modern assertion is not Gen 3 semantics anyway. | No Gen 3 OU runtime case. |
| `test/sim/abilities/shadowtag.js:44` “trap-immune Pokémon can switch” | trap immunity, legal choices/request | Same format-unreachability. The modern Ghost trap immunity is not a Gen 3 rule. | No Gen 3 OU runtime case. |

This is a descriptor-census omission, not a support claim. Shadow Tag is
source-proven unreachable rather than merely awaiting a creation-path search.
The generated supplemental JSON is an assertion-level map: every omitted test
records mechanics, observable boundaries, reachability and evidence, all four
native evidence categories, case necessity, and pinned source mappings.

## False terminal exclusions corrected

The inherited mapper previously searched the whole test body for names of
post-Gen-3 mechanics and treated any match as proof that the assertion was
unreachable. This confused scaffolding with semantics. For example, the
Intimidate/Substitute assertion happened to use a Protean Pokémon.

The mapper now makes a terminal post-Gen-3 disposition only when the semantic
test name identifies that dependency. Body-only matches remain visible source
adjudication debt. This reopens Intimidate/Substitute, Levitate's airborne
property, Pickup's switched-out state, Shield Dust's user-side secondary, and
several move assertions for honest review while retaining named Mold Breaker,
Z-Move, Life Orb, and similar assertions as unreachable.

## Remaining proof gaps

1. Entity-level native fixtures listed on inherited records are candidate
   evidence, not proof of the upstream assertion. Each applicable assertion
   needs an exact fixture, focused invariant, or an explicit explanation of
   why an existing case proves the same branch.
2. The 198 `required_case` records in the canonical map are the live upstream
   regression-evidence queue. Their presence does not change descriptor support.
3. The core census intentionally excludes `test/sim/othermetas` (non-OU custom
   formats) and `test/sim/tools` (test infrastructure). This scope decision
   should remain explicit if upstream reorganizes the suite.
4. Runtime-created and delegated descriptors require a closure proof in
   addition to submitted-set validation. The inventory now covers Metronome's
   pool and synthetic Struggle; the regression audit independently keeps this
   distinction visible.
