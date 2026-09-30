# Pay Day family

At the pinned Showdown revision, Gen 3 Pay Day is an ordinary 40-power,
100%-accurate Normal physical attack. Its inherited `onHit` callback only emits
the `-fieldactivate` battle-protocol message; it does not mutate canonical
battle state. Prize-money accounting is outside a simulated battle.

The generator asserts that source shape and emits the ordinary move descriptor.
The generic hit pipeline owns targeting, immunity, accuracy, critical and damage
draws, Protect, Substitute, damage, and PP. No Pay Day operation or move-name
branch exists in the kernel. The callback is classified inert at the explicit
canonical-state observer boundary.

Differential evidence:

- `pay-day-connected`: ordinary connected damage and labeled PRNG staging;
- `pay-day-protect`: Protect blocks the hit without callback state;
- `pay-day-substitute`: damage is routed to Substitute without callback state.

Authority: pinned `data/moves.ts`, revision
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`. Native boundaries are
`POKEMON_GEN3_MOVES` and the generic move-hit executor.
