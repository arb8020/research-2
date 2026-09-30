# Independent Gen 3 condition-path completeness audit

Oracle: Pokemon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

This is a read-only independent check of the condition extractor and frozen
inventory. It changes no support classification or native implementation.

## Result

The current extractor/frozen inventory has no remaining concrete condition-ID
omission. An independent execution of
`verify/inventory/gen3-condition-completeness-audit.js` against the clean pinned
checkout produced byte-identical output to
`verify/inventory/gen3-condition-completeness-audit.json`:

```text
0912a9415aeb2bfecc5083ef751dec9d82168b59afa43d078d6535980291f598
```

The result has zero unresolved expressions and exact frozen-domain equality:
6 statuses, 62 volatiles, 5 side conditions, 3 slot conditions, 4 weather
conditions, and 2 pseudo-weather conditions.

## Exact omissions corrected by the current extractor/inventory

- Slot condition `futuremove`: effective Gen 3 Future Sight and inherited Doom
  Desire each call `addSlotCondition(target, 'futuremove')`; the reached
  `futuremove` Condition calls `removeSlotCondition(..., 'futuremove')`.
- Linked volatile `trapper`: Block, Mean Look, and Spider Web call
  `addVolatile('trapped', source, move, 'trapper')`; generic
  `Pokemon#addVolatile` creates the linked source volatile.
- Pseudo-weather `sleepclausemod` and `freezeclausemod`: the Battle constructor
  installs resolved rules having runtime event handlers through
  `field.addPseudoWeather(rule)`. Both rules own reachable `onSetStatus`
  callbacks in Gen 3 OU.
- Volatile `minimize`: legal Metronome delegation reaches its effective move
  descriptor and condition.

These are denominator corrections only, not native-support claims.

## Complete reached descriptor/Condition mutation census

The audit reaches 354 moves, 70 abilities, 104 items, and 23 global Condition
objects. It finds 131 lifecycle API calls:

| API | Calls |
| --- | ---: |
| `addVolatile` | 41 |
| `removeVolatile` | 48 |
| `addSideCondition` | 0 |
| `removeSideCondition` | 5 |
| `addSlotCondition` | 2 |
| `removeSlotCondition` | 1 |
| `setWeather` | 1 |
| `clearWeather` | 0 |
| `addPseudoWeather` | 0 |
| `removePseudoWeather` | 0 |
| `setStatus` | 1 |
| `forceStatus` | 0 |
| `trySetStatus` | 7 |
| `cureStatus` | 22 |
| `clearStatus` | 3 |

The zero descriptor counts are not missing generic paths. Declarative
application and owner-level creation/removal live in generic simulator code;
they are separately enumerated by `runtime-condition-paths.json`.

Seven reached direct deletion paths are also accounted for: Substitute deletes
`partiallytrapped`; Rollout deletes `rollout`; Torment deletes `torment`; Ice
Ball deletes `iceball`; Uproar deletes `uproar`; the `partiallytrapped`
Condition deletes `partiallytrapped`; and `lockedmove` deletes `lockedmove`.

## Generic runtime surface

The pinned TypeScript AST census records 97 exact source rows: 33 lifecycle API
calls, 8 non-invocation API references, 41 assignments, and 15 deletes. The
reviewed ledger classifies 71 lifecycle-owning paths, 21 nested-payload or
declarative-field references, and 5 BattleStream debug-only paths. It covers
the generic declarative status/volatile/side/slot/weather/pseudo-weather
application paths, RuleTable pseudo-weather installation, status commit and
rollback, linked volatile creation/removal, callback-bound expiry, container
ownership, direct writes/deletes, and unreachable later-generation/debug
branches.

## Validation

Executed from `robots/envs/dev/pokemon_gen3` with
`POKEMON_SHOWDOWN_DIR=/private/tmp/pokemon-lockon-clean` where applicable:

- `node verify/inventory/gen3-condition-completeness-audit.js ...` — byte-identical artifact
- `node verify/inventory/test-condition-completeness.js` — pass
- `node verify/inventory/test-condition-extractor.js` — pass
- `node verify/inventory/condition-extractor.test.js` — pass
- `node verify/inventory/test-condition-integration.js` — pass
- `node verify/inventory/test-runtime-condition-paths.js` — pass, 97 source rows / 28 semantic paths
- `node verify/inventory/test-runtime-condition-review.js` — pass

No extractor patch was warranted: no isolated omission remains, and changing
the extractor would add churn without changing its denotation.

## Independent rerun, 2026-09-28

A second read-only audit independently reproduced the same condition domains
and mutation surface at pinned revision
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`: 6 statuses, 62 volatiles, 5 side
conditions, 3 slot conditions, 4 weather conditions, 2 pseudo-weather
conditions, 131 descriptor/Condition lifecycle calls, 7 direct deletions, and
97 generic runtime AST rows. It found zero unresolved expressions, missing
identities, false identities, or stale runtime-ledger rows.

In particular, both Gen 3 Doom Desire and inherited Future Sight reach
`addSlotCondition(target, 'futuremove')`; linked trapping reaches `trapper` via
the third `addVolatile` argument; and Battle construction installs the resolved
Sleep Clause and Freeze Clause callbacks as pseudo-weather. Dynamic two-turn
IDs, Rapid Spin's side-condition loop, condition-owned cleanup, and status
cures were included in the fixed-point traversal.

The composed verifier's final whole-file freshness comparison was temporarily
different only because concurrent native-ID generation changed six
`native_id_present` booleans. Every condition-specific assertion passed. This
rerun therefore warrants no inventory or support-classification change; rerun
the composed check after the current native-ID generation settles.
