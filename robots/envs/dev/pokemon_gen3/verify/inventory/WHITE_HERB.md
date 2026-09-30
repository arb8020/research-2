# White Herb lifecycle

White Herb is an item-owned lifecycle program, not a move special case. The
pinned Gen 3 bundle inherits its effective implementation through
`data/mods/gen4/scripts.ts`: `onStart` snapshots every negative boost stage,
uses the held item, and clears only the captured stages. `data/items.ts` binds
that operation to `onStart`, any `SwitchIn` at priority -2, `AfterMove`, and
Residual order 29. Its inherited `onAnyAfterMega` binding is unreachable in
Gen 3 because the generation has no Mega Evolution phase.

The native generation plugin emits four ordered descriptors whose common
three-operation program is:

1. capture the holder's negative-stage mask and stop when it is empty;
2. consume the handler-owned held item through the generic item transaction;
3. clear exactly the captured stages while preserving nonnegative stages.

The generic battle kernel owns direct Start dispatch, global SwitchIn and
AfterMove discovery, Residual dispatch, ordering, and tracing. It contains no
White Herb ID check. `AfterMove` runs once after each selected outer move; a
called or reflected nested invocation does not invent another turn-level
boundary.

Evidence is split deliberately:

- `test_white_herb_after_move_transaction` proves the program, captured mask,
  item transaction, positive-stage preservation, and no-op behavior.
- `item-white-herb-after-move` proves a connected Overheat clears its Special
  Attack drop while preserving a prior Attack boost.
- `item-white-herb-miss-control` proves a miss creates no drop and does not
  consume the item.
- `item-white-herb-start-consumes` and
  `item-white-herb-start-order-control` prove initial Start ordering around
  Intimidate.
- `item-white-herb-any-switch-in` proves the global SwitchIn trigger clears a
  previously retained drop when either side later switches.
- `item-white-herb-residual` stops both selected moves with labeled paralysis
  draws, proving Residual is the first post-Intimidate trigger that consumes
  the item.

Every fixture compares normalized choices, ordered action and handler traces,
canonical state, requests, events, and labeled PRNG consumption against
Pokémon Showdown revision `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
