# Gen 3 direct-boost family plan

Oracle: pinned Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, Gen 3 singles.

This is the recommended first semantic family after complete D1--D3 handler
discovery. It is a bounded implementation plan, not a support claim. No entry
listed here should move out of `unsupported` until the focused, rotation, and
differential evidence below exists.

## Why this family is next

The frozen inventory contains 34 reachable moves whose only non-core move
property is a declarative `boosts` table. `Bulk Up` and `Growl` already have
native evidence. The same general pipeline can therefore close exactly 32
currently unsupported move descriptors without introducing a named-move
resolver:

```text
Acid Armor, Agility, Amnesia, Barrier, Calm Mind, Charm, Cosmic Power,
Cotton Spore, Dragon Dance, Fake Tears, Feather Dance, Flash, Growth,
Harden, Howl, Iron Defense, Kinesis, Leer, Meditate, Metal Sound,
Sand Attack, Scary Face, Screech, Sharpen, Smokescreen, String Shot,
Sweet Scent, Swords Dance, Tail Glow, Tail Whip, Tickle, Withdraw
```

All of their target modes (`self`, `normal`, and `allAdjacentFoes`) are already
supported by the singles target algebra. Together they exercise every Gen 3
stat-stage consumer: Attack, Defense, Special Attack, Special Defense, Speed,
accuracy, and evasion.

The inventory also contains exactly five `TryBoost` ownership records:

| Owner | Frozen hooks relevant to this slice | Meaning |
|---|---:|---|
| Clear Body | `onTryBoost` | Unless the source exists and is the target, remove every negative delta. |
| White Smoke | `onTryBoost` | Same semantic operation as Clear Body. |
| Hyper Cutter | `onTryBoost` | Unless explicitly self-sourced, remove only a negative Attack delta. |
| Keen Eye | `onTryBoost` | Unless explicitly self-sourced, remove only a negative accuracy delta. |
| Mist condition | `condition.onTryBoost` | Remove externally sourced negative deltas while the side condition is live. |

The four abilities have no other effective frozen Gen 3 hook. Once their
generated descriptors, programs, focused cases, and rotated differential cases
pass, this slice can close four ability descriptors and four hook-ownership
records. Mist was intentionally deferred from this original boost slice
because it also required side-condition duration and removal semantics; it is
now implemented and classified by the later side-condition slice documented
in `SEMANTIC_SPIKE_REVIEW.md`.

The measurable closure is therefore 32 moves + 4 abilities + 4 hook records =
40 reachable obligations. With the current map this would reduce `unsupported`
from 1,106 to 1,066, subject to the evidence rule.

## Correct Showdown semantic boundary

`Battle.boost` in `sim/battle.ts:2650-2695` owns the operation:

1. reject a missing, fainted, or inactive target;
2. run `ChangeBoost` over a copied sparse boost table;
3. cap every requested delta against the target's current stage;
4. run `TryBoost` over another copied boost table;
5. apply every remaining stat independently;
6. report success if at least one stat changed.

`Pokemon.getCappedBoost` and `Pokemon.boostBy` in
`sim/pokemon.ts:1212-1232` define the `[-6, 6]` cap and actual mutation.
Ability filtering is in `data/abilities.ts` under `clearbody`, `hypercutter`,
`keeneye`, and `whitesmoke`. The effective Gen 3 `Keen Eye` descriptor has only
`onTryBoost`; its later-generation `onModifyMove` property resolves to
`undefined` in the pinned Gen 3 dex.

### Inventory contract correction

`event-vocabulary.json` currently classifies `TryBoost` as a
`boolean-or-null-gate`. That is not its denotation. Showdown passes a mutable
sparse boost table as the relay value, and these handlers delete selected keys
in place. This is observable for a multi-stat move: Hyper Cutter filters the
Attack drop from Tickle while allowing its Defense drop.

The event algebra must represent `TryBoost` as a mutable boost-table relay (or
an equivalent typed value/result pair), not as a Boolean gate. The generated
program operations should be semantic and reusable, for example:

```text
DROP_NEGATIVE_BOOSTS_IF_EXTERNAL
DROP_NEGATIVE_STAT_IF_EXTERNAL(ATK)
DROP_NEGATIVE_STAT_IF_EXTERNAL(ACCURACY)
```

