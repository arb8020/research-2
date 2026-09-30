# Revenge base-power family

Revenge is the first generated base-power handler that reads resolved
same-turn damage provenance. The native kernel does not branch on the move's
identity.

## Authoritative semantics

The pinned oracle revision is
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
`data/moves.ts#revenge.basePowerCallback` doubles the active move's base power
only when the user has an `attackedBy` entry whose source is the resolved
target, whose damage is positive, and whose `thisTurn` marker is true.
`sim/pokemon.ts#attackedBy` owns that provenance state.

## Native boundary

`native/gen3_slice_data.c` binds Revenge's generated BasePower program. The
program composes two generic operations:

1. guard on positive, current-turn damage from the resolved target;
2. multiply the unsigned base-power relay by two.

`native/pokemon.c` interprets both operations. The guard validates the active
move frame's user, target, move, and handler context. The direct relay
multiplier is distinct from Q12 event modifiers because Showdown's callback
returns `move.basePower * 2`; it does not call `chainModify`.

Bundle validation rejects malformed guard or multiplier operands before state
mutation or PRNG consumption.

## Evidence

Focused native test:

- `native/test_pokemon.c#test_recent_damage_from_resolved_target_base_power_guard`

Differential cases:

- `revenge-no-history`
- `revenge-same-turn-damage`
- `revenge-fixed-damage`
- `revenge-substitute-zero-damage`
- `revenge-stale-damage`
- `revenge-replacement-target`

Together these distinguish absent, positive, zero, stale, category-independent
fixed, and wrong-source damage records. They also cover target replacement,
Substitute interception, switch persistence, canonical state, and exact labeled
PRNG staging. Passing these cases promotes only the frozen `move:revenge`
descriptor; the inventory contains no separately classified Revenge callback
record.
