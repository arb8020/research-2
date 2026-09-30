# D1-D3 discovery and ordering audit

Oracle: pinned Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, Gen 3 singles. This is a
read-only verification proposal; it does not classify any frozen hook as
supported.

## Exact discovery topology

For a Pokémon target, `findEventHandlers` appends candidates in this order
before sorting:

1. target `onX` Pokémon owners;
2. each active ally including the target itself: `onAllyX`, then `onAnyX`;
3. each active foe: `onFoeX`, then `onAnyX`;
4. source Pokémon `onSourceX` when a source exists;
5. target-side `onX` and `onAnyX` side conditions;
6. foe-side `onFoeX` and `onAnyX` side conditions;
7. field `onX` owners;
8. battle/format `onX` owners.

In singles, `alliesAndSelf()` contains the target and `foes()` contains the
single opposing active. If the source is that foe, one installed owner may
legitimately contribute distinct `onFoeX`, `onAnyX`, and `onSourceX`
callbacks. There is no owner-level deduplication. Deduplication would be wrong:
the callback path/scope is part of binding identity.

A target Pokémon scan is status, every volatile in insertion order, ability,
item, base species, then slot conditions in insertion order. Side discovery
scans side conditions; field discovery scans pseudo-weather, weather, then
terrain; battle discovery scans the format and dynamically registered format
events. The Gen 3 inventory has no terrain mechanic, but the generic source
path exists.

`BeforeTurn`, `Update`, `Weather`, `WeatherChange`, and `TerrainChange` disable
ally/foe/any/source-prefix expansion. D1 must use a normal prefixed event, not
one of these exceptions.

## Ordering facts

Ordinary `runEvent` sorts by:

1. explicit `order`, ascending, unset last;
2. `priority`, descending;
3. holder Speed, descending;
4. `subOrder`, ascending;
5. listener `effectOrder`, ascending;
6. labeled PRNG shuffle for exact ties.

Default suborders are: status 0, volatile condition 2, slot condition 3, side
condition 4, field/pseudo-weather/weather/format 5, ability 7, and item 8.
Species is also 0.

Crucially, `resolvePriority` copies installation `effectOrder` onto the
listener only for callback names ending in `SwitchIn` or `RedirectTarget`.
For an ordinary synthetic event it must be zero even though the holder state
has a nonzero installation order. A native comparator that always copies
ability/item installation order adds a non-Showdown tie-breaker.

`TryHit`, `Invulnerability`, `DamagingHit`, and `EntryHazard` instead use
left-to-right sorting: order, priority, target-array index. They ignore Speed,
suborder, and effect order and consume no ordinary handler-order draw.

## Compact focused matrix

| Test | Fixture | Exact expected result |
|---|---|---|
| D1a scope topology | Distinct synthetic ability bindings on target `onX`, target `onAllyX`, target `onAnyX`, foe `onFoeX`, foe `onAnyX`, and foe/source `onSourceX`; explicit priorities 60..10 | Six records, once each, in priority order: target, ally, target-any, foe, foe-any, source. Holder is target for first three and foe/source for last three. All suborders 7; ordinary listener effect orders 0. |
| D1b topology swap | Same installations, reverse source and target | Scope-applicable set changes rather than merely reversing output. No duplicate suppression by owner. Explicit priorities retain deterministic order; no PRNG draw. |
| D1c prefix exception | Repeat with synthetic `Update` | Only direct `onUpdate`, side, field, and format callbacks; no ally/foe/any/source records. |
| D2a holder classes | Target owns status, volatile, ability, item, species, slot-condition handlers; give explicit orders 1..6 | Six distinct owner/state tokens, ordered by explicit order. Expected default suborders remain status0, volatile2, ability7, item8, species0, slot3. Effect order is 0 for the ordinary event. |
| D2b default ordering | Same six handlers, no order/priority, unequal target Speed is irrelevant because all share one holder | Volatile2, slot3, ability7, item8 are ordered. Status and species are an exact suborder-0 tie and require one labeled handler-order shuffle; assert seed, ordered identities, and post-seed against Showdown. |
| D2c left-to-right | Bind the same owner table to `TryHit` with unique binding ordinals | Discovery order is preserved by order/priority/index only; no ordinary tie PRNG and no default-suborder reordering. |
| D3a outer owners | Target-side `onX`, foe-side `onFoeX`, pseudo-weather `onX`, weather `onX`, and format `onX`; explicit priorities 50..10 | Five records once each with Side/Side/Field/Field/Battle holders. Expected default suborders 4,4,5,5,5 and ordinary effect orders 0. |
| D3b default ties | Same handlers without explicit priority; install side and field effects in known order | Side handlers precede field/format by suborder. All suborder-5 handlers are exact ordinary ties because listener effectOrder is absent; assert labeled shuffle rather than creation order. |
| D3c side target | Invoke with a Side target | `shouldBubbleDown` adds active Pokémon `onX` on the target side, active foe `onFoeX`, and both sides' `onAnyX`, then side/field/format owners exactly once. |

Every test should permute generated binding-table storage while preserving
metadata. Results must remain unchanged except in the explicitly seeded exact
tie cases. Also assert the frozen input battle, seed, and trace counts are
unchanged on capacity failure.

## Existing coverage and one safe differential

Current focused tests already cover:

- ordinary comparator axes and atomic capacity failure;
- seeded ordinary ties versus left-to-right `TryHit` behavior;
- ability/item installation generations and effect orders;
- nested frame restoration;
- target ability discovery through Water Absorb; and
- target ability + item ordering through Guts and Black Belt.

The existing `burned-guts-black-belt` differential is the compact
oracle-observable D2 subset that uses no unsupported mechanic: one target
Pokémon contributes Guts ability and Black Belt item `ModifyAtk` handlers.
Showdown order is Guts first (priority 5, suborder 7), then Black Belt
(priority 1, suborder 8); both have ordinary listener effectOrder 0. The final
modifier is chained and rounded once. Its handler projection should be
strengthened to assert owner kind and zero listener effectOrder if those fields
are not already compared.

Water Absorb's damaged- and full-HP cases are safe target-scope/cancellation
checks but contain only one discovered handler. No honest current mechanic
exercises ally, foe, source, side, field, or format handler discovery without
also depending on a descriptor still classified unsupported. Those scopes
should remain synthetic focused tests until their first supported mechanic,
not be smuggled into a differential via a routing-only fixture.
