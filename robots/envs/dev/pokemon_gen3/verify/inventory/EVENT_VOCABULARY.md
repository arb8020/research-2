# Gen 3 OU event vocabulary

This is the gate-3 source audit for the 514 reachable callback-owner records
in the pinned Gen 3 OU inventory. Normalizing `onAnyX`, `onFoeX`, `onSourceX`,
`onSideX`, and `onFieldX` by their event `X` yields 70 events. The generated
[`event-vocabulary.json`](event-vocabulary.json) retains every raw hook path,
scope, owner kind, and count. It also appends runtime call-site events that
have no owned callback in this generation. The original 69 hook-derived IDs
are frozen; `ChangeBoost` remains ID 70 and the newly visible `CriticalHit`
event is appended as ID 71, so the literal-false hook correction does not
renumber existing trace records. Regenerate it with:

```sh
node verify/inventory/generate-event-vocabulary.js
```

The classification is the expected relay algebra at the dispatcher boundary,
not a claim that callbacks sharing a name have interchangeable behavior. Every
relay class also admits Showdown's cancellation values: `false` stops with the
ordinary failure message, `null` stops while suppressing that message, and
`undefined` preserves the incoming relay.

## Relay/result algebra

| Algebra | Events |
|---|---|
| Numeric modifier or cancellation | Accuracy, BasePower, Damage, DeductPP, ModifyAtk, ModifyCritRatio, ModifyDamage, ModifyDamagePhase1, ModifyDef, ModifySpA, ModifySpD, ModifySpe, TryHeal, WeatherModifyDamage |
| Mutable value relay | ModifyBoost, ModifyMove, ModifySecondaries, ModifyType |
| Mutable sparse boost-table relay | ChangeBoost, TryBoost |
| Boolean/null gate | BeforeMove, BeforeSwitchOut, DragOut, EntryHazard, Immunity, Invulnerability, NegateImmunity, PrepareHit, SetStatus, StallMove, TakeItem, Try, TryAddVolatile, TryEatItem, TryHit, TryImmunity, TryMove, TryPrimaryHit |
| Target redirect | RedirectTarget |
| Selector or replacement | LockMove, OverrideAction |
| State-mutation notification | DisableMove, MaybeTrapPokemon, TrapPokemon |
| Void notification | AfterHit, AfterMega, AfterMove, AfterMoveSecondary, AfterMoveSecondarySelf, AfterSetStatus, AfterSubDamage, DamagingHit, Eat, End, Faint, Hit, HitField, MoveAborted, MoveFail, Residual, Restart, Start, SwitchIn, SwitchOut, Update, Use, UseMoveMessage, Weather, WeatherChange |

“Void notification” means the caller does not use a domain value from the
handler. A callback can still mutate canonical state, enqueue work, consume
PRNG, invoke nested events, faint a Pokémon, or terminate the battle. It is
therefore not an inert callback class.

## Dispatch and discovery

`singleEvent` invokes one known effect/state/holder and maintains the ambient
event frame (`effect`, `effectState`, target, source, source effect). It rejects
stale status state and suppresses ignored item, ability, or weather handlers.
An absent callback or `undefined` return preserves the relay.

`runEvent` discovers a handler set from the target topology:

- target Pokémon: its status, volatiles, ability, item and species effects;
- active allies and foes: `onAllyX`, `onFoeX`, and `onAnyX`;
- source Pokémon: `onSourceX`;
- target side or all sides when the target is a side or battle;
- field weather, terrain and pseudo-weather;
- format/rule handlers attached at battle scope;
- optionally the source effect's own `onX` callback.

Array targets retain a separate relay per target. `BeforeTurn`, `Update`,
`Weather`, `WeatherChange`, and `TerrainChange` suppress prefixed discovery.
`fieldEvent` is a distinct scheduler used for Residual and SwitchIn: it gathers
field, side, active-Pokémon, and battle handlers, decrements duration before a
residual callback, drops stale holders, executes end callbacks at expiry, and
drains faint work after every handler.

The current Showdown revision names the relevant functions `runEvent`,
`singleEvent`, `fieldEvent`, `findEventHandlers`,
`findPokemonEventHandlers`, `findSideEventHandlers`,
`findFieldEventHandlers`, and `findBattleEventHandlers` in `sim/battle.ts`.
Older descriptions calling this boundary `getRelevantEffects` refer to the
same discovery responsibility; that symbol is not present in the pinned
revision.

## Ordering

Each discovered listener is resolved to `(order, priority, speed, subOrder,
effectOrder)`. Ordinary events use Showdown's speed sort. `Invulnerability`,
`TryHit`, `DamagingHit`, and `EntryHazard` use left-to-right order. Redirect
events and `priorityEvent` use redirect order and stop on the first defined
result. `SwitchIn` and `RedirectTarget` use creation `effectOrder` to break
otherwise exact ties. Default `subOrder` distinguishes condition, slot, side,
field/weather/rule, ability, and item handlers; Poison Touch and Stall have
special positions. Speed ties may consume PRNG, so handler ordering belongs to
the labeled deterministic transcript.

## Required kernel state

A general native dispatcher needs more than an event enum:

- typed relay values: unit, gate, integer/fixed-point, mutable move/boost
  record, target reference, and selector/replacement;
- effect identity, effect-local mutable state, holder identity and lifetime;
- target/source/source-effect event frames and bounded nested-event depth;
- discovery indexes for Pokémon, side, slot, field/weather, and format owners;
- suppression predicates for ability, item, and weather effects;
- ordering keys plus stable creation order and speed-tie PRNG;
- per-target relay arrays;
- duration/end metadata and stale-holder checks;
- queue, faint, request, and terminal work that notifications may schedule.

These should be explicit sum types. A single integer return or universal
boolean callback would erase real semantic distinctions.

## Current native coverage

The generic native handler table currently represents five dispatcher
events:

- `ChangeBoost`: zero-handler runtime pass-through over a typed boost table;
- `TryBoost`: typed boost-table dispatch with per-stat presence preserved;
- `TryHit`: Water Absorb cancellation/immunity;
- `ModifyAtk`: ordered Q12 Guts and Black Belt modifiers;
- `Damage`: Rock Head recoil prevention.

The engine separately implements specific condition/effect operations such as
status application, residual work, Protect, Reflect, and Sandstorm. Those are
evidence for those mechanics, not evidence that the corresponding general
Showdown event vocabulary is implemented incrementally. Of the 514 frozen
hook records, 377 currently have descriptor-level implementation evidence;
the remainder stay unsupported in the descriptor map.

## Dependency order

1. Define the relay sum type, event frame, owner reference, and fail-closed
   descriptor schema.
2. Generalize discovery across Pokémon ability/item/status/volatile owners,
   preserving current TryHit/ModifyAtk/Damage behavior.
3. Implement exact ordering and labeled tie PRNG before adding more callbacks.
4. Add boolean gates and numeric relays; these cover the hit and damage
   pipeline without mutable aliasing.
5. Add mutable move/boost relays, selector/replacement, and target redirect.
6. Add side, slot, field/weather, and format discovery.
7. Add lifecycle notifications, duration/end handling, stale-holder checks,
   nested dispatch, and faint/request draining.
8. Rotate every frozen hook owner through focused and differential cases, then
   add withheld cross-owner ordering and cancellation recombinations.

This order prevents a large callback switch from masquerading as a dispatcher:
each later family depends on state ownership and ordering established earlier.
