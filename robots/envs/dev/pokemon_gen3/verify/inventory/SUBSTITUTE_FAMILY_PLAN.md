# Gen 3 Substitute semantic-family plan

This document records the pinned Showdown semantics required before the native
runtime may classify `substitute`, its volatile, or its event hooks as
implemented.  The oracle revision is
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Substitute is not a move-specific branch in damage resolution.  It is an
installed target condition whose `TryPrimaryHit` handler may consume the
primary hit and return a distinct `HIT_SUBSTITUTE` result.  That result is the
reusable native boundary.

## Authoritative Showdown path

Gen 3 inherits its battle scripts from Gen 4 in
`data/mods/gen3/scripts.ts:1-4`.  The effective Gen 3 Substitute condition is
therefore the Gen 4 override in `data/mods/gen4/moves.ts:1283-1319`, layered on
the move definition and lifecycle callbacks in
`data/moves.ts:18312-18368`.

The control-flow boundary is:

1. Gen 3 `useMoveInner` resolves natural immunity, accuracy, and `TryHit`
   before calling `moveHit` (`data/mods/gen3/scripts.ts:300-407`).
2. `moveHit` dispatches `TryPrimaryHit` before ordinary damage and move
   effects (`sim/battle-actions.ts:1058-1094`, especially 1075-1085).
3. A `HIT_SUBSTITUTE` result removes the real target from that hit.  Ordinary
   damage, primary effects, target `Hit` events, and secondaries therefore do
   not run for the absorbed hit (`sim/battle-actions.ts:1082-1089` and
   1092-1160).
4. Gen 3's multihit loop calls `moveHit` independently for every hit
   (`data/mods/gen3/scripts.ts:408-475`).  Consequently, a breaking hit is
   absorbed and capped, while later hits in the same move can damage the real
   Pokemon.

This ordering matters.  Substitute does not prevent the initial accuracy draw
or a multihit-count draw, and damage interception still computes the hit's
critical and damage roll.  It must not be modeled as immunity, Protect, a
post-damage redirect, or a check embedded in boost/status operations.

## Canonical state and lifecycle

The volatile payload must contain at least remaining Substitute HP in addition
to the generic condition installation identity (`descriptor_id`, state
generation, and effect order).  A boolean `has_substitute` is insufficient.

Creation has these exact rules (`data/moves.ts:18322-18345`):

- fail without replacing or refreshing an existing Substitute;
- fail when `hp <= maxhp / 4`, and explicitly for one-max-HP Pokemon;
- otherwise install the volatile with `floor(maxhp / 4)` HP and remove exactly
  `floor(maxhp / 4)` real HP through direct damage;
- installing Substitute removes `partiallytrapped` immediately;
- no PRNG is consumed by creation.

The apparent fractional comparison and the integer rule agree for integral
HP: creation requires at least `floor(maxhp / 4) + 1` current HP.  The explicit
one-max-HP clause remains generation data/policy rather than a generic kernel
assumption.

Ordinary switching, forced switching, and faint cleanup clear all volatiles,
including Substitute (`sim/pokemon.ts:1510-1543` and
`sim/battle.ts:3211-3229`).  Baton Pass is different: its
`selfSwitch: 'copyvolatile'` route (`data/moves.ts:1092-1114`) invokes
`Pokemon.copyVolatileFrom`, which shallow-copies every copyable volatile and
its payload before clearing the outgoing Pokemon
(`sim/pokemon.ts:1248-1269`; `sim/battle-actions.ts:72-117`).  Substitute has
no `noCopy` marker, so its remaining HP passes unchanged.  The incoming
installation needs a fresh native holder identity/effect order even though its
semantic payload is copied; stale field-event identity must not be reused.

## `TryPrimaryHit` result

The generic hit pipeline should gain an explicit result variant, for example:

```text
IMMUNE | MISSED | BLOCKED | HIT_SUBSTITUTE { calculated_damage,
                                              absorbed_damage,
                                              broke } |
CONNECTED { critical, damage_roll, damage }
```

`calculated_damage` is useful for exact trace evidence; game mutation uses
`absorbed_damage = min(calculated_damage, substitute_hp)`.

The installed Substitute handler behaves as follows
(`data/mods/gen4/moves.ts:1287-1317`):

- self-targeted hits bypass it;
- moves with the effective `bypasssub` flag bypass it;
- a status/non-damaging primary whose damage calculation yields neither a
  number nor zero is cancelled before its primary effects;
- a damaging hit calculates damage normally, subtracts at most the remaining
  Substitute HP, and records the capped amount as the source's last damage;
- reaching zero removes the volatile before the next hit; otherwise an
  activation/damage event is emitted;
