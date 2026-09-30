# Jump Kick failed-attempt family

Pinned oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Showdown semantics

Gen 3 defines Jump Kick and High Jump Kick at
`data/mods/gen3/moves.ts:357-380`. Their `onMoveFail` callback first performs
Fighting type admission, computes a fresh hypothetical ordinary hit through
`getDamage(source, target, move, true)`, halves it, clamps it to at least one
and at most half the failed target's maximum HP, then submits that amount as
ordinary move damage to the user. `sim/battle-actions.ts` owns miss,
invulnerability, Protect, and immunity failure staging; `sim/battle.ts` owns
MoveFail dispatch and faint draining. The corresponding upstream regression
is `test/sim/moves/highjumpkick.js`.

Natural Ghost immunity still reaches MoveFail but the callback's explicit
Fighting admission suppresses crash damage. Foresight negates that admission.
Rock Head does not prevent the damage because the effect is the move itself,
not the `recoil` condition. If the target faints before the queued action runs,
Gen 3 cancels the action without spending PP or invoking MoveFail.

## Native boundary

- `PokemonMoveFailurePolicy` is immutable generation-plugin data. It carries
  the failure operation, fraction, minimum, target-max-HP cap, and admission
  requirement.
- The generic move interpreter classifies an attempt as no-target,
  pre-hit-aborted, failed-after-target, or successful. Only
  failed-after-target dispatches MoveFail.
- `calculate_admitted_move_damage` is shared by connected hits and the failure
  policy, keeping critical and damage-roll ownership in one operation.
- The ordinary Damage relay performs the current-HP clamp and composes with
  Focus Band and Endure; the normal faint queue handles lethal crash damage.
- `PokemonEffectTrace` records a typed `crash-damage` result containing the
  hypothetical basis, critical result, damage roll, fraction, minimum, cap,
  requested/applied damage, and source HP transition.

No generic control-flow branch names either move or embeds a Gen 3 move ID.

## Evidence

Focused native test:

- `native/test_pokemon.c#test_move_fail_hypothetical_damage_family`

Differential fixtures:

- `jump-kick-miss-cap-lethal`
- `jump-kick-protect`
- `jump-kick-ghost-foresight`
- `jump-kick-dig`
- `jump-kick-target-gone-cancel`

The observer patch records the direct MoveFail callback and the structured
crash-damage effect. The focused set matches 12 boundaries, and the complete
corpus matches 2,839 boundaries with deterministic oracle and native replay.

## Classification closure

The evidence closes exactly four frozen inventory records:

- `move:jumpkick`
- `move:highjumpkick`
- `event_hook:move.jumpkick.onMoveFail`
- `event_hook:move.highjumpkick.onMoveFail`

No other support claim follows from this family.
