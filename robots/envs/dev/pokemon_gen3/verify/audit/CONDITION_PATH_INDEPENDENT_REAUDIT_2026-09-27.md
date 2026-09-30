# Independent Gen 3 OU condition-path re-audit

Pinned Pokemon Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

This is an independent, read-only audit of condition identity creation and
removal. It changes neither the native support classification nor the frozen
inventory.

## Result

No concrete Gen 3 OU condition identity is currently missing from the frozen
inventory. A fresh run of `gen3-condition-completeness-audit.js` against the
clean pinned checkout was byte-identical to the checked artifact:

```text
0912a9415aeb2bfecc5083ef751dec9d82168b59afa43d078d6535980291f598
```

The effective-descriptor fixed point reaches 354 moves, 70 abilities, 104
items, and 23 global Condition objects. It contains 131 lifecycle API calls,
seven direct condition deletes, and zero unresolved dynamic identities. Its
condition domains exactly equal the frozen inventory:

| Kind | Identities |
| --- | ---: |
| status | 6 |
| volatile | 62 |
| side condition | 5 |
| slot condition | 3 |
| weather | 4 |
| pseudo-weather | 2 |

The separate AST census of generic `sim/**/*.ts` code currently contains 97
source rows: 33 API calls, 41 assignments, 15 deletes, and eight stored method
references. Review classifies 71 as lifecycle-owning, 21 as payload-only, and
five as BattleStream debug/test-only. These rows are summarized by 28 semantic
paths.

## Corrected omissions now represented

- `futuremove`: effective Gen 3 Future Sight and inherited Doom Desire call
  `addSlotCondition(target, 'futuremove')`. The condition removes itself with
  `removeSlotCondition(..., 'futuremove')`. The extractor correctly reads the
  identity from argument 1, not argument 0.
- `trapper`: Block, Mean Look, and Spider Web pass it as the fourth argument to
  `addVolatile('trapped', source, move, 'trapper')`; generic
  `Pokemon#addVolatile` creates the linked source volatile.
- `sleepclausemod` and `freezeclausemod`: `Battle` installs resolved rules that
  have runtime handlers as field pseudo-weather. Both expose live Gen 3 OU
  `onSetStatus` handlers.
- `minimize`: reachable through legal Metronome delegation even though a scan
  limited to directly submitted moves can omit it.

These are inventory-denominator facts, not evidence that the native runtime
implements the mechanics.

## Creation and removal surfaces checked

The descriptor and Condition traversal covers declarative `status`,
`forceStatus`, `volatileStatus`, `sideCondition`, `slotCondition`, `weather`,
and `pseudoWeather` fields, plus these imperative APIs:

```text
addVolatile / removeVolatile
addSideCondition / removeSideCondition
addSlotCondition / removeSlotCondition
setWeather / clearWeather
addPseudoWeather / removePseudoWeather
setStatus / forceStatus / trySetStatus / cureStatus / clearStatus
```

It also follows the linked-status argument of `addVolatile`, resolves reviewed
dynamic argument domains, traverses newly discovered Condition objects to a
fixed point, and accounts for direct deletes. The seven reachable descriptor
deletes are:

- Substitute deleting `partiallytrapped`;
- Rollout deleting `rollout`;
- Torment deleting `torment`;
- Ice Ball deleting `iceball`;
- Uproar deleting `uproar`;
- `partiallytrapped` deleting itself;
- `lockedmove` deleting itself.

The generic simulator census independently covers owner-store construction,
normal add/remove transactions, rejected-Start rollback, status/weather
commit and rollback, linked volatile creation/removal, volatile copy and bulk
clear, duration-driven end callbacks, RuleTable pseudo-weather installation,
and stored removal callbacks. It scans all simulator TypeScript files rather
than a fixed owner-file list.

## Reviewed false positives and exclusions

- Writes below a condition identity slot, such as Substitute HP, Bide damage,
  duration, source, and linked-Pokemon metadata, mutate condition payload but
  do not create or remove an identity.
- `sim/dex-data.ts` assignments construct descriptor fields rather than live
  battle state.
- BattleStream condition commands are debug-only and unreachable from legal
  battle choices.
- Generation-gated Dynamax, Z-Move, Revival Blessing, Gen 1, and multi-battle
  branches remain in the source ledger but are marked unreachable for Gen 3
  OU rather than silently filtered.
- Empty container initialization creates storage, not a concrete condition
  identity.

## Fail-closed design and remaining limitations

The production extractor and the independent audit use different parsers: a
small balanced-call scanner produces the inventory, while the integration
test re-parses every effective callback with the pinned TypeScript AST and
requires exact call and deletion multisets. The runtime source ledger rejects
unknown, stale, or unreviewed AST identities. The pinned revision and clean
checkout checks prevent source drift from being silently accepted.

Both scanners nevertheless share an explicit lifecycle-API vocabulary. That
is acceptable for this pinned revision only because the full simulator source
was independently searched and every condition storage owner and wrapper was
reviewed. A future Showdown revision introducing a newly named lifecycle API
would require adding it to the vocabulary. Revision changes must therefore
remain an explicit re-audit boundary.

The following mutation tests should be added as defense in depth:

1. Replace a literal `removeSlotCondition` argument 1 with a computed value;
   extraction must fail.
2. Replace the fourth `addVolatile` linked-status argument with an unresolved
   computed value; extraction must fail.
3. Add a direct condition-identity assignment inside an effective descriptor
   callback; AST integration must fail.
4. Remove or alter the RuleTable pseudo-weather installation row; runtime
   ledger freshness must fail.
5. Add an alias/stored reference to any lifecycle method; the source ledger
   must report a new unreviewed row.

## Verification performed

- fresh independent completeness audit and artifact hash comparison;
- producer-versus-AST call/deletion multiset comparison;
- exact frozen-domain comparison;
- balanced-call scanner tests;
- runtime source census and reviewed-ledger freshness tests;
- generation-script condition-surface test.

An older independent report in this directory records 95 runtime rows and 27
semantic paths. Those figures are stale; the current checked artifact and
passing tests report 97 rows and 28 paths.
