# Gen 3 OU condition-path completeness audit

Pinned Pokemon Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

This is an inventory-completeness result, not a native support claim. The audit
does not promote any feature-map record.

## Result

Independent resolved-descriptor, source-AST, fixed-point condition, and generic
runtime scans agree. The Gen 3 OU condition domain contains:

- 6 statuses;
- 62 volatiles;
- 5 side conditions;
- 3 slot conditions;
- 4 weather conditions;
- 2 pseudo-weather conditions.

The checked artifacts contain 131 effective descriptor mutation calls, 7
direct deletes, 23 recursively reached `Condition` identities, and 95 generic
runtime source rows. All 16 computed condition arguments have finite reviewed
candidate domains. No unresolved or missing Gen 3 OU condition identity was
found.

An independent re-audit also freezes the complete lifecycle API-to-identity
argument map and requires the generic-runtime AST census and resolved-
descriptor extractor to recognize the same API set. This prevents a future
API addition or argument-index change from silently weakening only one half of
the completeness proof.

The audit covers declarative move condition fields, resolved move/ability/item/
condition/format callbacks, linked volatile arguments, direct storage deletes,
generic `sim/**/*.ts` mutations, expiry function references, recursive linked
condition creation/removal, and resolved generation scripts.

## Future move evidence

The previously omitted slot condition is now explicit:

- `data/mods/gen3/moves.ts:218-232`: Doom Desire calls
  `addSlotCondition(target, 'futuremove')`;
- effective `data/moves.ts:6388-6417`: Future Sight makes the same call;
- `data/conditions.ts:379-405`: `futuremove` owns start, residual, removal, and
  end behavior.

The inventory records `slot:futuremove`, its `onStart`, `onResidual`, and
`onEnd` handlers, both creator calls, residual removal, and Protect/Endure
cleanup. Existing differential cases cover the shared delayed-slot boundary;
the separate upstream Wish assertion at `test/sim/moves/wish.js:64` remains a
named regression-map gap.

## Audit-surface correction

The exhaustive runtime census previously scanned `sim/**/*.ts` but did not
independently scan the resolved generation `Scripts` bundle. Gen 3 inherits
`data/mods/gen4/scripts.ts:46-49` `actions.runSwitch`, which contains
`removeVolatile('substitutebroken')` behind `this.battle.gen === 4`. It is
unreachable in Gen 3 and adds no condition identity, but omission of that
surface weakened the completeness proof.

`test-generation-script-condition-surface.js` now scans the resolved scripts,
fails closed if their condition calls or deletes change, and verifies the
explicit Gen-4-only guard.

## Reviewed exclusions

The audit retains and adjudicates rather than silently filters:

- 17 payload-only writes that do not create or remove condition identity;
- 5 BattleStream debug mutation paths;
- later-generation, Z-Move, Dynamax, and multi-battle branches;
- 13 simulator-only conditions with no reachable Gen 3 OU creation edge:
  `arceus`, `commanded`, `commanding`, `deltastream`, `desolateland`,
  `dynamax`, `gem`, `healreplacement`, `primordialsea`, `silvally`,
  `snowscape`, `zacian`, and `zamazenta`.

The earlier `trapper`, `sleepclausemod`, and `freezeclausemod` corrections also
reproduce exactly from the pinned source.

## Completion rule

Condition inventory completeness establishes only that the authoritative
semantic identities and mutation paths are represented. A condition becomes a
supported feature only after its native boundary, focused test, differential
evidence, source mapping, and pinned revision all exist.
