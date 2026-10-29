# Source-linked trapping

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Block, Mean Look, and Spider Web share one semantic family. Their resolved Gen
3 `onHit` callbacks call `target.addVolatile('trapped', source, move,
'trapper')`. `data/conditions.ts` defines `trapped.onStart` and
`trapped.onTrapPokemon`; the paired `trapper` condition is a reachable internal
linked-status marker. Gen 3 inherits `noCopy: false` for both conditions from
`data/mods/gen4/conditions.ts`.

The native kernel normalizes the pair into one visible fixed-capacity relation.
`PokemonConditionRule.source_linked_kind` names the hidden counterpart. The
generic installer still executes the counterpart's `Immunity` and
`TryAddVolatile` admission against the source and consumes its holder effect
order after the visible condition's `Start`, matching `Pokemon.addVolatile`.
Duplicate links reuse the marker. Source switch or faint removes every relation
owned by that source. The helper is excluded from canonical volatile state,
while `trapped` retains source side, slot, and move provenance.

The frozen inventory exposes this identity twice: once as
`volatiles.trapper` in the resolved condition domain and once as the
simulator-only helper discovered from `linkedStatus`. Both records map to this
same normalized native relation and evidence; they do not denote two runtime
states or two implementation tasks.

Evidence:

- `native/test_pokemon.c#test_source_linked_trap_family` checks all three
  descriptors, linked admission, effect ordering, duplicate behavior, request
  restriction, and source-switch release.
- `source-trap-block-release`, `source-trap-mean-look-rotation`, and
  `source-trap-spider-web-rotation` contribute seven exact stable boundaries.
- Generated move/condition handlers live in `native/gen3_slice_data.c`; the
  resolved link policy lives in `native/gen3_rules.c`; the generic transaction
  lives in `native/pokemon.c`.

Baton Pass transfer remains outside this family because Baton Pass itself is
still unsupported. These cases prove ordinary installation, persistence, and
source departure; they do not claim the unsupported transfer interaction.
