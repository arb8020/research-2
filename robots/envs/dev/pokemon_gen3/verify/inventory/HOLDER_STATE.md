# Gen 3 ability and item holder state

Oracle: Pokemon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
Paths and line numbers below refer to that revision. This is a source audit, not
an assertion that the corresponding mechanics are executable natively.

## Canonical identities

Showdown deliberately stores three different facts:

| Fact | Showdown field | Lifetime |
|---|---|---|
| Ability selected by the set | `baseAbility` | Battle-long, except a permanent species/forme change |
| Ability currently installed | `ability` | May change while active; reset to `baseAbility` on leaving the field |
| Current ability installation | `abilityState` | Replaced whenever an ability is installed and again on switch-in |
| Item selected by the set | `set.item` | Immutable input/provenance |
| Item currently held | `item` | Battle-long mutable inventory; removal survives switching |
| Current item installation | `itemState` | Replaced when an item is installed and again on switch-in |
| Most recently consumed/used item | `lastItem` | In Gen 3, transferred by active slot on switching; used by effects such as Recycle |
| Gen 3/4 Knock Off lockout | `itemKnockedOff` | Battle-long per-Pokemon flag; prevents either participant in `takeItem` from yielding an item |

Construction copies the set ability into both `baseAbility` and `ability`, and
the set item into `item`, then creates the two states
(`sim/pokemon.ts:422-431`). Thus an empty current item is not evidence that the
set had no item.

An `EffectState` is the mutable state of one installation, not data belonging
to an ability or item species. `initEffectState` gives an installed effect a
monotonic `effectOrder` when its holder is active, otherwise zero
(`sim/battle.ts:3995-4004`). A switch-in replaces both state objects, assigning
fresh order (`sim/battle-actions.ts:135-144`). Payload such as `started` belongs
to the installation. `clearEffectState` preserves only `id`/`target`, empties
the id, resets order, and deletes other payload (`sim/battle.ts:4007-4017`).

## Lifecycle

| Transition | Current ability | Ability state | Current item | Item state / related state |
|---|---|---|---|---|
| Team creation | `baseAbility` | New, normally order 0 because benched | Set item | New, normally order 0 |
| Switch in | Unchanged current value (normally reset before the prior switch-out) | Replaced; fresh active `effectOrder` | Unchanged | Replaced; fresh active `effectOrder` |
| Ordinary switch out | Reset to `baseAbility` | Object retained but `started` removed; next switch-in replaces it | Unchanged, including empty after consumption/removal | Object retained but `started` removed; next switch-in replaces it |
| `setAbility` / Role Play / Trace | Replaced only in `ability`; `baseAbility` is unchanged | Old `End`, new state, and in Gen 3 **no** generic new `Start` call | Unchanged | Unchanged |
| Skill Swap | The two current ids are exchanged; base ids unchanged | Both old `End`; both states replaced; in Gen 3 no generic new `Start` | Unchanged | Unchanged |
| Eat/use item | Unchanged | Unchanged | Cleared after item callback(s) | Existing state is used for `Eat`/`Use`, then cleared; `lastItem` set and `usedItemThisTurn` set |
| Take item | Unchanged | Unchanged | Cleared | Old state cleared, then old installation receives `End`; `lastItem` is not set |
| Gen 3/4 Knock Off | Unchanged | Unchanged | Cleared | Direct override leaves old installation state intact, sets `itemKnockedOff`, and does not run `End`/`AfterTakeItem` |
| Set/transfer item | Unchanged | Unchanged | Replaced | New state; old `End`, then new `Start` |
| Switch after item loss | Reset as above | Replaced | Remains empty | Replaced empty state; item is not restored from `set.item` |
| Faint | Reset during volatile cleanup after ability/item `End` | No live handler installation | Item id remains canonical unless another effect removed it | No live handler installation |
| Start of later turn | Unchanged | Unchanged | Unchanged | `usedItemThisTurn` becomes false |

`clearVolatile` is the switch-out reset: it assigns `ability = baseAbility`,
clears volatiles and the two `started` flags, but does not restore `item`
(`sim/pokemon.ts:1510-1567`). The actual switch then replaces ability/item
states; Gen 3 also transfers `lastItem` from the outgoing active to the incoming
Pokemon and clears it on the outgoing one (`sim/battle-actions.ts:117-143`).
That slot-scoped `lastItem` behavior must not be simplified into ordinary
per-Pokemon inventory.

Trace copies the foe's current ability through `setAbility`
(`data/mods/gen3/abilities.ts:186-194`). Role Play does the same to its user
(`data/moves.ts:15327-15347`). Skill Swap exchanges the current ids and replaces
both states (`sim/battle.ts:1938-1968`). All three therefore disappear when the
affected Pokemon switches; none changes `baseAbility`.

