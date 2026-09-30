# Minimize family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

The resolved Gen 3 move is the inherited composition of three Showdown data
layers: `data/moves.ts` supplies the persistent condition and flagged-move
damage callback, Gen 4 overrides the evasion boost to `+1`, and Gen 5 disables
the later `onAccuracy` callback. The executable Gen 3 condition therefore has
only `onRestart` and `onSourceModifyDamage`; it is `noCopy` and durationless.

The native representation uses existing generic boundaries:

- the generated move program applies the ordinary evasion boost and installs
  `POKEMON_VOLATILE_MINIMIZE`;
- duplicate installation dispatches the condition's no-op `Restart` handler;
- reversed `ModifyDamage` discovery finds the target-owned condition, guards
  on the generated `minimize` move flag, and chains a 2x modifier;
- generic switch and faint teardown remove the marker.

No move-name branch was added to the battle kernel. `Stomp`, `Astonish`,
`Extrasensory`, and `Needle Arm` receive the behavior from their generated move
flags.

`native/test_pokemon.c#test_minimize_generated_marker_and_damage_modifier`
proves the `+1` boost, duplicate restart, one marker, 2x modifier, unchanged
accuracy/critical/damage-roll staging, and invariants. The legal
`metronome-minimize-flagged-damage` fixture reaches the OU-banned move through
Metronome and differentially proves the condition lifecycle, handler order,
canonical state, modifier relay, and labeled PRNG against the pinned oracle.
