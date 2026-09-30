# Sleep Talk: current-slot move delegation

Pinned oracle: Pokémon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Resolved Gen 3 Sleep Talk owns two boundaries in
`data/mods/gen3/moves.ts`: `onTry` requires sleep, while `onHit` enumerates the
user's current move slots, excludes `nosleeptalk` and charge moves, uniformly
samples the remaining slots, checks the selected slot's PP, and calls that
move without charging child PP. A zero-PP slot remains a candidate and can
consume the selection draw without producing a child invocation.

Generated move rows flatten the raw flags into the semantic
`call_eligibility` bitset. The generic kernel operation
`CALL_MOVE_FROM_USER_SLOTS` knows only that bitset and the current fixed-size
slot view; it contains no Sleep Talk or Gen 3 identity branch. The existing
called-move path owns targeting, hit resolution, effects, and trace
provenance. The parent alone owns selected PP.

Evidence:

- `test_generated_current_slot_move_delegation` covers asleep success, awake
  rejection, no eligible slot, zero-PP selection, exact labeled PRNG, child
  provenance/PP ownership, and invalid-plugin atomic rejection.
- `sleep-talk-current-slot-call`, `sleep-talk-awake-rejection`, and
  `sleep-talk-no-eligible-slot` compare every observable boundary against the
  pinned oracle.
- `tools/generate_slice_data.js` asserts the resolved callback shape and emits
  the eligibility facts, handlers, and owner bindings.

This slice does not claim Assist or mutable move slots. Assist needs a
teammate-slot selector; Mimic and Sketch require explicit base/current move
slot state with distinct switch persistence.
