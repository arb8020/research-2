# Gate 3: event-interpreter verification plan

Oracle: Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, format `gen3ou`.
Frozen denominator: 514 callback-hook records, 70 hook-derived event IDs plus
the zero-handler runtime event `ChangeBoost`, and eight result algebras in
`event-vocabulary.json`.

This gate tests the event interpreter with synthetic descriptors. It must not
depend on Earthquake, Toxic, or any other named move. Real mechanic tests come
after this structural proof and reuse the same interpreter.

## Oracle semantics being copied

`runEvent` owns discovery, ordering, relay threading, cancellation and frame
restoration; `singleEvent` executes one explicit owner
(`sim/battle.ts:1166-1256,1260-1363`). The important pinned rules are:

- Target events discover `onX` on the target, `onAllyX`/`onAnyX` on active
  allies, `onFoeX`/`onAnyX` on active foes, `onSourceX` on the source, then
  side, field and battle/format handlers (`sim/battle.ts:1662-1721`). Pokémon
  holders contribute status, volatiles, ability, item, species and slot
  conditions (`sim/battle.ts:1724-1782`); side, field/weather and format
  holders have separate discovery functions (`sim/battle.ts:1785-1857`).
- Ordinary ordering is `order` ascending (unset last), `priority` descending,
  speed descending, `subOrder` ascending, then `effectOrder` ascending
  (`sim/battle.ts:967-984`). Exact ties are PRNG-shuffled by `speedSort`
  (`sim/battle.ts:1002-1033`). Default suborders encode condition/slot/side/
  field/ability/item holder classes (`sim/battle.ts:1577-1627`).
- `Invulnerability`, `TryHit`, `DamagingHit`, and `EntryHazard` use left-to-right
  order; `priorityEvent` uses redirect order and exits on the first defined
  result (`sim/battle.ts:1394-1401,1570-1575`).
- `undefined` preserves the relay. Any defined return replaces it. A falsy
  relay stops later handlers; `false` and `null` remain observably distinct
  failure channels (`sim/battle.ts:1309-1340,1534-1547`). Numeric nonnegative
  integer relays receive the accumulated Q12 modifier once, after all handlers
  (`sim/battle.ts:1550-1563,2984-3007`).
- Each nested event saves and restores parent `event`, `effect`, and
  `effectState`. Depth 8 is rejected (`sim/battle.ts:1172-1179,1223-1256,
  1371-1378,1413-1415,1507-1517,1550-1562`).
- Residual/SwitchIn discovery is a snapshot, but execution skips fainted
  holders and handlers whose Pokémon/side/field state object is no longer the
  canonical attached state (`sim/battle.ts:1059-1158`). Ordinary `runEvent`
  independently rechecks changed status, ignored item/ability, and suppressed
  weather before invoking a discovered callback (`sim/battle.ts:1436-1502`).

## Synthetic fixture vocabulary

One test-only generation plugin should define no Pokémon mechanics. It contains
small fixed tables of:

- holders: target, ally, foe, source, status, volatile, ability, item, species,
  slot condition, target/foe side condition, weather, field condition, and
  format;
- handler metadata: event ID, scope, owner/holder reference, `order`,
  `priority`, `subOrder`, `effectOrder`, speed, and one test opcode;
- opcodes: return-undefined, return-value, cancel-false, cancel-null,
  chain-Q12, mutate-counter, replace-selector, replace-structured-value,
  redirect-target, remove-holder, nest-event, and consume-labeled-draw.

These opcodes are test interpreter instructions, not production move names.
Each case starts from a byte-comparable state and explicit seed. Failure cases
must prove atomic rejection by comparing state, trace counts and seed before
and after.

## Compact required matrix

### A. Discovery and holder validity

| ID | Synthetic setup | Required proof |
|---|---|---|
| D1 | One handler for each scope: target, ally, foe, any, source | Discovery contains each exactly once with the correct effect holder and source/target topology. Swap source and target and prove the changed set. |
| D2 | One target Pokémon carrying status, volatile, ability, item, species and slot-condition handlers | All six holder classes are found; their state/holder identities are distinct. |
| D3 | Target-side condition, foe-side condition, weather, field condition and format handler | Side/field/battle bubbling finds each once and does not attribute it to an active Pokémon. |
| D4 | Direct `singleEvent` owner plus the same owner discoverable through `runEvent` | Direct execution invokes exactly one requested owner; discovery invokes only topology-applicable owners. |
| D5 | Array/two-target event with per-target relay values | Handlers carry target index; cancellation suppresses only that target until every target is falsy, matching `runEvent`'s indexed relay handling (`sim/battle.ts:1417-1435,1534-1543`). |
| D6 | First residual handler removes a later volatile/side/weather holder; separate case faints its holder | The snapshotted later handler is recorded as discovered but skipped at execution. Slot-condition exception on a fainted holder is covered separately. |
| D7 | Ability/item/weather suppression toggled after discovery | Execution-time validity check skips the now-ignored handler without deleting or executing an unrelated valid handler. |

### B. Eight result algebras

Every row uses three ordered handlers: `undefined`, an algebra-specific value,
then an observer. This proves both identity behavior and relay threading.

