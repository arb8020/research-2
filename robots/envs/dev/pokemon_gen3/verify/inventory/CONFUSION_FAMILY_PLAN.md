# Gen 3 confusion implementation and verification plan

Oracle: pinned Pokemon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, effective `gen3ou` dex.

This is a source audit and implementation plan, not a native support claim.
Every descriptor and hook named below remains unsupported until its complete
interaction closure passes focused and differential verification.

## Reachable descriptor and hook inventory

The full reachable surface is 25 descriptors plus 32 hook records, 57 graded
entries in total:

- 14 moves: primary Confuse Ray, Supersonic, Sweet Kiss, Flatter, and Teeter
  Dance; secondaries Confusion, Psybeam, Signal Beam, Dizzy Punch, Water
  Pulse, and Dynamic Punch; and fatigue from Outrage, Petal Dance, and Thrash;
- `confusion` and `lockedmove`, with three and five hooks respectively;
- Own Tempo's three confusion hooks and Shield Dust's
  `onModifySecondaries`;
- Persim and Lum, with two and three hooks respectively; and
- Aguav, Figy, Iapapa, Mago, and Wiki Berries, with `onResidual`,
  `onTryEatItem`, and `onEat` each because their flavor payload can confuse.

Swagger is banned from direct Gen 3 OU submission but is runtime-reachable
through Metronome. Its delegated-entry closure is documented separately in
`SWAGGER_CALLED_FAMILY.md`. Dynamic Punch remains a secondary descriptor even
though its chance is 100%. The exact core hooks are
`condition.confusion.{onStart,onBeforeMove,onEnd}`,
`condition.lockedmove.{onStart,onRestart,onResidual,onEnd,onLockMove}`,
`ability.owntempo.{onTryAddVolatile,onHit,onUpdate}`,
`ability.shielddust.onModifySecondaries`,
`item.persimberry.{onUpdate,onEat}`, and
`item.lumberry.{onAfterSetStatus,onUpdate,onEat}`, plus the 15 flavor-berry
hooks above.

Own Tempo's modern `onTryBoost` property is explicitly absent in the effective
Gen 3 callback inventory and is not part of this closure. Lum's
`onAfterSetStatus` is part of the item descriptor even though it responds to a
major status rather than confusion; Lum cannot be classified without it.

## Authoritative semantics

`data/conditions.ts:162-177` owns Start/End; effective Gen 3 BeforeMove comes
from `data/mods/gen4/conditions.ts:65-85`. A successful
fresh installation draws one duration uniformly from 2 through 5 and stores
it on the volatile installation. Reapplication has no `Restart` callback and
must not refresh the duration or consume a draw. `BeforeMove` has priority 3:
it decrements duration first, removes the volatile and permits the move when
the result is zero, otherwise performs one 1/2 action draw. One result permits
the selected move; the other cancels it and calls Gen 3
`getDamage(pokemon, pokemon, 40)`. Numeric normalization makes a typeless,
physical, 40-power, never-critical move and then uses the Gen 3 damage path,
including physical Attack/Defense and their modifiers, weather/damage events,
the ordinary 85..100 roll, burn/final damage modifiers, but no STAB or type
effectiveness (`sim/battle-actions.ts:1603-1861`). The modern
`getConfusionDamage` helper at `:1865-1881` is not the Gen 3 oracle. The action
draw and damage roll are separate labeled operations. Self-hit can faint the
holder and suppress its selected move.

`data/conditions.ts:253-285` owns locked-move fatigue: Start draws a true
duration of 2 or 3, its residual/restart/lock hooks preserve the chosen move,
and natural End installs confusion. Those three producers require a separate
action-lock slice.

`sim/battle-actions.ts:95-125` and `sim/pokemon.ts:1510-1543` clear confusion
with the other non-passed volatiles on an ordinary switch. No duration or
action draw occurs after removal. Baton Pass/copy-volatile behavior is a
separate unsupported dependency and must not be implied by ordinary-switch
evidence.

`data/abilities.ts:3098-3113` owns the three effective Own Tempo hooks.
`TryAddVolatile` cancels every confusion installation, `Hit` emits the
move-facing immunity for moves whose primary `volatileStatus` is confusion,
and `Update` removes already-installed confusion. The distinction matters:
secondary confusion and non-move sources still pass through
`TryAddVolatile`, but do not use the primary-move `Hit` message path.

`data/items.ts:3540-3552` and `:4518-4528` own Lum and Persim. Persim checks
for confusion during `Update`, eats through the generic item transaction, and
removes confusion during `Eat`. Lum eats immediately after any successfully
set major status at `AfterSetStatus` priority -1; its `Update` path handles a
major status or confusion, and `Eat` clears both. The item remains installed
while `Eat` runs and is removed afterward by the existing generic transaction.

The Gen 3 move runner reaches `eachEvent('Update')` after the completed hit and
before `AfterMoveSecondary` (`data/mods/gen3/scripts.ts:476-508`). Therefore a
primary confusion effect can be cured at that Update boundary, while a
confusion secondary installed by `AfterMoveSecondary` is first visible at the
next genuine Update boundary. Verification must prove this difference rather
than normalizing it away.

