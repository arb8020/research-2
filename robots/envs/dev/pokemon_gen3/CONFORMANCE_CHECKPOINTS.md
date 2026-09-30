# Gen 3 conformance checkpoints

This document defines the work sequence from the current native slice to a Gen
3 OU Ocean environment. Each checkpoint has a fixed input set and a completion
gate. Passing one checkpoint does not imply support for later checkpoints.

## Test authority

Pinned Pokémon Showdown commit
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0` defines battle behavior. Reuse its
tests as the scenario catalog. Do not write a second expected-outcome suite for
the same mechanics.

The conformance runner converts each applicable Showdown scenario into shared
inputs:

- the format and normalized teams.
- the initial PRNG seed and forced probabilistic outcomes.
- the submitted choices at each request.
- the expected stable-boundary trace from Showdown.

The native runtime consumes the same normalized teams, seed, and choices. The
comparator checks legal choices, submitted choices, sorted actions, ordered
handlers when the native feature uses handlers, canonical state, events,
requests, phase transitions, PRNG draws, and the terminal result.

Native-only tests cover facts that Showdown cannot prove about the C runtime:

- fixed-capacity and no-heap operation.
- atomic rejection of invalid input.
- state invariants after every transition.
- deterministic replay and serialization.
- Ocean buffer and action-mask projection.
- sanitizer, timeout, and performance checks.

## Showdown test sources

Use these sources in order. A test applies only when its feature exists in Gen
3 and its expected behavior matches the Gen 3 implementation.

1. Use the simulator core tests in `test/sim/choice-parser.js`,
   `test/sim/decisions.js`, and `test/sim/events.js`.
2. Use the cross-cutting tests in `test/sim/misc/`. Start with accuracy,
   critical hits, speed and turn order, faint order, PRNG, state, statuses,
   target resolution, and weather.
3. Use the feature tests in `test/sim/abilities/`, `test/sim/items/`, and
   `test/sim/moves/` for effects available in Gen 3.
4. Use every explicit `common.gen(3)` regression in the pinned tree. Current
   examples cover Quick Claw, faint order, Flash Fire, Magnet Pull, Thick Fat,
   Sitrus Berry, Brick Break, Conversion 2, Fury Cutter, Haze, Pursuit, and
   Weather Ball.
5. Use `test/random-battles/all-gens.js` and the Gen 3 random-battle data as
   legal coverage input. Those tests validate team generation. They do not
   replace complete randomized battle simulation.

Showdown tests default to the current generation unless they call
`common.gen(3)`. The conformance runner must instantiate applicable generic
tests through `common.gen(3)` instead of assuming that the default test proves
Gen 3 behavior.

## Checkpoint 0: Generic runtime slice

Status: complete.

The native runtime supports typed choices and requests, a sorted action queue,
ordinary move resolution, switching, fainting, forced replacement, terminal
resolution, and deterministic replay. The six-boundary fixture in
`verify/slice/` agrees with pinned Showdown.

Evidence:

- `native/test_pokemon.c`.
- `native/test_random_play.c`.
- `native/test_ocean_slice.c`.
- `verify/slice/case.json`.
- `native/FEATURES.md`.

## Checkpoint 1: Showdown test adapter

Status: complete for the frozen Checkpoint 1 feature map.

Build a parameterized adapter that turns applicable Showdown tests into shared
differential cases. Start with the runtime-core families. Preserve the original
teams, choices, and forced randomness when Gen 3 accepts them.

The checkpoint is complete when:

- each imported case records its Showdown test file and test name.
- the adapter rejects tests whose mechanics or generation do not match the
  supported feature map.
- the native and Showdown drivers consume one case format.
- a failure reports the first divergent semantic boundary.
- repeated runs produce byte-identical traces.
- the original six-boundary fixture remains green.

Evidence:

- `verify/cases/case.schema.json` and `normalize.js` define and enforce the
  shared input contract.
- `verify/cases/inventory.json` records one accepted upstream test and explicit
  reasons for rejected candidates.
- `verify/cases/regressions/` preserves the original six-boundary fixture.
- `verify/cases/derived/` covers a forced miss and a forced critical/damage
  roll without claiming they are literal upstream imports.
- `verify/slice/oracle.js`, `native.c`, and `compare.js` agree on 14 stable
  boundaries and require byte-identical replay.
- Equal-speed startup differential coverage is deferred explicitly because it
  crosses the event-handler boundary owned by Checkpoint 2; native queue-tie
  behavior remains directly tested.

## Checkpoint 2: Ordered event handlers

Status: complete for the bounded slice below. The pinned-oracle differential
matches at 28 boundaries, and both oracle and native replay are byte-identical.

Add the fixed-capacity handler mechanism that later features share. Preserve
Showdown's semantic boundaries, but use generated descriptors and handler IDs
instead of dynamic callbacks.

The first feature cluster covers move immunity:

- ordinary Ground damage to a grounded target.
- natural Flying-type immunity.
- Levitate immunity through the generated grounding capability used by
  `Pokemon#isGrounded`; Levitate is not a Showdown callback handler.
