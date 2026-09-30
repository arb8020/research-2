# Secret Power family

Pinned oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Resolved semantics

Gen 3 recursively inherits the Gen 4 override for Secret Power. That override
fixes the secondary effect to 30% paralysis; the base move callback remains.
The callback returns immediately while the field terrain identity is empty.
Gen 3 has no reachable terrain creator, so the callback executes but is an
identity transformation throughout the supported format.

The generated move descriptor therefore supplies Normal type, Physical
category, 70 base power, 100% accuracy, and one ordinary after-hit 30%
paralysis effect. A zero-program move-owned `ModifyMove` handler preserves the
observable discovery and ordering boundary without adding terrain semantics or
a move-ID branch to the kernel.

Authoritative sources:

- `data/mods/gen3/scripts.ts`: Gen 3 identity and inherited data resolution.
- `data/mods/gen4/moves.ts`: fixed Secret Power paralysis secondary.
- `data/moves.ts`: inherited terrain callback and base descriptor.
- `sim/field.ts`: empty terrain initialization and terrain lookup.

## Evidence

- `native/test_pokemon.c#test_secret_power_resolved_terrain_free_descriptor`
  checks the flattened move, secondary, and zero-program observable handler.
- `secret-power-secondary-a` and `secret-power-secondary-b` cover the proc and
  non-proc paths against pinned Showdown across four stable boundaries.
- `tools/generate_slice_data.js` rejects changes to the inherited callback,
  effective descriptor, or 30% paralysis secondary at generation time.

The move record is `implemented`. `move.secretpower.onModifyMove` is `inert`,
not unreachable: handler discovery occurs, but its reachable denotation is the
identity function.
