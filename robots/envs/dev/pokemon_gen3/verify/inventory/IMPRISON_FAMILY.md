# Imprison semantic family

Pinned oracle: Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Source boundary

- `data/mods/gen4/moves.ts#imprison` supplies the inherited Gen 3 `onTryHit`:
  installation succeeds only while an active foe shares a current move.
- `data/moves.ts#imprison` supplies the persistent self volatile. Its
  `onFoeDisableMove` derives the foe's actual selectable set from the source's
  current move slots, and priority-4 `onFoeBeforeMove` cancels a stale queued
  shared move. Struggle is excluded.
- `test/sim/moves/imprison.js` supplies the upstream regression assertions for
  foe-only restriction, foe-switch persistence, source-switch teardown, and
  the all-shared Struggle fallback.

Showdown intentionally marks these moves `maybeDisabled` in a singles client
request. The verifier's normalized request is omniscient: it projects the
pinned engine's already-computed hidden move state as the actual selectable
set required by the native/Ocean action mask. This is a verifier boundary, not
a change to Showdown battle execution.

## Native boundary

The generated bundle owns the Imprison move, persistent volatile, and three
identity-free handler programs. The generic kernel owns:

- move-self `TryHit` for self-targeting status moves;
- active-foe current-move intersection;
- foe-scoped `DisableMove` discovery and request reduction;
- priority-ordered `BeforeMove` cancellation of an already queued action;
- ordinary switch teardown and request reprojection.

There is no Imprison ID or move-name branch in generic control flow. The
inherited `onStart` only announces the same condition installation already
represented by the generic lifecycle/event boundary, so it does not require a
second empty native callback program.

## Evidence

Focused `test_imprison_foe_scoped_choice_lifecycle` proves successful and
failed admission, queued-action cancellation without PP use, exact request
masking, handler ownership, invariants, and rollback before mutation or PRNG
for a malformed program.

Five legal differential fixtures cover 12 stable boundaries:

- `imprison-queued-shared-move-cancel`;
- `imprison-no-shared-move-fails`;
- `imprison-all-shared-forces-struggle`;
- `imprison-source-switch-clears`;
- `imprison-foe-switch-reprojects`.

These fixtures prove state, normalized choices, queue/event behavior, handler
ordering, lifecycle, and the absence of mechanic-owned PRNG. They do not imply
support for later-generation Z/Max exceptions or doubles topology.
