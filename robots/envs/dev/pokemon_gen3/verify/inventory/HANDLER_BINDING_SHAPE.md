# Gen 3 OU handler binding shape

This audit accounts for the exact binding-index shape of the 514 frozen
callback-owner records. It is source accounting only: a binding's presence in
this file does not change its descriptor-map support classification.

Regenerate the machine-readable
[`handler-binding-shape.json`](handler-binding-shape.json) with:

```sh
node verify/inventory/generate-handler-binding-shape.js
```

The generator preserves the full hook path before normalizing event and scope.
This matters because `onHit`, `self.onHit`, `secondary.onHit`, and
`condition.onHit` are distinct bindings even though all dispatch event `Hit`.

## Exact totals

| Owner kind | Owners | Bindings | Maximum bindings on one owner |
|---|---:|---:|---:|
| Ability | 64 | 89 | 5 |
| Condition | 21 | 65 | 5 |
| Format | 2 | 2 | 1 |
| Item | 58 | 95 | 6 |
| Move | 118 | 263 | 6 |
| **Total** | **263** | **514** | **6** |

The two six-binding owners are item `whiteherb` and move `charge`. The JSON
lists every owner descriptor with its exact bindings and
`max_same_event_scope_span`, so a generator can size per-owner spans without
assuming one callback per event.

## Normalized discovery scope

| Scope | Bindings |
|---|---:|
| target | 459 |
| source | 13 |
| ally | 0 |
| foe | 7 |
| any | 13 |
| side | 10 |
| field | 12 |

Scope is normalized from the terminal callback name: `onSourceX`, `onAllyX`,
`onFoeX`, `onAnyX`, `onSideX`, and `onFieldX`; an unprefixed `onX` is target
scope. Zero ally bindings is a property of this frozen Gen 3 OU closure, not a
reason to omit ally scope from the generic event algebra.

The JSON also contains exact counts for all 69 normalized events. Event name
alone is not a binding key: the minimum lossless index identity is owner,
embedded path, normalized scope, and event.

## Duplicate event/scope bindings

Exactly two owners contain multiple bindings for the same normalized event and
scope:

- ability `flashfire`, target `End`: `onEnd` and `condition.onEnd`;
- move `batonpass`, target `Hit`: `onHit` and `self.onHit`.

Collapsing either pair by `(owner, event, scope)` would silently delete
semantics. The binding index therefore needs either the full hook-path identity
or a stable generated binding ordinal.

## Embedded programs

There are 146 embedded bindings:

- 143 under `condition`;
- 2 under `self` (`batonpass` and `rapidspin`);
- 1 under `secondary` (`triattack`).

Embedded conditions have their own holder/state lifetime even when their
source descriptor is a move or ability. Self and secondary programs execute at
different effect phases from the primary move callback. They must not be
flattened into the owner's direct hook span without retaining embedded effect
identity and phase.

## Native generation consequence

A compact generated index can use one contiguous span per owner descriptor,
with at most six bindings in the current frozen universe. Each binding still
needs:

- normalized event and discovery scope;
- full embedded-path/effect identity or stable ordinal;
- callback program ID;
- ordering metadata;
- holder/state ownership metadata.

The maximum of six is a frozen Gen 3 OU sizing fact, not a universal constant
for other generations or future inventory revisions. Generation must assert
the bound and fail if the source inventory exceeds it.