- Gen 3 staging in which natural/grounding immunity is decided before
  accuracy, accuracy is still consumed, and a previously determined immunity
  wins over a miss.
- Water Absorb as the first actual `TryHit` ability handler, with bounded
  discovery and deterministic ordering.

This slice discovers the target ability only. It proves one real handler plus
the native ordering comparator; it does not yet claim differential coverage of
multiple simultaneous handlers. Exact handler-key ties will require Showdown's
PRNG shuffle when a later checkpoint makes such a tie reachable.

Mold Breaker does not exist in Gen 3 and is outside this checkpoint.

The checkpoint is complete only when the imported Showdown cases and recombined
differential cases agree on handlers, hit results, events, state, and PRNG
staging. The runtime must not dispatch on a move pair or a species pair.
Bone Rush participates only in miss/immunity staging cases here; its multi-hit
effect remains unsupported until Checkpoint 5.

## Checkpoint 3: Value modifiers

Status: complete for the bounded slice below. The pinned-oracle differential
matches at 38 boundaries across 16 cases, and both oracle and native replay are
byte-identical.

The shared relay-value event path now covers Showdown's Gen 3 `ModifyAtk`
boundary with one ability and one item:

- Guts contributes a 6144/4096 physical Attack modifier when its holder has a
  status.
- Black Belt contributes a 4505/4096 Attack modifier for Fighting moves.
- when both apply, Showdown's Q12 accumulator advances exactly 4096 -> 6144 ->
  6758, then applies the accumulated modifier to Attack once.
- the Gen 3 burn penalty is a separate direct damage stage with multiplier
  2048/4096. It is not fabricated as a handler, and Guts suppresses it.

The corpus separates an unstatused baseline, an item-only nonlethal turn,
ordinary burn, burned Guts, and burned Guts plus Black Belt. Under matched
inputs and randomness, the item-only damage check raises the baseline from 115
to 127. Its two actions also prove that sequence-tagged handler and relay
records are merged in execution chronology rather than grouped by trace type.
Handler discovery/order, every Q12 accumulator transition, the final relay
result, burn application or suppression, resulting state, and labeled PRNG
consumption agree with the pinned oracle.

This checkpoint does not include Choice Band. It also does not implement burn
acquisition, burn residual damage, arbitrary statuses, other modifier events,
or general ability/item coverage. Its explicit initial burn is verifier-owned
canonical fixture state, not a simulated status-infliction action. Those
features remain in the lifecycle, generic-effect, and inventory checkpoints.

## Checkpoint 4: Condition lifecycle

Status: complete for the bounded slice below. The pinned-oracle differential
matches at 92 stable boundaries across 31 cases, and both oracle and native
replay are byte-identical.

Add explicit state and lifecycle operations for persistent conditions. Cover:

- Toxic as an escalating status.
- Protect as a volatile condition.
- Reflect as a side condition.
- Sandstorm as weather with residual work.

The checkpoint is complete when application, duration changes, removal,
residual ordering, switching, fainting, and forced replacement agree with
Showdown. Conditions must use bounded tagged state. Do not use open-ended state
maps.

