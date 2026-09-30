# Memento: successful-hit self-faint

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Semantic boundary

Pinned Showdown describes Memento as an always-accurate status move with one
target boost product (`atk: -2`, `spa: -2`) and
`selfdestruct: "ifHit"` (`data/moves.ts#memento`, with the Gen 3 accuracy
override in `data/mods/gen3/moves.ts#memento`). In
`sim/battle-actions.ts#moveHit`, the target transaction and target `Hit` event
run before the source is queued to faint. A false hit result from Protect or
Substitute suppresses that queue; rejection of the requested drops by Clear
Body, or saturation at stage -6, does not.

This is not Explosion/Self-Destruct's pre-hit payment. The generated move
descriptor therefore uses `POKEMON_SELF_FAINT_IF_HIT`; the generic kernel
queues the user only after `execute_move_body` reports a successful primary
hit. The selected-action owner still runs `AfterMove` before draining the
faint queue, allowing target items such as White Herb to compose without a
Memento-specific branch. Memento consumes no accuracy or other PRNG draw.

## Evidence

- Focused C: `native/test_pokemon.c#test_if_hit_self_faint_family` covers the
  descriptor, ordinary drops, Clear Body, stage saturation, Protect, White
  Herb ordering, forced replacement, zero accuracy PRNG, invariants, and
  capacity-error rollback.
- Differential: `memento-standard-force-replacement`,
  `memento-clear-body-still-faints`, `memento-protect-no-faint`,
  `memento-substitute-no-faint`, `memento-white-herb-before-faint`, and
  `memento-terminal-loss` are legal Gen 3 OU cases.
- Upstream regressions: `test/sim/moves/memento.js:13` and `:24` map directly
  to the Clear Body and Substitute cases. Mirror Armor and Z-Memento tests are
  unreachable in Gen 3.

Passing this family classifies only the Memento move record. It does not widen
support for other self-faint timings or later-generation mechanics.
