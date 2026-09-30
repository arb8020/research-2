# Gen 3 effect owners and handler discovery

Oracle: Pokemon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
Paths and line numbers refer to that revision. This inventory describes the
generic simulator shape as exercised by Gen 3 singles; it does not claim that
all listed owners or handlers are implemented natively.

## Two independent axes

A handler has both:

1. an immutable effect descriptor: which callbacks exist and their order,
   priority, and explicit sub-order; and
2. a mutable installation state: where this particular status, volatile,
   condition, weather, item, or ability lives now.

These must not be collapsed. A generated handler table can index immutable
descriptors, while battle state owns installation identity, duration, source,
and effect order.

## Owner and state inventory

`initEffectState` assigns `effectOrder` from one battle-global monotonic counter
only when the state has a nonempty id and a target that is either not a Pokemon
or is an active Pokemon. Otherwise it assigns zero
(`sim/battle.ts:3995-4004`). Thus effect order is installation metadata, not a
generated descriptor property.

| Owner | Canonical id/state location | Install, restart, remove | Default subOrder | Discovery in a Pokemon scan | `fieldEvent` stale identity |
|---|---|---|---:|---|---|
| Major status | `pokemon.status`, `pokemon.statusState` | `setStatus` replaces state, sets source/duration, runs `Start`; clear uses empty status/state | 0 (`Status` is not mapped) | First | Checks current `statusState` object |
| Volatile | `pokemon.volatiles[id]` | New state plus source/duration and `Start`; duplicate uses same state and `Restart`; removal runs `End` then deletes | 2 | After status, insertion order | Checks `volatiles[effect.id]` object |
| Ability | `pokemon.ability`, `pokemon.abilityState` | See `HOLDER_STATE.md` | 7 | After all volatiles | Checks current `abilityState` object |
| Item | `pokemon.item`, `pokemon.itemState` | See `HOLDER_STATE.md` | 8 | After ability | Checks current `itemState` object |
| Species | descriptor is `pokemon.baseSpecies`; state is `pokemon.speciesState` | Constructed once from initial species id; no generic restart/removal | 0 | After item | No canonical-location check because state has no target |
| Slot condition | `side.slotConditions[position][id]`; state target is the Side and `isSlotCondition=true` | New state plus source/duration and `Start`; duplicate uses same state and `Restart`; removal runs `End` then deletes | 3 | Last in Pokemon scan for that active slot | No identity check (explicitly excluded from Side check) |
| Side condition | `side.sideConditions[id]`; state target is Side | New state plus source/duration and `SideStart`; duplicate uses same state and `SideRestart`; removal runs `SideEnd` then deletes | 4 | Separate side scan, insertion order | Checks `sideConditions[effect.id]` object |
| Pseudo-weather / field condition | `field.pseudoWeather[id]` | New source/duration state and `FieldStart`; duplicate uses same state and `FieldRestart`; removal runs `FieldEnd` then deletes | 5 | Field scan first, insertion order | No check: pinned creation omits `state.target` |
| Weather | `field.weather`, `field.weatherState` | Replaces id/state with source/duration and `FieldStart`; clear runs `FieldEnd` then clears existing state | 5 (`Weather`) | After pseudo-weather | No check: pinned creation omits `state.target` |
| Format | `battle.format`, `battle.formatData` | Created once for battle; no ordinary remove/restart | 5 | Battle scan | No canonical-location check because state has no target |

Status creation and duration are in `sim/pokemon.ts:1700-1755`; volatile
restart/creation/removal are in `sim/pokemon.ts:1987-2071`. Species and its
state are initialized separately at `sim/pokemon.ts:322-332`; discovery uses
`baseSpecies`, not `pokemon.species`, at `sim/battle.ts:1758-1763`.

Side and slot condition lifecycle is in `sim/side.ts:396-449` and
`sim/side.ts:452-498`. Weather lifecycle is in `sim/field.ts:39-101`, and
pseudo-weather lifecycle in `sim/field.ts:189-232`. The format state is created
at `sim/battle.ts:422` and discovered at `sim/battle.ts:1785-1805`.

In the pinned code, active Pokemon status/volatile/ability/item states and
side/slot conditions receive nonzero installation order because their state has
a target. Weather and pseudo-weather construction omits `target`, so their
states receive order zero; species and format states also have no target and
order zero. This follows the actual `initEffectState` predicate, even though
`fieldEvent` contains a generic Field-target stale-check branch.

Terrain exists in the generic engine and shares field-state semantics, but it
is not a Gen 3 mechanic. It should remain a generation capability, not be
smuggled into the Gen 3 supported-feature claim.

## Priority metadata

For each callback, `resolvePriority` reads `<callback>Order`,
`<callback>Priority`, and `<callback>SubOrder`. Missing values become false, 0,
and 0. If sub-order is still zero, the owner effect type supplies the defaults
shown above; slot and side conditions refine generic Condition from 2 to 3 and
4, while field conditions become 5 (`sim/battle.ts:1577-1620`).

`effectOrder` participates only for callback names ending in `SwitchIn` or
`RedirectTarget` in this implementation (`sim/battle.ts:1621-1627`). It breaks
otherwise-perfect ties by installation order. It must therefore be captured
from state when a handler record is discovered, not generated into the handler
descriptor.

Duration is likewise state, not handler metadata. For `Residual`, discovery
includes owners with a duration even if no callback exists. Before execution,
`fieldEvent` decrements duration and invokes the owner's removal function when
it reaches zero (`sim/battle.ts:1061-1064`, `1101-1111`).

## Discovery scopes and order

### `runEvent`

