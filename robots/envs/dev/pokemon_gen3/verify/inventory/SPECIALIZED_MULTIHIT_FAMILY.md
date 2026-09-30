# Specialized per-hit composition

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Triple Kick and Twineedle are expressed by the ordinary multi-hit interpreter,
not named resolver branches. Generated move descriptors select two orthogonal
facts:

- whether accuracy is checked once or for every hit;
- whether base power is constant or multiplied by the one-based hit index.

The existing secondary-effect transaction executes after every completed hit.
Thus Twineedle owns one labeled secondary draw per hit, including failed status
applications, while Triple Kick owns one accuracy draw per attempted hit and
stops silently after a later miss. Fixed hit counts consume no multi-hit-count
draw. The kernel records explicit accuracy and source-sleep stop reasons.

## Source mapping

- `data/moves.ts`: `triplekick`, `twineedle` descriptors.
- `sim/battle-actions.ts`: `hitStepMoveHitLoop` and per-hit accuracy staging.
- `data/mods/gen3/scripts.ts`: Gen 3 `moveHit` loop, Update placement, and
  early-stop behavior.
- Native boundary: `PokemonMoveData.multihit_accuracy`,
  `POKEMON_BASE_POWER_HIT_INDEX`, and the generic multi-hit loop in
  `native/pokemon.c`.

## Evidence

- Focused: `native/test_pokemon.c#test_specialized_per_hit_composition`.
- Differential: `triple-kick-per-hit-complete`,
  `triple-kick-per-hit-stop`, `twineedle-per-hit-poison`, and
  `twineedle-poison-immunity`.
- The four fixtures match eight stable request/action boundaries exactly,
  including state, events, immunity decisions, effects, and labeled PRNG.

This claim does not include Beat Up. Party-member hit planning and temporary
attacker-stat overlays remain a separate unsupported capability.
