# Gen 3 weather-family plan

Oracle: pinned Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, format `gen3ou`.

This is an inventory and implementation plan, not a support claim.  The
frozen legal/reachable inventory contains exactly four weather conditions:
Rain Dance, Sunny Day, Sandstorm, and Hail.  The native Sandstorm slice is a
useful storage/residual anchor, but it does not prove the general weather
lifecycle: all four of Sandstorm's event-hook records are still classified
unsupported.

## The generic boundary

Weather is one installed field effect, not four battle flags.  The generic
kernel should own a `WeatherState` product containing the generated condition
id, source reference, remaining duration (`0` means indefinite), installation
generation, and effect order.  A generation plugin supplies descriptors and
programs for duration, damage modifiers, residual effects, immunity, and
weather consumers.  Generic control flow should only:

1. request `SetWeather` handlers;
2. reject the Gen 3 same-weather restart when required by the generation
   rule;
3. atomically replace the installed id/state and run `FieldStart`, rolling
   back if it cancels;
4. announce `WeatherChange` to active holders;
5. discover weather `FieldResidual` work in the common residual queue;
6. decrement finite duration before the residual callback, clearing it at
   zero through `FieldEnd`;
7. dispatch `Weather` to active Pokémon in speed order; and
8. clear through the same `FieldEnd` transaction.

This follows `sim/field.ts:36-109`, `sim/battle.ts:1048-1133`, and
`sim/battle.ts:1824-1844`.  Replacement by a different weather does **not**
run the old weather's `FieldEnd`; Showdown replaces its state and runs the new
`FieldStart`.  A repeated move-set weather fails in Gen 3 rather than
refreshing.  Sand Stream may replace a finite Sandstorm with indefinite
Sandstorm, but a second ability application fails once duration is already
zero.

Move weather lasts five turns.  Because `fieldEvent('Residual')` decrements a
finite duration before calling its handler, weather set during a turn reaches
duration four at that turn's residual and expires before its fifth residual
callback.  Ability weather is indefinite.  Gen 3 has no legal weather rocks,
so modern `durationCallback` item extensions are outside this frozen
inventory, not hidden branches in the runtime.

## Exact core closure

The first tranche after the existing Sandstorm anchor has exactly **19
currently unsupported obligations**:

| Weather | Move | Condition | Frozen hook records |
|---|---|---|---|
| Hail | `hail` | `weather.hail` | `FieldStart`, `FieldResidual`, `FieldEnd`, `Weather` (4) |
| Rain | `raindance` | `weather.raindance` | `FieldStart`, `FieldResidual`, `FieldEnd`, `WeatherModifyDamage` (4) |
| Sun | `sunnyday` | `weather.sunnyday` | `FieldStart`, `FieldResidual`, `FieldEnd`, `Immunity`, `WeatherModifyDamage` (5) |

```text
3 move descriptors + 3 condition descriptors + 13 hook records = 19
```

The same reusable implementation must also close Sandstorm's four currently
unsupported hooks (`FieldStart`, `FieldResidual`, `FieldEnd`, `Weather`).
Thus the generic weather-core change has an exact ceiling of **23 current
unsupported entries**, while the already-implemented Sandstorm move and
condition remain regression anchors rather than newly claimed closure.

Generated policy, not named branches, distinguishes the four effects:

- rain multiplies Water damage by 1.5 and Fire by 0.5;
- sun multiplies Fire damage by 1.5 and Water by 0.5 and rejects freeze
  through its installed `Immunity` handler;
- hail applies `floor(baseMaxHP / 16)` through ordinary weather damage, with
  Ice's natural status immunity preventing it;
- sand applies the same fraction, with Rock, Ground, and Steel immunity; the
  Gen 3 override explicitly removes the modern Rock Special Defense boost.

All damage modifiers use the generation's fixed-point modifier path and
ordering.  Hail and Sandstorm damage must enter the normal weather-damage
transaction so type immunity, `Damage` handlers, faint work, and forced
replacement are shared rather than reimplemented.

## Ranked consumer tranches

These tranches are dependencies of full weather-family conformance, but they
must not be claimed merely because the field can store a weather id.

### 1. Weather core and suppression

Implement the 23-entry core above, then Cloud Nine.  `FieldStart`,
`FieldResidual`, and `FieldEnd` still execute while weather is suppressed, so
finite duration continues ticking.  Other weather handlers and each active
Pokémon's `Weather` event are skipped while an active, living, non-ignored
Cloud Nine holder suppresses weather.  Suppression never deletes weather.

Cloud Nine contributes **1 ability descriptor + 2 hook records** (`Start`,
`End`) = **3 obligations**.  Its start/end transitions invoke
`WeatherChange`; its suppression predicate is descriptor data.  Air Lock is
not in the frozen legal/reachable ability inventory.  Drizzle and Drought are
also absent; Sand Stream is the only legal ability weather setter.  Sand Veil
is explicitly format-banned and absent from the legal ability inventory.

### 2. Speed, residual healing, and weather setting

Four abilities contribute **4 descriptors + 4 hooks = 8 obligations**:

- Chlorophyll `ModifySpe`: double Speed in effective sun;
- Swift Swim `ModifySpe`: double Speed in effective rain;
- Rain Dish `Residual`: heal `floor(baseMaxHP / 16)` at residual order 10,
  suborder 3, only in effective rain;
- Sand Stream `Start`: install indefinite Sandstorm through the generic
  weather transaction.

The modifier abilities must affect both action ordering and every other
Speed consumer through the common stat relay.  Rain Dish is deliberately a
Gen 3 `Residual` callback, not the modern `Weather` callback.  Its healing is
the generic heal primitive, including full-HP failure/clamping.