For these four abilities, filtering is bypassed only when a source exists and
`source == target`. A missing source is not a self-source and is therefore
filtered. This is deliberately different from Mist, whose callback requires a
present, distinct source before it filters.
Programs must modify the event's boost-table value; they must not mutate the
target's canonical stages during handler execution.

The hook-derived vocabulary also omits `ChangeBoost`, because the effective
Gen 3 inventory owns zero callbacks for it. The runtime nevertheless calls the
event at this semantic boundary. A complete event vocabulary must include
runtime call-site events with zero handlers, so `ChangeBoost` needs a typed
pass-through event specification. Deriving vocabulary only from owned
callbacks is insufficient.

## Native representation

Use a fixed-size `PokemonBoostTable` product with one signed delta and one
presence bit for each stage-bearing stat. The boost operation should receive
the whole product, dispatch `ChangeBoost` and `TryBoost` once each, cap once,
then apply fields in canonical stat order. Calling `TryBoost` separately for
each existing `PokemonEffectOp` would be wrong because handlers may partially
filter a multi-stat product.

Move data remains declarative: a move points at one or more boost-delta records
and a target. Ability bindings point at generic filter programs. No generic
kernel branch should mention a Gen 3 move or ability ID.

Generation policy must supply the stage arithmetic that differs across
generations. The generic kernel owns where stages are consumed:

- Attack/Defense and Special Attack/Special Defense in damage calculation;
- Speed when constructing each turn's ordered action queue; and
- accuracy/evasion during move-hit accuracy resolution.

The current native kernel applies the four damage stages but queues raw stored
Speed and compares an accuracy draw against raw move accuracy. Merely adding
the 32 generated move rows would therefore be dishonest.

For Gen 3, `data/mods/gen3/scripts.ts:337-383` defines the accuracy/evasion
table as `[1, 4/3, 5/3, 2, 7/3, 8/3, 3]`. It applies the attacker's accuracy
stage and target's evasion stage before `ModifyAccuracy`, `alwaysHit`, and
`Accuracy`, preserving Showdown's truncation and PRNG staging. Speed must be
resolved before action sorting through the generation's stat-stage policy;
later modifier hooks can extend that same boundary.

## Focused proof

The focused native matrix should include:

1. positive and negative single-stat changes at 0, near a cap, and at a cap;
2. a multi-stat move where both fields apply and one where one field is capped;
3. source-equals-target bypass for each external-negative filter operation;
4. Clear Body and White Smoke removing every negative field while preserving
   positive fields in the same product;
5. Hyper Cutter filtering Attack but allowing Tickle's Defense drop;
6. Keen Eye filtering accuracy but not another negative stat;
7. Mist filtering external negative products, preserving self-sourced drops,
   refusing duplicate installation without refreshing, and expiring exactly;
8. Speed boosts changing next-turn action order and the exact tie-draw/no-draw
   boundary;
9. accuracy and evasion stages changing the hit threshold with exact labeled
   accuracy draws, including an always-hit move consuming no accuracy draw;
10. switch-out resetting stages and deterministic replay producing identical
    state, trace, and final seed;
11. event capacity/configuration failure rolling the battle back byte-for-byte;
12. a three-handler synthetic mutable-relay case proving discovery order,
    partial filtering, and preservation of the input product.

Every focused event test should also assert owner kind, scope, holder,
source/target references, handler order, and that ordinary untied handlers
consume no handler-order draw.

## Differential proof

Generate a deterministic rotation that executes all 34 structurally pure
boost-table moves, including the already supported Bulk Up and Growl as
regression anchors. For each move compare:

- normalized choices and queued action;
- accuracy decision and labeled PRNG consumption;
- ordered `ChangeBoost` and `TryBoost` boundaries;
- per-stat before/delta/after effect trace;
- resulting canonical stages and request; and
- replay state and final seed.

Rotate all four abilities against affected and unaffected deltas. Required
recombinations are at least:

- Tickle × Hyper Cutter for partial filtering;
- Flash × Keen Eye;
- Charm or Growl × Clear Body and White Smoke;
- a positive self boost on each ability holder, proving the external-negative
  predicate does not over-filter;
- Agility × next-turn queue ordering; and
- Flash/Sand Attack/Sweet Scent × subsequent hit/miss thresholds.

Use forced seeds on both sides of every accuracy threshold and preserve the
first divergent semantic boundary as a minimized regression artifact. Only
after this matrix passes may the 32 move entries, four ability entries, and
four hook entries be reclassified as implemented.
