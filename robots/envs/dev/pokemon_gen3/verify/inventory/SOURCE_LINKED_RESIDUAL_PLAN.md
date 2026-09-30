# Source-linked residual transfer

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This document records the selection-time plan for a capability that is now
implemented. It is witnessed by
Leech Seed, Liquid Ooze, and Rapid Spin cleanup, but the native boundary is a
position-linked damage-transfer transaction rather than three move-specific
resolvers.

## Why this slice is next

The selection-time inventory contained 239 unsupported records. Three independent
audits ranked this slice above the other eligible battle-kernel work because
it composes already-earned condition installation, residual ordering, damage,
healing, switching, and handler dispatch while exposing one missing semantic
type: a battlefield position is not a Pokemon identity.

Admission validation remains required, but belongs to a separate generated
`PokemonAdmissionBundle` and pre-battle verifier.  Perish Song is the next
condition-lifecycle candidate after this slice.

## Resolved Showdown semantics

The authoritative object is `Dex.forGen(3)`, including recursive mod
inheritance.  Relevant source boundaries are:

- `data/moves.ts#leechseed`: Grass admission, Start, residual damage and heal;
- `data/mods/gen4/moves.ts#leechseed`: resolved residual order 10/suborder 5;
- `sim/pokemon.ts#addVolatile`: records both source identity and `sourceSlot`;
- `sim/battle.ts#heal`: dispatches `SourceTryHeal` before committing healing;
- `data/mods/gen4/abilities.ts#liquidooze`: converts drain/Leech Seed healing
  into equal indirect damage and returns zero;
- resolved `rapidspin`: cleanup after ordinary HP damage and Substitute damage.

The required denotation is:

1. Leech Seed's `TryImmunity` records the Grass rejection before accuracy, but
   the status-move pipeline still performs its labeled accuracy draw before
   emitting the immunity result.
2. A successful hit installs a persistent volatile with the source's active
   battlefield position.
3. At residual order 10/suborder 5, resolve the current living occupant of
   that position.  If none exists, do nothing.
4. Damage the seeded holder by `max(1, floor(baseMaxHP / 8))` and retain the
   actual HP damage after clamping.
5. Offer exactly that amount as healing to the current position occupant via
   `SourceTryHeal`.
6. Liquid Ooze on the damaged holder changes the offered heal into equal
   indirect damage to the would-be recipient and returns zero healing.
7. Drain faint work only after the damage-transfer transaction is complete.
8. Switching/faint cleanup of the seeded holder is silent.  Switching the
   original seeder does not clear the relation; its replacement occupies the
   same source position and receives the transfer.
9. Rapid Spin removes Leech Seed, Spikes, and partial trapping only after a
   qualifying ordinary or Substitute damage path.  Miss, immunity, no damage,
   or a fainted spinner does not clean up.

There is no mechanic-specific PRNG beyond Leech Seed accuracy and the existing
residual-handler tie ordering.

## Native boundary

The generic state and interpreter additions are:

- an explicit source-position resolver boundary.  The current kernel is
  singles-only (`PokemonSide.active` is scalar), so the stored source side and
  position zero resolve the current occupant without enlarging public state;
- a generated target-type admission program for Leech Seed;
- a generated residual operation which damages the condition owner, retains
  actual damage, resolves the current source-position occupant, dispatches
  `SourceTryHeal`, commits allowed healing, then drains faint work;
- a generated numeric-relay operation for Liquid Ooze which applies the relay
  amount as indirect damage to the would-be healer and replaces the relay with
  zero;
- generic post-real-damage and post-Substitute-damage cleanup programs for
  Rapid Spin.  The programs name generated condition descriptors; kernel
  control flow names no moves, abilities, or Gen 3 IDs.

The operation must not interpret `PokemonEntityRef.source.slot` as
`sourceSlot`.  That field is a roster member identity; Showdown's `sourceSlot`
is a field position whose occupant may change.  When the kernel earns a
multi-active side layout, replace the singles resolver with an explicit
`PokemonActivePositionRef {side, position}` rather than changing the meaning
of the roster slot.

Bundle validation must reject missing condition descriptors, unsupported
position capacities, invalid handler routes/algebras, or incomplete cleanup
programs before mutation or PRNG consumption.

## Observer contract

The test-only observer must expose the generic facts needed for causal
localization:

- Leech Seed volatile identity plus normalized `{side, position}` source slot;
- `TryHeal` handler discovery/order under the name `try-heal`;
- generic move-owned `after-hit` and `after-sub-damage` boundaries;
- ordinary condition removal traces and resulting canonical state.

Do not add Leech-Seed-, Liquid-Ooze-, or Rapid-Spin-specific observer events.

## Compact proof basis

The legal Gen 3 singles basis is:

1. successful install and exact one-eighth damage/heal;
2. low target HP proves transfer uses actual damage;
3. miss consumes only the labeled accuracy draw;
4. Grass immunity is discovered before accuracy, while the accuracy draw is
   still consumed before the immunity result is emitted;
5. duplicate application fails without Restart;
6. original source switches and its replacement receives healing;
7. no living source-position occupant suppresses both damage and healing;
8. target switching silently clears the volatile;
9. Giga Drain and Leech Seed each trigger Liquid Ooze damage/no-heal;
10. Dream Eater does not trigger the resolved Gen 3 Liquid Ooze override;
11. Rapid Spin removes Leech Seed, Spikes, and partial trapping after real HP
    damage;
12. the same cleanup occurs after Substitute damage;
13. miss/no-damage and a spinner fainting during contact response do not clean
    up;
14. mutual seeds at equal speed prove residual tie ordering and labeled PRNG.

Focused C tests additionally construct a changed position occupant directly,
prove source-position and source-identity are distinct products, verify bundle
rejection is atomic, and exercise lethal damage on both sides of the transfer.

Upstream regression mappings include `test/sim/moves/leechseed.js`,
`test/sim/abilities/liquidooze.js`, `test/sim/moves/rapidspin.js`, and
`test/sim/misc/trapmoves.js`.  Their semantic assertions are ported to legal
Gen 3 OU teams; their TypeScript implementation and later-generation-only
mechanics are not.

## Classification gate

Only after focused tests, every applicable differential fixture, full corpus,
deterministic replay, random play, Ocean adapter, and sanitizer gates pass may
the following nine records be reclassified:

- `move:leechseed`;
- `condition:volatiles.leechseed`;
- `event_hook:move.leechseed.onTryImmunity`;
- `event_hook:move.leechseed.condition.onStart`;
- `event_hook:move.leechseed.condition.onResidual`;
- `ability:liquidooze`;
- `event_hook:ability.liquidooze.onSourceTryHeal`;
- `event_hook:move.rapidspin.onAfterHit`;
- `event_hook:move.rapidspin.onAfterSubDamage`.

Rapid Spin itself and its Gen 3 `self.onHit` callback are already supported;
they are regression evidence, not new closure credit.

## Completion evidence

The slice closes exactly the nine records above. Five legal focused fixtures
match the pinned oracle, and the complete corpus matches at 2,259 boundaries
with deterministic oracle and native replay. Native unit, 128-battle random
play, Ocean-adapter, inventory-contract, and Address/UndefinedBehavior
sanitizer gates pass. The live map therefore moves from 239 to 230 unsupported
records; no other support claim changes.
