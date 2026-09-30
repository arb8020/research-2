# Gen 3 `TryBoost` ability audit

Oracle: pinned Pokemon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, Gen 3 singles.

This document fixes the implementation boundary for Clear Body, White Smoke,
Hyper Cutter, and Keen Eye. It is an audit and implementation plan, not a
support claim.

## Effective pinned semantics

The four callbacks are defined in `data/abilities.ts`. The pinned
`data/mods/gen3/abilities.ts` does not override them, so the ordinary modded-Dex
inheritance supplies their Gen 3 behavior. The effective Gen 3 Keen Eye has no
`onModifyMove`; that later-generation property is removed along the older-mod
inheritance chain.

All four callbacks are ordinary target-scope `onTryBoost` handlers with no
explicit order, priority, or sub-order:

| Ability | Numeric ID | Relay mutation |
|---|---:|---|
| Clear Body | 29 | Delete every present negative delta. |
| Keen Eye | 51 | Delete a present negative accuracy delta. |
| Hyper Cutter | 52 | Delete a present negative Attack delta. |
| White Smoke | 73 | Delete every present negative delta. |

Before that mutation, each callback performs the same self-source check:

```text
if source exists and source == target: do nothing
otherwise: filter the boost table
```

Consequently, a missing source is filtered. It must not be normalized to
"self" or described as an external-source predicate. The existing
`GUARD_SOURCE_NOT_TARGET` opcode has the correct truth table: it admits a
missing source and a distinct Pokemon source, and rejects only an explicitly
self-sourced event.

This predicate is not interchangeable with Mist. Mist filters only when a
source exists and is distinct, in addition to its move/infiltration rule.

The abilities are marked `breakable`, but Gen 3 supplies no Mold Breaker-like
suppression mechanic. That flag creates no extra behavior in this slice.

## Native program boundary

`TryBoost` is correctly typed as a mutable `PokemonBoostTable` relay. Handler
programs mutate only the relay copy; canonical stages are mutated later by the
boost operation.

The existing `DROP_BOOST_STAT(stat)` opcode is not sufficient for production
bindings because it deletes a positive delta too. Add these generation-neutral
relay operations:

```text
DROP_NEGATIVE_BOOST_STAT(stat)
DROP_ALL_NEGATIVE_BOOSTS
```

They inspect presence and sign, clear only fields whose delta is negative, and
continue the program. `DROP_ALL_NEGATIVE_BOOSTS` is earned compression for the
single semantic operation shared by Clear Body and White Smoke; spelling it as
seven named-stat branches would enlarge the program without exposing more
meaning.

The generated programs are then:

```text
Clear Body:   GUARD_SOURCE_NOT_TARGET; DROP_ALL_NEGATIVE_BOOSTS
White Smoke: GUARD_SOURCE_NOT_TARGET; DROP_ALL_NEGATIVE_BOOSTS
Hyper Cutter: GUARD_SOURCE_NOT_TARGET; DROP_NEGATIVE_BOOST_STAT(ATK)
Keen Eye:     GUARD_SOURCE_NOT_TARGET; DROP_NEGATIVE_BOOST_STAT(ACCURACY)
```

Each descriptor and owner-index entry uses target scope and owner routing.
There is at most one installed ability on the target, so these bindings consume
no handler-order PRNG by themselves.

Supporting these handlers also requires routing move boosts through the whole
boost-table boundary. `Battle.boost` in `sim/battle.ts` copies the product,
runs `ChangeBoost` once, caps every field, runs `TryBoost` once, and only then
applies each surviving field. Calling the handlers once per move effect, or
retaining the current direct `apply_boost_effect` path, would give the wrong
denotation for multi-stat moves such as Tickle.

Showdown emits failure messages under additional `effect.secondaries` and
`effect.id` conditions. Those are reporting semantics, not relay-filtering
semantics. If protocol messages enter the native observable contract, model
them separately rather than complicating these relay operations.

## Required focused evidence

The native matrix must prove:

1. a distinct Pokemon source filters;
2. an explicitly equal source and target bypasses filtering;
3. a missing source filters;
4. positive, zero, absent, and unrelated fields survive;
5. Clear Body and White Smoke remove all negative fields in a mixed product;
6. Hyper Cutter removes Attack while preserving a negative Defense field;
7. Keen Eye removes accuracy while preserving another negative field;
8. each invocation records the expected owner, target scope, holder, and source;
9. a single untied ability handler consumes no ordering draw;
10. invalid stat arguments and capacity/configuration failures roll the battle
    back byte-for-byte.

The full move path must separately prove one `ChangeBoost` and one `TryBoost`
dispatch per product, cap-before-filter staging, partial multi-stat filtering,
and deterministic replay.

## Required differential evidence

Use legal Gen 3 holders such as Metagross (Clear Body), Torkoal (White Smoke),
Kingler (Hyper Cutter), and Skarmory (Keen Eye). At minimum retain cases for:

- Tickle x Hyper Cutter, preserving the Defense drop while filtering Attack;
- Flash x Keen Eye;
- Charm, Growl, or Tickle x Clear Body and White Smoke;
- a self-caused negative stage change, once that move family is supported, to
  prove the explicit self-source bypass; and
- unaffected and positive deltas for every holder.

Compare handler discovery/order, `ChangeBoost` and `TryBoost` boundaries,
per-stat effect traces, canonical stages, requests, final PRNG state, and replay.
Only after focused and differential evidence passes may the four abilities and
four hook-ownership records move from `unsupported` to `implemented`.
