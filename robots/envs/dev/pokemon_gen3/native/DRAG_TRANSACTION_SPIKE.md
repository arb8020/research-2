# Generic forced-drag transaction spike

Oracle: Pokémon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Source boundary

- `data/moves.ts` (`roar`, `whirlwind`) supplies only ordinary move data plus
  `forceSwitch: true`; resolved Gen 3 changes inherited always-hit accuracy to
  numeric 100.
- `sim/battle-actions.ts#runMoveEffects/#forceSwitch` first makes switchable-bench
  availability part of `runMoveEffects`, then runs source/move-aware `DragOut`
  after ordinary hit effects. No bench and a false/null status result are move
  failures.
- `sim/battle.ts#runAction` drains the accepted flag after the action.
- `sim/battle-actions.ts#dragIn` chooses uniformly from switchable inactive
  party members, dispatches a second `DragOut`, then reuses `switchIn`. Thus a
  second veto consumes the candidate-selection draw but cancels the switch;
  this second event has no source or source effect.
- `sim/battle.ts#possibleSwitches/#getRandomSwitchable` defines eligibility as living inactive party
  members. `PRNG#sample` consumes a draw even for a singleton list.

## Native boundary

Generated `POKEMON_EFFECT_FORCE_SWITCH` programs select the behavior without
move IDs and enter only after the ordinary hit pipeline has connected.
The generic kernel dispatches the ordered boolean/null `DragOut` event, labels
uniform selection `POKEMON_DRAW_FORCED_SWITCH_TARGET`, and performs a typed
`POKEMON_SWITCH_CAUSE_DRAG` transaction through the existing switch and
run-switch lifecycle. Because native queued moves are side-addressed rather
than retaining Showdown's Pokémon object, the transaction explicitly removes
the displaced Pokémon's stale action before inserting run-switch work.

The focused test covers acceptance with two eligible members, singleton/no-
bench staging, stale queue cancellation, observable switch cause, and ordered
handler cancellation with no selection draw. A second focused test and two
exact differential fixtures prove the generated blockers: Suction Cups owns a
priority-1 ability `DragOut` veto; Ingrain installs a generated volatile whose
`Start`, `Residual`, `TrapPokemon`, and `DragOut` handlers all execute through
the generic lifecycle. Its Gen 3 residual policy heals `baseMaxhp / 16` and its
trap handler removes voluntary switch choices. Neither blocker adds an ID or
move-name branch to generic control flow.

Seven legal differential fixtures cover successful Roar and Whirlwind,
uniform singleton/multi-bench selection, no eligible bench, cancellation of a
displaced member's queued move, recombination with entry lifecycle/Spikes,
and both blockers. The full corpus matches 2,207 stable boundaries and both
oracle and native traces replay byte-for-byte.

## Integration order and conflicts

1. Land `pokemon.h/c` API and kernel changes.
2. Land the generator and regenerate native IDs/data once with other batched
   families.
3. Port focused tests, then add legal Showdown differential fixtures.
4. Update observer serialization for `switch_cause` and the new PRNG label
   before asserting exact boundary parity.

Likely conflicts: central edits to `PokemonMoveData`, `PokemonAction`,
`PokemonEvent`, draw/event enums, `execute_move`, `execute_switch`, generated
native IDs/data, and the monolithic native test file.