- recoil is calculated from the capped absorbed amount and damages the source;
- drain heals from the capped absorbed amount, using the move's drain ratio;
- the discovered `AfterSubDamage` event runs with the capped amount;
- the handler returns `HIT_SUBSTITUTE`, preventing ordinary target mutation
  for that hit.

For Gen 3's outer move loop, `HIT_SUBSTITUTE` must contribute zero to ordinary
`move.totalDamage`.  Recoil/drain for the absorbed hit already occurred inside
the interception.  If later multihits reach real HP, their ordinary total and
post-loop recoil remain distinct.  This avoids both missing and double-paying
recoil.

## Status, boosts, flags, and sound

Substitute blocks ordinary foe-targeted primary status, volatile, and boost
effects because `TryPrimaryHit` consumes the hit before `runMoveEffects`.
Self-targeted effects continue to work.

`bypasssub` is a declarative move flag read by the generic interceptor, not a
list of move IDs in the kernel.  In the frozen Gen 3 data:

- Tickle explicitly gains `bypasssub`
  (`data/mods/gen3/moves.ts:618-621`) and must apply both of its stat drops;
- Growl, Screech, Metal Sound, and other sound moves do **not** gain modern
  sound-through-Substitute behavior in Gen 3;
- the `sound` flag and `bypasssub` are independent facts.  The kernel must not
  derive one from the other.

The generated move descriptor therefore needs the effective, flattened
`bypasssub` bit for this generation.  The runtime asks only that bit.

## Related families that must remain explicit obligations

Substitute interception establishes boundaries for several mechanics but does
not implement them by itself:

- **Rapid Spin:** the frozen inventory contains the sole `AfterSubDamage`
  owner, `move.rapidspin.onAfterSubDamage`.  The callback removes the user's
  trapping effects/hazards even when Rapid Spin hits a Substitute
  (`data/moves.ts:14718-14733`).  Dispatch the event now; keep Rapid Spin
  unsupported until its removal operations are implemented and proven.
- **Focus Punch:** its installed condition loses focus on a damaging `Hit`
  event (`data/moves.ts:5998-6028`).  A Substitute-absorbed hit never reaches
  the target `Hit` event, so it does not break focus.  Keep Focus Punch
  unsupported until priority-charge, before-move cancellation, PP timing, and
  its one-turn condition are implemented.
- **Baton Pass:** copying remaining Substitute HP is required, but Baton Pass
  also transfers other copyable volatiles and boosts.  Do not classify Baton
  Pass from a Substitute-only copy primitive.
- **Knock Off and other on-hit effects:** because the real target is removed
  from the absorbed hit, its item/effect callbacks do not run.  This falls out
  of the hit sum type; it is not a Knock Off exception.
- **Indirect damage:** recoil, confusion damage, status residual, weather, and
  similar direct damage to the holder do not hit its Substitute in Gen 3.
  Only an opposing primary hit enters this interceptor.
- **OHKO moves:** the hit removes the Substitute rather than the Pokemon and
  emits the appropriate OHKO marker.  Their separate accuracy/level family
  remains an obligation.

`substitutebroken` requires special inventory honesty.  The inherited Gen 4
Substitute callback **does install it** after every break, even in Gen 3, and
stores the breaking move ID (`data/mods/gen4/moves.ts:1302-1305`).  Its
Gen 4-specific consumer and opponent-switch cleanup do not apply to Gen 3:
Gen 3 overrides Intimidate to inspect only a live Substitute
(`data/mods/gen3/abilities.ts:61-85`), while the cleanup is guarded by
`gen === 4` (`data/mods/gen4/scripts.ts:46-50`).  The marker therefore remains
reachable canonical state in Gen 3 until ordinary volatile cleanup, but has no
Gen 3 handler behavior and is `noCopy`
(`data/mods/gen4/conditions.ts:99-101`).  It may be classified inert only after
the native runtime installs, serializes/traces, and clears the marker exactly;
it must not be called unreachable or silently omitted from canonical state.

## Native boundary

The smallest compositional shape is:

1. Extend `PokemonVolatileState` with a tagged payload (initially a Substitute
   remaining-HP member), rather than repurposing `duration` or `counter`.
2. Add `POKEMON_VOLATILE_SUBSTITUTE` and generated Gen 3 descriptors/programs
   for creation, start/end, and `TryPrimaryHit`.
3. Add `bypass_substitute` to flattened `PokemonMoveData`; populate it from
   effective Showdown data.
4. Let generic `resolve_hit` dispatch `TryPrimaryHit` after the existing
   immunity/accuracy/Protect/`TryHit` stages.  The handler may return the
   explicit substitute-hit variant.
5. Centralize mutation in one `absorb_substitute_hit` operation: decrement
   payload, remove on zero, emit condition/hit evidence, apply damage-relative
   source effects, then dispatch `AfterSubDamage`.