The implemented slice proves:

- Toxic application, 85%-accuracy staging, Poison/Steel status immunity,
  escalating `max(1, floor(max HP / 16)) * stage` residual damage, the Gen 3 residual
  key `(order 10, suborder 6)`, and stage reset when the afflicted Pokemon
  switches back in.
- move-started Sandstorm with duration five, four damage ticks, expiry before
  the fifth tick, Ground/Rock/Steel immunity, and residual order 8. Sandstorm
  therefore executes before Toxic when both are present.
- Protect's one-turn volatile, guaranteed first use, consecutive success odds
  of 1/2, 1/4, and 1/8, and reset after a non-stalling move or a switch.
- Reflect as a five-turn side condition, singles physical-damage halving,
  critical-hit bypass, persistence across switches, and expiry.
- fixed-capacity residual discovery and ordering, lifecycle traces, residual
  fainting, and a suspended forced-replacement request after residual knockout.

The corpus includes matched Reflect damage (22 without Reflect, 11 with it),
matched critical damage (49 both without and through Reflect), forced
`stall.success` outcomes, a five-turn Sandstorm/Toxic residual knockout, and
legal Gen 3 OU source teams. Cases may have different team cardinalities per
side; the native initializer preserves each side's explicit size while the
selected singles format supplies its maximum.

At its original boundary this checkpoint did not claim regular poison, status
curing or Natural Cure, Sand Stream or Sand Veil, weather replacement or
suppression, Detect/Endure, Brick Break, Light Screen, doubles Reflect scaling,
or general condition descriptors. Later Checkpoint 6 families have closed many
of those gaps—including Detect/Endure through the shared generated stalling
operation—but that later evidence does not retroactively widen Checkpoint 4.

## Checkpoint 5: Generic move effects

Status: complete for the bounded slice below. The pinned-oracle differential
matches at 198 stable boundaries across 68 cases, and native and oracle replay
are byte-identical.

Add reusable descriptors or effect programs for Gen 3 move families:

- status and boost changes.
- secondary effects.
- recoil and drain.
- multi-hit moves.
- variable power and fixed damage.
- targeting and redirection where Gen 3 singles requires them.

Keep a named handler only when the move has behavior that the shared operations
cannot express. Import the applicable Showdown move tests before adding each
family.

The implemented slice proves four compositional families:

- signed self and opposing boosts, downstream damage, switch reset, stage
  caps, and failed changes; damage-plus-secondary status/boost success,
  failure, Protect blocking, and immunity without a secondary draw;
- actual-damage-based recoil and drain, floor rounding, healing clamp,
  overkill basis, Rock Head prevention through an ordered handler, blocked or
  immune no-followup, and recoil faint/forced-replacement/terminal ordering;
- Bone Rush's Gen 3 2--5-hit distribution, requested versus actual hits,
  per-hit critical and damage rolls, early knockout, and no hit-count draw on
  immunity, miss, or Protect;
- level-based Seismic Toss and Night Shade, their Fighting/Ghost type
  immunities, and all six Gen 3 Reversal HP brackets with resolved-power
  traces and ordinary downstream damage staging.

The additional semantic PRNG owners are `move.secondary` and
`move.multihit_count`. Per-hit `move.critical` and `move.damage_roll` draws
remain owned by each connected hit. Fixed-level damage consumes neither.

Cases may specify verifier-owned `initial_hp` in the inclusive range
`1..maxHP`. Omission means full HP. The oracle and native initializer receive
the same canonical initial mutable state; this is not a simulated damage
history and cannot initialize a fainted Pokemon.

This completes only the named generic families and interactions. It does not
claim arbitrary primary/secondary programs, all recoil/drain or multi-hit
moves, Counter/Mirror Coat/Bide, Substitute interactions, trapping,
redirection, spread targets, or the full ability/item/move inventory.

## Checkpoint 6: Gen 3 OU inventory

Status: authoritative inventory and initial exhaustive classification frozen;
semantic gaps remain.

