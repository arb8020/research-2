# Post-Curse unsupported-frontier audit

Pinned oracle: Pokemon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This is a read-only work-order audit. It does not change classification or
claim support. It assumes the seven Curse records, `condition.mustrecharge.onStart`,
and `move.sleeptalk.onTryHit` have obtained their required evidence and will
leave the unsupported frontier. On that assumption, 48 records remain.

## Recommendation

Implement these two semantic families next, in order:

1. **Pokemon-owned action-cadence state, witnessed by Truant.**
2. **Canonical battle-time species overlays, witnessed by Forecast.**

Then implement Transform on top of both. Do not select Assist or Metronome
yet: their candidate sets can choose moves which remain unsupported, so a few
forced-selection fixtures cannot prove either full descriptor. They are a
late closure/recombination family even though the child-invocation machinery
already exists.

| Family | Uncertainty removed (0--5) | Downstream unlocks (0--5) | Verification affordability (0--5) | Direct closure (0--5) | Score |
| --- | ---: | ---: | ---: | ---: | ---: |
| Truant cadence | 4 | 4 | 4 | 3 | **3.85** |
| Forecast species overlay | 5 | 4 | 3 | 2 | **3.75** |
| Beat Up party-hit construction | 5 | 2 | 1 | 4 | 3.15 |
| Transform whole-Pokemon projection | 5 | 4 | 1 | 1 | 3.05, but blocked |
| Assist/Metronome candidate selection | 3 | 5 | 1 | 3 | 3.00, but blocked |

The score uses the dependency graph's weights: 35% uncertainty, 30% unlocks,
20% verification affordability, and 15% normalized direct closure. Transform
is blocked by unsupported copied abilities and by the absence of an effective
species overlay. Assist/Metronome are blocked as complete support claims by
their still-unsupported candidate universe.

## 1. Pokemon-owned action-cadence state (Truant)

### Exact inventory disposition

Implement these four records:

- `ability.truant`
- `event_hook.ability.truant.onSwitchIn`
- `event_hook.ability.truant.onBeforeMove`
- `event_hook.ability.truant.onResidual`

Independently reclassify this record as unreachable in resolved Gen 3, after
the extractor/classifier proof is added:

- `condition.volatiles.truant`

The condition is inherited metadata from the modern ability. The Gen 3
override deletes `onStart` and never calls `addVolatile('truant')`; instead it
uses `Pokemon.truantTurn`. At the pinned revision the only runtime
`addVolatile('truant')` calls are in the overridden modern callbacks in
`data/abilities.ts`. Repository-wide source search finds no Gen 3 path which
creates the condition. This is an unreachable classification, not an inert or
implemented claim.

### Authoritative semantics

`data/mods/gen3/abilities.ts:197-213` is the defining override:

- `SwitchIn` initializes the phase to `battle.turn !== 0`;
- `BeforeMove` returns false on the loafing phase;
- priority-27 `Residual` toggles the phase.

The state belongs to the Pokemon, not a temporary volatile. Showdown declares
`truantTurn` on `Pokemon` (`sim/pokemon.ts`) and does not clear it in
`clearVolatile`; `SwitchIn` writes the new phase explicitly.

The important hidden dependency is Pursuit. Gen 3 Pursuit's
`beforeTurnCallback` declines to install interception when its user has
Truant and is currently loafing (`data/mods/gen3/moves.ts:477-483`). The
family therefore proves that pre-turn queue preparation reads the same
canonical cadence state as later `BeforeMove` and `Residual` dispatch. A
handler that merely cancels alternate ordinary move executions would be
semantically incomplete.

### Smallest honest native boundary

Add a bounded Pokemon-owned generated state cell, not a Truant-named field or
volatile in the generic kernel. The resolved plugin binds typed operations to
the cell:

- initialize a boolean from a generation policy at `SwitchIn`;
- reject a move when the boolean is true;
- toggle it at ordered residual;
- allow pre-turn policies such as Pursuit eligibility to query it.

The state cell needs an explicit lifetime and owner binding. It survives
ordinary volatile cleanup exactly as Showdown's Pokemon field does, while the
generated handlers decide when it is initialized and read. Bundle validation
must reject duplicate cells, invalid indices, wrong relay/event algebra, and
missing initialization before mutation or PRNG. No operation consumes PRNG.

Do not encode `if ability == Truant`, odd/even global turns, or a generic
"skip every other action" shortcut. Sleep, freeze, recharge, failed moves,
two-turn preparation, switching, ability replacement, and Pursuit setup all
make the semantic distinction observable.

### Focused/differential proof basis

At minimum prove:

- first-turn switch-in versus later-turn switch-in initialization;
- successful move, loaf, successful move;
- recharge turn recombination (the next turn may act);
- sleep/freeze immobilization while residual still toggles cadence;
- a failed or blocked selected move and the following cadence;
- switch-out/in reset;
- Skill Swap into and away from Truant without inventing `Start` semantics;
- Pursuit chosen on a loafing turn does not install/execute interception;
- exact `SwitchIn`, `BeforeMove`, and residual handler order and zero draws.

The upstream baseline is `test/sim/abilities/truant.js`; port its semantic
assertions, especially recharge and sleep interactions, rather than its test
implementation. Add the Gen 3 Pursuit recombination because that dependency
is defined in the Gen 3 move override rather than covered by the generic
Truant test file.

