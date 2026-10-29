# Transform battle-profile family

Pinned oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Semantic boundary

Showdown's `data/moves.ts#transform` delegates to
`sim/pokemon.ts#Pokemon.transformInto`. The native move descriptor likewise
owns only a generated Hit handler. Its program selects one validated
`PokemonTransformPolicy`; the generic kernel performs the profile-copy
transaction.

The copied mutable product is current species and types, non-HP stored stats,
boosts, current move identities, copied PP state, the Gen 3 Hidden Power
profile, ability, transformed state, and current-turn speed staging. HP,
maximum HP, level, status, item, immutable submitted identity, base move state,
and ordinary volatiles remain source-owned. Switching or faint cleanup restores
the complete immutable base profile without refunding spent Transform PP.

Gen 3 policy permits a transformed source to transform again and permits
Transform through Substitute, but rejects an already-transformed target.
Copied abilities replace the old ability without running the copied ability's
Start callback. Focus Energy and other ordinary target volatiles are not
copied.

The generic kernel contains no Transform move ID. Generation data supplies the
policy and handler binding; a typed generation formula reconstructs the
temporary species-derived speed from the source set's normalized stat inputs.

## Evidence

- Focused C test:
  `native/test_pokemon.c#test_transform_generic_profile_copy_policy`.
- Differential fixtures:
  `transform-substitute-hidden-power`, `transform-source-retransform`,
  `transform-target-rejection`, `transform-ability-start-switch-reset`, and
  `transform-forecast-freeze`.
- Source mapping:
  `data/moves.ts#transform`, `sim/pokemon.ts#transformInto`,
  `sim/pokemon.ts#setSpecies`, and `sim/pokemon.ts#clearVolatile`.

The fixtures prove 17 stable boundaries, including labeled PRNG consequences
of speed staging, Substitute bypass, Hidden Power construction, source
re-transformation, transformed-target rejection, copied-ability no-Start,
switch restoration, and Forecast suppression. Classification is limited to
the Transform move and its reachable Hit hook; no unrelated profile-copy or
future-generation behavior is claimed.
