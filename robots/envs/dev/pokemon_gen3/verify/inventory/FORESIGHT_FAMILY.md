# Foresight family

Pinned oracle: Pokémon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Foresight and Odor Sleuth install the same target volatile. The volatile owns
two reusable semantics: `NegateImmunity` admits Normal and Fighting moves
through a Ghost type's raw immunity, and `ModifyBoost` replaces a positive
evasion stage with zero. It does not rewrite the type chart, so the remaining
type-effectiveness factors still apply, and it does not bypass ability-owned
immunity such as Wonder Guard.

Authoritative control flow:

- `data/moves.ts`: Foresight and Odor Sleuth descriptors and the shared
  `foresight` condition.
- `data/mods/gen3/moves.ts`: both moves have numeric 100 accuracy in Gen 3.
- `data/mods/gen3/scripts.ts`: pre-accuracy immunity and accuracy staging.
- `sim/battle-actions.ts`: the post-`TryPrimaryHit` damage-admission recheck.
- `sim/pokemon.ts`: raw immunity, effectiveness, and sparse `ModifyBoost`
  stat calculation.

Native boundaries:

- `native/gen3_slice_data.c`: generated move/condition descriptors, owner
  bindings, type guards, and the zero-positive-boost operation.
- `native/pokemon.c`: generic raw-immunity admission distinct from
  effectiveness, post-primary-hit admission, sparse boost-table dispatch,
  damage-stat staging, and ordinary volatile cleanup on switch.
- `native/gen3_rules.c`: generated condition identity and indefinite volatile
  lifecycle.

Evidence:

- focused C test:
  `test_foresight_generic_immunity_and_boost_staging`;
- differential cases: `foresight-immunity-core`,
  `odor-sleuth-immunity-alias`, and
  `foresight-wonder-guard-independent`;
- both cases compare choices, queues, discovered handlers, condition
  lifecycle, immunity decisions, canonical state, protocol events, and labeled
  PRNG boundaries against the pinned oracle.

The direct Gen 3 `onTryHit` callbacks are preserved as generated move-owned
callbacks because they are part of the resolved descriptor surface, although
their Gen 3 branch is semantically inert without Miracle Eye. The `onStart`
callback contributes the condition lifecycle/message boundary; the reusable
game semantics remain condition-owned rather than move-name branches.
