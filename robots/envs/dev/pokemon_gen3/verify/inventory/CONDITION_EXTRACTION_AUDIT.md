# Gen 3 OU condition-extraction completeness audit

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

This is an independent audit of every condition-creation/removal surface in
the pinned simulator. It corrects the inventory denominator; it does not make
new native support claims.

## Confirmed omissions and corrections

- `futuremove` is a reachable slot condition. Effective Future Sight and Doom
  Desire both call `addSlotCondition(target, 'futuremove')`.
- `trapper` is a reachable volatile, not a simulator-only identity. Block,
  Mean Look, and Spider Web establish `trapped` with linked status `trapper`;
  `Pokemon.addVolatile` creates the linked source state.
- `sleepclausemod` and `freezeclausemod` are runtime pseudo-weather owned by
  the field. `Battle` installs resolved rules with runtime event handlers, and
  both rules own `onSetStatus`. Direct construction of pinned `gen3ou`
  produces both keys in `field.pseudoWeather` before players or turns exist.
- Consequently, `format:sleepclausemod:onSetStatus` and
  `format:freezeclausemod:onSetStatus` are live callback hooks.

The corrected frozen counts are 62 volatiles, two pseudo-weather conditions,
three slot conditions, 514 callback hooks, 13 simulator-only conditions, and
1,560 total inventory records. The additional volatile is `minimize`, reached
through legal Metronome delegation.

## Mutation census

Across 354 runtime-reachable moves, 70 legal abilities, and 104 legal items,
effective descriptors contribute 113 condition API calls. Reachable
Condition-table callbacks contribute another 18, for 131 total: 41
`addVolatile`, 48 `removeVolatile`, two `addSlotCondition`, one
`removeSlotCondition`, five `removeSideCondition`, one `setWeather`, one
`setStatus`, seven `trySetStatus`, 22 `cureStatus`, and three `clearStatus`.

Reachable Condition-table callbacks add 18 lifecycle API calls, including
`lockedmove -> confusion`, dynamic two-turn move state, Future Sight removal,
Protect/Endure removal, recharge/truant cleanup, nightmare cleanup, and
sleep/freeze cure paths. Direct state deletes also exist and must be audited:
Ice Ball, Rollout, Substitute, Torment, Uproar, `lockedmove`, and
`partiallytrapped`.

The independent balanced-call/fixed-point audit is preserved in
`verify/inventory/gen3-condition-completeness-audit.js`; its complete callsite
artifact is `gen3-condition-completeness-audit.json` (SHA-256
`0912a9415aeb2bfecc5083ef751dec9d82168b59afa43d078d6535980291f598`).
It found 131 reachable descriptor/Condition mutation calls, seven direct
deletes, 23 reached global Conditions, zero unresolved dynamic expressions,
and exact frozen-domain equality: 6 statuses, 62 volatiles, 5 side conditions,
3 slot conditions, 4 weather conditions, and 2 pseudo-weather conditions.
No further concrete condition ID omission was found.

This independently proves the current denominator. The production generator
now uses a separate importable balanced-call scanner, per-API ID argument
positions, fixed-point Condition traversal, runtime-format scanning, and
direct-delete accounting. It fails closed on unknown dynamic condition IDs,
unknown dynamic deletions, missing arguments, kind mismatches, and stale
manual resolutions. Synthetic scanner tests and this independent audit are
both required. The producer uses the small balanced-text scanner, while the
integration check re-parses every effective callback with the pinned
TypeScript AST and requires the exact owner, hook, API, and argument multiset
to agree. A bug in the producer's parser therefore cannot certify itself.
The traversal covers every function nested in each effective descriptor, not
only `on*` event callbacks; this keeps setup callbacks such as
`beforeTurnCallback`, formula callbacks such as `basePowerCallback`, and
nested payload callbacks such as `fling.effect` inside the proof surface.

## Enforced extractor proof obligations

The generator must fail closed for:

- slot-condition IDs in the second argument;
- linked-status IDs in the fourth argument;
- nested/balanced call expressions rather than unbounded regex matches;
- dynamic IDs in every ID-bearing condition API;
- fixed-point traversal through newly discovered Condition objects;
- pseudo-weather created from the resolved RuleTable;
- direct delete/removal paths;
- stale manual resolutions at the correct argument position.

