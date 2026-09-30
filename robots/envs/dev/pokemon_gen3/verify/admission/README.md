# Gen 3 OU admission verification

This verifier is separate from the battle differential harness. It compares
normalized submitted-set admission against the pinned Showdown `TeamValidator`
without adding validator work to the Ocean hot path.

The verifier currently covers the nine resolved atomic ability/item/move bans
and three generated descriptor-tag bans: Uber, Unobtainable, and Nonexistent.
It also covers OHKO Clause through a generated move predicate whose exact
closure is Fissure, Guillotine, Horn Drill, and Sheer Cold; delegated execution
through Metronome is an explicit legal control.
Accuracy Trap Clause is a two-term use of the same all-of interpreter over
generated guaranteed-accuracy-drop and trapping predicates. Ability and move
trapping routes, each predicate alone, probabilistic accuracy drops, and
partial trapping are covered by the shared differential corpus.
Speed Pass and One Boost Passer are exercised through explicit team fixtures
and `TeamValidator.validateTeam`. Native mirrors that boundary with a
six-member fixed-capacity input, team-index diagnostics, generated source
predicates, and a generic anchored-cardinality rule.
EV Limit is exercised through a generated six-stat vector policy bound to the
resolved format manifest. Fixtures cover omitted and explicit vectors,
component bounds `0..255`, totals 509/510/511, the level-one all-zero
exception, and rejection on a later team member. The inclusive total cap is
the EV Limit rule; omission, zero-total, and component validation are adjacent
normalization semantics proved at the same boundary.
Obtainable Abilities is exercised through one generated compressed-row
relation from canonical species IDs to canonical ability IDs. The pinned
resolved Gen 3 data produces 393 species rows and 517 legal pairs; the generic
relation interpreter contains no species- or ability-specific branches.
Fixtures prove primary and secondary slots, both slots of a dual-ability
species, modern-slot and cross-species rejection, and diagnostics on a later
team member. Unknown names remain boundary errors rather than relation misses.
Obtainable Formes is exercised as a transactional normalized product rather
than a verdict-only check. Three generated guarded rewrites map
Castform-Sunny, Castform-Rainy, and Castform-Snowy to base Castform only when
Forecast is present. Set and team outputs are committed only after every
applicable rule succeeds; rejection leaves the caller's output unchanged.
Selectable Deoxys formes are not battle-only rewrites. The pinned upstream
scenario that changes among them is unreachable in Gen 3 OU because the
resolved format bans those Uber identities, so their existing ban evidence is
kept separate. The current native boundary accepts canonical IDs and returns
canonical IDs; preserving user-facing spelling or aliases is outside this
normalization product.
A native non-rejection is reported as `INCOMPLETE`, never as legal. Release,
learnset/source, remaining set-metadata, and aggregate rules remain
unsupported.

Run the oracle half with:

```sh
POKEMON_SHOWDOWN_DIR=/path/to/clean/pinned/showdown node verify/admission/oracle.js
```

The native runner and exact comparator are built around the generated
`PokemonAdmissionBundle`; both sides must agree on rejection for every case.
The focused native test separately proves the generated rule mapping and
native program order. Showdown's human-facing problem order is deliberately
not treated as part of the runtime contract. `cases.json` is the single
scenario source for both runners.

Run the exact differential and deterministic replay check with:

```sh
make -C verify/admission test \
  POKEMON_SHOWDOWN_DIR=/path/to/clean/pinned/showdown
```

The bounded randomized acquisition/source-recombination gate adds 1,250
deterministically generated multi-member teams across five fixed seeds. It
performs exact replay, structured comparison, and causal failure minimization
without changing the curated fixture corpus. See `random/README.md` and run:

```sh
make -C verify/admission random-test \
  POKEMON_SHOWDOWN_DIR=/path/to/clean/pinned/showdown
```
