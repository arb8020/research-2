# Independent audit of the Gen 3 OU upstream regression map

Pinned Pokemon Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

This is an independent review of the regression map, not a support claim and
not a replacement for the canonical machine-readable artifact at
`verify/upstream-tests/gen3ou-unified-regression-map.json`. No feature-map or
descriptor classification follows from this audit.

## Result

The checked-in map has complete **static-declaration coverage** of the pinned
`test/sim` tree, and the independent runtime-registration census now makes the
previously implicit loop expansion explicit:

- 1,976 static `it()` / `test()` declarations are present exactly once;
- all 31 declarations which independently mention or select Gen 3 are mapped;
- 264 static records are adjudicated applicable to the Gen 3 OU native
  contract;
- 64 applicable static assertions have assertion-specific evidence;
- 36 have related but non-assertion-specific evidence and remain partial;
- 200 applicable static records still name a required focused or differential
  case;
- five dynamically expanded Gen 3 Random Battle generator checks are recorded
  separately as admission evidence.
- pinned Mocha registers 2,172 `test/sim` cases: 2,129 active and 43 pending;
- nine files account for 196 expansions beyond the 1,976 syntax declarations;
- 41 Gen 3 OU-applicable runtime variants are recorded for 11 loop-defined
  declarations, exposing 30 cases previously compressed away.

The following independent checks passed against the pinned checkout:

```text
validate-unified-regression-map.js:
  1976 static declarations + 5 dynamic Random Battle admission records

validate-all-test-census.js:
  1053 canonical + 923 overlay-adjudicated = 1976; no omissions

validate-semantic-map.js --require-complete:
  1053 declarations; 0 unresolved semantic adjudications
```

The runtime-expanded companion map contains 294 applicable registrations, 70
with assertion-specific evidence and 226 which still require an exact case.
The difference from the static map is expected: loop-defined tests register
multiple descriptor variants.

The map therefore satisfies the requested per-declaration fields: pinned
source/test identity, mechanics, semantic boundaries, four distinct evidence
categories, case need, and an evidenced terminal reason for excluded tests.
Consumers should use the JSON, not infer completeness from narrative totals.
The unified JSON reports both `assertion_specific_total: 66` and
`applicable_assertion_specific: 64`. The difference is two source-mapped but
Gen-3-inapplicable assertions (`snatch.js:95` and `stockpile.js:13`) whose
evidence proves why the modern assertion differs.

## Important qualification: declarations are not runtime expansions

The declaration census still counts syntax nodes, but
`runtime-registration-census.json` and its validator now reproduce the Mocha
registration totals and enumerate the Gen 3 OU-applicable loop variants. A
variant cannot be closed by a sibling descriptor unless an explicit generated-
descriptor equivalence proof is recorded.

Applicable Gen 3 examples:

| Source declaration | Runtime expansion relevant to Gen 3 OU | Map risk |
|---|---|---|
| `test/sim/moves/rollout.js:18,42,72,100` | each runs for both Rollout and Ice Ball | Required-case IDs say `rollout`; evidence must either exercise both descriptors or explicitly prove their resolved programs are identical except generated type data. |
| `test/sim/misc/trapmoves.js:16,28,52` | Block, Mean Look, and Spider Web are the Gen 3 members of the six-move loop | One family assertion is reasonable, but at least one exact case plus generated-descriptor equivalence is needed before treating all three identities as covered. |
| `test/sim/misc/trapmoves.js:131,143,167,182` | Bind, Clamp, Fire Spin, Sand Tomb, Whirlpool, and Wrap are the Gen 3 members of the eight-move loop | The same family proof must include Gen 3 duration/residual data and Rapid Spin cleanup; the modern declaration's `1/8` residual assertion is correctly rejected because Gen 3 differs. |
| `test/sim/data.js:388` | expands once for each generation, including Gen 3 | Correctly outside the battle-transition contract; retain as verifier/generated-data admission evidence if data completeness becomes graded. |

The other obvious loop-defined suites, Plates, Drives, and modern type-addition
moves, are unreachable in Gen 3 and do not create a Gen 3 OU runtime gap.

The static and unified maps now also preserve `execution_status`, so a pending
upstream assertion cannot masquerade as an upstream-enforced regression.

One independent reclassification was required:
`test/sim/moves/brickbreak.js:41` is pending and constructs Gen 4, but its
assertion is directly applicable to Gen 3. The pinned Gen 3 Brick Break
`onTryHit` removes Reflect and Light Screen before the ordinary type-immunity
boundary. It is now `g3_source_applicable` with required case
`upstream-brickbreak-41`; existing entity-level Brick Break fixtures are not
silently promoted to assertion-specific proof.

## Omission-sensitive findings

The Future Sight omission has been repaired in the current evidence model:

- `futuremove` is represented as the shared slot-condition boundary used by
  Future Sight and Doom Desire;
- duplicate-slot rejection, switch-stable slot ownership, cast-time damage
  snapshot, expiry-time accuracy, Protect/Endure removal, faint/forced
  replacement, terminal resolution, and Wish ordering have focused and exact
  differential evidence;
- modern Future Sight assertions are not imported wholesale where Gen 3 source
  differs (notably damage staging and type-immunity behavior).

One mapped Wish assertion remains an explicit gap:
`test/sim/moves/wish.js:64` still requires `upstream-wish-64`. Passing other
delayed-slot cases is not assertion-specific proof of that scenario.

The audit also confirms the resolved-Dex supplement for Shadow Tag. Its four
upstream declarations are source-proven unreachable in legal Gen 3 OU because
the only standard Gen 3 origins are Wobbuffet and Wynaut (Uber), and Gen 3's
ability-changing paths cannot synthesize an unrelated ability. This is a
reachability proof, not a reason to omit Shadow Tag silently from a census.

## Highest-value new cases

These are selected from the 200 live static required-case records by boundary value,
not by raw test count:

1. **Bide lifecycle basis**: accumulation across qualifying move damage,
   last-source targeting, deterministic source-left retargeting in singles,
   no-damage failure, Ghost immunity on the Gen 3 release, Protect/Substitute,
   interruption cleanup, forced Bide choices, and release priority.
2. **Fury Cutter**: success-only progression, miss/immunity interruption,
   switch reset, and cap.
3. **Loop-family closure**: Rollout **and Ice Ball**; then the three direct-trap
   and six partial-trap Gen 3 descriptors with equivalence checks.
4. **Existing-family false positives**: Quick Claw induced speed tie, Sitrus
   residual deferral, Glare versus Ground, Haze preserving Focus Energy, and
   Thick Fat composed with a type item.
5. **Wish line 64**: preserve the exact upstream scenario shape while using
   Gen 3 healing semantics and legal teams.

Conversion 2 is no longer an open priority: the map now has assertion-specific
focused and differential evidence for all three applicable declarations,
including resolved Weather Ball type provenance and Gen 3's already-held-type
rule. This audit records evidence only; it does not promote the move in the
feature map.

Use differentials for choices, queues/events, phase/request transitions,
canonical state, PRNG, switching/fainting, and winner outcomes. Use focused C
tests only for internal invariants or constructed states that legal Gen 3 OU
cannot expose.

## Completion rule

An applicable record is complete only when its source adjudication and native
semantic boundary are accompanied by an assertion-specific focused test or
differential fixture. Entity-level fixtures, randomized reachability, and a
passing neighboring test remain useful evidence but do not close the record.
Feature-map promotion remains a separate gate requiring native boundary,
focused evidence, differential evidence, source mapping, and the pinned oracle
revision.
