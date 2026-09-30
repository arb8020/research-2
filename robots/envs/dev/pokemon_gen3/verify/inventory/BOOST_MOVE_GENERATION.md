# Gen 3 direct-boost move generation audit

Oracle: pinned Pokemon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, resolved with
`Dex.forGen(3)`.

This audit fixes the generated-data boundary for the direct-boost move family.
It is not by itself a support claim. A move may have a completely declarative
boost effect while its Protect, Magic Coat, Snatch, Substitute, or other flag
interaction remains unsupported.

## Representation

Showdown passes one sparse boost product through `ChangeBoost`, caps the whole
product, passes one copy through `TryBoost`, and only then mutates the remaining
fields (`sim/battle.ts:2650-2695`). The generated native representation must
therefore retain one product-valued operation:

```c
typedef struct {
    uint8_t present_mask;
    int8_t delta[POKEMON_STAT_COUNT];
} PokemonBoostTable;

typedef struct {
    PokemonEffectTarget target;
    PokemonBoostTable boosts;
} PokemonBoostEffect;
```

An equivalent contiguous operation span is acceptable only if the runtime
normalizes every unconditional primary `BOOST` operation in that span into one
`PokemonBoostTable` before either event is dispatched. Dispatching
`ChangeBoost` or `TryBoost` once per stat is observably wrong: Hyper Cutter can
remove Tickle's Attack field while retaining its Defense field.

The generator must preserve `accuracy: true` separately from numeric accuracy
100. An always-hit move consumes no `move.accuracy` draw; a numeric-100 move
does consume that draw in Gen 3. All moves below have priority zero and category
Status. `PP` is Showdown's base PP; the Ocean battle image may separately store
the existing maximum-PP value.

## Exact resolved descriptors

| Move | Num | Target | Accuracy | Sparse boost product | PP |
|---|---:|---|---:|---|---:|
| Acid Armor | 151 | self | true | Defense +2 | 40 |
| Agility | 97 | self | true | Speed +2 | 30 |
| Amnesia | 133 | self | true | Special Defense +2 | 20 |
| Barrier | 112 | self | true | Defense +2 | 30 |
| Bulk Up | 339 | self | true | Attack +1, Defense +1 | 20 |
| Calm Mind | 347 | self | true | Special Attack +1, Special Defense +1 | 20 |
| Charm | 204 | normal | 100 | Attack -2 | 20 |
| Cosmic Power | 322 | self | true | Defense +1, Special Defense +1 | 20 |
| Cotton Spore | 178 | normal | 85 | Speed -2 | 40 |
| Dragon Dance | 349 | self | true | Attack +1, Speed +1 | 20 |
| Fake Tears | 313 | normal | 100 | Special Defense -2 | 20 |
| Feather Dance | 297 | normal | 100 | Attack -2 | 15 |
| Flash | 148 | normal | 70 | Accuracy -1 | 20 |
| Growl | 45 | allAdjacentFoes | 100 | Attack -1 | 40 |
| Growth | 74 | self | true | Special Attack +1 | 40 |
| Harden | 106 | self | true | Defense +1 | 30 |
| Howl | 336 | self | true | Attack +1 | 40 |
| Iron Defense | 334 | self | true | Defense +2 | 15 |
| Kinesis | 134 | normal | 80 | Accuracy -1 | 15 |
| Leer | 43 | allAdjacentFoes | 100 | Defense -1 | 30 |
| Meditate | 96 | self | true | Attack +1 | 40 |
| Metal Sound | 319 | normal | 85 | Special Defense -2 | 40 |
| Sand Attack | 28 | normal | 100 | Accuracy -1 | 15 |
| Scary Face | 184 | normal | 90 | Speed -2 | 10 |
| Screech | 103 | normal | 85 | Defense -2 | 40 |
| Sharpen | 159 | self | true | Attack +1 | 30 |
| Smokescreen | 108 | normal | 100 | Accuracy -1 | 20 |
| String Shot | 81 | allAdjacentFoes | 95 | Speed -1 | 40 |
| Sweet Scent | 230 | allAdjacentFoes | 100 | Evasion -1 | 20 |
| Swords Dance | 14 | self | true | Attack +2 | 30 |
| Tail Glow | 294 | self | true | Special Attack +2 | 20 |
| Tail Whip | 39 | allAdjacentFoes | 100 | Defense -1 | 30 |
| Tickle | 321 | normal | 100 | Attack -1, Defense -1 | 20 |
| Withdraw | 110 | self | true | Defense +1 | 40 |

