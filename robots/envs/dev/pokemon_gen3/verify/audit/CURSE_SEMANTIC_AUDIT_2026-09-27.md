# Curse semantic audit

Pinned oracle: Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This is a read-only design audit. It does not classify Curse as supported.

## Resolved Gen 3 definition

Gen 3 inherits Gen 4, and Gen 4's `curse` entry inherits the base move. The
flattened result is therefore not the current base implementation alone:

- base `data/moves.ts:3262-3303` supplies always-hit status semantics, the
  target Curse volatile, duplicate rejection, source half-HP direct damage,
  Start, and residual behavior;
- `data/mods/gen4/moves.ts:268-287` replaces the flags with only `metronome`,
  replaces `onModifyMove`, changes the condition residual order to 10 and
  sub-order to 8, and changes the type to `???`;
- `data/mods/gen3/scripts.ts:1-4` declares Gen 3's parent as Gen 4 and contains
  no Curse algorithm override;
- `sim/dex.ts:638-668` proves that the child entry shallow-overwrites parent
  fields and that the nested condition is separately merged. In particular,
  Gen 4's flags replace the base flags; Gen 3 Curse has neither `protect` nor
  `bypasssub`.

The resolved move is consequently typeless, status, always hit, priority 0,
10 PP, initially opponent-targeted, and has two invocation-time variants:

| Predicate at `ModifyMove` | Resolved target/effects |
|---|---|
| user currently has Ghost type | selected opponent; add Curse volatile, then directly damage the user by `floor(maxHP / 2)` |
| user does not currently have Ghost type | user; `Atk +1`, `Def +1`, `Spe -1`; no volatile and no direct damage |

The predicate is the user's **current effective type**, not immutable species
typing. The target shown in a move request is likewise `normal` for a known
Ghost and `self` for a known non-Ghost (`test/sim/moves/curse.js:13-63`). The
current upstream tests use later-generation type-changing scaffolding, so the
assertion should be ported, not those teams.

## Exact control flow

1. A copied active move is constructed. Its initial target is resolved.
2. Move-owned `ModifyType`, then move-owned `ModifyMove`, run before holder
   events (`sim/battle-actions.ts:428-443`). Curse tests current effective
   Ghost typing here. A non-Ghost invocation deletes the target volatile and
   hit callback, installs its three self boosts, and changes target to self.
   Showdown then re-resolves the target because its target mode changed.
3. The move is announced and ordinary TryMove staging runs. Accuracy is
   `true`; the move performs no accuracy, critical-hit, damage-roll, or other
   PRNG draw.
4. For the Ghost branch, move-owned `TryHit` rejects a target already holding
   Curse before primary-hit/Substitute handling
   (`data/moves.ts:3279-3286`, `sim/battle-actions.ts:1055-1079`). Rejection
   prevents the user's HP payment.
5. The Gen 4 override notices a target Substitute during `ModifyMove` and
   removes the volatile and hit callback (`data/mods/gen4/moves.ts:277-280`).
   The later Gen 4 Substitute `TryPrimaryHit` also blocks the now effectless
   status move. Observable result: Substitute is unchanged, target is not
   cursed, and user pays no HP. This is a block, not bypass behavior.
6. Protect does **not** block Gen 3 Curse: the resolved flags do not contain
   `protect`. No move-name exception is warranted.
7. On a connected Ghost invocation, `runMoveEffects` installs the target
   volatile first (`sim/battle-actions.ts:1257-1259`). Volatile installation
   records source and source effect before dispatching Start
   (`sim/pokemon.ts:1994-2013`). The move `onHit` then directly damages the
   source by half current maximum HP (`data/moves.ts:3288-3289`). Thus the
   target is already cursed if the user faints from the payment.
8. At residual order 10/sub-order 8, the condition deals
   `floor(target.baseMaxHP / 4)`, minimum one. It has no duration and does not
   depend on its source remaining alive or active.
9. Ordinary switch cleanup removes it (`sim/pokemon.ts:1509-1532`), as does
   faint cleanup (`sim/battle.ts:2564-2579`). It has no End callback. In Gen 3
   singles, a faint drains/cancels remaining queued actions before residual
   processing (`sim/battle.ts:2606-2616`).

No immunity, accuracy, critical, damage-roll, secondary, duration, or handler
tie draw belongs to this family. Any Curse PRNG record is a staging bug.

## Exact unsupported inventory records

The current descriptor map contains seven and only seven unsupported Curse
records:

1. `move:curse`
2. `condition:volatiles.curse`
3. `event_hook:move.curse.onModifyMove`
4. `event_hook:move.curse.onTryHit`
5. `event_hook:move.curse.onHit`
6. `event_hook:move.curse.condition.onStart`
7. `event_hook:move.curse.condition.onResidual`

The catalog identity already exists as typeless/status/always-hit, but its
`executable_id` is zero; that is inventory presence, not semantic support.

## Native gap and smallest honest boundary

