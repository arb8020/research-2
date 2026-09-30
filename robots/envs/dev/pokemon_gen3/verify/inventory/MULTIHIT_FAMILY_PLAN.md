# Ordinary multi-hit family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

The native runtime implements the callback-free Gen 3 multi-hit family as
move data plus one generic hit loop. The implemented descriptors are Bone Rush
and these thirteen additional moves:

- fixed two hits: `bonemerang`, `doublekick`;
- Gen 3 distributed two-to-five hits: `armthrust`, `barrage`, `bulletseed`,
  `cometpunch`, `doubleslap`, `furyattack`, `furyswipes`, `iciclespear`,
  `pinmissile`, `rockblast`, and `spikecannon`.

Twineedle and Triple Kick are separate semantic families. Twineedle has a
poison secondary; Triple Kick changes power per hit and checks accuracy per
hit. Neither is classified by this slice.

## Authoritative control flow

The effective descriptors come from `data/moves.ts`. Gen 3 selects a ranged
hit count from `{2,2,2,3,3,3,4,5}` in
`data/mods/gen3/scripts.ts:411-480`. Accuracy, immunity, and `TryHit` precede
the plan. Every reached hit independently owns critical and damage-roll draws
and is followed by `Update`; one further `Update` follows the complete
sequence. A fixed numeric hit count consumes no `move.multihit_count` draw.

The generic native loop is in `native/pokemon.c`. `PokemonMoveData` retains
the flattened minimum and maximum. A fixed row has equal nonzero bounds. A
ranged row selects from `PokemonGeneration.multihit`, so the kernel does not
encode Gen 3's probability law. Configuration validation rejects half-empty,
sub-two, reversed, unsupported ranged, and out-of-range policy data before
battle construction.

## Evidence

`native/test_pokemon.c` proves all descriptor shapes, all four Gen 3 ranged
outcomes, fixed-count absence of a count draw, per-hit critical/damage order,
final-hit versus early faint, pre-plan gates, trace capacity, invalid policy
rejection, and atomic initialization failure.

The thirteen `multihit-rotation-*` differential cases each exercise one new
descriptor. The existing Bone Rush corpus supplies miss, natural and ability
immunity, Protect, Substitute breakthrough, two/five-hit plans, and early-KO
recombination. Together they compare choices, queue, handlers, state, events,
hit-loop traces, and labeled PRNG at every stable boundary.

The generator reads the pinned effective Dex, asserts that these rows have no
callbacks, secondaries, alternative damage formula, or per-hit accuracy, and
emits append-only executable IDs. Classification is allowed only after the
focused tests, full differential replay, random/Ocean tests, deterministic
generation, and sanitizers pass.
