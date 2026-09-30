# Choice Band and Choice Lock

Choice Band is represented by two generated item handlers plus one generic
choice-control condition. It is not a move resolver branch.

The pinned Gen 3 Dex inherits Choice Band from `data/items.ts` and
`data/mods/gen4/items.ts`: priority-1 `ModifyAtk` chains a 1.5 multiplier and
item-owned `AfterMove` installs `choicelock`. The effective Gen 3 condition
inherits `onStart` and `onDisableMove`, but its `onBeforeMove` is deliberately
absent: `data/mods/gen6/conditions.ts` removes that modern callback before the
Gen 4 override replaces only `onStart`. The resolved pinned Dex assertion in
`tools/generate_slice_data.js` guards this inheritance result.

The native plugin supplies:

- an item `ModifyAtk` program with Q12 multiplier 6144;
- an item `AfterMove` program that installs or restarts a typed volatile on
  its holder;
- an indefinite choice-control policy whose Start captures the holder's last
  usable move and whose DisableMove disables every other move slot;
- the required held-item identity, so request projection removes the exact
  stale volatile after Choice Band is lost.

The generic kernel owns handler discovery, modifier composition, volatile
installation, Start admission, request reduction, fallback Struggle,
switch cleanup, item-loss cleanup, rollback, and tracing. It contains no move
pair or Choice Band ID branch. Because the effective Gen 3 condition has no
BeforeMove handler, action safety comes from normalized legal choices; when no
enabled move remains, the existing request reducer synthesizes Struggle.

Evidence:

- `test_choice_band_choice_lock_lifecycle` proves the 1.5 modifier, captured
  move, indefinite state invariant, narrowed request, absence of a Gen 3
  BeforeMove callback, voluntary switching, switch cleanup, and stale-owner
  removal after item loss.
- `item-choice-band-connected-lock` proves connected physical damage and the
  following request lock.
- `item-choice-band-miss-lock` proves a normally executed missed move still
  reaches AfterMove and locks.
- `item-choice-band-status-lock` proves a status move locks through the same
  boundary.
- `item-choice-band-switch-reset` proves switching remains legal and returning
  the holder restores both move choices.

All 14 boundaries agree exactly on requests, normalized choices, queues,
handlers, state, events, modifier relays, and labeled PRNG with Pokémon
Showdown revision `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