Bulk Up and Growl are existing regression anchors. The other 32 are the new
direct-boost descriptors. None of the 34 resolved descriptors has an effective
callback, self effect, secondary effect, volatile, side condition, weather,
healing, recoil, drain, forced switch, or custom damage operation.

## Descriptor-wide caveat

The absence of callbacks does not make these descriptors completely supported.
Their resolved flags participate in generic mechanics:

- targeted moves are Protect-affected, reflectable, and mirrorable;
- self-targeting moves are Snatch-affected;
- Growl, Metal Sound, and Screech are sound moves;
- Cotton Spore is a powder move;
- Tickle's Gen 3 override has `bypasssub`;
- Dragon Dance, Feather Dance, and Swords Dance carry the dance flag.

These facts should remain generated even before every consumer exists. Direct
boost execution can be classified independently, but descriptor-wide support
must remain conservative until each reachable flag interaction has focused and
differential evidence. In particular, Tickle must not be treated as an ordinary
Substitute-blocked status move.

For the bounded Gen 3 OU format, the sound flag has no remaining reachable
consumer for this family: pinned Gen 3 Substitute does not grant sound moves a
bypass, and the resolved format rule table bans `ability:soundproof`. Metal
Sound, Screech, and Growl therefore use ordinary Substitute interception; the
Soundproof interaction is excluded by format admission rather than silently
implemented by the battle kernel.

## Nine-case descriptor rotation

Use one fresh battle per row so accumulated stages never accidentally turn the
descriptor rotation into a cap test. Give the rotating Pokemon the listed four
move slots and use a Splash-only opponent. Execute each slot once, forcing
accuracy success only where the move has numeric accuracy below 100.

| Case | Four move slots |
|---|---|
| 1 | Acid Armor, Agility, Amnesia, Barrier |
| 2 | Bulk Up, Calm Mind, Cosmic Power, Dragon Dance |
| 3 | Growth, Harden, Howl, Iron Defense |
| 4 | Meditate, Sharpen, Swords Dance, Tail Glow |
| 5 | Withdraw, Charm, Cotton Spore, Fake Tears |
| 6 | Feather Dance, Flash, Kinesis, Metal Sound |
| 7 | Sand Attack, Scary Face, Screech, Smokescreen |
| 8 | String Shot, Sweet Scent, Tail Whip, Tickle |
| 9 | Growl, Leer |

For every action compare normalized choice, queued action, labeled accuracy
draw, ordered `ChangeBoost` and `TryBoost` boundaries, per-stat effect trace,
canonical stages, request, final seed, and replay. Self-targeting `accuracy:
true` rows must prove the absence of an accuracy draw. Numeric-100 rows must
prove the presence of the Gen 3 accuracy draw.

The rotation is necessary but not sufficient. Add focused recombinations for:

- Agility changing next-turn queue order, including tie-draw/no-draw edges;
- forced draws immediately below and at the hit threshold after Flash, Sand
  Attack, and Sweet Scent;
- Tickle against Hyper Cutter, proving partial product filtering;
- Flash against Keen Eye;
- Charm or Growl against both Clear Body and White Smoke;
- a positive self boost on every negative-filter ability holder;
- one whole-product cap and one partial cap;
- switch-out resetting all seven stages.

## Minimal verifier work

No protocol extension is needed if the existing boundary stream exposes
`ChangeBoost`, `TryBoost`, per-stat boost effects, state, and PRNG records. Add:

1. deterministic case generation for the nine rows and their team text;
2. case inventory and differential Makefile registration;
3. forced `move.accuracy` outcomes for numeric sub-100 moves;
4. assertions distinguishing always-hit/no-draw from numeric-100/one-draw;
5. the focused recombination artifacts above.

Reclassify the 32 new moves only after this rotation and the applicable flag
interactions pass. If classification is feature-granular, the direct-boost
semantic family may close earlier while descriptor-wide flag obligations stay
explicitly unsupported.
