# Present family

Pinned oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Semantic boundary

Present selects one invocation-local outcome in its move-owned `ModifyMove`
callback: heal one quarter of the target's base maximum HP with weight 2, or
deal damage at power 40, 80, or 120 with weights 4, 3, and 1. The selection is
labeled `move.resolution_variant` and precedes hit admission.

The kernel represents this as a generated sum type:

- `DAMAGE { power, message_value }`
- `TARGET_MAX_HP_HEAL { numerator, denominator }`

The selected variant is stored in `PokemonActiveMoveFrame`, so called and
nested moves cannot mutate immutable move data or leak state between
invocations. Both variants retain Present's Normal type, Physical category,
90% accuracy, immunity, and Protect staging. Healing reaches the shared
`TryHeal` transaction only for an injured active target and consumes neither a
critical nor damage-roll draw.

Pinned Gen 3 inherits the Gen 4 Substitute callback, which checks `bypasssub`
but not the later `infiltrates` property. Therefore Substitute blocks the heal
variant and absorbs damage variants normally. The generated-data assertion
retains Present's `infiltrates` mutation as source provenance, but the Gen 3
resolved condition semantics deliberately do not interpret it.

## Evidence

- `data/moves.ts:present`: weighted callback and descriptor.
- `data/mods/gen3/scripts.ts`: Gen 3 move-hit staging.
- `data/mods/gen4/moves.ts:substitute`: inherited Gen 3 interception rule.
- `native/test_pokemon.c#test_weighted_move_resolution_outcomes`: generated
  distribution, all four buckets, heal amount, and PRNG absence/presence.
- `generate-present-cases.js`: ten legal differential cases and 20 exact
  boundaries covering each outcome, miss, Ghost immunity, Protect, full HP,
  healing blocked by Substitute, and damaging Substitute interception.

The move and its `onModifyMove` hook are classified `implemented` only after
all of the above evidence agrees with the pinned oracle.
