# Gen 3 obtainability provenance design

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Status: bounded implementation slice complete; broad support claims remain
withheld pending the remaining upstream-regression and randomized proof.

## Boundary

Obtainable Moves and the source-dependent portion of Obtainable Misc are one
semantic capability. A species-to-move relation is insufficient: Showdown
unions the possible acquisition sources for each requested move, intersects
those alternatives across the whole moveset, then validates the surviving egg
or event source against the submitted set.

The authoritative flow is `TeamValidator.validateSet`, `validateMoves`,
`checkCanLearn`, `validateSource`, `validateEvent`, and
`findEggMoveFathers` in `sim/team-validator.ts`. Gen 3 OU admits generation-3
level-up, machine, tutor, egg, event, and restricted sources. It does not enable
tradeback, Mimic Glitch, or Pomeg Glitch.

## Native model

Build time flattens Showdown inheritance into immutable tables:

- species lineage, evolution level, gender, hatchability, and egg groups;
- sparse `(learnset species, move)` rows;
- typed `L | M | T | E | S | R` acquisition alternatives;
- bounded event descriptors and their set-field constraints;
- generated counts, maxima, fingerprints, and reciprocal-reference checks.

The cold-path interpreter uses a small acquisition sum type. `L/M/T` can
establish an unrestricted current-generation origin when their level
preconditions hold. `E` and `S` contribute exact egg/event origins. `R`
contributes the current-generation origin plus a set-wide single restricted
move. Sketch is delegation through Sketch's own acquisition alternatives, not
a universal boolean.

For at most four submitted moves, the solver performs bounded depth-first
choice over alternatives while intersecting origin sets. It validates a final
event witness against level, gender, nature, shiny, IV, move, and ability
constraints. It validates an egg witness by a bounded father/chain-breeding
search over immutable species and learnset data. This search stays in the
admission module and never enters `PokemonBattle` or the Ocean hot path.

The implementation split is:

- `pokemon_admission.c`: normalization, format-rule orchestration, and atomic
  publication of the normalized team;
- `pokemon_acquisition.h`: generated data ADTs and the pure solver contract;
- `pokemon_acquisition.c`: source intersection, Sketch, event filtering, and
  bounded father search;
- `gen3_admission_data.c`: one coherent, fingerprinted Gen 3 bundle.

Invalid generated tables reject the bundle before mutation. User illegality
returns a typed decision naming the originating format rule and failing move or
field. No path may silently accept an event-only set because its required input
field is absent.

## Proven bounds and evidence plan

The integrated generator emits 18,293 direct species/move rows, 20,195 direct
generation-3 methods, 305 generation-3 event records, and evolution depth at
most three. It recomputes and validates all runtime capacities.

The differential basis includes ordinary level/TM/tutor sources, pre-evolution
inheritance, legal chain breeding, incompatible egg pairs, event intersection
and each constrained event field, egg minimum level, underlevel evolution,
Shedinja's single restricted-source rule, Sketch limits, duplicate canonical
moves, and Hidden Power type/IV consistency. `obtainablemoves`,
`obtainablemisc`, and their aliases remain unsupported until this entire basis
and the independent upstream-test map plus randomized recombination gate show
that this basis is complete. The current focused gate covers malformed-table
rejection, atomic output, duplicate moves, Hidden Power type/IV behavior,
level-up-as-egg descriptors, bounded father recursion, event-only species,
optional-shiny event semantics, and lineage-aware underlevel event evolution.
It matches 136
pinned-oracle cases with byte-identical replay; that bounded result alone is
not a support claim.
