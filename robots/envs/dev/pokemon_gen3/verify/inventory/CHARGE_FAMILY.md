# Charge family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

Charge is implemented as one ordinary self-targeting move, one persistent
volatile, and six generated handlers. The generic kernel contains no Charge
move-ID branch.

## Effective Gen 3 semantics

The authoritative behavior is the resolved Gen 3 `ModdedDex`, not
`data/mods/gen3/moves.ts` in isolation. The resolution chain is:

`gen3 -> gen4 -> gen5 -> gen6 -> gen7 -> gen8 -> gen9/base`

The Gen 3 move override removes the modern Special Defense boost. It retains
the base move's Electric-only, priority-9 BasePower callback, while the
recursive chain supplies Gen 8's cleanup callbacks: every non-Charge move
removes the volatile after completion or through `MoveAborted` when
`BeforeMove` cancels the action. Reusing Charge dispatches `Restart` and keeps
the condition. Explicit removal runs `End`; switch/faint bulk cleanup is
silent. `Pokemon.removeVolatile` is a no-op at zero HP.

Authoritative sources:

- `data/moves.ts#charge`
- `data/mods/gen8/moves.ts#charge`
- `data/mods/gen3/moves.ts#charge`
- `data/mods/gen3/scripts.ts#Scripts.inherit`
- `sim/battle-actions.ts#runMove`
- `sim/pokemon.ts#addVolatile`, `removeVolatile`, and `clearVolatile`

## Native boundary

- `tools/generate_slice_data.js` flattens the resolved move and emits the move
  effect, condition identity, six owner bindings, and compact handler programs.
- `native/pokemon.c` supplies generic condition installation/restart/removal,
  scalar BasePower relay, `MoveAborted` and `AfterMove` dispatch, End dispatch,
  and silent switch/faint clearing.
- `native/gen3_rules.c` binds the generated descriptor to the persistent,
  duration-free condition policy.

`native/test_pokemon.c#test_generic_charge_lifecycle` covers Start, Restart,
Electric power modification, ordinary-move cleanup, Electric status cleanup,
BeforeMove cancellation, End, and silent switching. The differential basis
adds a zero-HP recoil/faint case and proves all six scenarios boundary by
boundary against the pinned oracle. No Charge-specific PRNG draw exists.
