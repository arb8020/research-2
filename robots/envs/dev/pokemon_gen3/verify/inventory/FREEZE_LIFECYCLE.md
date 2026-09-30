# Gen 3 freeze lifecycle

The native kernel represents freeze as a generated status owner, not as a
move-pair resolver. The resolved Gen 3 plugin binds four reachable callbacks
to ordinary event descriptors:

| Showdown callback | Native boundary | Evidence |
|---|---|---|
| `frz.onStart` | status installation and generated no-op Start handler | all three `freeze-lifecycle-*` cases; `test_freeze_thaw_boundaries` |
| `frz.onBeforeMove` | ordered status-owner `BeforeMove`; labeled one-in-five draw | `freeze-lifecycle-random-thaw`, `freeze-lifecycle-defrost` |
| `frz.onModifyMove` | generated defrost guard followed by the status-clear transaction | `freeze-lifecycle-defrost`; later-flinch focused regression |
| `frz.onDamagingHit` | generated immutable base-type Fire guard, living-holder guard, then status clear | `freeze-lifecycle-fire-hit`; Ember-secondary, lethal-hit, and Weather Ball focused regressions |

The authoritative sources are `data/conditions.ts` for `onStart` and
`onModifyMove`, `data/mods/gen4/conditions.ts` for the inherited Gen 3
`onBeforeMove`, and `data/mods/gen3/conditions.ts` for `onDamagingHit`, all at
pinned Showdown revision `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
`tools/generate_slice_data.js` asserts that the flattened descriptor still has
these functions and emits their handler programs and owner bindings.

The order is semantically significant. A failed random thaw permits a defrost
move to continue, but the cure occurs only at `ModifyMove`, after every
`BeforeMove` handler succeeds. A later flinch therefore leaves the user
frozen. A connected Fire hit applies its secondary effects first and only then
dispatches `DamagingHit`: the Ember fixture forces a successful burn roll,
observes the burn rejection against the existing freeze, and then observes the
Fire-hit cure. A lethal Fire hit does not cure because Showdown's
`cureStatus()` rejects a fainted holder.

The Fire predicate reads the immutable catalog type rather than the active
move frame. Sunny Weather Ball therefore remains unable to thaw even though
its effective type is Fire. This negative staging rule is covered by
`test_weather_ball_active_frame_mutation`; it is focused evidence rather than
a separate differential support claim.

The inherited `frz.onAfterMoveSecondary` callback is separately classified
unreachable. Generation fails if any legal Gen 3 move acquires the required
`thawsTarget` flag, so this is a pinned reachability proof rather than a silent
omission.

The exact corpus contains 1,872 stable boundaries after the three new cases.
Oracle/native comparison and both replay runs are byte-identical.
