# Generic native battle slice

This directory is the first structurally final slice of the replacement battle
runtime. It is independent of `engine/gen3_abi.*`: the old engine remains only
as regression evidence.

See the [Gen 3 conformance checkpoints](../CONFORMANCE_CHECKPOINTS.md) for the
Showdown-derived test plan and the completion gate for each expansion stage.

The ownership boundaries are deliberately small:

- `pokemon.[ch]` owns generation-independent state, typed requests/choices,
  sorted actions, move execution, faint/replacement work, and terminal state.
- `gen3_rules.[ch]` owns Gen 3 damage and probabilistic constants.
- `gen3_slice_data.[ch]` is generated immutable species, move, type, ability,
  item, and handler-descriptor data.
- `singles2.[ch]` supplies one-, two-, and three-member singles format
  configurations; each battle also stores each side's actual cardinality.
- `../ocean/pokemon_slice.h` only maps fixed buffers and actions to that API.

The battle object is embedded, heap-free, and copyable. A step validates both
choices atomically, constructs and snapshots the sorted queue, executes it,
drains faint/replacement work, and exposes the next stable request. Random
draws are made by their owning operation and retained with semantic labels.

## Supported semantic slice

The native runtime is Gen 3 singles with fixed capacity for six supplied
Pokemon per side. All 369 frozen Gen 3 species identities are executable;
existing compact IDs remain stable and the remaining species are appended at
generation time. Actual team cardinality is explicit per side, so asymmetric
teams need no dummy members.
Sets may contain multiple moves. It supports these mechanics:

- fixed-team-slot switches.
- priority, speed ordering, and seeded ties.
- type immunity, generated grounding capabilities, accuracy, critical hits,
  and Gen 3 damage rolls.
- fixed-capacity ordered `TryHit` handler discovery and dispatch, currently
  exercised by Water Absorb.
- fixed-capacity ordered numeric relay handlers, including `ModifyAtk` for
  Guts/physical type items and `ModifySpA` for special type items, using
  Showdown-compatible Q12 accumulation and one final relay application.
- explicit initial burn state and the Gen 3 direct burn damage stage, including
  Guts suppression.
- fixed-capacity tagged condition state for Toxic status, Protect/stall
  volatiles, Reflect side condition, and Sandstorm weather.
- fixed-capacity residual discovery and Showdown-key ordering, including
  condition duration/counter transitions and residual faint handling.
- generic signed boosts and primary, secondary, and self-secondary effects.
- actual-damage-based recoil/drain and ordered Rock Head prevention.
- a generic multi-hit loop with explicit plan, per-hit, and result state.
- fixed-level damage and Gen 3 HP-bracket variable power.
- PP and HP changes.
- voluntary switches, forced switches, fainting, and victory.
- deterministic replay.
- generated item mutation programs for Thief/Covet transfer, Knock Off
  removal and slot lockout, and Recycle recovery. Sticky Hold and Mail gate
  those transactions through typed ability/item policy.

The generated bounded data also contains Bulk Up, Growl, Splash, Ember, Steel
Wing, Body Slam, Double-Edge, Giga Drain, Seismic Toss, Night Shade, and
Reversal, Thief, Covet, Knock Off, Recycle, and Trick. Exhausting every
ordinary move's PP projects and executes synthetic Struggle through a distinct
fallback action. This slice
does not claim general ability, item, status, weather, side-condition,
volatile, targeting, or move coverage. Levitate is a generated grounding
capability, matching
Showdown's `Pokemon#isGrounded`; it is not an event handler. Water Absorb is
the first supported `TryHit` handler. Bone Rush covers both miss/immunity
staging and the generic two-to-five-hit loop.

Guts and all 18 Gen 3 type-boost items share one generated
descriptor/discovery/ordering path. Physical and special categories preserve
Showdown's distinct `ModifyAtk` and `ModifySpA` event identities. Matching
items chain exact Q12 4505 except Sea Incense's Gen 3-specific 4300; a
mismatched type is a discovered no-op. Burn's
2048/4096 physical-damage penalty remains a direct Gen 3 damage stage, and
Guts suppresses it. Species-conditioned and lock-bearing stat items remain
outside this family.