## 2. Canonical battle-time species overlay (Forecast)

### Exact records closed

- `ability.forecast`
- `event_hook.ability.forecast.onStart`
- `event_hook.ability.forecast.onWeatherChange`

### Authoritative semantics

Gen 3 inherits the ordinary Forecast callbacks while replacing only its flags
(`data/mods/gen3/abilities.ts:48-51`). The defining callbacks are
`data/abilities.ts:1425-1453`:

- `Start` immediately invokes its own `WeatherChange` event;
- `WeatherChange` selects base, Sunny, Rainy, or Snowy Castform from effective
  weather;
- it does nothing for a transformed holder or a non-Castform base species;
- it changes form only while active and only when the effective form differs.

The generated species catalog already contains all four Gen 3 Castform forms,
but current native battle identity is still read primarily from immutable
`PokemonSet.species_id`. `PokemonMutable` has effective types and temporary
moves/ability, but no canonical effective species identity. Forecast exposes
that missing boundary.

### Smallest honest native boundary

Add `effective_species_id` to mutable Pokemon state, initialized and restored
from the submitted base species on battle setup and switch cleanup. All
battle-time species observers must read it through one accessor. Generated
plugin data supplies a validated form-selection table:

```text
base species + effective weather class -> resolved species identity
```

The ordinary generated handler applies that table only when its predicates
hold (active, matching base species, not transformed). Applying a form updates
the coherent derived projection—species identity, types, relevant calculated
stats/weight—and emits the canonical state transition. The generic kernel
must not name Castform, Forecast, or Gen 3 weather IDs.

For Gen 3 all Castform forms share base stats, which makes this a deliberately
small first proof. The abstraction must nevertheless define stat
recalculation rather than rely on that coincidence, because later generation
plugins may provide forms whose data differs. Bundle validation must prove all
mapped identities exist in the same resolved bundle and reject cross-bundle
IDs before mutation or PRNG. Forecast consumes no PRNG.

### Focused/differential proof basis

Prove:

- clear weather -> Castform, sun -> Sunny, rain -> Rainy, hail -> Snowy;
- Start under already-active weather and WeatherChange after entry;
- replacement/removal of weather returns to the correct form;
- redundant weather notifications do not invent transitions;
- effective type changes affect STAB, weaknesses/immunities, and Weather Ball;
- switch cleanup/restoration and re-entry;
- Transform guard: a transformed holder does not form-change;
- Skill Swap/ability replacement and inactive holders;
- exact Start/WeatherChange ordering and zero draws;
- malformed or mixed-bundle form tables fail atomically.

Current upstream tests only exercise Forecast incidentally in
`test/sim/abilities/{primordialsea,desolateland}.js` and Weather Ball/Counter
tests. Native Gen 3 fixtures therefore need an explicit four-weather rotation
plus the interactions above.

## Why the other frontier families follow

### Transform follows Truant and Forecast

Transform closes `move.transform` and `event_hook.move.transform.onHit`, but
its Showdown boundary is a whole-Pokemon projection, not just copied types:
effective species, types, stored non-HP stats, current move identities and
temporary PP, boosts, Hidden Power profile, and ability are copied while HP,
status, item, level, and base identity remain owned by the user
(`sim/pokemon.ts:1271-1353`). Switching restores the base projection.

Forecast earns the effective-species/derived-data half of that representation;
the existing temporary move and ability machinery earns other pieces. Truant
must precede a full Transform claim because a legal target's copied Truant
ability has active cadence semantics. After both recommended families close,
Transform becomes the next high-uncertainty integration slice.

### Assist and Metronome are late closure families

Resolved Gen 3 Assist inherits the Gen 4 `onHit` candidate construction and
only changes flags (`data/mods/gen4/moves.ts`, `data/mods/gen3/moves.ts`). It
samples eligible moves from other party members. Metronome constructs and
sorts a generation-wide flag-selected candidate list before one uniform draw.
Both then use the existing called-move entry.

Their descriptor-wide correctness therefore depends on every legal candidate
being executable. Implementing candidate selection now would be useful
infrastructure, but classifying the moves implemented from a few forced draws
would overclaim. Close the remaining move families first, then use
Assist/Metronome as strong recombination and candidate-universe proofs.

### Beat Up remains an isolated high-cost slice

Beat Up closes six runtime records—`move.beatup`,
`condition.volatiles.beatup`, `move.beatup.onModifyMove`, and the condition's
two stat handlers, plus the related presentation rule only if the observable
contract includes its nickname protocol. It constructs hits from living,
status-free party members and substitutes each participant's species base
Attack against the target species' base Defense. This is high uncertainty,
but it does not unlock another remaining family and has a substantially larger
verification matrix than either recommended ability slice. Take it after the
shared mutable-identity boundary, not merely because it owns several records.

## Resulting dependency order

```text
Truant Pokemon-owned cadence state
    -> exact Pursuit/pre-turn recombination
    -> copied-ability behavior required by Transform

Forecast effective-species overlay
    -> coherent mutable species/type/stat projection
    -> Transform whole-Pokemon projection

remaining move families
    -> complete callable candidate universe
    -> Assist and Metronome closure/recombination
```

