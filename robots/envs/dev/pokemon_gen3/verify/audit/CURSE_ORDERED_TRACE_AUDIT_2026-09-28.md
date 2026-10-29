# Curse ordered-trace audit

Pinned oracle: Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This is an independent read-only trace of the seven legal fixtures emitted by
`verify/cases/generate-curse-cases.js`. The observer was applied to a separate
pinned checkout and each fixture was executed through `verify/slice/oracle.js`.
This document does not make a native support claim.

## Resolved definition and shared ordering

Gen 3 inherits Gen 4's Curse override. The effective move has type `???`, only
the `metronome` flag, accuracy `true`, initial target `normal`, and
`nonGhostTarget: self`. Its invocation follows this order:

1. Showdown copies the move and initially selects its normal target.
2. Move-owned `ModifyType` and then move-owned `ModifyMove` execute. Gen 4's
   `onModifyMove` reads the user's current effective type.
   - Non-Ghost: remove `volatileStatus` and `onHit`, install
     `self.boosts = {atk: +1, def: +1, spe: -1}`, and change the target to
     `self`.
   - Ghost with a target Substitute already present: retain the opponent target
     but remove `volatileStatus` and `onHit`.
   - Other Ghost: retain the opponent target, target Curse volatile, and hit
     callback.
3. If the move-owned callback changed the target mode, the target is resolved
   again immediately. Holder `ModifyType` and `ModifyMove` events then run; a
   second target re-resolution occurs if those events changed the target mode.
4. After announcement and ordinary `TryMove`, the outer `TryHit` event runs.
   This is where Protect's volatile handler is discovered. Gen 4 Protect calls
   `checkMoveBypassesProtect`; Curse lacks the `protect` flag, so the handler
   returns without blocking it.
5. Type immunity and the move's always-hit accuracy stage run without a
   Curse-owned draw. The per-hit path then invokes the move's own `onTryHit`.
   For Ghost Curse, an existing target Curse returns `false` here. This is
   before `TryPrimaryHit`, volatile creation, or HP payment.
6. `TryPrimaryHit` follows. For the Substitute branch, Gen 4 Substitute asks
   for damage from the now-effectless status move, fails it, and leaves the
   Substitute HP unchanged. Neither volatile creation nor payment occurs.
7. On an admitted ordinary Ghost hit, `runMoveEffects` first calls
   `target.addVolatile('curse', source, move)`. `addVolatile` writes source,
   source slot, and source effect, then synchronously runs the condition's
   `Start` callback. Only afterward does the move's `onHit` call
   `directDamage(source.maxhp / 2, source, source)`. Integer clamping floors an
   odd maximum HP: 261 becomes 130 damage.
8. For non-Ghost Curse, the primary hit is effectless and then generic
   `selfDrops` executes the installed self boost. It **unconditionally calls
   `random(100)` before checking whether `self.chance` is absent**, then applies
   the boost. The observer labels this draw `move.secondary`.
9. End-of-turn residual discovery finds target-owned Curse at order 10,
   sub-order 8. Its callback deals `floor(baseMaxHP / 4)`, minimum one. It has
   no duration and no End callback. Target switch/faint cleanup drops the
   volatile before later residual discovery; switching or fainting the source
   does not affect it.

The relevant control-flow sources are `sim/battle-actions.ts:428-455,
553-638, 1049-1118, 1140-1170, 1207-1360`, `sim/pokemon.ts:1509-1532,
1969-2050`, and `sim/battle.ts:2535-2620`. The resolved callbacks come from
`data/moves.ts:3262-3303` and `data/mods/gen4/moves.ts:268-287`.

## Exact fixture traces

The ubiquitous `turn.quick_claw` records below are format turn-staging draws,
not Curse draws. The initial boundary of every fixture has one such draw, and
each completed turn has another. Only additional labels are called out.

### `curse-nonghost-self-profile`

Magikarp's faster action is Splash. Snorlax then enters Curse's move-owned
`ModifyMove`, selects the non-Ghost profile, and re-resolves the target to
Snorlax. The effectless primary path succeeds; `selfDrops` consumes exactly one
`move.secondary` draw (`random(100)`, observed result 65) and applies Attack
+1, Defense +1, Speed -1. There is no Curse volatile, HP payment, or residual
handler.

### `curse-ghost-lifecycle`