For a Pokemon target, the scan begins with the target's own Pokemon owners in
the exact order status, volatiles, ability, item, species, slot conditions.
Then it adds `onAlly*`/`onAny*` handlers from allies and `onFoe*`/`onAny*` from
foes. A source Pokemon contributes `onSource*`. The event then bubbles to side
conditions, field owners, and format/battle handlers
(`sim/battle.ts:1662-1721`, `1724-1782`).

In Gen 3 singles, “allies” contains only the target itself and each side has
one active, but prefix semantics remain observable: target-local, source, foe,
any, side, field, and format scopes are not interchangeable. For events whose
target is a Side, discovery can bubble down to active Pokemon on both sides
before side/field/format scans. `BeforeTurn`, `Update`, `Weather`,
`WeatherChange`, and `TerrainChange` deliberately suppress prefixed discovery
(`sim/battle.ts:1676-1717`).

`findPokemonEventHandlers` performs no global descriptor scan. It resolves the
currently installed owners and asks each descriptor for precisely the named
callback (`sim/battle.ts:1724-1782`). Side, field, and format scans do the same
(`sim/battle.ts:1785-1857`).

### `fieldEvent`

`fieldEvent` is specialized for `Residual` and `SwitchIn`. It collects field
`onField*`, side `onSide*`, then for every active Pokemon its Pokemon, side,
field, and format handlers. `SwitchIn` additionally collects Pokemon
`onAnySwitchIn`. It sorts the complete snapshot before execution
(`sim/battle.ts:1053-1083`). In singles this is still a cross-field snapshot,
not two independent per-Pokemon calls.

### Stale handlers

After snapshot discovery, `fieldEvent` validates installation object identity
for Pokemon status/volatile/ability/item and side-condition states
(`sim/battle.ts:1115-1145`). Its code also supports weather/pseudo-weather state
whose target is a Field, but pinned `Field` lifecycle methods do not set that
target (`sim/field.ts:39-101`, `189-232`), so those installations do not enter
the check. Species, format, and slot conditions also receive no
canonical-location check. Slot conditions are notably excluded because their
state target is a Side with `isSlotCondition=true`; this is the pinned behavior,
whether intentional or not.

Ordinary `runEvent` does **not** perform general state-identity validation. It
only rejects a status descriptor whose id no longer equals the holder's status,
then applies ability/item/weather suppression rules
(`sim/battle.ts:1436-1502`). Therefore a generic “skip every stale token” rule
would diverge from Showdown. `singleEvent` similarly checks status identity and
suppression, not arbitrary installation identity (`sim/battle.ts:1194-1217`).

## Recommended C sum types

Keep descriptor identity and mutable ownership explicit:

```text
EffectDescriptorId = { kind: STATUS | ABILITY | ITEM | SPECIES |
                             CONDITION | WEATHER | FORMAT,
                       catalog_id }

EffectOwner =
  POKEMON_STATUS(pokemon)
| POKEMON_VOLATILE(pokemon, volatile_slot)
| POKEMON_ABILITY(pokemon)
| POKEMON_ITEM(pokemon)
| POKEMON_SPECIES(pokemon)
| SIDE_SLOT_CONDITION(side, active_slot, condition_slot)
| SIDE_CONDITION(side, condition_slot)
| FIELD_WEATHER
| FIELD_CONDITION(condition_slot)
| FORMAT

EffectState = {
  descriptor_id,
  installation_token,
  effect_order,
  duration,
  source_ref,
  payload_tag,
  payload
}
```

The owner variant determines the canonical state lookup and permitted
lifecycle. It also makes Showdown's stale policy representable as an explicit
event-class operation:

```text
is_live_for_field_event(owner, token) -> bool
```

That operation should return the pinned behavior, including unconditional true
for species, format, slot-condition, weather, and pseudo-weather snapshots as
currently constructed. Do not encode owner kind as nullable pointers or infer
it from effect type: all volatiles, slot conditions, side conditions, and
pseudo-weather are `Condition` descriptors, yet have different ownership,
sub-order, removal, and stale semantics.

For bounded static allocation, each variable-cardinality owner map can be a
small fixed array of `{descriptor_id, installation_token, state}` entries.
Iteration order must be stable insertion order because Showdown uses object-key
iteration before the final stable sort, and unresolved ties can expose it.

## Generated handler-span index

A shared generated index is faithful and desirable if its key includes both
descriptor kind/id and callback identity:

```text
handler_span[descriptor_kind][descriptor_id][callback_id]
    -> contiguous HandlerDescriptor[]
```

Each immutable handler descriptor should contain callback scope/prefix,
program/opcode id, explicit order/priority/sub-order metadata, and flags. The
runtime must still:

1. enumerate installed owners in Showdown's owner and scope order;
2. resolve the exact callback/prefix for each owner;
3. combine generated metadata with owner-derived default sub-order;
4. capture holder speed, installation `effect_order`, and installation token;
5. sort the collected snapshot using the event comparator;
6. apply the event-class-specific stale rule at execution.

An index keyed only by `{owner kind/id}` is insufficient if it requires a
linear scan of every callback belonging to that descriptor on each event. A
secondary per-callback span (or a sorted span plus offset table) avoids that
scan. Conversely, a global `event -> all handlers` list is also wrong as the
primary hot path: it would scan effects that are not installed and complicate
owner scope.

The expected hot-path cost is then:

```text
O(installed owners visited + matching handlers + H log H)
```

where `H` is the small collected handler count. Lookup is array arithmetic,
not hashing, and generated spans are read-only/shareable across vectorized
environments. Runtime storage remains only bounded installation state plus a
bounded event-handler scratch array. This mirrors Showdown's semantic boundary
while being cheaper than dynamic descriptor lookup and object allocation.

The index must not own duration, source, payload, installation order, current
holder identity, or stale validity. Putting any of those in generated data
would confuse effect meaning with one battle's mutable installation.
