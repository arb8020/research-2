# Bide stored-damage family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Authoritative semantics

- `data/moves.ts#bide` supplies the base move and condition lifecycle.
- `data/mods/gen4/moves.ts#bide` is inherited by Gen 3 and supplies the
  stored-damage and forced-action shape which Gen 3 overrides selectively.
- `data/mods/gen3/moves.ts#bide` supplies numeric accuracy, priority, release
  targeting, the fixed doubled-damage move, and Gen 3 lifecycle differences.
- `sim/battle-actions.ts#runMove` defines the staging distinction between the
  ordered `BeforeMove` event and the move's direct `beforeMoveCallback`.

The direct callback is not an event handler. It runs after `BeforeMove` and
before PP commitment or move announcement. A forced middle-turn Bide action
therefore cancels silently, while a failed `BeforeMove` dispatches
`MoveAborted`. The release itself is condition-owned `BeforeMove` work.

## Native boundary

- `PokemonMovePreUseProgram` represents direct pre-use cancellation without
  a callback dictionary or a generation-specific move branch.
- `POKEMON_VOLATILE_STORED_DAMAGE` owns cumulative requested move damage and
  the most recent source.
- generated condition programs initialize, accumulate, release, and clean up
  that state through ordinary ordered events.
- `PokemonConstructedHitTemplate` describes the Gen 3 fixed-damage release;
  the generic hit pipeline owns protection, immunity, Substitute, accuracy,
  damage, fainting, and source retargeting.
- malformed or mixed pre-use/template bundles fail during bundle validation,
  before state mutation or PRNG consumption.

No generic-kernel branch names Bide or a Gen 3 numeric identity.

## Proof basis

Focused native tests:

- `test_bide_stored_damage_and_direct_pre_use_stage`
- `test_move_pre_use_program_bundle_validation_is_atomic`

Differential scenarios:

- `bide-core-additive`
- `bide-no-damage`
- `bide-protect-release`
- `bide-substitute-release`
- `bide-ghost-immunity`
- `bide-source-switch-retarget`
- `bide-forced-drag-cleanup`
- `bide-source-faint-retarget`
- `bide-paralysis-abort`

Together these cover single PP commitment, silent middle-turn cancellation,
additive requested damage, zero-damage failure, protection, Substitute,
natural type immunity, source replacement/fainting, forced drag cleanup,
status-owned `MoveAborted`, exact labeled PRNG staging, and deterministic
replay. They justify only the Bide move, its volatile, and its five reachable
condition hooks; they do not imply support for unrelated stored-damage or
constructed-move mechanics.
