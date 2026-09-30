# Gen 3 stat-stage consumer audit

Oracle: pinned Pokemon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, Gen 3 singles.

This is an implementation audit for `BOOST_FAMILY_PLAN.md`, not a support
claim. It describes the minimum generation boundary needed before the direct
boost family can honestly cover all seven stage-bearing stats.

## Current native gaps

The native kernel has the right seven-value state product in
`native/pokemon.h:164-173` and `PokemonMutable.boosts` in
`native/pokemon.h:936-950`, but only four consumers exist:

- `native/pokemon.c:391-394` hard-codes the ordinary stat-stage formula;
- `native/pokemon.c:1503-1521` consumes Attack/Defense or Special Attack/
  Special Defense during damage;
- `native/pokemon.c:620-655` snapshots raw stored Speed into an action; and
- `native/pokemon.c:1343-1405` and `native/pokemon.c:1849-1867` compare an
  accuracy draw against raw move accuracy through separate damaging and status
  paths.

The damage consumer has the correct Gen 3 floor for an isolated ordinary
stage, including critical-hit suppression of a negative offensive stage and a
positive defensive stage. It is nevertheless generation policy embedded in
generic control flow. It also dispatches `ModifyAtk` only for physical moves;
the other ordinary stat modifier events are absent.

The Speed path skips `ModifyBoost`, the Speed stage, `ModifySpe`, and Gen 3
`getActionSpeed`. The accuracy paths skip `ModifyBoost`, accuracy/evasion
stages, `ModifyAccuracy`, `alwaysHit`, and `Accuracy`. Both accuracy paths
unconditionally consume a draw when they are entered. `PokemonMoveData` also
lacks the `alwaysHit`, `ignoreAccuracy`, and `ignoreEvasion` facts already
available in flattened Showdown move data.

Finally, `apply_boost_effect` at `native/pokemon.c:373-389` applies one
`PokemonEffectOp` at a time. That cannot implement Showdown's product-valued
`ChangeBoost`/cap/`TryBoost` boundary for a multi-stat move.

## Authoritative boundaries

The pinned sources establish these boundaries:

- `sim/pokemon.ts:568-636`: `calculateStat` and `getStat` copy the boost table,
  run `ModifyBoost`, clamp the selected stage to `[-6, 6]`, apply the ordinary
  stage table with `Math.floor`, and then apply the corresponding stat modifier.
- `sim/battle-actions.ts:1688-1730`: damage chooses the offensive and defensive
  stat, maps a critical hit's ignored stage to zero, calculates both stats, then
  dispatches `ModifyAtk`/`ModifySpA` and `ModifyDef`/`ModifySpD`.
- `data/mods/gen3/scripts.ts:16-30` and `sim/battle.ts:3310-3334`: action Speed
  is resolved before queue sorting through `getActionSpeed`; it is a snapshot
  used by the queue.
- `data/conditions.ts:20-38`: paralysis is a `ModifySpe` handler. It finalizes
  preceding modifiers and only then floors Speed times `50 / 100`; it is not a
  stat-stage rule.
- `data/mods/gen3/scripts.ts:337-383`: move accuracy copies and dispatches
  `ModifyBoost` for attacker and target, applies accuracy and inverse evasion
  stages, dispatches `ModifyAccuracy`, lets `alwaysHit` replace the value with
  true, otherwise dispatches `Accuracy`, and consumes `move.accuracy` only for
  a numeric result.
- `sim/battle.ts:2647-2722` and `sim/pokemon.ts:1212-1232`: a boost operation
  runs `ChangeBoost` once over a copied sparse product, caps the whole product,
  runs `TryBoost` once over another copy, then applies each remaining field.

The generated event vocabulary currently misclassifies `ModifyAccuracy` as a
void notification. This is contradicted by Gen 3 Hustle's
`onSourceModifyAccuracy` in `data/mods/gen3/abilities.ts:48-58`, which returns a
chain modifier. `ModifyAccuracy` must be a numeric relay before this consumer
can be complete. `Accuracy` is also numeric-or-cancel, while `ModifyBoost`,
`ChangeBoost`, and `TryBoost` are typed mutable-table boundaries.

## Minimal generation parameterization

Use immutable rational tables rather than seven mechanic callbacks:

```c
typedef struct {
    uint16_t numerator;
    uint16_t denominator;
} PokemonStageRatio;

typedef struct {
    int8_t minimum;
    int8_t maximum;
    PokemonStageRatio ordinary[13];
    PokemonStageRatio accuracy[13];
} PokemonStagePolicy;
```

`PokemonGeneration` should own a `const PokemonStagePolicy *stages`. The
generic kernel clamps with this policy and owns the semantic placement of each
consumer. This is smaller and more auditable than a callback per stat while
still allowing a later generation to supply different tables. If a later
generation genuinely needs algorithmic stage resolution, the same boundary
can become two typed operations without changing consumers:

```c
uint32_t resolve_stat_stage(PokemonStat stat, uint32_t base, int8_t stage);
PokemonRational resolve_accuracy_stages(
    uint16_t base_accuracy, int8_t accuracy, int8_t evasion
);
```

Gen 3's ordinary table is `2 / (2 - stage)` for negative stages and
`(2 + stage) / 2` for nonnegative stages. It serves Attack, Defense, Special
Attack, Special Defense, and Speed. Gen 3's accuracy table is
`3 / (3 - stage)` for negative stages and `(3 + stage) / 3` for nonnegative
stages. Accuracy uses that ratio directly and evasion uses its reciprocal.

The generic ordinary helper performs one floor after multiplying the base by
the selected rational. Damage and Speed then dispatch their typed modifier
events. Critical-hit behavior maps only the ignored offensive/defensive stage
to zero; it does not bypass later stat modifier events.

Accuracy must retain an exact rational until the chance decision. The Gen 3
script does not truncate stage-adjusted accuracy. Showdown draws an integer in
`[0, 100)` and tests it against a possibly fractional numerator. The exact C
test is therefore:

```c
draw * resolved_accuracy.denominator < resolved_accuracy.numerator
```

where the rational denotes a percentage. Flooring the threshold is an
off-by-one error: `66.666...` succeeds for draws `0` through `66`. The existing
`draw_below(..., 100, ...)` remains the correct single labeled draw. Numeric
event modifiers require Showdown's Q12 chain and final rounding semantics; in
particular `Battle.modify` truncates the Q12 modifier and computes
`trunc((trunc(value * modifier) + 2047) / 4096)`. Preserve the rational/value
distinction through this boundary rather than silently flooring it.

## Minimal descriptor and control-flow changes

1. Add the stage policy to `PokemonGeneration` and populate Gen 3's two
   rational tables in `native/gen3_rules.c`.
2. Replace `apply_stat_stage` with a generic policy consumer used for all five
   ordinary stats.
3. Add `always_hits`, `ignore_accuracy`, and `ignore_evasion` to
   `PokemonMoveData`; generate them from the flattened move descriptor. Keep
   OHKO as a separate exceptional accuracy step when that family is added.
4. Introduce one shared move-accuracy preflight used by status and damaging
   moves. Its order is immunity setup, stage resolution, modifier events,
   always-hit/`Accuracy`, then the one labeled draw. A natural type immunity
   still reaches Gen 3 accuracy staging and its draw before the immune result.
5. Resolve active Speed during choice compilation using `ModifyBoost`, the
   stage policy, and `ModifySpe`, and store that resolved snapshot in
   `PokemonAction.speed`. Keep the existing tie draw only when order, priority,
   and final Speed are equal.
6. Represent one declarative boost effect as a fixed `PokemonBoostTable` with
   a presence mask and seven signed deltas, or as a contiguous delta span that
   is normalized into that product. Run `ChangeBoost`, cap, and `TryBoost` once
   per product, then mutate and trace fields in canonical `PokemonStat` order.
   The stage cap comes from `PokemonStagePolicy`, not a literal six.
7. Generalize numeric stat-event dispatch for `ModifyAtk`, `ModifyDef`,
   `ModifySpA`, `ModifySpD`, and `ModifySpe`. Do not claim the consumers exact
   merely because the stage tables exist: the frozen Gen 3 inventory has one
   `ModifyBoost`, 15 `ModifyAtk`, two `ModifyDef`, 15 `ModifySpA`, three
   `ModifySpD`, four `ModifySpe`, two `ModifyAccuracy`, and two `Accuracy`
   ownership records.

## Focused proof required

- Every ordinary and accuracy ratio from stage `-6` through `+6`, using base
  values that expose flooring or fractional thresholds.
- Each of the four damage stats and both critical-hit stage bypasses.
- Agility changing next-turn queue order, plus exact tie-draw/no-draw cases.
- Paralysis after preceding Speed modifiers.
- Accuracy and evasion independently and together, with forced draws directly
  below and at each fractional threshold and exact final seeds.
- `alwaysHit` consuming no accuracy draw, plus `ignoreAccuracy` and
  `ignoreEvasion` isolation.
- The same shared accuracy behavior for status and damaging moves.
- Multi-stat boost application, one capped field, partial `TryBoost` filtering,
  canonical trace order, and source-equals-target filtering bypass.
- Switch-out resetting all seven stages; deterministic replay reproducing
  queue, effects, draws, state, and final seed.
- Capacity/configuration failure rolling the battle back byte-for-byte.

Differential rotation must include all 34 pure boost-table moves, Agility into
next-turn ordering, Flash/Keen Eye, Tickle/Hyper Cutter, Clear Body and White
Smoke, and Flash/Sand Attack/Sweet Scent into subsequent accuracy thresholds.
No descriptor should be reclassified until the focused and differential proof
exists.