Gengar's `ModifyMove` keeps the Ghost profile and opponent target. Outer
admission, always-hit accuracy, move `onTryHit`, and Substitute admission all
succeed. Curse is installed on Magikarp and Start runs; Gengar then pays 130 of
261 HP, leaving 131. Magikarp uses Splash. Residual discovery selects Curse at
order 10/sub-order 8 and deals 45 of Magikarp's 181 base maximum HP, leaving
136. There is no Curse-owned PRNG draw.

### `curse-ghost-duplicate-rejects`

Turn one is identical to the lifecycle trace. On turn two, `ModifyMove` again
keeps the Ghost profile. The move's own `onTryHit` sees the existing target
volatile and returns false before `TryPrimaryHit`; the protocol consequently
shows a failed Curse target and Gengar remains at 131 HP. Magikarp uses Splash,
then the preexisting Curse is still discovered and deals another 45 damage,
leaving 91. No new Start occurs and there is no Curse-owned draw.

### `curse-ghost-substitute-block`

Jolteon first creates a 67-HP Substitute and pays 67 HP. Gengar's move-owned
`ModifyMove` sees that Substitute and removes the invocation's volatile and hit
callback. Target mode remains opponent. Outer admission and the move-owned
`onTryHit` do not reject; Substitute's `TryPrimaryHit` then fails the
effectless status move. Jolteon remains at 204 HP with a 67-HP Substitute,
Gengar remains at 261, and Curse is never started or discovered. There is no
Curse-owned draw.

### `curse-ghost-protect-nonblock`

Smeargle first installs Protect. Gengar retains the Ghost profile. Outer
`TryHit` discovers Protect at priority 3/sub-order 2, but its bypass check lets
Curse continue because Gen 3 Curse has no `protect` flag. Curse Start precedes
Gengar's 130-HP payment. Residual Curse deals `floor(251 / 4) = 62`, leaving
Smeargle at 189. The observed `field_event.residual.handler_order` draw belongs
to ordering the simultaneously expiring Protect/stall residual work, not to
Curse; Curse's explicit order 10 separates it from that tie. There is no
Curse-owned draw.

### `curse-target-switch-teardown`

Turn one installs Curse, pays 130 Gengar HP, and deals 45 residual damage to
Magikarp as above. On turn two Magikarp switches to Blissey before residual
discovery. Switch cleanup clears Magikarp's Curse without an End callback; the
replacement has no Curse, and no Curse residual handler is discovered or
executed that turn. Gengar's later Protect action does not alter that result.

### `curse-source-switch-independent`

Turn one is the ordinary Ghost lifecycle. On turn two Gengar switches to
Blissey. The volatile remains owned by Magikarp, so Magikarp's Splash is
followed by Curse discovery at order 10/sub-order 8 and another 45 damage,
leaving 91. The source need not be active; no Curse-owned draw occurs.

## Corrections to `CURSE_SEMANTIC_AUDIT_2026-09-27.md`

1. Its claims that Curse has “no ... PRNG draw,” that every fixture should
   assert zero labeled draws, and that any Curse PRNG record is a staging bug
   are false for the non-Ghost branch. Showdown's generic `selfDrops` consumes
   one unconditional `random(100)` even when `self.chance` is undefined. The
   native semantic contract therefore needs one `move.secondary` draw for each
   admitted non-Ghost Curse self-boost, at exactly that stage.
2. The prior control-flow summary elides the distinction between the outer
   target `runEvent('TryHit')` and the later move-owned
   `singleEvent('TryHit')`. Protect is consulted in the former; duplicate Curse
   is rejected in the latter, after accuracy staging but before
   `TryPrimaryHit` and effects.
3. Substitute is not simply blocked because a generic status-move rule sees
   the original Curse effects. Gen 4 Curse first deletes `volatileStatus` and
   `onHit` during `ModifyMove`; Substitute's later `TryPrimaryHit` then fails
   the resulting effectless status move. Both steps are required for the exact
   trace.
4. Target re-resolution can happen twice: once after move-owned ModifyMove and
   once after holder-event ModifyMove. The first is the one exercised by
   non-Ghost Curse, but the kernel boundary should preserve both stages if it
   claims Showdown structural equivalence.
5. Residual teardown wording should distinguish clearing from dispatch:
   ordinary switch and faint cleanup clear Curse without an End callback, so a
   target that leaves before residual discovery contributes no Curse handler.

The prior audit's remaining central conclusions are upheld: current effective
typing selects the branch; Protect does not block; duplicate rejection prevents
payment; volatile Start precedes payment; payment and residual damage floor;
the target owns lifecycle; and source departure is irrelevant.
