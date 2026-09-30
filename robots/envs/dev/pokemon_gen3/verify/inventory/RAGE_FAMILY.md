# Rage reactive-condition family

Pinned oracle: Pokémon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Rage is represented compositionally: an ordinary 20-power Normal physical
move installs a generated, persistent volatile after a connected hit. The
volatile owns three handlers from `data/moves.ts`: `Start` is lifecycle-only;
`Hit` raises the holder's Attack when another Pokémon hits it with a physical
or special move; and priority-100 `BeforeMove` removes the volatile. Normal
switch/faint cleanup remains kernel-owned.

Native boundaries:

- `native/gen3_slice_data.c`: move/effect descriptors, condition handlers,
  handler programs, and owner bindings.
- `native/pokemon.c`: generic condition installation/removal, ordered event
  discovery, move-category guard, and holder-boost operation.
- `native/test_pokemon.c#test_rage_generated_reactive_lifecycle`: focused
  install, status rejection, damaging-hit reaction, and pre-move teardown.

Differential evidence:

- `rage-lifecycle-basis`: per-hit multihit reaction, status rejection,
  teardown/reinstallation, switch cleanup, and exact labeled PRNG staging.
- `rage-no-install-on-miss`: a missed Rage does not install the volatile.

These cases prove exactly `move:rage`, `condition:volatiles.rage`, and the
condition's `onStart`, `onHit`, and `onBeforeMove` hooks. They do not widen any
other supported claim.