### 3. Weather-sensitive ordinary moves

Six moves contribute **6 descriptors + 8 hook records = 14 obligations**:

- Weather Ball: `ModifyType` plus the Gen 3 `ModifyMove`; effective weather
  doubles base power, chooses Fire/Water/Rock/Ice, and Gen 3's type-based
  category rules make Fire, Water, and Ice Special while Rock stays Physical;
- Thunder: `ModifyMove`; effective rain makes accuracy unconditional and sun
  makes it 50, before the ordinary accuracy draw;
- Solar Beam: `TryMove` and `BasePower`; sun removes the charge turn, while
  rain, sand, and hail halve base power;
- Moonlight, Morning Sun, and Synthesis: one shared generated
  weather-recovery operation (`onHit` each), healing half base max HP in
  clear weather, two thirds max HP in sun, and one quarter base max HP in
  rain/sand/hail.

These are move programs attached by generated data, not `resolve_thunder`,
`resolve_solarbeam`, or three recovery handlers.  Solar Beam additionally
depends on the generic two-turn move family; Thunder depends on ordinary
status-secondary support; the descriptors cannot be reclassified until
those independent obligations are closed.

### 4. Forecast form projection

Forecast contributes **1 ability descriptor + 2 hooks = 3 obligations**.
`Start` immediately invokes its `WeatherChange` handler.  A live,
untransformed Castform projects to its normal, sunny, rainy, or snowy form
from effective weather and returns to normal under Cloud Nine.  This tranche
requires the generic species/forme-change transaction and generated Castform
form descriptors; it should follow suppression rather than being encoded in
the weather kernel.

Across the ranked plan, excluding the already implemented Sandstorm move and
condition, there are exactly **51 current unsupported inventory entries**:

```text
weather core 23
+ six abilities and eight ability hooks 14
+ six moves and eight move hooks 14
= 51
```

The ability subtotal includes Cloud Nine and Forecast.  This count is an
upper bound on entries this family can honestly reclassify, not a proxy for
passing tests; independent Solar Beam and Thunder dependencies still gate
their descriptors.

## Proof matrix

Focused native and differential tests should cover:

1. each move-started weather from empty state, same-weather failure, all 12
   directed replacements, five-turn duration, switch persistence, expiry,
   and deterministic replay;
2. replacement observation order, including the absence of old `FieldEnd`,
   installation identity change, and rollback if new `FieldStart` cancels;
3. Sand Stream from clear, finite Sandstorm, and indefinite Sandstorm;
4. rain/sun Fire and Water modifiers at every rounding boundary used by the
   Gen 3 damage formula, including Cloud Nine suppression;
5. Hail/Sandstorm residual at small and non-divisible HP, every natural type
   immunity, `Damage` cancellation/modification, residual KO, forced
   replacement, and terminal resolution;
6. weather plus poison/burn/toxic/Rain Dish residual ordering, with handler
   discovery and execution traces and no unlabeled PRNG;
7. Cloud Nine entering, leaving, fainting, and being ignored: stored weather
   and duration persist while effects disappear/reappear and `WeatherChange`
   reaches Forecast;
8. Chlorophyll/Swift Swim action-order reversal, ties with exact labeled
   queue-order draws, and recomputation after weather replacement;
9. Weather Ball's four type/category projections and clear-weather baseline;
10. Thunder's clear/rain/sun accuracy staging, including proof that rain
    consumes no accuracy draw and sun consumes exactly one;
11. Solar Beam charge/install/release in clear/rain/sand/hail and immediate
    execution in sun, including switches and failed targets;
12. all three recovery moves under clear/rain/sun/sand/hail at odd HP,
    near-full clamp, full-HP failure, expiry, and suppression; and
13. Forecast start and every weather transition, suppression/un-suppression,
    transformed/non-Castform guards, switching, and stable form state.

Each differential artifact must compare normalized choices, action queue,
field/event handler discovery and ordering, phase/request transitions,
canonical field and Pokémon state, residual/faint work, terminal result, and
labeled draws.  Rotate weather producers against every consumer rather than
testing only named pairs.

The current generic owner-residual queue deliberately fails closed if one
owner exposes more than one applicable callback for the same residual event.
Rain Dish has exactly one reachable `onResidual` callback, so that generic
capacity gap does not limit its supported descriptor or hook. A later core
tranche must enqueue one independently ordered work item per applicable
handler before descriptors with multiple same-event callbacks can be claimed.

## Authoritative sources

- `sim/field.ts:14-130`: weather storage, set/replace/clear, effective weather,
  and suppression;
- `sim/battle.ts:1048-1165`: field-event discovery, duration decrement,
  stale-state checks, residual execution, and faint draining;
- `sim/battle.ts:1208-1232` and `sim/battle.ts:1490-1517`: weather suppression
  at single-event and ordinary-event execution;
- `sim/battle-actions.ts:1275-1277` and `sim/battle-actions.ts:1758-1761`:
  move weather installation and damage-modifier boundary;
- `data/conditions.ts` records `raindance`, `sunnyday`, `sandstorm`, `hail`;
- `data/mods/gen3/conditions.ts` Sandstorm override removing modern SpD;
- `data/moves.ts` plus `data/mods/gen4/moves.ts` and
  `data/mods/gen3/moves.ts`: effective weather setters and consumers;
- `data/abilities.ts` and `data/mods/gen3/abilities.ts`: effective Cloud Nine,
  Forecast, Rain Dish, Sand Stream, Chlorophyll, and Swift Swim behavior;
- `data/typechart.ts`: natural Hail and Sandstorm immunity; and
- `verify/inventory/gen3ou-inventory.json`: frozen legal/reachable membership
  and callback-hook records.