6. Make both single-hit and multihit execution consume the same result variant.
   No move-ID branch belongs in either loop.
7. Reuse generic volatile clear for normal switch/faint.  Later, Baton Pass
   should use a general descriptor-driven `copyable` policy and payload copy,
   not a Substitute branch.

The current native kernel has only Protect and Stall volatile kinds and assumes
those are the only legal volatile states in its invariant checks
(`native/pokemon.h` and `native/pokemon.c:3411-3452`).  It also mutates real HP
immediately after `HIT_CONNECTED` in separate single- and multihit paths.  The
new sum-type result must be consumed before either real-HP mutation site.

## Bounded first slice

The first slice may expose the Substitute move only after all of the following
work together:

- legal creation, duplicate/low-HP/Shedinja rejection, exact cost, and partial
  trap removal;
- payload-bearing installed volatile with start/end/removal evidence;
- ordinary damaging interception, including break versus survive;
- ordinary targeted status/boost interception and declarative `bypasssub`;
- recoil and drain based on capped absorbed damage;
- multihit continuation after the breaking hit;
- `AfterSubDamage` dispatch (even if Rapid Spin's handler remains unsupported);
- ordinary switch, forced-switch, and faint cleanup;
- invariant validation and exact deterministic replay/PRNG traces.

This is the smallest honest **enabled** slice.  A smaller internal development
slice may inject a Substitute volatile to prove direct-boost blocking and
Tickle bypass, but it must not mark the move, volatile, or hooks implemented or
make Substitute legal through the Ocean action surface.

After this slice, these inventory entries can be reconsidered independently:

- `move:substitute`;
- `condition:volatiles.substitute`;
- `move.substitute.onTryHit`;
- `move.substitute.onHit`;
- `move.substitute.condition.onStart`;
- `move.substitute.condition.onTryPrimaryHit`;
- `move.substitute.condition.onEnd`;
- `event:TryPrimaryHit` support for its one frozen handler.

Do not close Focus Punch, Baton Pass, Rapid Spin, OHKO, or unrelated status and
volatile families as collateral progress.

## Required focused and differential evidence

Focused native tests should cover:

1. creation at HP exactly `floor(maxhp/4)` (fail) and one greater (success),
   divisible and non-divisible max HP, duplicate use, and max HP one;
2. exact real-HP cost and exact Substitute payload;
3. removal of partial trap on creation;
4. an ordinary direct stat drop blocked with no boost mutation, and Tickle
   applying its complete two-stat product through Substitute;
5. Toxic/paralysis/sleep-style primary statuses and common target volatiles
   blocked without their downstream PRNG/effects;
6. Growl, Screech, and Metal Sound blocked despite `sound`;
7. damage below, equal to, and above remaining Substitute HP; overkill never
   spills into real HP;
8. critical and noncritical absorbed hits with the exact normal damage-roll
   staging;
9. recoil and drain from capped absorbed damage, including a broken Substitute;
10. a fixed two-hit move where hit one breaks the Substitute and hit two damages
    real HP; and a variable 2-5 hit move with the multihit-count draw before per-hit
    damage draws;
11. self-targeted moves unaffected by the user's own Substitute;
12. normal switch, forced switch, and faint clear; a focused internal copy test
    preserves remaining HP while giving the incoming holder a fresh installation
    identity;
13. an `AfterSubDamage` dispatch trace with exact source, target, move, capped
    damage, and handler order;
14. Focus Punch's target `Hit` notification absent for a Substitute-absorbed
    damaging hit (without claiming the whole Focus Punch family);
15. rollback on event/trace/volatile capacity failure.

Differential cases against the pinned oracle should preserve actions plus
resulting canonical state and compare the first semantic boundary for:

- Substitute creation followed by an ordinary physical and special hit;
- Charm or Screech blocked versus Tickle bypass;
- Toxic blocked;
- a sub-surviving hit and a sub-breaking hit;
- Double-Edge recoil and a draining move against a Substitute;
- a deterministic two-hit break-through sequence and a seeded 2-5-hit move;
- switch-away cleanup and forced-switch cleanup;
- Baton Pass preserving remaining Substitute HP (kept as a regression artifact
  even if Baton Pass remains unsupported during the first slice);
- Rapid Spin firing `AfterSubDamage` through Substitute (also retained as a
  future-family artifact);
- Focus Punch retaining focus when the incoming damaging hit is absorbed.

For every probabilistic case, compare labeled calls in semantic order:
accuracy, multihit count where applicable, then each hit's critical check and
damage roll.  Substitute creation, blocking of a non-damaging status move,
payload capping, break/removal, and bypass selection consume no extra draws.
