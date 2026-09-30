# Fury Cutter: generic ramping-power condition

Fury Cutter is the first bounded success-only move-local counter implemented
through generated condition programs. It is not a Fury Cutter resolver and it
does not claim Rollout, Ice Ball, or Stockpile support.

## Pinned Showdown semantics

At revision `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`:

- `data/moves.ts#furycutter` installs the condition before base-power
  evaluation and multiplies base power by its current multiplier;
- `data/mods/gen4/moves.ts#furycutter` supplies Gen 3's inherited base power
  10 and multiplier cap 16;
- `data/mods/gen3/moves.ts#furycutter` restarts the condition only from a
  successful `onHit`;
- `test/sim/moves/furycutter.js` asserts the Gen 3 progression.

The resulting sequence is `10, 20, 40, 80, 160, 160`. A miss, Protect,
immunity, or a turn spent on another move does not refresh the duration-two
condition. Switching the attacker removes it.

## Native boundary

The generated move descriptor is ordinary Bug physical damage. Generated
programs compose four generic kernel operations:

1. ensure an attacker-owned condition exists before BasePower without
   restarting it;
2. initialize its counter on condition Start;
3. multiply the numeric BasePower relay by that counter;
4. add or restart the attacker-owned condition after a connected hit, where
   Restart advances and caps the counter and refreshes fixed duration.

`POKEMON_VOLATILE_FURY_CUTTER` is a concrete condition identity.
`POKEMON_RULE_CONDITION_RAMPING_POWER` is the reusable lifecycle capability.
Keeping those distinct prevents later Rollout or Ice Ball state from aliasing
Fury Cutter. Counter bounds are read from the generated Start/Restart programs,
not hardcoded in the generic kernel.

## Verification

Focused native evidence:

- `test_fury_cutter_generated_ramping_power_lifecycle` proves advancement,
  cap, expiry after a non-refreshing turn, reset, invariants, and source-owned
  state.

Pinned-oracle differential cases:

- `fury-cutter-ramp-cap`
- `fury-cutter-miss-expires`
- `fury-cutter-protect-expires`
- `fury-cutter-wonder-guard-expires`
- `fury-cutter-source-switch-reset`

All cases force and compare labeled probabilistic outcomes where applicable.
The complete 2,437-boundary differential corpus and its repeated oracle/native
replays remain byte-exact, so the new family is also recombined with every
previously supported boundary.

Only these inventory records are promoted: move `furycutter`, condition
`volatiles.furycutter`, and its `onStart`, `onRestart`, and `onHit` hooks.
