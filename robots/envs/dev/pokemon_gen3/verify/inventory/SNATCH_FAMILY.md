# Snatch family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Gen 3 inherits Snatch's effective implementation through the Gen 4 mod at
`data/mods/gen4/moves.ts:1213-1237`. It installs a duration-one self volatile.
Its ordered `AnyPrepareHit` handler ignores moves without the Snatch flag;
otherwise it removes the volatile, charges Pressure against the stolen move's
original user and the Snatch slot, invokes the move as the Snatch holder, and
cancels the original invocation. Gen 3 intentionally lacks the modern
`sourceEffect === 'snatch'` guard, so another installed Snatch condition may
discover the called invocation.

The native boundary is generated data plus generic control flow:

- `native/gen3_slice_data.c` owns the condition descriptor, handler program,
  owner binding, and move flag guard.
- `native/gen3_rules.c` owns the duration-one condition policy.
- `native/pokemon.c` owns condition installation/removal, ordered handler
  discovery, PP-event dispatch, called-move reentry, and rollback.

`test_snatch_reenters_active_move_as_handler_owner` proves positive and
ineligible paths, owner/source provenance, Pressure PP ownership, nested
rediscovery, ordering draws and replay, expiry, duplicate installation,
capacity rejection, and rollback. Differential cases recombine Snatch with
single- and multi-stat boosts, healing, weather recovery, Focus Energy, and
Pressure. `snatch-ineligible-expiry` independently proves that Splash does not
consume the volatile and residual expiry still removes it.

Showdown's `onStart` also emits a textual `-singleturn` protocol message. Text
logs are outside the native observable contract; installation and condition
lifecycle remain observable and exact. The Sky Drop, Z-Move, and Max-Move
guards in the modern base definition are unreachable in Gen 3 OU.
