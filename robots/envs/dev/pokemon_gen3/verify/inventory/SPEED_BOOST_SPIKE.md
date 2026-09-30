# Speed Boost semantic spike

Oracle: Pokémon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Source boundary

- `data/abilities.ts:4413-4423` defines Speed Boost as an ability-owned
  `onResidual` callback. The resolved Gen 3 mod inherits
  `data/mods/gen4/abilities.ts`'s ordering override: order 10, suborder 3.
  The callback performs one `spe: +1` boost only when `pokemon.activeTurns`
  is nonzero.
- `sim/battle-actions.ts:137` resets `activeTurns` to zero when a Pokémon
  switches in.
- `sim/battle.ts:2540` increments `activeTurns` while producing the next
  request, after the completed turn's residual phase. An initial active has
  already crossed this boundary before its first submitted choice.
- `sim/battle.ts:1190-1280` discovers and orders residual handlers using the
  ordinary event machinery; Speed Boost is not a bespoke turn-phase branch.

The honest native denotation is therefore:

```text
ability-owned Residual(10, 3)
  -> require living holder
  -> require holder.active_turns > 0
  -> ChangeBoost/TryBoost(holder, {spe: +1}, source = ability)
```

There is no Speed Boost PRNG call and no reason for a Speed Boost ability-ID
check in generic control flow.

## Prototype API

The spike adds two general handler operations:

- `GUARD_HOLDER_ACTIVE_TURNS`
- `BOOST_HOLDER_STAT(stat, signed_delta)`

It also adds `PokemonMutable.active_turns`, initialized to one for initial
actives, reset to zero on switch-in, and incremented for each living active at
the next-turn request boundary. The boost operation reuses the existing
ChangeBoost/TryBoost transaction and generation stage caps.

The generated Gen 3 binding should be three instructions (alive guard,
active-turn guard, speed boost) plus one ability-owned Residual descriptor at
order 28/suborder 2. This spike deliberately does not modify the generator,
native IDs, generated data, observer, or classification.

## Focused proof

`test_residual_active_turn_boost_family` proves with a synthetic ability that:

1. an initial active gains one Speed stage at its first Residual;
2. a voluntary same-turn switch-in does not gain a stage;
3. that switch-in gains a stage on the following Residual;
4. malformed generated boost bytecode is rejected transactionally, preserving
   the complete battle and consuming no PRNG.

The full native focused suite, randomized legal-play suite, Ocean adapter suite,
and an ASan/UBSan focused run pass in the isolated spike.

## Legal differential fixtures to generate during integration

All teams below are Gen 3 legal and should use the pinned observer.

1. `speed-boost-initial-active`: Ninjask with Swords Dance versus Feebas with
   Splash; one ordinary turn, expecting Speed stage `0 -> 1`, a Residual
   handler at `(10, 3)`, and no ability-owned draw.
2. `speed-boost-switch-delay`: Magikarp switches to bench Ninjask while Feebas
   uses Splash; expect no boost that Residual. On the next turn Ninjask uses
   Swords Dance; expect Speed stage `0 -> 1`.
3. `speed-boost-residual-ko`: a poisoned 1-HP Ninjask with a living bench uses
   Swords Dance; poison resolves before order 28, so the fainted holder gains
   no Speed stage and forced replacement is requested.
4. `speed-boost-stage-cap`: Ninjask repeatedly uses Swords Dance against
   Splash through seven Residuals; Speed caps at `+6`, and the seventh callback
   still executes without changing canonical state or consuming PRNG.

Do not use Baton Pass as the first fixture: its boost-transfer semantics would
couple this family to another unsupported mechanic.

## Integration overlap and merge order

Potential overlap is confined to `PokemonMutable`, switch lifecycle,
`begin_next_turn`, handler validation/execution, and `native/test_pokemon.c`.
It does not overlap generated tables until the integration owner adds the real
descriptor/program.

Recommended order:

1. merge any concurrent lifecycle changes touching switch or next-turn state;
2. port `active_turns` and the two generic operations, resolving those small
   lifecycle overlaps explicitly;
3. run focused/random/Ocean/sanitizer gates;
4. update the serialized generator and regenerate once with the batch;
5. add the four legal fixtures, run exact differential/replay, then classify
   Speed Boost only if every boundary is exact.
