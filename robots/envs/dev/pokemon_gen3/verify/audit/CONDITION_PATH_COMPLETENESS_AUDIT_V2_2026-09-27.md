# Gen 3 OU condition-path completeness audit (v2)

Pinned Pokemon Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

This is an independent, read-only completeness audit. It does not change any
support classification. The audit used a separate clean checkout at
`/private/tmp/pokemon-showdown-condition-v2` and compared fresh results to the
currently checked inventory and condition-path artifacts.

## Conclusion

No reachable Gen 3 OU condition identity or lifecycle path was omitted by the
current frozen inventory/extractor. In particular, `futuremove` is present as
a slot condition and both its creation and removal are mechanically captured.

A fresh effective-descriptor traversal was byte-identical to
`verify/inventory/gen3-condition-completeness-audit.json`:

```text
0912a9415aeb2bfecc5083ef751dec9d82168b59afa43d078d6535980291f598
```

A fresh generic-runtime AST census was byte-identical to
`verify/inventory/runtime-condition-paths.json`:

```text
98ab7e5ba43029c8dad900c3135e808db82d7d033edeec22cca8bb8b0ac336a2
```

The current frozen inventory used for the comparison had SHA-256:

```text
ab40867fb988b88b8646dac3ebf50edd02bc17af19439408f2c7dc0d62d6e4de
```

That was the inventory digest at audit time. The later callback-provenance
freeze changed only `callback_hooks[].showdown_source`; its frozen digest is
`750cf157997651d1b2e0e891af99c25f83607530c4193331ade5d4a901edbbf4`.

## Exact descriptor-level census

The traversal starts from the resolved `gen3ou` Dex and legal set validation,
adds Metronome-reachable moves and Struggle, then repeatedly scans every newly
discovered Condition object until the identity set stops changing.

| Reachable owner class | Count |
| --- | ---: |
| effective moves | 354 |
| effective abilities | 70 |
| effective items | 104 |
| discovered Condition objects scanned | 23 |

It found 131 lifecycle API calls and seven direct condition-container deletes:

| API | Calls |
| --- | ---: |
| `addSlotCondition` | 2 |
| `addVolatile` | 41 |
| `clearStatus` | 3 |
| `cureStatus` | 22 |
| `removeSideCondition` | 5 |
| `removeSlotCondition` | 1 |
| `removeVolatile` | 48 |
| `setStatus` | 1 |
| `setWeather` | 1 |
| `trySetStatus` | 7 |
| **Total** | **131** |

The extractor also consumes declarative `status`, `forceStatus`,
`volatileStatus`, `sideCondition`, `slotCondition`, `weather`, and
`pseudoWeather` descriptor fields. Therefore the absence of an imperative API
from the table does not mean its condition domain is absent.

All 16 non-literal identity positions are resolved by an explicit reviewed
domain: Effect Spore, Synchronize, Tri Attack; eight two-turn move removals;
three Rapid Spin side-condition removals; and the `twoturnmove` condition's
dynamic add/remove paths. There are zero unresolved dynamic identities.

The fixed point exactly equals the frozen inventory in every domain:

| Domain | Count | Missing | Extra |
| --- | ---: | ---: | ---: |
| status | 6 | 0 | 0 |
| volatile | 62 | 0 | 0 |
| side condition | 5 | 0 | 0 |
| slot condition | 3 | 0 | 0 |
| weather | 4 | 0 | 0 |
| pseudo-weather | 2 | 0 | 0 |

The seven direct deletes are the reachable descriptor callbacks for
`partiallytrapped`, `rollout`, `torment`, `iceball`, `uproar`, and the
`partiallytrapped` and `lockedmove` Conditions removing their own identities.

## `futuremove` proof

The extractor reads slot-condition identity from argument 1, not the target in
argument 0. It captured these exact effective callbacks:

| Owner and hook | Mutation |
| --- | --- |
| `move:futuresight.onTry` | `addSlotCondition(target, "futuremove")` |
| `move:doomdesire.onTry` | `addSlotCondition(target, "futuremove")` |
| `condition:futuremove.onResidual` | `removeSlotCondition(..., "futuremove")` |

It also follows the discovered `futuremove` Condition and captures its `onEnd`
cleanup of Protect and Endure. `futuremove` is one of the three exact frozen
slot identities, alongside `followme` and `wish`.

## Generic-runtime and indirect-path census

An independent TypeScript-AST scan of every pinned `sim/**/*.ts` file found 97
source rows and 28 reviewed semantic paths:

| Source-row kind | Count |
| --- | ---: |
| lifecycle API call | 33 |
| direct assignment | 41 |
| direct delete | 15 |
| stored method reference | 8 |
| **Total** | **97** |

The review classifies 71 rows as lifecycle-owning, 21 as payload-only, and five
as BattleStream debug/test-only. By Gen 3 OU reachability, 41 rows are generic
runtime paths, 21 are later-generation or descriptor-unreachable paths, two
are unreachable topology paths, seven initialize storage, two construct
descriptors, 19 mutate payload rather than identity, and five are debug-only.

This catches lifecycle operations not visible as literal descriptor calls,
including generic descriptor-field dispatch, transaction rollback after a
rejected Start event, linked volatile construction/removal, condition copying,
bulk clearing, duration/event-driven removal, RuleTable pseudo-weather
installation, and the stored `side.removeSlotCondition` end callback.

For slot conditions specifically, the runtime scan records the reachable
generic `moveData.slotCondition` creation path and stored removal callback.
Later-generation `healreplacement`/`revivalblessing` callsites remain present
in the source ledger and are explicitly marked unreachable rather than being
silently filtered.

## Extractor assessment and proposed tests

There is no current extractor omission to repair. The important defense is to
keep both independent obligations fail-closed: the effective-descriptor
identity traversal and the whole-simulator lifecycle census.

The existing tests already verify a computed slot identity and computed slot
removal are rejected as unresolved, and that a computed linked-volatile
identity is rejected. Add these mutation cases if further defense is wanted:

1. Replace one literal `futuremove` argument with a computed expression and
   require the effective-descriptor audit to report exactly one unresolved
   identity rather than silently dropping it.
2. Add an alias/stored reference to any lifecycle method and require the
   runtime source-ledger freshness check to fail.
3. Add a direct identity assignment or delete in an effective callback and
   require the AST integration multiset comparison to fail.
4. Remove the RuleTable pseudo-weather installation row and require runtime
   semantic-path validation to fail.
5. Add a new lifecycle method name in `sim/` and require a vocabulary/source
   review before accepting a new pinned revision.

The final item remains the unavoidable revision boundary: both independent
scanners use an explicit lifecycle vocabulary. Completeness is proven for this
pinned revision because every simulator source mutation and method reference
was separately censused and reviewed; a new Showdown revision requires a new
audit.

## Commands reproduced

```sh
node verify/inventory/gen3-condition-completeness-audit.js \
  /private/tmp/pokemon-showdown-condition-v2
node verify/inventory/build-runtime-condition-paths.js \
  /private/tmp/pokemon-showdown-condition-v2 /private/tmp/condition-v2-runtime.json
POKEMON_SHOWDOWN_DIR=/private/tmp/pokemon-showdown-condition-v2 \
  node verify/inventory/test-condition-completeness.js
```

The extractor contract, fail-closed runtime review, 97-row/28-path freshness
check, and generation-script condition-surface test all passed. The aggregate
test then reached an unrelated concurrent edit in `generate.js` and stopped at
`hookSource`: `ReferenceError: assert is not defined`. The two fresh audit
artifacts and exact comparisons above completed before that failure; rerun the
aggregate gate after the generator edit imports `assert`.