Gen 3 inherits the Gen 4 Knock Off override: a successful `TakeItem` event gate
is followed by direct current-item removal and `itemKnockedOff = true`,
preventing later acquisition through `takeItem`. This move override does not
call the generic `takeItem` method and therefore preserves the old installation
state until another lifecycle transition replaces it
(`data/mods/gen4/moves.ts:694-704`, `sim/pokemon.ts:1869-1883`).

## Handler validity

Discovery binds the resolved effect descriptor to the holder's current
`abilityState` or `itemState` (`sim/battle.ts:1724-1756`). The state object is
therefore the installation identity.

`fieldEvent` explicitly rejects a discovered Pokemon ability/item handler if
its saved state object is no longer exactly the holder's canonical state object
(`sim/battle.ts:1115-1129`). This handles removal or replacement by an earlier
handler in the same collected list. Side and field effects have equivalent
identity checks (`sim/battle.ts:1130-1145`).

Ordinary `runEvent` is less strict: its execution loop rechecks changed status
ids and suppression/ignoring rules, but does not compare an ability/item
handler's saved state object or effect id to the holder's current installation
(`sim/battle.ts:1436-1495`). `singleEvent` likewise checks suppression, not
installation identity (`sim/battle.ts:1194-1210`). A native engine claiming
Showdown equivalence must preserve this distinction rather than applying the
`fieldEvent` stale-state rule globally.

## Required mutation operations

### `EatItem`

The operation requires, in order:

1. held-item, living/active, and invoking-item identity guards;
2. `runEvent(UseItem)` and, unless forced, `runEvent(TryEatItem)` gates;
3. the held installation's `singleEvent(Eat)`;
4. `runEvent(EatItem)`;
5. copy current id to `lastItem`, clear current id and state, set
   `usedItemThisTurn` and `ateBerry`;
6. `runEvent(AfterUseItem)`.

This ordering is canonical (`sim/pokemon.ts:1786-1826`): the item remains
installed while its `Eat` callback and the global `EatItem` event run, but is
already absent for `AfterUseItem`.

### `TakeItem`

The operation requires the Gen 3/4 Knock Off guards, a held item, and
`runEvent(TakeItem)` as a cancellable gate. Success clears the current id and
state, runs the removed installation's `singleEvent(End)`, then
`runEvent(AfterTakeItem)`, returning the removed immutable item descriptor
(`sim/pokemon.ts:1869-1883`). Setting a received item is a separate operation:
replace id/state, old `End`, new `Start` (`sim/pokemon.ts:1886-1906`).

### `SetAbility`

The operation requires living-target and unsuppressible-ability guards, then a
cancellable `runEvent(SetAbility)` gate. Success calls old `End`, replaces the
current id and state, and returns the old id. The generic new-ability `Start`
call is deliberately restricted to generations after Gen 3
(`sim/pokemon.ts:1926-1963`). Skill Swap performs both `SetAbility` gates before
mutating either holder, then swaps atomically (`sim/battle.ts:1938-1968`).

## Recommended native state and invariants

Use numeric catalog ids; zero can denote no current installation.

```text
PokemonSetData (immutable): species_id, ability_id, item_id, ...
PokemonState:
  base_ability_id
  ability_id
  ability_installation { id, instance, effect_order, payload }
  item_id
  item_installation { id, instance, effect_order, payload }
  last_item_id
  used_item_this_turn, ate_berry, item_knocked_off
```

`instance` should be a monotonic token or pool handle. It is the static-C
equivalent of Showdown object identity and must change on every replacement,
including switch-in with the same id. Do not use only `(holder, effect_id)`:
remove-and-reinstall of the same effect would make a stale handler appear live.

Required invariants:

- `ability_installation.id == ability_id` and
  `item_installation.id == item_id` at every stable boundary.
- An empty current id has no discoverable handlers and a cleared payload/order.
- Handler records capture both immutable descriptor id and installation token.
- Only `fieldEvent`-class execution performs Showdown's canonical stale-token
  rejection; other event classes follow their own execution-time checks.
- Switching resets current ability to base ability, but never restores an item.
- Gen 3 `last_item_id` follows the active slot on a switch; `item_knocked_off`
  follows the Pokemon.
- `effect_order` is battle-global and monotonic for active installations; it is
  not regenerated during handler discovery.

## Admission boundary

The state shape, installation identity, switch reset, and stale-handler rules
belong in the generic runtime before mutable-holder mechanics are admitted.
The full operations can remain non-executable until their first owning feature:

- defer `EatItem`/`UseItem` until consumable berries or held-item activation is
  admitted;
- defer `TakeItem`, item transfer, `lastItem`, and Knock Off lockout behavior
  until Knock Off/Thief/Covet/Trick/Recycle-class mechanics are admitted;
- defer `SetAbility` mutation until Trace, Role Play, Skill Swap, or another
  ability-changing feature is admitted.

Passive effects such as Black Belt do not justify pretending these operations
exist. Conversely, admitting one of the features above requires its complete
operation ordering and lifecycle, not a move-specific shortcut.