The native kernel already has the reusable pieces for boost transactions,
descriptor-backed volatile installation with provenance and Start dispatch,
ordered residual handlers, max-HP fraction residual damage, direct damage,
switch/faint volatile teardown, and always-hit accuracy. Those should be
reused unchanged.

The missing capability is **invocation-local move profiles selected at the
ModifyMove boundary**. `PokemonActiveMoveFrame` can mutate type/category/power,
accuracy and flags, but effect execution still reads the immutable move's one
effect slice, and `execute_move_body` retains the pre-mutation resolved-target
classification. Encoding Curse in a resolver branch would conceal this real
gap.

Recommended generation-neutral representation:

```text
PokemonMoveProfile = {
    target_mode,
    effect_offset, effect_count,
    profile_tag
}

PokemonMoveProfileSelection = {
    current_user_type_mask,
    matching_profile,
    nonmatching_profile
}
```

The active frame should carry the selected profile. A generated move-owned
`ModifyMove` program selects a profile from current effective typing, and the
generic kernel must re-resolve the target after target-mode mutation, exactly
where Showdown does. Generated TryHit and hit-callback programs may guard on
the profile tag. This permits:

- Ghost profile: opponent target plus one ordinary `ADD_VOLATILE` primary;
  TryHit duplicate guard; hit callback direct-damages event source by a
  generated max-HP fraction;
- non-Ghost profile: self target plus three ordinary boost operations;
- Substitute: generic primary-hit admission blocks the Ghost profile before
  its primary and callback. The generated ModifyMove callback must still be
  present in structural traces; it need not introduce a move-name branch.

If profile selection is represented as handler operations rather than a table,
the same invariants still apply: the operation must select a bounded generated
effect slice and target mode atomically, validation must reject foreign slices
or invalid targets before mutation/PRNG, and execution must consume the active
slice rather than `move->effect_offset/count`.

One additional generic operation is justified for the Ghost hit callback:
direct-damage the event source by a generated fraction of current max HP, with
move provenance. Do not reuse the ability-only `DAMAGE_EVENT_SOURCE_BASE_MAX_HP_FRACTION`
contract without generalizing its event/source ownership and provenance.

## Focused native tests

1. Profile selection uses mutable effective type, not species type; switching
   restores type and changes the next selection.
2. Non-Ghost profile re-resolves to self and performs exactly three ordinary
   boost transactions, including stage-cap partial success.
3. Ghost profile installs target condition before source half-HP direct damage;
   at low HP, the source faints while the target condition remains.
4. Duplicate target Curse returns false before volatile mutation or HP payment.
5. Substitute blocks both volatile and payment and leaves Substitute HP intact.
6. Protect does not block Curse.
7. Odd maximum HP proves floor-half payment; odd base maximum HP proves
   floor-quarter/minimum-one residual damage.
8. Residual ordering is exactly order 10/sub-order 8 relative to existing
   status/item/weather handlers.
9. Switching and fainting remove Curse; source switching/fainting does not.
10. Malformed/foreign profile slices, invalid profile tags, and target modes
    fail bundle validation before state mutation or PRNG.
11. Every case asserts zero labeled PRNG draws.

## Compact legal differential basis

Use legal Gen 3 sets and retain action plus resulting state for every boundary:

1. **Non-Ghost branch:** Snorlax uses Curse against a passive foe. Assert
   self target and `Atk +1 / Def +1 / Spe -1`, with foe unchanged.
2. **Ghost lifecycle:** Gengar uses Curse against a passive foe. Assert target
   Start, Gengar half-HP payment, same-turn quarter residual, provenance, and
   zero draws.
3. **Duplicate:** Gengar uses Curse twice without a switch. The second use
   fails before payment; the existing condition still performs its residual.
4. **Substitute:** a faster legal target creates Substitute before Gengar uses
   Curse. Assert no Curse, no source payment, and unchanged Substitute HP.
5. **Protect:** target uses Protect while Gengar uses Curse. Assert Curse still
   installs and pays HP because the move lacks the `protect` flag.
6. **Teardown/source independence:** curse a target, then switch that target;
   the replacement is unaffected. In a companion case, switch or faint the
   source and prove the target's Curse continues.
7. **Current-type selection:** where the existing supported type-change family
   permits a legal Gen 3 team, use Conversion to make a non-Ghost user Ghost,
   then assert Curse selects the Ghost profile. Keep this fixture only if the
   pinned validator accepts the exact set; otherwise retain it as a focused C
   constructed-state test rather than weakening legality.

The first six scenarios cover every Curse callback and lifecycle branch. The
seventh proves the abstraction's input boundary rather than a species-name
shortcut.

## Merge dependency

Implement after the integration owner has chosen the active-profile shape:

1. kernel/frame plus bundle validation and target re-resolution;
2. generated Curse profiles, condition descriptor, and four handlers;
3. focused tests;
4. legal oracle fixtures and observer comparison;
5. only then classify the seven records and run the complete corpus,
   replay/random/Ocean, and sanitizer gates.

No existing central files were changed by this audit.
