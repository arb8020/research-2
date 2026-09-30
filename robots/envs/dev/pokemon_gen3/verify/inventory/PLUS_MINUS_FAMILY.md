# Plus and Minus relational ability family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

## Semantic boundary

Effective Gen 3 `Plus` and `Minus` are symmetric `onModifySpA` handlers. Each
multiplies its holder's Special Attack by 1.5 when any living active Pokemon
has the complementary ability. The pinned implementation uses
`battle.getAllActive()`, so the complementary holder may be an opponent in an
OU singles battle. Matching abilities do not activate one another, fainted
holders do not count, and physical damage is unaffected.

Authoritative source:

- `data/mods/gen3/abilities.ts`, `minus.onModifySpA` and
  `plus.onModifySpA`
- `sim/battle.ts`, `getAllActive`
- `sim/battle.ts`, ordered `ModifySpA` event relay

## Native denotation

Generated ability descriptors bind `Plus` and `Minus` to two-instruction
programs:

1. `GUARD_ANY_LIVING_ACTIVE_ABILITY` checks for the complementary generated
   ability ID across active positions;
2. `CHAIN_Q12(6144)` applies the 1.5 modifier through the generic scalar relay.

The generic kernel knows neither ability name. Bundle validation rejects this
guard unless it is owned by an ability `ModifySpA` handler and references a
known ability in the same resolved generation plugin.

Native boundaries:

- `native/gen3_slice_data.c`: generated ability data, handlers, owner bindings,
  and programs
- `native/pokemon.c`: generic living-active relational guard and ordered scalar
  modifier execution
- `native/test_pokemon.c#test_relational_active_ability_modifier`: positive,
  symmetric, matching-ability, fainted-holder, and physical-control assertions

## Differential basis

- `plus-minus-opponent-boost`
- `plus-minus-reverse-opponent-boost`
- `plus-minus-same-no-boost`
- `plus-minus-physical-control`

These four cases agree with the pinned oracle at all eight stable boundaries.
They close exactly `ability:plus`, `ability:minus`,
`event_hook:ability.plus.onModifySpA`, and
`event_hook:ability.minus.onModifySpA`; they do not imply support for a broader
active-Pokemon query API or doubles targeting.