The item-mutation boundary keeps current item, last item, per-install item
state, and Gen 3 Knock Off lockout distinct. Thief and Covet use the shared
take/set transaction; Recycle reinstalls the last item with fresh item state.
Trick uses a distinct typed swap operation that preserves Showdown's
sequential two-holder takes and raw-ID rollback on a later gate failure.
Gen 3 Knock Off intentionally follows Showdown's direct-clear override: it
sets the lockout bit without rewriting `last_item` or running the ordinary
take-item lifecycle. None of these operations consumes item-specific PRNG.

A separate nonlethal Black Belt case holds the seed and combat inputs constant
against its baseline: damage changes from 115 to 127. Because both queued moves
execute, it also verifies that the native view's sequence-tagged handler,
relay-result, and damage-stage records are serialized in semantic execution
order rather than grouped by storage array.

Gen 3 hit staging determines natural or grounding immunity before accuracy,
always consumes the accuracy draw, and reports the already-determined immunity
instead of a miss. Actual `TryHit` handlers run only after accuracy succeeds.

Toxic uses the same accuracy stage, then applies tagged status after Poison and
Steel immunity checks. Its residual counter increments before damage and resets
on switch-in. Move-started Sandstorm lasts five turns but expires before its
fifth residual callback, producing four damage ticks. Its order 8 work runs
before Toxic's order 10/suborder 6 work.

Protect installs a one-turn block plus a stall counter. The first use is
guaranteed; consecutive uses then have odds 1/2, 1/4, and 1/8 at the Gen 3
cap. `stall.success` owns the probabilistic draw. A non-stalling move or
switching removes the chain.
Reflect and Light Screen are five-turn side conditions. In singles, generated
`ModifyDamagePhase1` handlers halve noncritical physical or special damage,
respectively. Both conditions persist when the active Pokemon switches.

This condition slice does not include regular poison, curing/Natural Cure,
Sand Stream or Sand Veil, weather replacement or suppression, Detect/Endure,
Brick Break, doubles screen scaling, or arbitrary condition
callbacks.

Checkpoint 5's effect slice covers signed boosts, Ember/Steel Wing
secondaries, Double-Edge recoil, Giga Drain healing, Rock Head prevention,
Bone Rush multi-hit execution, level-based Seismic Toss/Night Shade, and all
six Gen 3 Reversal brackets. The differential trace exposes effect phase,
requested/actual hits, per-hit randomness and damage, damage-relative basis,
and resolved damage formulas. `move.secondary` and `move.multihit_count` are
labeled at their owning operations; fixed damage consumes no critical or
damage-roll draw.

The verifier may initialize HP to a nonzero value at or below max HP to test a
formula boundary. Omission means full HP. This is canonical initial fixture
state, not a simulated prior turn.

The frozen differential corpus contains 68 cases and 198 stable boundaries.
It is not an inventory-completeness claim. Arbitrary effect programs,
Substitute and Counter-family interactions, targeting/redirection, and the
long tail of legal Gen 3 OU descriptors remain Checkpoint 6 work.

Nor is the historical corpus uniformly ladder-legal. All Checkpoint 4/5 team
sources and the repaired Persian/Scratch derived cases pass the pinned Gen 3
OU validator. Twelve inherited Checkpoint 0--3 sources remain deliberately as
simulator-mechanic fixtures, principally with zero-EV sentinels or legacy
evolution-level regression data.

This is a vertical architecture proof, not “complete Gen 3 OU.” A mechanic is
added only when its state, data descriptor or handler boundary, focused tests,
and Showdown differential evidence are added together.

## Verification

`make test` runs focused semantic tests, 128 seeded legal-play battles with
invariants after each transition, and the thin Ocean projection test. The
complete request-to-request oracle case and strict boundary comparator live in
`../verify/slice`; Showdown and Node are required only on that verifier side.

```sh
make -C native test
make -C verify/slice test
```
