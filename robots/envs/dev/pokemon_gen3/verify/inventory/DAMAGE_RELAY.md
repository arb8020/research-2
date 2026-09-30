# Generic real-HP Damage relay

Pinned oracle: Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Boundary

Showdown's `Battle#spreadDamage` runs the ordered numeric `Damage` event after
hit admission and damage calculation but immediately before mutating real HP.
Substitute owns a separate transaction in `battle-actions.ts` and therefore
never enters this real-HP relay.  The native kernel mirrors that boundary in
`run_ordinary_move_damage_event`:

1. accuracy, immunity, critical, damage roll, and calculated damage resolve;
2. Substitute may consume the hit and return early;
3. the active source effect and installed target handlers are discovered and
   ordered for `Damage`;
4. handlers transform the numeric relay;
5. numeric zero short-circuits later handlers without becoming cancellation;
6. the final relay is clamped to current HP and committed.

The kernel knows no False Swipe identity.  The generated Gen 3 plugin supplies
its source-effect binding and a one-operation program,
`CAP_DAMAGE_TO_HOLDER_HP_MINUS_ONE`, corresponding to
`data/moves.ts#falseswipe.onDamage` at priority `-20`.

The observer records each event's source-effect identity.  This distinguishes
ordinary move damage from Showdown's exact `struggle-recoil` bypass and avoids
inferring event semantics from nearby protocol messages.

## Evidence

- Focused native test:
  `test_false_swipe_generic_damage_relay`
- Differential cases: `damage-relay-false-swipe-*`
- Covered outcomes: nonlethal pass-through, lethal cap to one HP, numeric-zero
  repeat, critical lethal hit, Protect, Ghost immunity
- Substitute bypass is proved directly by the focused native test
- Full deterministic corpus: 1,801 exact boundaries
- ASan/UBSan: focused, random legal play, Ocean adapter, and all 1,801 native
  boundaries

This closes `move:falseswipe` and
`event_hook:move.falseswipe.onDamage`.  Endure and Focus Band remain separate
unsupported descriptors; they can reuse this event boundary but require their
own generated owner programs and complete differential evidence.
