# Attract and Cute Charm semantic family

The oracle is Pokémon Showdown revision
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`. The effective Gen 3 descriptors
are resolved from `data/mods/gen3/moves.ts` (`attract`) and
`data/mods/gen3/abilities.ts` (`cutecharm`), with generic event staging in
`sim/battle-actions.ts`, `sim/battle.ts`, and `sim/pokemon.ts`.

## Boundary

- The move descriptor owns `TryImmunity`. It checks gender before accuracy,
  but Gen 3 still consumes the move's accuracy draw; immunity wins if both
  rejection and miss occur.
- The Attract condition owns admission (`Start`), action denial
  (`BeforeMove`), and source-liveness cleanup (`Update`). Source liveness means
  active-slot membership, not positive HP.
- Cute Charm owns only its `DamagingHit` response: contact, a labeled 1/3
  activation draw, then installation of Attract on the event source with the
  ability holder recorded as provenance.
- The generic kernel owns event ordering, accuracy staging, volatile state,
  source provenance, and cleanup. It contains no Attract, Cute Charm, species,
  or move-ID branch.

## Native mapping

- Generated descriptors and owner bindings: `tools/generate_slice_data.js`
  and `native/gen3_slice_data.c`.
- Generic handler opcodes and state: `native/pokemon.h`.
- Program validation/execution, move `TryImmunity`, event dispatch, and
  invariants: `native/pokemon.c`.
- Gen 3 condition lifetime policy: `native/gen3_rules.c`.
- Focused proof: `native/test_pokemon.c#test_generated_attraction_family`.

## Differential proof

- `attract-direct-action`
- `attract-same-gender-immunity`
- `cute-charm-contact`

The observer exposes the two owned PRNG labels, handler ordering, condition
state, effect events, and source provenance. The complete deterministic corpus
matches at 1,672 boundaries. The observer patch checksum is
`11371f91b72c5a73b758c39ef619a848c245de565b11c901999f80a71c458152`.

The inherited condition `onEnd` callback is silent and is not claimed as
implemented. Removing Attract through the generic lifecycle is observable, but
that is not evidence that the callback itself executed.
