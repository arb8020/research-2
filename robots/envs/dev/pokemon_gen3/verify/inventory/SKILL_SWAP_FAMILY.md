# Skill Swap ability-replacement family

Pinned oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Semantic boundary

Showdown's inherited move descriptor (`data/moves.ts#skillswap`) delegates to
`Battle#skillSwap` in `sim/battle.ts`. That operation rejects fainted holders,
equal Gen 3 abilities, and abilities marked `failskillswap`; runs `SetAbility`
for both proposed destinations before mutation; dispatches both old abilities'
`End` callbacks; then exchanges the effective abilities. Gen 3 deliberately
does not dispatch the new abilities' `Start` callbacks. `Pokemon#setAbility`
in `sim/pokemon.ts` supplies the same `SetAbility -> End -> replace` lifecycle
for one-sided replacement and restores the base ability on switch.

The native representation keeps these responsibilities separate:

- generated move data owns the move flags and a move-owned Hit program;
- generated ability data owns the `failskillswap` admission flag;
- the generic kernel owns the two-gate transaction, ordered `End` dispatch,
  generation/effect-order renewal, switch restoration, and rollback behavior;
- the generation plugin owns whether a replaced ability receives `Start`
  (`false` for Gen 3).

No generic control-flow branch names Skill Swap or a Gen 3 ability ID.

## Proof basis

`native/test_pokemon.c#test_skill_swap_transaction` proves successful exchange,
both `SetAbility` rejection orientations without partial mutation, equal-ability
and Wonder Guard rejection, absence of Gen 3 `Start`, effect-generation/order
renewal, switch restoration, and invariant/PRNG preservation.

The exact differential cases are:

- `skill-swap-flash-fire-end`
- `skill-swap-intimidate-no-start`
- `skill-swap-protect-block`
- `skill-swap-same-ability-failure`
- `skill-swap-substitute-bypass`
- `skill-swap-switch-restores-base`
- `skill-swap-wonder-guard-failure`

Together they cover 17 stable boundaries. The upstream assertion at
`test/sim/moves/skillswap.js:13` is mapped to the Wonder Guard case plus the
focused transaction test; later-generation-only prohibited abilities in that
test are not treated as Gen 3 entities.

Only `move:skillswap` and `event_hook:move.skillswap.onHit` are reclassified by
this slice. Forecast and Truant remain unsupported.
