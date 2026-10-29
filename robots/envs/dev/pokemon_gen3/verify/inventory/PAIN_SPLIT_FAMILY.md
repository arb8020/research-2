# Pain Split atomic HP assignment

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Pain Split establishes one reusable native boundary: atomic bilateral direct-HP
assignment. It is not damage, healing, drain, or two sequential transactions.
The operation snapshots both current HP values, computes
`max(1, floor((source_hp + target_hp) / 2))`, and independently clamps that
result to each Pokémon's maximum HP before committing both writes.

## Source mapping

| Semantic fact | Pinned Showdown source | Native boundary |
| --- | --- | --- |
| floor average, minimum one, direct assignment | `data/moves.ts#painsplit` | `POKEMON_HANDLER_OP_SET_SOURCE_TARGET_HP_TO_FLOOR_AVERAGE` |
| per-Pokémon `1..maxhp` clamp | `sim/pokemon.ts#sethp` | handler-program validation and execution in `native/pokemon.c` |
| Protect, Substitute, callback staging | `sim/battle-actions.ts` | generic move-hit pipeline and `MOVE_HIT_CALLBACK` dispatch |
| immutable move and owner binding | resolved Gen 3 `ModdedDex` | generated descriptor, program, and binding in `native/gen3_slice_data.c` |

The operation consumes no PRNG and emits no damage, heal, attacked-by, faint,
berry, or condition side effect. Impossible direct invocations—aliased,
fainted, or out-of-range participants—fail validation before mutation.

## Evidence

Focused native test:

- `native/test_pokemon.c#test_pain_split_atomic_bilateral_hp_assignment`

Legal differential cases:

- `pain-split-odd-floor`
- `pain-split-source-max-clamp`
- `pain-split-shedinja-target-clamp`
- `pain-split-protect-block`
- `pain-split-substitute-block`
- `pain-split-equal-hp`

These cases exercise both clamp directions, odd rounding, Wonder Guard
non-interaction, generic hit prevention, and a successful zero-delta callback.
The pinned upstream assertion in `test/sim/moves/painsplit.js:13` maps to the
first three cases using legal Gen 3 entities; the upstream Shedinja/Pain Split
set itself is not legal in Gen 3.
