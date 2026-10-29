# Gen 3 high-critical move family

## Authoritative boundary

Pinned Showdown resolves a damaging move's base `critRatio`, passes it through
the ordered `ModifyCritRatio` relay, clamps the resulting stage according to
the generation, draws `move.critical`, and—only when that draw succeeds—runs
the target-facing cancellable `CriticalHit` event.  This precedes `BasePower`
and damage calculation.  The relevant sources are
`sim/battle-actions.ts:1643-1670` and Gen 3 damage staging in
`data/mods/gen3/scripts.ts:30-130`, pinned at
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

The native kernel represents this as:

1. generated `PokemonMoveData.critical_stage`;
2. a generic numeric-or-cancel `ModifyCritRatio` event;
3. `PokemonGeneration.critical_chance`, which owns clamping and probability;
4. the labeled `POKEMON_DRAW_CRITICAL` draw;
5. a generic boolean-or-null `CriticalHit` cancellation event;
6. the existing critical stage-bypass and Gen 3 damage pipeline.

Gen 3 clamps stages to 0..5 and maps them to no draw, 1/16, 1/8, 1/4,
1/3, and 1/2.  A critical ignores only detrimental offensive stages and
beneficial defensive stages.  Its 2x modifier occurs after burn, phase-one
damage modifiers, weather, and the `+2` base offset, before STAB,
effectiveness, and the damage roll.

## Closed descriptors

The callback-free, non-charge high-critical moves are Leaf Blade, Crabhammer,
Air Cutter, Karate Chop, Aeroblast, Blaze Kick, Cross Chop, Poison Tail,
Razor Leaf, and Slash.  Three differential rotations exercise every
descriptor, both critical and noncritical ratio-2 outcomes, physical and
special categories, `normal`, `any`, and `allAdjacentFoes` target
normalization, and the burn/poison secondary programs.  Existing focused and
differential cases retain the no-draw immunity/miss/Protect gates,
Substitute interception, Reflect bypass, and critical stage-bypass behavior.

Razor Wind and Sky Attack remain in the two-turn family. Focus Energy now
installs an indefinite volatile whose generated `Start` and
`ModifyCritRatio` handlers add two stages. Scope Lens adds one stage; Lucky
Punch and Stick add two behind declarative Chansey and Farfetch'd holder
guards. Battle Armor and Shell Armor use the ordinary `CriticalHit` gate to
return false after the draw, preserving Showdown's draw-then-cancel staging.

Eleven focused differential cases cover duplicate Focus Energy, switch
cleanup, Snatch transfer, both matching and nonmatching species guards, both
critical-cancel abilities, and the ordinary item path. They contribute 25
exact boundaries to the 1,094-boundary corpus. The two literal
`onCriticalHit: false` callbacks also corrected the authoritative inventory:
literal-false hooks are executable obligations, not absent callbacks.