| Algebra | Frozen coverage | Synthetic assertion |
|---|---:|---|
| `numeric-or-cancel-relay` | 14 events / 76 hooks | Input 100; handlers accumulate Q12 3/2 then 11/10 and return an intermediate 80; the next handler sees 80, while final Q12 is applied exactly once with Showdown rounding. Separate `0`, `false`, and `null` cases stop before observer. |
| `void-notification` | 26 / 272 | No public relay argument; two `undefined` handlers both execute and mutate independent counters. A mistakenly returned `false` still cancels subsequent notification, matching Showdown's generic engine. |
| `boolean-or-null-gate` | 18 / 112 | `undefined` and `true` continue. `false` stops and preserves visible-failure result; `null` stops and preserves silent-failure result. Trace/result encoding must distinguish both. |
| `state-mutation-notification` | 3 / 13 | Handler mutates a legal-choice/trap/disable bit and returns `undefined`; later handler observes the new state. Result remains the identity while state mutation is retained. |
| `selector-or-replacement-relay` | 2 / 3 | First handler preserves the selector, second replaces it with another typed selector, third receives the replacement. Invalid selector tags are rejected before execution. |
| `mutable-value-relay` | 4 / 18 | First handler edits one field of a typed struct, second replaces it with another valid struct, third sees the replacement. Input storage is not aliased accidentally across a replay. |
| `mutable-boost-table-relay` | 2 / 5 | `ChangeBoost` with zero handlers preserves the complete sparse table. A `TryBoost` handler deletes one present stat while retaining another, proving per-field mutation rather than Boolean collapse. |
| `target-redirect-relay` | 1 / 4 | Three candidate targets ordered by redirect comparator. First `undefined` continues; first defined target returns immediately even though truthy; later candidates do not execute. A no-result chain preserves the original target. |

Counts are generated from `event-vocabulary.json`; tests select synthetic event
IDs with the same algebra declarations, rather than borrowing behavior from a
particular frozen owner.

### C. Ordering, ties and early exit

| ID | Synthetic setup | Required proof |
|---|---|---|
| O1 | Five handlers differing one axis at a time | Exact ordinary key order: order asc, priority desc, speed desc, suborder asc, effectOrder asc. Discovery order must not affect the result. |
| O2 | Condition, slot, side, field/weather, ability and item with no explicit suborder | Derived suborder is 2, 3, 4, 5, 7, 8 respectively, and execution follows it. |
| O3 | Three exact ordinary ties, explicit seed | One labeled `event.<id>.handler_order` shuffle; exact handler order and post-draw seed match the oracle. Repeat is byte-identical. |
| O4 | Same tie under `TryHit`/left-to-right path | Index order is stable and no handler-order PRNG is consumed. |
| O5 | Ability redirect candidates tied on priority/speed with distinct ability-state effectOrder | Redirect comparator selects effectOrder order, returns on first defined result, and consumes no ordinary tie shuffle. |
| O6 | Cancelling handler followed by draw/mutation handlers | Neither later handler executes; there is no later PRNG record or mutation. |

### D. Frames, lifecycle and bounds

| ID | Synthetic setup | Required proof |
|---|---|---|
| F1 | Outer handler invokes an inner event with different source, target, effect, state and relay | Inner trace has depth 1 and its own frame; after return, the next outer handler sees the exact outer frame and threaded outer relay. |
| F2 | Nest recursively to the supported maximum, then one deeper | Maximum succeeds; excess depth fails loudly and deterministically. No frame leaks into the caller. Native failure must use its explicit result channel rather than corrupt state. |
| F3 | Fill discovered-handler capacity exactly, then exceed it by one | Exact capacity executes; overflow rejects before any handler, mutation or PRNG draw. Input battle and seed remain byte-identical. |
| F4 | Fill trace/relay-result capacity exactly, then require one more record | Exact capacity succeeds; overflow is an atomic capacity error, not truncation. |
| F5 | Remove and replace a holder during an earlier handler | Old state identity is stale and skipped; the replacement is not retroactively inserted into the current snapshot, but is discovered on the next event. |

## Structural differential records

The existing observer's `handlers` record already captures event, ordered
effect/effectType/holder, order, priority, subOrder, effectOrder and speed
(`sim/battle.ts:583-607`). Its current `modifier` records are restricted to
`ModifyAtk` and `ModifyDamagePhase1` (`sim/battle.ts:609-632`). Gate 3 needs a
test-only generalization with the following canonical records:

1. `event-enter`: sequence, depth, event ID, algebra, source, target, source
   effect, typed input relay;
2. `handlers`: the existing ordered discovery record plus scope, target index,
   stable handler ID and holder-state generation/identity;
3. `handler`: sequence, depth, handler ID, frame effect/holder, typed relay
   before, result (`undefined` must be explicit), relay after, Q12 before/after,
   and disposition `executed | stale | suppressed`;
4. `event-exit`: typed relay before final modifier, Q12 modifier, typed final
   result, cancellation kind, and executed/skipped counts;
5. labeled `prng`: only tie-order draws, using the existing
   `event.<id>.handler_order` label.

Native records use dense IDs instead of strings but must project losslessly to
this verifier schema. Comparison stops at the first record/field divergence.
Nested records share one monotonically increasing semantic sequence so frame
restoration is observable rather than inferred from final state.

## Gate and anti-overfitting rule

Gate 3 passes only when D1-D7, all seven algebra rows, O1-O6 and F1-F5 pass as
native focused tests and as structural differentials against the pinned oracle,
with byte-identical deterministic repeats. The suite must instantiate handler
tables from test data in multiple permutations. No production descriptor or
test may branch on a move, ability or item name; frozen hook owners are used
only later to prove that generated bindings select the already-tested event ID,
scope, holder class and algebra.