Generate every legal and reachable Gen 3 OU species, move, ability, and item
from the pinned revision. Map each feature to its Showdown source, native
boundary, focused test, differential case, and oracle revision.

The checkpoint is complete when every required feature-map entry passes its
focused cases and recombined hidden cases. An unsupported reachable descriptor
is a failure. A finite trace corpus alone does not complete this checkpoint.

Start by freezing an inventory of every Gen 3 OU-reachable species, move,
ability, item, status, volatile, side condition, weather effect, target mode,
and callback/event hook at the pinned revision. Classify each descriptor as
implemented, inert metadata, unreachable, or unsupported; map implemented
entries to source, native boundary, focused tests, and differential cases.
Then expand by generic semantic family and recombine features rather than
adding move-pair resolvers.

The machine-checkable classification contract is
`verify/inventory/descriptor-map.schema.json`; its dependency-free validator
is `verify/inventory/validate.js`. `verify/inventory/gen3ou-inventory.json` is
the sole generated universe: 369 species/forms, 354 moves, 70 abilities, 104
items, 82 reachable conditions, 12 target modes, 514 callback-hook ownership
records, 13 simulator-only conditions, and 42 effective format rules/bans at
the pinned revision. Its digest and selector counts are checked by the
validator. All 1,560 generated descriptors have a fail-closed classification:
859 implemented, 424 inert, 30 unreachable, and 247 unsupported. Support still
requires source, native, focused, and differential evidence; aggregate,
admission, set-field, and battle-runtime gaps remain explicit. The map is
structurally exhaustive but not inventory-ready while
any reachable descriptor remains unsupported. `inventory_ready` is distinct
from overall completion: even a fully mapped inventory cannot satisfy semantic
and hidden-recombination gates by declaration.

Handler-program classification is likewise fail-closed. Water Absorb is
implemented with both damaged-HP healing and full-HP cancellation evidence;
Levitate remains implemented at the immunity boundary. Guts is unsupported
until poison, sleep, and freeze interactions are represented and recombined.
Rock Head is unsupported because its reachable Struggle-recoil exception is
absent from the current action surface. The four hook-owner records remain
unsupported independently of the generic interpreter infrastructure.

Team-source legality is a separate corpus property. All Checkpoint 4 and 5
sources, plus the repaired Persian/Scratch Checkpoint 1 derived cases, pass the
pinned Gen 3 OU validator. Twelve inherited Checkpoint 0--3 focused/regression
source files intentionally remain simulator-mechanic fixtures outside the
ladder-team legality claim: most use the validator's zero-EV sentinel, and the
preserved complete regression also includes legacy set/evolution-level data.
Therefore the 68-case corpus is not claimed to be wholly ladder-legal.

The generic drag/phazing slice closes Roar, Whirlwind, Ingrain, Suction Cups,
the Ingrain volatile, and their five executable hooks. Seven legal fixtures
prove no-bench failure, singleton and multi-bench selection, labeled PRNG,
stale queued-action cancellation, ordinary entry lifecycle reuse, Ingrain's
trap/residual/DragOut behavior, and Suction Cups' ordered veto. The complete
corpus now matches the pinned oracle at 2,207 stable boundaries and replays
deterministically. Pursuit and Baton Pass remain unsupported because they need
distinct interception and state-transfer semantics.

## Checkpoint 7: Complete battles and Ocean release

Run deterministic and coverage-guided complete battles over legal Gen 3 OU
teams. Retain minimized failures as regression cases.

The release gate requires:

- zero differential failures across the frozen public and hidden corpus.
- invariants after every transition.
- deterministic replay from teams, choices, and seed.
- stable observations, legal-action masks, rewards, and terminal signals.
- no runtime Node, Python, or Showdown dependency.
- no heap allocation in the battle step.
- the frozen vectorized performance and memory floors.

Completion means conformance over the frozen feature map and observable
contract. It does not mean exhaustive enumeration of all battle states.

## Change rule

Add a mechanic only with its state representation, generated descriptor or
named handler, imported or source-linked Showdown test, differential case, and
native invariant test. If a mechanic requires a new semantic boundary, add the
boundary before adding more examples of the mechanic.