Exact-result tests must assert reachable `trapper`, pseudo-weather
`{freezeclausemod, sleepclausemod}`, and the two format-owned `onSetStatus`
hooks. Classification may change only after source mapping, native boundary,
focused test, and differential evidence all exist.

## Source boundaries

- `sim/battle-actions.ts`: declarative status, volatile, side, slot, weather,
  and pseudo-weather application.
- `sim/battle.ts`: resolved RuleTable pseudo-weather installation and residual
  lifecycle.
- `sim/pokemon.ts`: linked volatile creation/removal.
- `sim/side.ts` and `sim/field.ts`: side, slot, weather, and pseudo-weather
  state ownership.
- `data/rulesets.ts`: Sleep Clause Mod and Freeze Clause Mod handlers.
- `data/mods/gen3/moves.ts` plus inherited move data: Future Sight, Doom
  Desire, and Gen 3 condition overrides.

## Generic-runtime source census

The effective-descriptor fixed point above is only one proof obligation. It
cannot prove that every generic simulator path which owns condition storage
was reviewed. `runtime-condition-source-audit.js` therefore parses every
pinned `sim/**/*.ts` file with the pinned TypeScript parser. It records every
condition-API call, plus direct status/weather and condition-container
writes/deletes across every `sim/**/*.ts` file.

The reviewed `runtime-condition-paths.json` v2 ledger contains 97 exact source
rows: 33 API calls, eight non-invocation API references, 41 assignments, and
15 deletes. They are separated into 71 lifecycle-owning paths, 21 nested
payload-only mutations or declarative-field references, and five
BattleStream debug/test-only calls. Every row carries a Gen 3 OU disposition
and evidence. `build-runtime-condition-paths.js` will not bless a newly found
row: unknown, stale, or unreviewed identities fail regeneration and the test.

The non-invocation reference census closes callback and alias indirection. It
records lifecycle methods stored as event-handler `end` callbacks (for
example, `end: pokemon.removeVolatile`) and retains same-named declarative
fields such as `moveData.forceStatus` as reviewed payload-only references.

This census exposed omissions in the former 27-row semantic manifest. Missing
generic paths included move-owned volatile setup/teardown, dynamic Brick Break
condition removal, declarative condition application, copy/clear transactions,
status commit/rollback, owner-store creation/removal, later-generation action
paths, and debug commands with arbitrary computed IDs. The old manifest was a
useful lifecycle summary, but not an exhaustive source census.

False positives are retained and classified rather than silently filtered:
nested writes such as Substitute HP, Bide damage, linked-volatile metadata,
duration/source payloads, and `BasicEffect` descriptor construction do not
create or remove battle condition identities;
BattleStream commands are debug-only; empty constructor stores do not create
concrete identities; Gen 1, Z-Move, Dynamax, Revival Blessing, and multi-battle
branches are unreachable in Gen 3 OU. Keeping these rows makes the exclusion
auditable.

`test-condition-integration.js` now asserts both effective Future Sight and
Doom Desire literal `addSlotCondition(target, "futuremove")` calls and audits
every computed effective-descriptor ID against a nonempty, disposition-tagged
candidate domain. `test-runtime-condition-review.js` proves that unknown,
stale, and unreviewed generic-runtime rows fail closed.

An independent rerun against the pinned revision produced a byte-identical
audit artifact with SHA-256
`0912a9415aeb2bfecc5083ef751dec9d82168b59afa43d078d6535980291f598`.
No condition identity was missing or extra. Four additional mutation tests are
useful defense in depth: reject a computed `removeSlotCondition` ID at argument
1; reject a computed linked-status ID passed to `addVolatile` at argument 3;
reject an effective callback that directly assigns a condition identity; and
make removal or mutation of the RuleTable pseudo-weather installation row fail
the runtime-ledger freshness check.

The direct-write census deliberately scans every simulator source file rather
than trusting a fixed list of state owners. This closes a fail-open boundary:
a direct mutation moved into a new runtime file now becomes an unknown ledger
row. The two currently discovered non-owner writes are the `status` and
`weather` descriptor fields copied by `sim/dex-data.ts`; both remain in the
ledger as reviewed payload-only construction.

No checked-in audit artifact is disposable. Temporary files created during
this re-audit, if present, are exactly:

- `/tmp/all-condition-api-calls.txt`
- `/tmp/runtime-condition-census.json`
- `/tmp/runtime-condition-paths.corrected.json`

They are scratch output only; cleanup should target those exact paths rather
than any repository directory or wildcard.