Substitute is an interaction, not part of confusion state. The existing
`TryPrimaryHit` boundary blocks opponent-targeted primary volatile effects,
and the existing secondary gate blocks confusion secondaries while the hit is
absorbed. Once confusion is installed, self-hit damages the real holder and
never the Substitute payload.

## Native boundaries and dependencies

The native representation should add one generated volatile policy with a
duration payload, not a confusion field on `PokemonMutable` and not move-name
branches. Required reusable boundaries are:

1. generated `ADD_VOLATILE(confusion)` primary and secondary effect programs;
2. generic `TryAddVolatile` discovery/cancellation before fresh installation;
3. generic Start/End lifecycle with installation identity, source, source
   effect, duration, and exact condition traces;
4. generation-owned duration sampling and a generation-owned confusion
   self-hit operation, reached by the generic `BeforeMove` phase;
5. generic ordinary-switch volatile removal;
6. generated Own Tempo handler programs over `TryAddVolatile`, `Hit`, and
   `Update`, without an ability-ID branch;
7. generic remove-volatile item payloads for Persim/Lum, reusing the existing
   Update/eat transaction; and
8. `AfterSetStatus` scheduling for Lum at its declared priority.

The current engine already supplies the effect-program, Update/eat,
Substitute-primary/secondary, stat-stage, faint/request, and switch skeletons.
Missing prerequisites are a general installed-volatile Start/BeforeMove/End
interpreter, `TryAddVolatile`, the dedicated confusion damage policy and its
labeled draws, ordinary-switch removal traces for this volatile, and
`AfterSetStatus` scheduling.

## Smallest complete reusable slice

The first honest slice is the three plain primary producers—Confuse Ray,
Supersonic, and Sweet Kiss—plus the confusion condition and Own Tempo,
including Substitute and ordinary switching. It closes five descriptors and
six hooks while proving every new runtime boundary once:

- successful and missed rotations of all three producers;
- duration endpoints 2 and 5, no refresh on reapplication, decrement-before-
  action, natural expiry, and switch removal;
- action-pass, self-hit, exact Gen 3 damage pipeline, Attack/Defense stages,
  minimum damage, self-KO, request, and terminal ordering;
- exact PRNG staging: duration only after successful installation, action only
  while duration remains, damage roll only after a self-hit result;
- Own Tempo primary immunity, direct `TryAddVolatile` cancellation, and
  Update cleanup of a preinstalled volatile;
- Substitute blocks installation, while an already-confused holder damages
  its real HP rather than the Substitute.

This is the minimum reusable family because Flatter adds an ordered boost,
Teeter Dance adds multi-target iteration, secondaries add Shield Dust and
post-secondary timing, and fatigue adds action locking. Omitting Own Tempo or
Substitute would make even the plain descriptors false under legal
recombination.

## Follow-on slices

1. Add Flatter only after its ordered positive boost-plus-confusion
   transaction is exact, then Teeter Dance after generic multi-target
   iteration. Teeter Dance must retain its
   resolved multi-target semantics even though the current Ocean format is
   singles.
2. Route all six damaging-secondary descriptors through one generated
   volatile-secondary program together with Shield Dust. Prove success/failure, 100% Dynamic Punch,
   immunity/accuracy/Protect/Substitute gates, secondary ordering, and no
   duration draw when the secondary is not attempted or is cancelled.
3. Add Persim through the existing Update/eat transaction and generic
   remove-volatile payload. Prove same-boundary primary cure, delayed
   secondary cure, mismatch, consumption state, switch persistence, and exact
   handler traces.
4. Add Lum only with all three hooks. Prove immediate major-status cure,
   Update confusion cure, status-plus-confusion clearing during one `Eat`,
   ordering against status abilities/items, and no double consumption.
5. Add lockedmove plus Outrage, Petal Dance, and Thrash only with complete
   action-lock/restart/residual semantics and fatigue-only confusion.
6. Add the five flavor berries only after the set representation retains the
   nature/flavor fact and their residual heal/eat transaction is complete.
   The flattened Gen 3 dex uses a `floor(baseMaxHP / 3)` TryHeal gate but an
   effective `floor(baseMaxHP / 8)` Eat heal inherited through the mod chain;
   the latter, not the unflattened base item's one-third body, is authoritative.

## Verification contract

Focused tests must exercise duration, action, and damage-roll endpoints with
forced outcomes; all Attack/Defense stage signs; reapplication; switch; faint;
Own Tempo; Substitute; Persim/Lum; and primary versus secondary timing.
Differential cases must rotate all 14 moves and recombine at least one primary
and one secondary producer with Own Tempo, Substitute, switch, Persim, and Lum.
After every stable boundary compare choices, action queue, handler discovery
and invocation, volatile installation state and duration, condition/effect
traces, HP, item state, requests, terminal result, labeled draws, and final
seed. Persist minimized failures and classify only descriptors whose complete
reachable interaction closure is represented by those cases.
