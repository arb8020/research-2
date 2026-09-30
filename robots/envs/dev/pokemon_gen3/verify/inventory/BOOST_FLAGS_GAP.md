# Gen 3 direct-boost interaction-flag gap

Oracle: pinned Pokemon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, resolved with
`Dex.forGen(3)`.

This is a descriptor-wide support audit for the 32 direct-boost moves that are
not the existing Bulk Up and Growl anchors. It supplements
`BOOST_MOVE_GENERATION.md`; a correct boost-table program is necessary but is
not enough to classify a move descriptor as implemented.

## Result

All 32 boost products can now be added to the executable native move table
without weakening fail-closed initialization. Protect, Substitute (including
Tickle's Gen 3 `bypasssub` exception), whole-product `ChangeBoost`/`TryBoost`,
the four reachable negative-boost-filter abilities, accuracy/evasion stage
consumers, stage caps, and switch reset are implemented by reusable families.
There is no remaining blocker in an interaction that can occur between the
currently executable descriptors.

That is deliberately narrower than a final descriptor-wide `implemented`
classification in the complete feature map. Three flags connect these moves to
legal Gen 3 moves that are not executable yet:

- 16 self-targeting moves are Snatch-affected: Acid Armor, Agility, Amnesia,
  Barrier, Calm Mind, Cosmic Power, Dragon Dance, Growth, Harden, Howl, Iron
  Defense, Meditate, Sharpen, Swords Dance, Tail Glow, and Withdraw.
- 16 foe-targeting moves are Protect-affected, reflectable by Magic Coat, and
  copyable by Mirror Move: Charm, Cotton Spore, Fake Tears, Feather Dance,
  Flash, Kinesis, Leer, Metal Sound, Sand Attack, Scary Face, Screech,
  Smokescreen, String Shot, Sweet Scent, Tail Whip, and Tickle.

The generated catalog preserves these flags exactly. Because initialization
rejects every move, ability, and item absent from the executable tables, Magic
Coat, Mirror Move, Snatch, and Soundproof cannot currently enter a native
battle. Their consumers are therefore not prerequisites for safely exposing
the 32 boost moves in today's supported subgraph. They *are* prerequisites for
calling the descriptors completely implemented over the final Gen 3 OU feature
map: the final contract makes all legal descriptors executable and recombines
them in hidden tests. Keep the descriptor-map entries `unsupported` until
those future edges and the required rotation/recombination evidence close.

The exact current judgment is:

| Move group | Count | Reachable blocker today | Future descriptor-wide blocker |
|---|---:|---|---|
| Acid Armor, Agility, Amnesia, Barrier, Calm Mind, Cosmic Power, Dragon Dance, Growth, Harden, Howl, Iron Defense, Meditate, Sharpen, Swords Dance, Tail Glow, Withdraw | 16 | none | Snatch re-entry/interception |
| Charm, Cotton Spore, Fake Tears, Feather Dance, Flash, Kinesis, Leer, Metal Sound, Sand Attack, Scary Face, Screech, Smokescreen, String Shot, Sweet Scent, Tail Whip | 15 | none | Magic Coat reflection and Mirror Move provenance/re-entry |
| Tickle | 1 | none; its complete two-stat product and Substitute bypass are already executable | Magic Coat reflection and Mirror Move provenance/re-entry |

## Flag-by-flag judgment

| Flag | Affected new moves | Pinned Gen 3 meaning | Current native state | Judgment |
|---|---|---|---|---|
| `protect` | all 16 foe-targeting moves | The Gen 3 override rolls accuracy first, then Protect's priority-3 `TryHit` handler cancels a flagged move on a hit | generated move flags feed a declarative volatile-owned `TryHit` program; the generic status and damage paths dispatch it after accuracy | implemented interaction family; these descriptors remain unsupported for their other live flags |
| `reflectable` | all 16 foe-targeting moves | Magic Coat's priority-2 `TryHit` handler re-executes the move from the reflector, swaps the target, marks it bounced, and cancels the original | Magic Coat is rejected by current fail-closed initialization; its volatile, handler, active-move re-entry, and bounced provenance remain absent | no current executable-subgraph blocker; future descriptor-wide blocker |
| `mirror` | all 16 foe-targeting moves | makes the move eligible for later selection by Mirror Move through recorded attack/move provenance | Mirror Move is rejected by current fail-closed initialization; required last-attacker/last-move provenance remains absent | no current executable-subgraph blocker; future descriptor-wide blocker |
| `snatch` | all 16 self-targeting moves | Snatch's global `onAnyPrepareHit` removes Snatch, re-executes the selected move from the snatcher, and cancels the original | Snatch is rejected by current fail-closed initialization; its volatile, `ANY` PrepareHit interception, and re-entrant move execution remain absent | no current executable-subgraph blocker; future descriptor-wide blocker |
| `sound` | Metal Sound and Screech (Growl is an existing anchor) | Soundproof cancels sound moves against another Pokemon; sound does not inherently bypass Substitute in Gen 3 | Soundproof is both banned by the frozen Gen 3 OU ruleset and rejected by current fail-closed initialization | no current Gen 3 OU executable-subgraph blocker; retain live metadata for other formats |
| `powder` | Cotton Spore | natural powder immunity is explicitly gated to Gen 6+ in Showdown | no native consumer | inert in Gen 3; preserve as generated metadata |
| `bypasssub` | Tickle only | Tickle's Gen 3 override passes through Substitute; all other foe-targeted direct boosts are intercepted by Substitute | generated flag is consumed by generic `TryPrimaryHit`; the differential Tickle case proves bypass plus its complete two-stat product | implemented interaction family; Tickle x Hyper Cutter recombination evidence is still required |
| `dance` | Dragon Dance, Feather Dance, Swords Dance | Dancer copies dance moves, but Dancer is a Gen 7 ability | no native consumer | inert in Gen 3; preserve as generated metadata |

`sound` deserves a narrow qualification. The pinned `gen3ou` rule table has
`-ability:soundproof`, so Soundproof is outside the legal format. That makes
the sound interaction irrelevant only after team admission proves the ban.
The three sound moves are still ordinary Substitute-blocked moves in Gen 3;
the modern sound-through-Substitute rule must not be backported.

## Authoritative source boundaries

- `data/mods/gen3/scripts.ts:285-405` is the authoritative Gen 3
  `tryMoveHit` override. It records natural/type and move-specific immunity,
  rolls accuracy, and only on an accuracy hit dispatches `TryHit`; a prior
  natural immunity is reported after `TryHit` succeeds. The modern generic
  ordering in `sim/battle-actions.ts` does not control Gen 3.
- `data/moves.ts` `protect.condition.onTryHit` consumes the `protect` flag at
  priority 3.
- `data/moves.ts` `magiccoat.condition.onTryHit` consumes `reflectable` at
  priority 2 and performs once-only active-move re-entry.
- `data/moves.ts` `snatch.condition.onAnyPrepareHit` consumes `snatch`, removes
  its volatile, re-executes the move from the snatcher, and returns null to
  cancel the original.
- `sim/battle-actions.ts:1070-1082` and `TryPrimaryHit` own Substitute
  interception; Tickle's effective Gen 3 descriptor supplies `bypasssub` in
  `data/mods/gen3/moves.ts`.
- `sim/battle-actions.ts:661-668` gates natural powder immunity to Gen 6+.
- `sim/battle-actions.ts:319-345` invokes Dancer, which is unavailable in Gen
  3.
- `data/abilities.ts` `soundproof` consumes `sound`; the pinned Gen 3 OU format
  bans that ability.

## Recommended closure order

1. **Generate and rotate all 32 direct-boost moves.** Emit their sparse boost
   products through the existing generic program, make their catalog records
   executable, and run the nine-case descriptor rotation. This is one semantic
   family, not 32 resolvers. Split verification only by meaningful staging:
   always-hit self moves; numeric-100 foe moves; sub-100 accuracy moves; and
   `allAdjacentFoes` singles projection.
2. **Close live recombinations before changing inventory classification.** Run
   Protect, ordinary Substitute, Tickle bypass, partial `TryBoost` filtering,
   stage-cap, switch-reset, queue-order, and accuracy/evasion threshold cases.
3. **Generic active-move re-entry.** Add an explicit bounded execution frame
   carrying original user, current user/target, source effect, bounced state,
   external-use state, and recursion protection. This is shared infrastructure
   for Magic Coat, Mirror Move, and Snatch rather than three move resolvers.
4. **Magic Coat reflection.** Install its one-turn volatile and ordered
   `TryHit` handler over the re-entry primitive. Protect priority 3 must beat
   Magic Coat priority 2 when both apply.
5. **Mirror Move provenance.** Record the exact successful opposing move/source
   facts required by Gen 3, then select and re-enter that move without charging
   the copied move's PP.
6. **Snatch interception.** Add the global `ANY` PrepareHit handler, consume the
   Snatch volatile exactly once, redirect execution to the snatcher, and cancel
   the original.
7. **Admission proof for Soundproof.** Enforce and differentially test the
   frozen ban. Keep `sound` live in generated data for other formats and later
   generations.

Already closed prerequisites:

1. **Correct generic Protect staging.** Protect is an ordered
   volatile-owned `TryHit` condition handler with a generated move-flag
   predicate and a distinct `NOT_FAIL` result. The Gen 3 rules path dispatches
   it after the generation's accuracy roll, matching the override and oracle.
2. **Substitute / `TryPrimaryHit`.** Generic interception uses bounded HP
   payload state and consults `bypasssub`; `sound` does not imply bypass in Gen
   3.
3. **Whole-product boost mutation.** `ChangeBoost`/cap/`TryBoost` operates on
   one sparse product, so Tickle can lose Attack to Hyper Cutter while retaining
   Defense. Clear Body, Hyper Cutter, Keen Eye, and White Smoke are installed as
   ordered ability handlers.

This order closes the cheapest shared boundary first and makes all three
move-replay mechanics depend on one honest execution-frame abstraction.

## Required focused and differential tests

### Protect

- Each target shape (`normal`, singles-projected `allAdjacentFoes`) is blocked
  only when the move has `protect`.
- Protected numeric-85 and numeric-100 moves consume exactly one accuracy
  draw before `TryHit`; an accuracy miss never invokes Protect.
- Protect + Magic Coat must prove handler priority among the `TryHit` handlers
  after the Gen 3 accuracy roll: Protect cancels first and no reflected
  execution occurs.

### Substitute

- Charm (or another ordinary targeted boost) hits the Substitute and leaves
  the holder's stages unchanged.
- Tickle passes through Substitute and applies its complete two-stat product.
- Growl, Metal Sound, and Screech remain Substitute-blocked in Gen 3 despite
  `sound`.
- Tickle + Hyper Cutter filters Attack while retaining Defense after bypass.

### Magic Coat

- Reflect all three accuracy classes: always-hit is not present in this target
  family, numeric 100 consumes the reflected execution's exact draw, and
  numeric sub-100 proves hit and miss outcomes.
- The original user receives the boost drop; the reflector does not.
- A reflected move cannot bounce again; PP is charged only to the original
  selected move; source-effect and labeled PRNG trace match Showdown.

### Mirror Move

- Copy a successful eligible targeted boost and apply it to the original user.
- Reject an ineligible/non-`mirror` move and a missing/stale source.
- Switching, failed moves, and intervening actions update or preserve
  provenance exactly as pinned Showdown does.
- Copied execution consumes no copied-slot PP and preserves exact accuracy and
  event/PRNG staging.

### Snatch

- Steal one single-stat and one multi-stat self boost; the original user's
  stages remain unchanged and the snatcher gets the entire sparse product.
- Snatch is removed after the first eligible move and does not steal a second
  move in the same turn.
- An ineligible move leaves Snatch installed until normal one-turn expiry.
- Snatched execution does not charge the snatcher's move PP and identifies
  `snatch` as its source effect.

### Generation-inert flags and format reachability

- Cotton Spore affects Grass targets in Gen 3, proving no modern powder
  immunity leaked into the generation plugin.
- Dance moves receive no extra execution in Gen 3.
- Gen 3 OU team validation rejects Soundproof, and a verifier-only non-OU
  fixture proves the generic sound predicate remains data-driven if Soundproof
  is later implemented.

Only after these tests, the nine-case descriptor rotation, boost-table event
tests, canonical state comparison, and deterministic replay all pass may the
32 descriptors be reclassified from `unsupported` to `implemented`.
