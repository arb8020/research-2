# Gen 3 straightforward flinch family

## Closed boundary

Pinned Showdown revision `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`
defines flinch as a one-turn volatile whose `onBeforeMove` handler has priority
8 and returns false. The native interpreter installs that generated condition
through the ordinary secondary-effect program and discovers its handler through
the generic ordered `BeforeMove` event. The complete ordering at this boundary
is sleep/freeze priority 10, flinch 8, confusion 3, and paralysis 1.

Fresh fixed-duration volatile installation follows Showdown's transaction:
reject a duplicate, dispatch `TryAddVolatile`, reject cancellation, reject
capacity exhaustion, then commit the condition. Inner Focus is a generated
`onTryAddVolatile` handler that guards on the flinch condition and returns null;
the runtime contains no move or ability identifier branch for this behavior.

The closed inventory is exactly 15 obligations: Astonish, Extrasensory, Needle
Arm, Bone Club, Hyper Fang, Rolling Kick, Bite, Headbutt, Rock Slide, Stomp,
and Twister; `volatiles.flinch`; `condition.flinch.onBeforeMove`; Inner Focus;
and `ability.innerfocus.onTryAddVolatile`.

## PRNG and effect staging

The ordinary target-secondary gate owns the single labeled `move.secondary`
draw. Miss, type or ability immunity, Protect, and Shield Dust suppression do
not draw. Substitute still draws but prevents installation. A connected lethal
hit still draws, after which installation fails because the target has fainted.
Inner Focus cancellation happens after that draw. Flinch itself consumes no
PRNG and expires during the same turn's residual lifecycle.

Focused native evidence is
`test_flinch_secondary_family_and_inner_focus`. Four differential fixtures
cover all eleven move descriptors in three rotations plus Inner Focus. They
add 19 boundary records to the preserved 1,050-record corpus.

## Explicit deferrals

Fake Out (`onTry` and first-turn state), Snore (`onTry` and sleep coupling),
Sky Attack (two-turn behavior), Serene Grace (`onModifyMove`), and King's Rock
(`onModifyMove`) remain unsupported. They are not ordinary declarative flinch
secondaries and are not implied by this family.
